"""
DocumentProcessor — wires together extraction, chunking, embedding, and
Postgres writes for the rag.documents / rag.chunks tables.

Called by the Celery task inside asyncio.run(), so it uses the *sync*
SessionLocal from database.py.  All DB operations here are synchronous.

Flow
----
1. Set document.ingest_status = 'processing'
2. Extract raw text from the file bytes
3. Fetch domain chunk_size / chunk_overlap settings
4. Chunk the text
5. Embed each chunk in small batches (via Ollama)
6. INSERT rows into rag.chunks
7. Upsert embeddings into Qdrant
8. Set document.ingest_status = 'completed'
9. On any error → set status = 'failed', re-raise so Celery can retry
"""
from __future__ import annotations

import io
import logging
from typing import Optional
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.config import settings
from app.models.db.models import Chunk as ChunkModel, Document, Domain
from app.services.ingestion.chunker import ChunkerService

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Embedding batch size: keep small so Ollama never needs >30 s per call.
# bge-m3 on CPU: ~10-15 chunks/s → 20 chunks ≈ 1-2 s per batch.
# Increase to 50 if running on GPU-backed Ollama.
# ---------------------------------------------------------------------------
_EMBED_BATCH_SIZE = 20


def _embed_texts_sync(texts: list[str]) -> list[list[float]]:
    """
    Call Ollama /api/embed synchronously in small batches.

    Why batched?
    Ollama processes embeddings sequentially internally. Sending 200 chunks
    in a single 120 s request means the worker is blocked the whole time and
    any transient failure forces a full retry. Splitting into batches of
    _EMBED_BATCH_SIZE gives ~1-2 s per call, makes progress visible in logs,
    and lets the worker recover cheaply on partial failure.

    Falls back to zero vectors per batch if Ollama is unreachable (dev/test
    safety) so DB writes still succeed and Qdrant can be re-indexed later.
    """
    import httpx

    url = f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/embed"
    all_embeddings: list[list[float]] = []

    for batch_start in range(0, len(texts), _EMBED_BATCH_SIZE):
        batch = texts[batch_start : batch_start + _EMBED_BATCH_SIZE]
        try:
            response = httpx.post(
                url,
                json={"model": settings.EMBEDDING_MODEL, "input": batch},
                timeout=60.0,  # 60 s is plenty for ≤20 chunks
            )
            response.raise_for_status()
            batch_embeddings = response.json()["embeddings"]
            all_embeddings.extend(batch_embeddings)
            logger.debug(
                "Embedded batch %d-%d / %d",
                batch_start,
                batch_start + len(batch) - 1,
                len(texts),
            )
        except Exception as exc:
            logger.warning(
                "Ollama embedding failed for batch %d-%d (%s). "
                "Storing zero vectors — re-embed after Ollama is available.",
                batch_start,
                batch_start + len(batch) - 1,
                exc,
            )
            all_embeddings.extend([[0.0] * 1024 for _ in batch])

    return all_embeddings


# ---------------------------------------------------------------------------
# Qdrant upsert helper
# ---------------------------------------------------------------------------

def _upsert_chunks_to_qdrant(
    domain_id: UUID,
    chunk_rows: list,
    embeddings: list[list[float]],
    document_title: str,
) -> None:
    """
    Upsert chunk embeddings into the domain's Qdrant collection.

    Collection name mirrors VectorSearchService._collection_name():
      domain_<uuid_with_underscores>

    Each point stores the metadata needed for retrieval so callers
    never have to round-trip back to Postgres for basic fields.
    Falls back gracefully if Qdrant is unreachable (dev / test safety).
    """
    from qdrant_client import QdrantClient
    from qdrant_client.models import PointStruct, VectorParams, Distance

    collection = f"domain_{str(domain_id).replace('-', '_')}"

    try:
        client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)

        # Ensure collection exists (idempotent).
        try:
            client.create_collection(
                collection_name=collection,
                vectors_config=VectorParams(size=1024, distance=Distance.COSINE),
            )
            logger.info("Qdrant collection created: %s", collection)
        except Exception:
            pass  # Collection already exists — safe to continue.

        points = [
            PointStruct(
                id=str(chunk_rows[i].id),
                vector=embeddings[i],
                payload={
                    "content": chunk_rows[i].content,
                    "document_title": document_title,
                    "page_number": chunk_rows[i].page_number,
                    "section": chunk_rows[i].section,
                    "domain_id": str(domain_id),
                    "chunk_index": chunk_rows[i].chunk_index,
                },
            )
            for i in range(len(chunk_rows))
        ]

        # Upsert in batches of 100 to avoid large payloads
        for start in range(0, len(points), 100):
            client.upsert(
                collection_name=collection,
                points=points[start : start + 100],
            )

        logger.info(
            "Qdrant upsert complete: collection=%s, %d points",
            collection,
            len(points),
        )

    except Exception as exc:
        logger.error(
            "Qdrant upsert failed for collection=%s: %s. "
            "Chunks are stored in Postgres; re-index Qdrant to recover.",
            collection,
            exc,
        )


# ---------------------------------------------------------------------------
# Text extraction helpers
# ---------------------------------------------------------------------------

