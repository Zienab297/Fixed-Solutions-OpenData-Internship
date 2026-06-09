from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.v1.dependencies.auth import get_current_user, require_role
from app.core.database import get_db
from app.core.security import (
    create_access_token,
    get_or_create_user,
    local_user_id,
)
from app.models.user import User, Role
from app.schemas.user import LoginRequest, TokenResponse, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/login", response_model=TokenResponse)
def login(data: LoginRequest, db: Session = Depends(get_db)):
    email = data.email.strip().lower()
    if not email or not data.password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email and password are required.",
        )

    user = get_or_create_user(
        db=db,
        keycloak_id=local_user_id(email),
        email=email,
        role=Role.admin,
    )
    token = create_access_token(
        keycloak_id=user.keycloak_id,
        email=user.email,
        role=user.role,
    )
    return TokenResponse(access_token=token, user=user)

@router.get("/me", response_model=UserOut)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user

@router.get("/admin-only")
def admin_route(current_user: User = Depends(require_role(Role.admin))):
    return {"message": f"Hello admin {current_user.email}"}
