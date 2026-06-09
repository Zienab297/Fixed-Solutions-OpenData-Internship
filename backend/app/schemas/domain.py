from pydantic import BaseModel
from app.models.user import Role
from typing import Optional
import datetime

# --- Domain schemas ---

class DomainCreate(BaseModel):
    name: str
    description: Optional[str] = None

class DomainOut(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    is_archived: bool
    created_by: str
    created_at: datetime.datetime

    model_config = {"from_attributes": True}

class DomainArchive(BaseModel):
    is_archived: bool

# --- Membership schemas ---

class MembershipCreate(BaseModel):
    user_id: str
    role: Role

class MembershipOut(BaseModel):
    id: str
    user_id: str
    domain_id: str
    role: Role

    model_config = {"from_attributes": True} 