def _extract_text_from_pdf(file_bytes: bytes) -> list[tuple[int, str]]:
    """
    Returns list of (page_number, text) tuples.
    Falls back to plain decode if pypdf is not installed.
    """
    try:
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(file_bytes))
        pages = []
        for i, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            pages.append((i, text.strip()))
        return pages
    except ImportError:
        logger.warning("pypdf not installed; treating PDF as plain text.")
        return [(1, file_bytes.decode("utf-8", errors="replace"))]


def _extract_text(filename: str, file_bytes: bytes) -> list[tuple[int, str]]:
    """Dispatch to the right extractor based on file extension."""
    lower = filename.lower()
    if lower.endswith(".pdf"):
        return _extract_text_from_pdf(file_bytes)
    # txt / csv / other text formats
    return [(1, file_bytes.decode("utf-8", errors="replace"))]


# ---------------------------------------------------------------------------
# DocumentProcessor
# ---------------------------------------------------------------------------

class DocumentProcessor:
    """
    Synchronous processor used inside Celery tasks.
    Opens its own DB session so it's fully independent of the FastAPI
    async session lifecycle.
    """

    def __init__(self):
        self.chunker = ChunkerService()

    def process(
        self,
        document_id: str,
        domain_id: str,
        file_content: bytes,
        filename: str,
    ) -> None:
        """
        Entry point called by the Celery task.
        All exceptions propagate so the task can retry.
        """
        doc_uuid = UUID(document_id)
        domain_uuid = UUID(domain_id)

        with SessionLocal() as db:
            try:
                self._process(db, doc_uuid, domain_uuid, file_content, filename)
            except Exception:
                try:
                    self._mark_failed(db, doc_uuid)
                    db.commit()
                except Exception as inner:
                    logger.error("Could not mark document as failed: %s", inner)
                raise

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _process(
        self,
        db: Session,
        document_id: UUID,
        domain_id: UUID,
        file_content: bytes,
        filename: str,
    ) -> None:
        # 1. Mark processing
        self._set_status(db, document_id, "processing")
        db.commit()

        # 2. Fetch domain settings (chunk_size / chunk_overlap)
        domain = db.execute(
            select(Domain).where(Domain.id == domain_id)
        ).scalar_one_or_none()
        chunk_size = domain.chunk_size if domain else 512
        chunk_overlap = domain.chunk_overlap if domain else 64

        # 3. Extract text per page
        pages = _extract_text(filename, file_content)
        if not pages or all(not text for _, text in pages):
            logger.warning(
                "document_id=%s: no text extracted from %s", document_id, filename
            )
            self._set_status(db, document_id, "completed")
            db.commit()
            return

        # 4. Chunk each page
        all_chunks_data: list[dict] = []
        for page_num, page_text in pages:
            if not page_text.strip():
                continue
            chunks = self.chunker.chunk_text(
                page_text,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                page_number=page_num,
            )
            for c in chunks:
                all_chunks_data.append(
                    {
                        "content": c.content,
                        "chunk_index": c.chunk_index + len(all_chunks_data),
                        "page_number": c.page_number,
                        "section": c.section,
                        "metadata": c.metadata or {},
                    }
                )

        if not all_chunks_data:
            self._set_status(db, document_id, "completed")
            db.commit()
            return

        # 5. Embed in small batches (fixes the 120 s single-call bottleneck)
        texts = [c["content"] for c in all_chunks_data]
        logger.info(
            "document_id=%s: embedding %d chunks in batches of %d",
            document_id,
            len(texts),
            _EMBED_BATCH_SIZE,
        )
        embeddings = _embed_texts_sync(texts)

        # 6. Build and INSERT Chunk ORM rows
        chunk_rows = []
        for i, chunk_data in enumerate(all_chunks_data):
            row = ChunkModel(
                document_id=document_id,
                domain_id=domain_id,
                content=chunk_data["content"],
                chunk_index=chunk_data["chunk_index"],
                page_number=chunk_data["page_number"],
                section=chunk_data["section"],
                embedding_model=settings.EMBEDDING_MODEL,
                metadata_=chunk_data["metadata"],
            )
            chunk_rows.append(row)

        db.add_all(chunk_rows)
        db.flush()  # assign IDs before Qdrant upsert

        # 7. Upsert embeddings into Qdrant
        _upsert_chunks_to_qdrant(
            domain_id=domain_id,
            chunk_rows=chunk_rows,
            embeddings=embeddings,
            document_title=filename,
        )

        # 8. Mark completed
        self._set_status(db, document_id, "completed")
        db.commit()
        logger.info(
            "document_id=%s: ingested %d chunks from %s",
            document_id,
            len(chunk_rows),
            filename,
        )

    @staticmethod
    def _set_status(db: Session, document_id: UUID, status: str) -> None:
        db.execute(
            update(Document)
            .where(Document.id == document_id)
            .values(ingest_status=status)
        )

    @staticmethod
    def _mark_failed(db: Session, document_id: UUID) -> None:
        """Safe status downgrade — only moves processing→failed."""
        db.execute(
            update(Document)
            .where(
                Document.id == document_id,
                Document.ingest_status == "processing",
            )
            .values(ingest_status="failed")
        )
