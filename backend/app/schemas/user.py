from pydantic import BaseModel, EmailStr
from uuid import UUID
from typing import Optional
import datetime


class UserOut(BaseModel):
    id: UUID
    keycloak_id: str
    email: str
    user_pool: str
    role: Optional[str] = None
    created_at: datetime.datetime

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    user: UserOut


class CreateUserRequest(BaseModel):
    email: EmailStr
    password: str
    role: str  # "reader" | "contributor"
    domain_id: UUID