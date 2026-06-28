"""
Destination: app/schemas/document.py
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class DocumentOut(BaseModel):
    id: UUID
    domain_id: UUID
    title: str
    source_type: str
    ingest_status: str
    ocr_used: bool
    language: Optional[str] = None
    has_file: bool
    created_at: datetime
    updated_at: datetime