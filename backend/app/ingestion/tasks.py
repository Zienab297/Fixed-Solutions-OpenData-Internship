import logging

from celery import Celery
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.ingestion.models import IngestionJob
from app.ingestion.pipeline.chunker import split_pages
from app.ingestion.pipeline.embedder import EmbeddingService
from app.ingestion.pipeline.extractor import extract_pdf_text
from app.ingestion.pipeline.indexer import QdrantIndexer


logger = logging.getLogger(__name__)

celery_app = Celery(
    "rag_ingestion",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)


def _set_status(
    db: Session,
    job: IngestionJob,
    status: str,
    error_message: str | None = None,
) -> None:
    job.status = status
    job.error_message = error_message
    db.add(job)
    db.commit()
    db.refresh(job)


@celery_app.task(name="app.ingestion.process_pdf")
def process_pdf(job_id: str) -> str:
    db = SessionLocal()
    try:
        job = db.query(IngestionJob).filter(IngestionJob.id == job_id).first()
        if not job:
            logger.error("Ingestion job %s was not found.", job_id)
            return job_id

        _set_status(db, job, "processing")

        pages = extract_pdf_text(job.file_path)
        if not pages:
            logger.warning(
                "PDF %s produced no text. Sprint 1 skips OCR for scanned PDFs.",
                job.filename,
            )
            _set_status(db, job, "done")
            return job_id

        chunks = split_pages(
            pages=pages,
            doc_id=job.id,
            domain_id=job.domain_id,
            chunk_size=settings.INGESTION_CHUNK_SIZE,
            overlap=settings.INGESTION_CHUNK_OVERLAP,
        )
        if not chunks:
            logger.warning("PDF %s produced no chunks.", job.filename)
            _set_status(db, job, "done")
            return job_id

        embedder = EmbeddingService(
            model_name=settings.EMBEDDING_MODEL,
            batch_size=settings.EMBEDDING_BATCH_SIZE,
        )
        vectors = embedder.encode([chunk.text for chunk in chunks])

        indexer = QdrantIndexer(
            url=settings.QDRANT_URL,
            collection_name=settings.QDRANT_COLLECTION,
        )
        indexer.upsert(chunks=chunks, vectors=vectors)

        _set_status(db, job, "done")
        return job_id
    except Exception as exc:
        logger.exception("Failed to process ingestion job %s.", job_id)
        job = db.query(IngestionJob).filter(IngestionJob.id == job_id).first()
        if job:
            _set_status(db, job, "failed", str(exc))
        raise
    finally:
        db.close()
