from pydantic import BaseModel, HttpUrl
from typing import Optional, List
from uuid import UUID


class DocumentIngestRequest(BaseModel):
    domain_id: UUID
    title: Optional[str] = None


class WebIngestRequest(BaseModel):
    domain_id: UUID
    seed_urls: List[HttpUrl]
    max_depth: int = 2


class IngestJobResponse(BaseModel):
    job_id: str
    document_id: Optional[UUID] = None
    status: str
    message: str


class FileChangedResponse(BaseModel):
    """
    Returned when the same filename exists in the domain but content changed.
    Client should present this to the user and call POST /ingest/replace to confirm.
    """
    error: str                  # always "file_changed"
    existing_document_id: UUID
    old_hash_preview: str       # first 8 chars of old hash — enough for user to see it changed
    new_hash_preview: str       # first 8 chars of new hash
    message: str


class ReplaceDocumentRequest(BaseModel):
    """Multipart form companion — these fields come alongside the new file upload."""
    domain_id: UUID
    old_document_id: UUID
    title: Optional[str] = None