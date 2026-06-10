from pydantic import BaseModel
from uuid import UUID
import datetime

class UserOut(BaseModel):
    id: UUID
    keycloak_id: str
    email: str
    user_pool: str
    created_at: datetime.datetime

    model_config = {"from_attributes": True}