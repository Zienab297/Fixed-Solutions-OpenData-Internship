from pydantic import BaseModel, Field
from app.models.user import Role


class LoginRequest(BaseModel):
    email: str = Field(min_length=3)
    password: str = Field(min_length=1)

class UserOut(BaseModel):
    keycloak_id: str
    email: str
    role: Role

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
