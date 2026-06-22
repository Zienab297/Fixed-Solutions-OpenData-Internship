"""
DocumentProcessor — wires together extraction, chunking, embedding, and
Postgres writes for the rag.documents / rag.chunks tables.

Called by the Celery task inside asyncio.run(), so it uses the *sync*
SessionLocal from database.py.  All DB operations here are synchronous.

Flow
----
1. Set document.ingest_status = 'processing'
2. Extract text blocks from the file bytes
3. Fetch domain chunk_size / chunk_overlap settings
4. Chunk the text
5. Embed each chunk in small batches (via Ollama)
6. INSERT rows into rag.chunks
7. Upsert embeddings into Qdrant
8. Set document.ingest_status = 'completed'
9. On any error → set status = 'failed', re-raise so Celery can retry
"""
from __future__ import annotations

import json
import logging
from uuid import UUID

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.config import settings
from app.models.db.models import Chunk as ChunkModel, Document, Domain
from app.services.ingestion.chunker import ChunkerService
from app.services.ingestion.extractors import ExtractedBlock, extract_document

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Embedding batch size: keep small enough for large CSV-derived chunks on CPU.
# ---------------------------------------------------------------------------
_EMBED_BATCH_SIZE = 5
_EMBED_TIMEOUT_SECONDS = 120.0


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

        # 3. Extract text blocks
        document = db.execute(
            select(Document).where(Document.id == document_id)
        ).scalar_one_or_none()
        source_type = document.source_type if document else None
        blocks = extract_document(filename, file_content, source_type)
        ocr_used = _blocks_used_ocr(blocks)

        if not blocks or all(not block.text.strip() for block in blocks):
            logger.warning(
                "document_id=%s: no text extracted from %s", document_id, filename
            )
            self._set_status(db, document_id, "completed", ocr_used=ocr_used)
            db.commit()
            return

        # 4. Chunk each extracted block
        all_chunks_data: list[dict] = []
        for block in blocks:
            if not block.text.strip():
                continue

            if block.metadata.get("source_type") == "csv":
                all_chunks_data.append(
                    {
                        "content": block.text,
                        "chunk_index": len(all_chunks_data),
                        "page_number": block.page_number,
                        "section": block.section,
                        "metadata": _merge_metadata(block, None),
                    }
                )
                continue

            chunks = self.chunker.chunk_text(
                block.text,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                page_number=block.page_number,
                section=block.section,
            )
            for c in chunks:
                all_chunks_data.append(
                    {
                        "content": c.content,
                        "chunk_index": len(all_chunks_data),
                        "page_number": c.page_number,
                        "section": c.section,
                        "metadata": _merge_metadata(block, c.metadata),
                    }
                )

        if not all_chunks_data:
            self._set_status(db, document_id, "completed", ocr_used=ocr_used)
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

        # 7. Persist structured CSV rows for deterministic table QA.
        if source_type == "csv":
            _replace_structured_table_rows(
                db=db,
                document_id=document_id,
                domain_id=domain_id,
                chunk_rows=chunk_rows,
            )

        # 8. Upsert embeddings into Qdrant
        _upsert_chunks_to_qdrant(
            domain_id=domain_id,
            chunk_rows=chunk_rows,
            embeddings=embeddings,
            document_title=filename,
        )

        # 9. Mark completed
        self._set_status(db, document_id, "completed", ocr_used=ocr_used)
        db.commit()
        logger.info(
            "document_id=%s: ingested %d chunks from %s",
            document_id,
            len(chunk_rows),
            filename,
        )

    @staticmethod
    def _set_status(
        db: Session,
        document_id: UUID,
        status: str,
        *,
        ocr_used: bool | None = None,
    ) -> None:
        values = {"ingest_status": status}
        if ocr_used is not None:
            values["ocr_used"] = ocr_used

        db.execute(
            update(Document)
            .where(Document.id == document_id)
            .values(**values)
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


def _merge_metadata(block: ExtractedBlock, chunk_metadata: dict | None) -> dict:
    metadata = dict(block.metadata or {})
    metadata.update(chunk_metadata or {})
    return metadata


def _blocks_used_ocr(blocks: list[ExtractedBlock]) -> bool:
    return any(
        block.metadata.get("ocr_used") is True
        or block.metadata.get("block_type") == "ocr"
        for block in blocks
    )


def _replace_structured_table_rows(
    db: Session,
    document_id: UUID,
    domain_id: UUID,
    chunk_rows: list[ChunkModel],
) -> None:
    _ensure_table_rows_schema(db)

    db.execute(
        text("DELETE FROM rag.table_rows WHERE document_id = :document_id"),
        {"document_id": str(document_id)},
    )

    for chunk in chunk_rows:
        rows = (chunk.metadata_ or {}).get("rows") or []
        if not isinstance(rows, list):
            continue

        for row in rows:
            if not isinstance(row, dict):
                continue
            values = row.get("values")
            if not isinstance(values, dict):
                continue
            row_number = row.get("row_number")
            if not isinstance(row_number, int):
                continue

            db.execute(
                text(
                    """
                    INSERT INTO rag.table_rows (
                        document_id, domain_id, chunk_id, row_number, row_data
                    )
                    VALUES (
                        :document_id,
                        :domain_id,
                        :chunk_id,
                        :row_number,
                        CAST(:row_data AS jsonb)
                    )
                    ON CONFLICT (document_id, row_number)
                    DO UPDATE SET
                        domain_id = EXCLUDED.domain_id,
                        chunk_id = EXCLUDED.chunk_id,
                        row_data = EXCLUDED.row_data
                    """
                ),
                {
                    "document_id": str(document_id),
                    "domain_id": str(domain_id),
                    "chunk_id": str(chunk.id),
                    "row_number": row_number,
                    "row_data": json.dumps({str(k): str(v) for k, v in values.items()}),
                },
            )


def _ensure_table_rows_schema(db: Session) -> None:
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS rag.table_rows (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                document_id UUID NOT NULL REFERENCES rag.documents(id) ON DELETE CASCADE,
                domain_id UUID NOT NULL REFERENCES rag.domains(id) ON DELETE CASCADE,
                chunk_id UUID REFERENCES rag.chunks(id) ON DELETE SET NULL,
                row_number INTEGER NOT NULL,
                row_data JSONB NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE (document_id, row_number)
            )
            """
        )
    )
    db.execute(text("CREATE INDEX IF NOT EXISTS idx_table_rows_domain ON rag.table_rows(domain_id)"))
    db.execute(text("CREATE INDEX IF NOT EXISTS idx_table_rows_document ON rag.table_rows(document_id)"))
    db.execute(text("CREATE INDEX IF NOT EXISTS idx_table_rows_chunk ON rag.table_rows(chunk_id)"))
    db.execute(text("CREATE INDEX IF NOT EXISTS idx_table_rows_data_gin ON rag.table_rows USING GIN (row_data)"))
