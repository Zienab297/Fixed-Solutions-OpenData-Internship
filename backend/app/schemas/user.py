from pydantic import BaseModel
from app.models.user import Role

class UserOut(BaseModel):
    keycloak_id: str
    email: str
    role: Role

    model_config = {"from_attributes": True}