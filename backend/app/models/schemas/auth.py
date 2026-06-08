from pydantic import BaseModel
from typing import Optional, List
from uuid import UUID

class CurrentUser(BaseModel):
    id: str
    email: Optional[str]
    user_pool: str  # 'internal', 'external', 'api'
    auth_method: str  # 'oidc', 'api_key'
    allowed_domains: Optional[List[UUID]] = None
    role: Optional[str] = None
