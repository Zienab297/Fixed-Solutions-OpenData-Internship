from fastapi import APIRouter, Depends
from app.models.user import User, Role
from app.api.v1.dependencies.auth import get_current_user, require_role
from app.schemas.user import UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me", response_model=UserOut)
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.get("/admin-only")
async def admin_route(current_user: User = Depends(require_role(Role.admin))):
    return {"message": f"Hello admin {current_user.email}"}