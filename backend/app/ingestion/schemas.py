import datetime
from typing import Literal

from pydantic import BaseModel


IngestionStatus = Literal["pending", "processing", "done", "failed"]


class IngestStatus(BaseModel):
    id: str
    status: IngestionStatus
    domain_id: str
    filename: str
    error_message: str | None = None
    created_at: datetime.datetime
    updated_at: datetime.datetime

    model_config = {"from_attributes": True}
