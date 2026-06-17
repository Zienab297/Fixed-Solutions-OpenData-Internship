from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import get_db
from app.core.security import (
    create_access_token,
    get_current_user,
    get_user_by_email,
    hash_password,
    keycloak_create_user,
    keycloak_login,
)
from app.models.db.models import Domain, DomainRole, User
from app.schemas.user import CreateUserRequest, TokenResponse, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])

ROLE_RANK = {"reader": 0, "contributor": 1, "domain_admin": 2, "admin": 3}


def _top_role(user: User) -> str:
    if user.email == settings.ADMIN_EMAIL:
        return "admin"
    roles = [dr.role for dr in (user.domain_roles or [])]
    return max(roles, key=lambda r: ROLE_RANK.get(r, 0)) if roles else "reader"


def _is_system_admin(user: User) -> bool:
    return user.email == settings.ADMIN_EMAIL


def _caller_domain_role(user: User, domain_id: str) -> str | None:
    for dr in (user.domain_roles or []):
        if str(dr.domain_id) == domain_id:
            return dr.role
    return None


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

@router.post("/token", response_model=TokenResponse)
async def login(
    form: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    if settings.DEV_MODE:
        # Local DB auth — no Keycloak needed
        from app.core.security import verify_password
        user = await get_user_by_email(db, form.username)
        if not user or not getattr(user, "password_hash", None):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
            )
        if not verify_password(form.password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
            )
        token = create_access_token(keycloak_id=str(user.keycloak_id), email=user.email)
        token_type = "bearer"
    else:
        # Full Keycloak flow
        kc_response = await keycloak_login(form.username, form.password)
        token = kc_response["access_token"]
        token_type = kc_response.get("token_type", "bearer")

        # Ensure user exists locally (first login auto-provision)
        user = await get_user_by_email(db, form.username)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User authenticated but not provisioned locally. Contact an admin.",
            )

    return TokenResponse(
        access_token=token,
        token_type=token_type,
        user=UserOut(
            id=user.id,
            keycloak_id=user.keycloak_id,
            email=user.email,
            user_pool=user.user_pool,
            role=_top_role(user),
            created_at=user.created_at,
        ),
    )


# ---------------------------------------------------------------------------
# Current user
# ---------------------------------------------------------------------------

@router.get("/me", response_model=UserOut)
async def get_me(current_user: User = Depends(get_current_user)):
    return UserOut(
        id=current_user.id,
        keycloak_id=current_user.keycloak_id,
        email=current_user.email,
        user_pool=current_user.user_pool,
        role=_top_role(current_user),
        created_at=current_user.created_at,
    )


# ---------------------------------------------------------------------------
# Create user
#
# Permissions:
#   - System admin (ADMIN_EMAIL): any domain, any role including domain_admin
#   - Domain admin: only their own domain(s), roles limited to reader/contributor
#   - Anyone else: 403
# ---------------------------------------------------------------------------

@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: CreateUserRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    is_sysadmin = _is_system_admin(current_user)
    caller_role_on_domain = _caller_domain_role(current_user, str(payload.domain_id))

    # Permission check
    if not is_sysadmin and caller_role_on_domain != "domain_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to create users in this domain",
        )

    # Role validation
    allowed_roles = {"reader", "contributor", "domain_admin"} if is_sysadmin else {"reader", "contributor"}
    if payload.role not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Role must be one of: {', '.join(sorted(allowed_roles))}",
        )

    # Domain existence check
    domain_result = await db.execute(select(Domain).where(Domain.id == payload.domain_id))
    domain = domain_result.scalar_one_or_none()
    if not domain:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Domain not found")

    # Create or fetch the user
    existing_result = await db.execute(
        select(User).where(User.email == payload.email).options(selectinload(User.domain_roles))
    )
    new_user = existing_result.scalar_one_or_none()

    if not new_user:
        if settings.DEV_MODE:
            from uuid import uuid4
            new_user = User(
                keycloak_id=str(uuid4()),
                email=payload.email,
                user_pool="internal",
                password_hash=hash_password(payload.password),
            )
        else:
            keycloak_id = await keycloak_create_user(
                email=payload.email,
                password=payload.password,
                user_pool="internal",
            )
            new_user = User(
                keycloak_id=keycloak_id,
                email=payload.email,
                user_pool="internal",
            )

        db.add(new_user)
        await db.flush()
        await db.refresh(new_user)

    # Assign or update domain role
    existing_role_result = await db.execute(
        select(DomainRole).where(
            DomainRole.user_id == new_user.id,
            DomainRole.domain_id == payload.domain_id,
        )
    )
    domain_role = existing_role_result.scalar_one_or_none()

    if domain_role:
        domain_role.role = payload.role
        domain_role.granted_by = current_user.id
    else:
        db.add(DomainRole(
            user_id=new_user.id,
            domain_id=payload.domain_id,
            role=payload.role,
            granted_by=current_user.id,
        ))

    await db.commit()

    return UserOut(
        id=new_user.id,
        keycloak_id=new_user.keycloak_id,
        email=new_user.email,
        user_pool=new_user.user_pool,
        role=payload.role,
        created_at=new_user.created_at,
    )