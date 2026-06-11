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
5. Embed each chunk in small batches
6. INSERT rows into rag.chunks
7. Upsert embeddings into Qdrant
8. Set document.ingest_status = 'completed'
9. On any error → set status = 'failed', re-raise so Celery can retry
"""
from __future__ import annotations

import base64
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
from app.services.ingestion.embedder import EmbeddingService

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Embedding batch size: keep memory use predictable for local model inference.
# ---------------------------------------------------------------------------
_EMBED_BATCH_SIZE = 20


def _embed_texts_sync(texts: list[str]) -> list[list[float]]:
    """
    Embed texts synchronously in small batches.

    Why batched?
    Sending all chunks through the local model at once can spike memory usage.
    Splitting into batches makes progress visible in logs and lets the worker
    recover cheaply on partial failure.

    Falls back to zero vectors per batch if model loading or inference fails (dev/test
    safety) so DB writes still succeed and Qdrant can be re-indexed later.
    """
    embedder = EmbeddingService()
    all_embeddings: list[list[float]] = []

    for batch_start in range(0, len(texts), _EMBED_BATCH_SIZE):
        batch = texts[batch_start : batch_start + _EMBED_BATCH_SIZE]
        try:
            batch_embeddings = embedder.embed_sync(batch)
            all_embeddings.extend(batch_embeddings)
            logger.debug(
                "Embedded batch %d-%d / %d",
                batch_start,
                batch_start + len(batch) - 1,
                len(texts),
            )
        except Exception as exc:
            logger.warning(
                "Embedding failed for batch %d-%d (%s). "
                "Storing zero vectors — re-embed after the model is available.",
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
                vectors_config=VectorParams(
                    size=settings.EMBEDDING_DIMENSION,
                    distance=Distance.COSINE,
                ),
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
# Image extraction helpers (multimodal pipeline)
# ---------------------------------------------------------------------------

def _extract_images_from_pdf(
    file_bytes: bytes,
) -> list[tuple[int, str, bytes, str, str]]:
    """
    Extract all embedded images from a PDF using PyMuPDF.

    Returns a list of tuples:
        (page_number, image_id, image_bytes, mime_type, img_base64)

    - page_number : 1-indexed page where the image lives
    - image_id   : unique key  "page_<N>_img_<M>"  (0-indexed internally)
    - image_bytes: raw image bytes for embedding
    - mime_type  : e.g. "image/png" or "image/jpeg"
    - img_base64 : base64-encoded image (stored in chunk metadata for LLM)
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        logger.warning("PyMuPDF (fitz) not installed; skipping image extraction.")
        return []

    results: list[tuple[int, str, bytes, str, str]] = []
    doc = fitz.open(stream=file_bytes, filetype="pdf")

    for page_index, page in enumerate(doc):
        for img_index, img in enumerate(page.get_images(full=True)):
            try:
                xref = img[0]
                base_image = doc.extract_image(xref)
                image_bytes = base_image["image"]
                image_ext = base_image["ext"]  # e.g. 'png', 'jpeg'

                # Normalise extension to valid MIME type
                mime_type = (
                    "image/jpeg" if image_ext in ("jpg", "jpeg") else f"image/{image_ext}"
                )

                image_id = f"page_{page_index}_img_{img_index}"
                img_base64 = base64.b64encode(image_bytes).decode()

                results.append(
                    (page_index + 1, image_id, image_bytes, mime_type, img_base64)
                )
            except Exception as exc:
                logger.warning(
                    "Skipping image %d on page %d: %s", img_index, page_index, exc
                )

    doc.close()
    return results


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
                        "type": "text",
                    }
                )

        if not all_chunks_data:
            self._set_status(db, document_id, "completed")
            db.commit()
            return

        # 5. Embed text chunks in small batches
        texts = [c["content"] for c in all_chunks_data]
        logger.info(
            "document_id=%s: embedding %d text chunks in batches of %d",
            document_id,
            len(texts),
            _EMBED_BATCH_SIZE,
        )
        text_embeddings = _embed_texts_sync(texts)

        # 6. Build and INSERT text Chunk ORM rows
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

        all_embeddings = list(text_embeddings)

        # ---------- Multimodal: extract & embed images (PDF only) ----------
        image_chunk_rows: list[ChunkModel] = []
        image_embeddings: list[list[float]] = []

        if filename.lower().endswith(".pdf"):
            embedder = EmbeddingService()
            extracted_images = _extract_images_from_pdf(file_content)
            logger.info(
                "document_id=%s: found %d images in %s",
                document_id,
                len(extracted_images),
                filename,
            )

            for page_number, image_id, image_bytes, mime_type, img_base64 in extracted_images:
                try:
                    img_embedding = embedder.embed_image_sync(image_bytes, mime_type)
                    image_embeddings.append(img_embedding)

                    image_chunk_index = len(all_chunks_data) + len(image_chunk_rows)
                    img_row = ChunkModel(
                        document_id=document_id,
                        domain_id=domain_id,
                        # Placeholder content mirrors multimodal_rag_pipeline convention
                        content=f"[Image: {image_id}]",
                        chunk_index=image_chunk_index,
                        page_number=page_number,
                        section=None,
                        embedding_model=settings.EMBEDDING_MODEL,
                        metadata_={
                            "type": "image",
                            "image_id": image_id,
                            "mime_type": mime_type,
                            # Store base64 so the generation LLM can retrieve it
                            "image_base64": img_base64,
                        },
                    )
                    image_chunk_rows.append(img_row)
                    all_embeddings.append(img_embedding)

                except Exception as exc:
                    logger.warning(
                        "document_id=%s: failed to embed image %s (%s)",
                        document_id,
                        image_id,
                        exc,
                    )
        # -------------------------------------------------------------------

        db.add_all(chunk_rows)
        if image_chunk_rows:
            db.add_all(image_chunk_rows)
        db.flush()  # assign IDs before Qdrant upsert

        # 7. Upsert all embeddings (text + image) into Qdrant
        combined_rows = chunk_rows + image_chunk_rows
        _upsert_chunks_to_qdrant(
            domain_id=domain_id,
            chunk_rows=combined_rows,
            embeddings=all_embeddings,
            document_title=filename,
        )

        # 8. Mark completed
        self._set_status(db, document_id, "completed")
        db.commit()
        logger.info(
            "document_id=%s: ingested %d text chunks + %d image chunks from %s",
            document_id,
            len(chunk_rows),
            len(image_chunk_rows),
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
