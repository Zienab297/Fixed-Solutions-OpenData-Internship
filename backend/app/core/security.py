"""
Authentication and authorization utilities.
Handles both OIDC tokens (human users) and API keys (machine clients).
"""
import hashlib
import secrets
from typing import Optional
from fastapi import HTTPException, Security, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, APIKeyHeader
from jose import jwt, JWTError
import httpx
from app.core.config import settings

bearer_scheme = HTTPBearer(auto_error=False)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def hash_api_key(raw_key: str) -> str:
    """Hash API key before storing — never store raw keys."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


def generate_api_key() -> tuple[str, str]:
    """Generate a new API key. Returns (raw_key, hashed_key)."""
    raw_key = f"sk-{secrets.token_urlsafe(32)}"
    return raw_key, hash_api_key(raw_key)


async def get_keycloak_public_key() -> str:
    """Fetch Keycloak realm public key for token verification."""
    url = f"{settings.KEYCLOAK_URL}/realms/{settings.KEYCLOAK_REALM}"
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()["public_key"]


async def verify_oidc_token(token: str) -> dict:
    """Verify OIDC JWT token from Keycloak."""
    try:
        public_key = await get_keycloak_public_key()
        formatted_key = f"-----BEGIN PUBLIC KEY-----\n{public_key}\n-----END PUBLIC KEY-----"
        payload = jwt.decode(
            token,
            formatted_key,
            algorithms=["RS256"],
            audience=settings.KEYCLOAK_CLIENT_ID,
        )
        return payload
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}",
        )
