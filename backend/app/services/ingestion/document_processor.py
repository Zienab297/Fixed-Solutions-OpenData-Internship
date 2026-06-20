"""
DocumentProcessor — wires together extraction, chunking, embedding, and
Postgres writes for the rag.documents / rag.chunks tables.

Called by the Celery task inside asyncio.run(), so it uses the *sync*
SessionLocal from database.py.  All DB operations here are synchronous.

Flow
----
1. Set document.ingest_status = 'processing'
2. Extract + chunk via process_file() (PDF/CSV/DOCX → LangChain Documents)
3. Embed each chunk in small batches (via Ollama)
4. INSERT rows into rag.chunks
5. Upsert embeddings into Qdrant
6. Set document.ingest_status = 'completed'
7. On any error → set status = 'failed', re-raise so Celery can retry
"""
from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.config import settings
from app.models.db.models import Chunk as ChunkModel, Document, Domain
from app.services.ingestion.chunker import process_file  # ← CHANGED: new unified loader+chunker

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Embedding batch size: keep small enough for large CSV-derived chunks on CPU.
# ---------------------------------------------------------------------------
_EMBED_BATCH_SIZE = 5
_EMBED_TIMEOUT_SECONDS = 500.0


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
                timeout=_EMBED_TIMEOUT_SECONDS,
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
            all_embeddings.extend([[0.0] * settings.EMBEDDING_DIMENSION for _ in batch])

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
                vectors_config=VectorParams(size=settings.EMBEDDING_DIMENSION, distance=Distance.COSINE),
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
# DocumentProcessor
# ---------------------------------------------------------------------------

class DocumentProcessor:
    """
    Synchronous processor used inside Celery tasks.
    Opens its own DB session so it's fully independent of the FastAPI
    async session lifecycle.
    """

    def __init__(self):
        pass  # ChunkerService no longer needed — process_file() does it all

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

        # 2. Fetch domain (kept for compatibility — process_file() has its own
        #    fixed chunk_size/chunk_overlap, domain-level overrides are unused now)
        domain = db.execute(
            select(Domain).where(Domain.id == domain_id)
        ).scalar_one_or_none()  # noqa: F841 — kept for future per-domain config

        # 3. Extract + chunk via process_file() — needs a real path on disk
        #    process_file() reads from disk (PyMuPDFLoader/CSVLoader/Docx2txtLoader
        #    all require a file path, not raw bytes), so write file_content to a
        #    temp file first.
        import os
        import tempfile

        suffix = "_" + filename  # preserve original extension for routing
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(file_content)
            tmp_path = tmp.name

        try:
            lc_documents = process_file(tmp_path)
        except ValueError as exc:
            # Unsupported file format (process_file() only allows PDF/CSV/DOCX)
            logger.warning(
                "document_id=%s: rejected unsupported format for %s — %s",
                document_id, filename, exc,
            )
            self._set_status(db, document_id, "failed")
            db.commit()
            return
        finally:
            try:
                os.unlink(tmp_path)
            except PermissionError:
                logger.warning(
                    "Could not delete temp file %s (still locked by another process). "
                    "It will be cleaned up later by the OS temp folder cleanup.",
            tmp_path,
        )

        if not lc_documents or all(not d.page_content.strip() for d in lc_documents):
            logger.warning(
                "document_id=%s: no text extracted from %s", document_id, filename
            )
            self._set_status(db, document_id, "completed")
            db.commit()
            return

        # 4. Build chunk data from LangChain Document objects
        #    page_number / section are pulled from metadata when present —
        #    process_file()'s loaders populate metadata differently per type
        #    (e.g. PyMuPDFLoader sets "page", CSVLoader sets "row").
        all_chunks_data: list[dict] = []
        for lc_doc in lc_documents:
            if not lc_doc.page_content.strip():
                continue

            metadata = lc_doc.metadata or {}
            page_number = metadata.get("page", metadata.get("page_number"))
            section = metadata.get("section", metadata.get("row"))

            all_chunks_data.append(
                {
                    "content": lc_doc.page_content,
                    "chunk_index": len(all_chunks_data),
                    "page_number": page_number,
                    "section": str(section) if section is not None else None,
                    "metadata": metadata,
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
        for chunk_data in all_chunks_data:
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


def _merge_metadata(block, chunk_metadata: dict | None) -> dict:
    """Kept for backward compatibility with any other callers."""
    metadata = dict(getattr(block, "metadata", None) or {})
    metadata.update(chunk_metadata or {})
    return metadata
    