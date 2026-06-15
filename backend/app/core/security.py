from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
import bcrypt
import jwt as pyjwt

from app.core.config import settings
from app.core.database import get_db
from app.models.db.models import User, DomainRole

bearer_scheme = HTTPBearer(auto_error=True)

ALGORITHM = "HS256"

# ---------------------------------------------------------------------------
# DEV_MODE password helpers (unused when DEV_MODE=False)
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


# ---------------------------------------------------------------------------
# DEV_MODE: local JWT
# ---------------------------------------------------------------------------

def create_access_token(keycloak_id: str, email: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": keycloak_id, "email": email, "exp": expire}
    return pyjwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def _decode_local_token(token: str) -> dict:
    try:
        return pyjwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has expired")
    except pyjwt.PyJWTError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {e}")


# ---------------------------------------------------------------------------
# Keycloak: exchange credentials for token
# ---------------------------------------------------------------------------

async def keycloak_login(email: str, password: str) -> dict:
    """
    Call Keycloak's token endpoint with the user's credentials.
    Returns the full Keycloak token response.
    """
    token_url = (
        f"{settings.KEYCLOAK_URL}/realms/{settings.KEYCLOAK_REALM}"
        f"/protocol/openid-connect/token"
    )
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            token_url,
            data={
                "grant_type": "password",
                "client_id": settings.KEYCLOAK_CLIENT_ID,
                "client_secret": settings.KEYCLOAK_CLIENT_SECRET,
                "username": email,
                "password": password,
                "scope": "openid email profile",
            },
        )
    if resp.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )
    return resp.json()


async def keycloak_create_user(
    email: str,
    password: str,
    user_pool: str = "internal",
) -> str:
    """
    Create a user in Keycloak via the Admin REST API.
    Returns the new user's Keycloak ID (UUID string).
    """
    token_url = (
        f"{settings.KEYCLOAK_URL}/realms/master/protocol/openid-connect/token"
    )
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": settings.KEYCLOAK_CLIENT_ID,
                "client_secret": settings.KEYCLOAK_CLIENT_SECRET,
            },
        )
        if token_resp.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Could not obtain Keycloak admin token",
            )
        admin_token = token_resp.json()["access_token"]

        users_url = (
            f"{settings.KEYCLOAK_URL}/admin/realms/{settings.KEYCLOAK_REALM}/users"
        )
        create_resp = await client.post(
            users_url,
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "username": email,
                "email": email,
                "enabled": True,
                "attributes": {"user_pool": [user_pool]},
                "credentials": [
                    {"type": "password", "value": password, "temporary": False}
                ],
            },
        )

    if create_resp.status_code == 409:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists in Keycloak",
        )
    if create_resp.status_code not in (200, 201):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Keycloak user creation failed: {create_resp.text}",
        )

    # Keycloak returns the new user URL in the Location header
    location = create_resp.headers.get("Location", "")
    keycloak_id = location.rstrip("/").split("/")[-1]
    if not keycloak_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Keycloak did not return a user ID",
        )
    return keycloak_id


def _decode_keycloak_token(token: str) -> dict:
    """
    Decode a Keycloak JWT without signature verification.
    For production, replace this with JWKS-based verification using python-keycloak.
    """
    try:
        return pyjwt.decode(token, options={"verify_signature": False})
    except pyjwt.PyJWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {e}",
        )


# ---------------------------------------------------------------------------
# User lookup
# ---------------------------------------------------------------------------

async def get_user_by_email(db: AsyncSession, email: str) -> Optional[User]:
    result = await db.execute(
        select(User).where(User.email == email).options(selectinload(User.domain_roles))
    )
    return result.scalar_one_or_none()


async def get_user_by_keycloak_id(db: AsyncSession, keycloak_id: str) -> Optional[User]:
    result = await db.execute(
        select(User).where(User.keycloak_id == keycloak_id).options(selectinload(User.domain_roles))
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# FastAPI dependency — get current user from token
# ---------------------------------------------------------------------------

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    token = credentials.credentials

    if settings.DEV_MODE:
        payload = _decode_local_token(token)
    else:
        payload = _decode_keycloak_token(token)

    keycloak_id = payload.get("sub")
    if not keycloak_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user = await get_user_by_keycloak_id(db, keycloak_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    return user


# ---------------------------------------------------------------------------
# Domain role guard
# ---------------------------------------------------------------------------

def require_domain_role(*allowed_roles: str):
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