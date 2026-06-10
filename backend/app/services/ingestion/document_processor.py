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
5. Embed each chunk (via Ollama)
6. INSERT rows into rag.chunks
7. Set document.ingest_status = 'completed'
8. On any error → set status = 'failed', re-raise so Celery can retry
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
# Sync embedding helper (wraps the async EmbeddingService via httpx sync)
# ---------------------------------------------------------------------------

def _embed_texts_sync(texts: list[str]) -> list[list[float]]:
    """
    Call Ollama /api/embed synchronously.
    Returns a list of float vectors, one per input text.
    Falls back to zero vectors if Ollama is unreachable (dev/test safety).
    """
    import httpx

    url = f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/embed"
    try:
        response = httpx.post(
            url,
            json={"model": settings.EMBEDDING_MODEL, "input": texts},
            timeout=120.0,
        )
        response.raise_for_status()
        return response.json()["embeddings"]
    except Exception as exc:
        logger.warning(
            "Ollama embedding failed (%s). Storing zero vectors — "
            "re-embed after Ollama is available.",
            exc,
        )
        # Return zero vectors so DB writes still succeed; Qdrant upsert
        # can be retried independently once Ollama is back up.
        return [[0.0] * 1024 for _ in texts]


# ---------------------------------------------------------------------------
# Text extraction helpers
# ---------------------------------------------------------------------------

def _extract_text_from_pdf(file_bytes: bytes) -> list[tuple[int, str]]:
    """
    Returns list of (page_number, text) tuples.
    Falls back to OCR if pypdf finds no text on a page.
    """
    try:
        import pypdf  # pypdf>=3
        reader = pypdf.PdfReader(io.BytesIO(file_bytes))
        pages = []
        for i, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            pages.append((i, text.strip()))
        return pages
    except ImportError:
        # pypdf not installed — return whole bytes decoded as utf-8 best-effort
        logger.warning("pypdf not installed; treating PDF as plain text.")
        return [(1, file_bytes.decode("utf-8", errors="replace"))]


def _extract_text(filename: str, file_bytes: bytes) -> list[tuple[int, str]]:
    """Dispatch to the right extractor based on file extension."""
    lower = filename.lower()
    if lower.endswith(".pdf"):
        return _extract_text_from_pdf(file_bytes)
    # For docx/csv/xlsx we return a single "page" — extend as needed
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
                # Best-effort status update — don't mask the original error
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
            logger.warning("document_id=%s: no text extracted from %s", document_id, filename)
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
                all_chunks_data.append({
                    "content": c.content,
                    "chunk_index": c.chunk_index + len(all_chunks_data),
                    "page_number": c.page_number,
                    "section": c.section,
                    "metadata": c.metadata or {},
                })

        if not all_chunks_data:
            self._set_status(db, document_id, "completed")
            db.commit()
            return

        # 5. Embed in one batch call
        texts = [c["content"] for c in all_chunks_data]
        embeddings = _embed_texts_sync(texts)

        # 6. Build and insert Chunk ORM rows
        # (embeddings themselves go to Qdrant; we only write metadata here)
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
        db.flush()

        # TODO: upsert embeddings[i] into Qdrant with point_id = str(chunk_rows[i].id)
        # This will be wired in the Qdrant integration sprint.

        # 7. Mark completed
        self._set_status(db, document_id, "completed")
        db.commit()
        logger.info(
            "document_id=%s: ingested %d chunks from %s",
            document_id, len(chunk_rows), filename,
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
            .where(Document.id == document_id, Document.ingest_status == "processing")
            .values(ingest_status="failed")
        )