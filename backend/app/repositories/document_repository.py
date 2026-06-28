"""
DocumentRepository — the only place that touches rag.documents and rag.chunks.

Duplicate detection logic:
- Same hash + same domain          → exact duplicate, reject silently
- Same title + same domain         → file changed, raise FileChangedError
- Different title, different hash  → new document, insert normally
"""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db.models import Chunk, Document


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class DuplicateDocumentError(Exception):
    """Same file (same hash) already exists in this domain — no action needed."""
    def __init__(self, existing_id: UUID):
        self.existing_id = existing_id
        super().__init__(f"Document already exists with id={existing_id}")


class FileChangedError(Exception):
    """
    Same title in this domain but different hash — file has been modified.
    Caller should ask the user: replace or keep the old version?
    """
    def __init__(self, existing_id: UUID, existing_hash: str, new_hash: str):
        self.existing_id = existing_id
        self.existing_hash = existing_hash
        self.new_hash = new_hash
        super().__init__(
            f"File changed for document id={existing_id} "
            f"(old={existing_hash[:8]}… new={new_hash[:8]}…)"
        )


# ---------------------------------------------------------------------------
# DocumentRepository
# ---------------------------------------------------------------------------

class DocumentRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------

    async def find_by_hash(self, content_hash: str, domain_id: UUID) -> Optional[Document]:
        result = await self.db.execute(
            select(Document).where(
                Document.content_hash == content_hash,
                Document.domain_id == domain_id,
            )
        )
        return result.scalar_one_or_none()

    async def find_by_title(self, title: str, domain_id: UUID) -> Optional[Document]:
        result = await self.db.execute(
            select(Document).where(
                Document.title == title,
                Document.domain_id == domain_id,
            )
        )
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    async def create(
        self,
        *,
        domain_id: UUID,
        title: str,
        source_type: str,
        file_bytes: bytes,
        ingested_by: Optional[UUID] = None,
        source_url: Optional[str] = None,
        author: Optional[str] = None,
        language: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> Document:
        """
        Insert a new document record.

        Raises:
            DuplicateDocumentError  — same hash + same domain (exact copy)
            FileChangedError        — same title + same domain but different hash
        """
        new_hash = Document.hash_content(file_bytes)

        # 1. Exact duplicate check
        exact = await self.find_by_hash(new_hash, domain_id)
        if exact is not None:
            if exact.ingest_status == "failed":
                await self.db.execute(
                    delete(Document).where(Document.id == exact.id)
                )
                await self.db.flush()
            else:
                raise DuplicateDocumentError(exact.id)

        # 2. Changed file check — same title, different hash
        existing = await self.find_by_title(title, domain_id)
        if existing is not None:
            if existing.ingest_status == "failed":
                await self.db.execute(
                    delete(Document).where(Document.id == existing.id)
                )
                await self.db.flush()
            else:
                raise FileChangedError(existing.id, existing.content_hash, new_hash)

        doc = Document(
            domain_id=domain_id,
            title=title,
            source_type=source_type,
            source_url=source_url,
            author=author,
            content_hash=new_hash,
            ingest_status="pending",
            ingested_by=ingested_by,
            language=language,
            metadata_=metadata or {},
        )
        self.db.add(doc)
        await self.db.flush()
        return doc

    # ------------------------------------------------------------------
    # Replace (hard delete old → insert new)
    # ------------------------------------------------------------------

    async def replace(
        self,
        *,
        old_document_id: UUID,
        domain_id: UUID,
        title: str,
        source_type: str,
        file_bytes: bytes,
        ingested_by: Optional[UUID] = None,
        source_url: Optional[str] = None,
        author: Optional[str] = None,
        language: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> Document:
        """
        Hard delete the old document (and its chunks via CASCADE),
        then insert a fresh document with the new hash.

        Called only after the user explicitly confirms they want to replace.
        Returns the new Document.
        """
        # Verify old document exists and belongs to this domain
        old_doc = await self.get_or_raise(old_document_id)
        if old_doc.domain_id != domain_id:
            raise ValueError(
                f"Document {old_document_id} does not belong to domain {domain_id}"
            )

        # Hard delete — chunks cascade via FK ondelete="CASCADE"
        await self.db.execute(
            delete(Document).where(Document.id == old_document_id)
        )
        await self.db.flush()

        # Insert fresh
        new_hash = Document.hash_content(file_bytes)
        new_doc = Document(
            domain_id=domain_id,
            title=title,
            source_type=source_type,
            source_url=source_url,
            author=author,
            content_hash=new_hash,
            ingest_status="pending",
            ingested_by=ingested_by,
            language=language,
            metadata_=metadata or {},
        )
        self.db.add(new_doc)
        await self.db.flush()
        return new_doc

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get(self, document_id: UUID) -> Optional[Document]:
        result = await self.db.execute(
            select(Document).where(Document.id == document_id)
        )
        return result.scalar_one_or_none()

    async def get_or_raise(self, document_id: UUID) -> Document:
        doc = await self.get(document_id)
        if doc is None:
            raise ValueError(f"Document {document_id} not found")
        return doc

    async def list_by_domain(
        self,
        domain_id: UUID,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Document]:
        q = select(Document).where(Document.domain_id == domain_id)
        if status:
            q = q.where(Document.ingest_status == status)
        q = q.order_by(Document.created_at.desc()).limit(limit).offset(offset)
        result = await self.db.execute(q)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Status transitions
    # ------------------------------------------------------------------

    _VALID_TRANSITIONS = {
        "pending": {"processing"},
        "processing": {"completed", "failed"},
    }

    async def update_status(
        self,
        document_id: UUID,
        new_status: str,
        *,
        ocr_used: Optional[bool] = None,
        language: Optional[str] = None,
    ) -> Document:
        doc = await self.get_or_raise(document_id)
        allowed = self._VALID_TRANSITIONS.get(doc.ingest_status, set())
        if new_status not in allowed:
            raise ValueError(
                f"Cannot transition document from '{doc.ingest_status}' to '{new_status}'"
            )
        values: dict = {"ingest_status": new_status}
        if ocr_used is not None:
            values["ocr_used"] = ocr_used
        if language is not None:
            values["language"] = language
        await self.db.execute(
            update(Document).where(Document.id == document_id).values(**values)
        )
        await self.db.refresh(doc)
        return doc

    async def mark_failed(self, document_id: UUID) -> None:
        doc = await self.get(document_id)
        if doc and doc.ingest_status == "processing":
            await self.db.execute(
                update(Document)
                .where(Document.id == document_id)
                .values(ingest_status="failed")
            )


# ---------------------------------------------------------------------------
# ChunkRepository
# ---------------------------------------------------------------------------

class ChunkRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def bulk_create(self, chunks: list[Chunk]) -> list[Chunk]:
        self.db.add_all(chunks)
        await self.db.flush()
        return chunks

    async def list_by_document(self, document_id: UUID) -> list[Chunk]:
        result = await self.db.execute(
            select(Chunk)
            .where(Chunk.document_id == document_id)
            .order_by(Chunk.chunk_index)
        )
        return list(result.scalars().all())

    async def list_by_ids(self, chunk_ids: list[UUID]) -> list[Chunk]:
        if not chunk_ids:
            return []
        result = await self.db.execute(
            select(Chunk).where(Chunk.id.in_(chunk_ids))
        )
        return list(result.scalars().all())

    async def update_graph_nodes(
        self, chunk_id: UUID, graph_node_ids: list[UUID]
    ) -> None:
        await self.db.execute(
            update(Chunk)
            .where(Chunk.id == chunk_id)
            .values(graph_node_ids=graph_node_ids)
        )
