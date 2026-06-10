from uuid import UUID

from pydantic import AnyUrl, BaseModel, Field


class WebIngestRequest(BaseModel):
    domain_id: UUID
    seed_urls: list[AnyUrl] = Field(min_length=1)
    max_depth: int = Field(default=2, ge=0, le=5)


class IngestJobResponse(BaseModel):
    job_id: str
    document_id: UUID | None = None
    status: str
    message: str
