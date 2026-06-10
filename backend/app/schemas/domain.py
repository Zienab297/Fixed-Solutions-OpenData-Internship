from pydantic import BaseModel
from uuid import UUID
from typing import Optional, List
import datetime

# --- Domain schemas ---

class DomainCreate(BaseModel):
    name: str
    description: Optional[str] = None
    llm_route: Optional[str] = "auto"
    confidence_threshold: Optional[float] = 0.7
    chunk_size: Optional[int] = 512
    chunk_overlap: Optional[int] = 64
    supported_languages: Optional[List[str]] = ["en"]

class DomainOut(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    status: str
    llm_route: str
    confidence_threshold: float
    chunk_size: int
    chunk_overlap: int
    supported_languages: List[str]
    created_at: datetime.datetime

    model_config = {"from_attributes": True}

class DomainArchive(BaseModel):
    archived: bool  # True = archive, False = restore

# --- Domain role / membership schemas ---

class MembershipCreate(BaseModel):
    user_id: UUID
    role: str  # 'domain_admin' | 'contributor' | 'reader'

class MembershipOut(BaseModel):
    id: UUID
    user_id: UUID
    domain_id: UUID
    role: str
    granted_at: datetime.datetime

    model_config = {"from_attributes": True}    