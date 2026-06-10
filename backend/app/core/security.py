from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import jwt as pyjwt
from app.core.config import settings
from app.core.database import get_db
from app.models.db.models import User, DomainRole

bearer_scheme = HTTPBearer(auto_error=not settings.DEV_MODE)


async def get_or_create_user(
    db: AsyncSession, keycloak_id: str, email: str, user_pool: str = "internal"
) -> User:
    result = await db.execute(select(User).where(User.keycloak_id == keycloak_id))
    user = result.scalar_one_or_none()
    if not user:
        user = User(keycloak_id=keycloak_id, email=email, user_pool=user_pool)
        db.add(user)
        await db.flush()
        await db.refresh(user)
    return user


def decode_token(token: str) -> dict:
    jwks_client = pyjwt.PyJWKClient(
        f"{settings.KEYCLOAK_URL}/realms/{settings.KEYCLOAK_REALM}/protocol/openid-connect/certs"
    )
    try:
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        return pyjwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            options={"verify_aud": False},
        )
    except pyjwt.PyJWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {e}",
        )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    # ── DEV MODE: skip Keycloak entirely ──────────────────────────────────
    if settings.DEV_MODE:
        return await get_or_create_user(
            db,
            keycloak_id=settings.DEV_USER_ID,
            email=settings.DEV_USER_EMAIL,
            user_pool="internal",
        )

    # ── Production: validate JWT ──────────────────────────────────────────
    payload = decode_token(credentials.credentials)
    keycloak_id = payload.get("sub")
    email = payload.get("email", "")

    # Determine pool from realm roles (optional convention)
    realm_roles = payload.get("realm_access", {}).get("roles", [])
    user_pool = "external" if "external_user" in realm_roles else "internal"

    return await get_or_create_user(db, keycloak_id, email, user_pool)


def require_domain_role(*allowed_roles: str):
    """
    Dependency factory: checks the caller has one of `allowed_roles`
    on a specific domain.  The endpoint must also accept `domain_id` as a
    path parameter.
    """
    from fastapi import Path

    async def checker(
        domain_id: str = Path(...),
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        result = await db.execute(
            select(DomainRole).where(
                DomainRole.user_id == current_user.id,
                DomainRole.domain_id == domain_id,
            )
        )
        dr = result.scalar_one_or_none()
        if dr is None or dr.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient domain permissions",
            )
        return current_user

    return checker