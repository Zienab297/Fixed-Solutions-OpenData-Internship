"""
FastAPI dependencies for authentication and RBAC.
Used in every protected endpoint via Depends().
"""
from uuid import UUID
from typing import Optional
from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.security import bearer_scheme, api_key_header, verify_oidc_token, hash_api_key
from app.models.schemas.auth import CurrentUser


async def get_current_user(
    bearer=Depends(bearer_scheme),
    api_key: Optional[str] = Depends(api_key_header),
    db: AsyncSession = Depends(get_db),
) -> CurrentUser:
    """
    Resolve identity from either OIDC bearer token or API key.
    Returns a unified CurrentUser regardless of auth method.
    """
    if bearer:
        # Human user — OIDC token from Keycloak
        payload = await verify_oidc_token(bearer.credentials)
        return CurrentUser(
            id=payload.get("sub"),
            email=payload.get("email"),
            user_pool=payload.get("user_pool", "internal"),
            auth_method="oidc",
        )

    if api_key:
        # Machine client — API key
        from sqlalchemy import select, text
        key_hash = hash_api_key(api_key)
        result = await db.execute(
            text("""
                SELECT id, owner_id, allowed_domains, role, is_active, expires_at
                FROM rag.api_keys
                WHERE key_hash = :key_hash
            """),
            {"key_hash": key_hash},
        )
        key_record = result.fetchone()

        if not key_record or not key_record.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or inactive API key",
            )

        return CurrentUser(
            id=str(key_record.id),
            email=None,
            user_pool="api",
            auth_method="api_key",
            allowed_domains=key_record.allowed_domains,
            role=key_record.role,
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required. Provide Bearer token or X-API-Key header.",
    )


async def require_domain_access(
    domain_id: UUID,
    required_role: str = "reader",
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CurrentUser:
    """
    RBAC enforcement — server-side, never trust the client.
    Checks user has at least the required role in the given domain.
    """
    # API key users: check pre-configured domain permissions
    if current_user.auth_method == "api_key":
        if domain_id not in (current_user.allowed_domains or []):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"API key not authorized for domain {domain_id}",
            )
        return current_user

    # OIDC users: check domain_roles table
    from sqlalchemy import text
    role_hierarchy = {"reader": 0, "contributor": 1, "domain_admin": 2}
    result = await db.execute(
        text("""
            SELECT role FROM rag.domain_roles
            WHERE user_id = (SELECT id FROM rag.users WHERE keycloak_id = :keycloak_id)
            AND domain_id = :domain_id
        """),
        {"keycloak_id": current_user.id, "domain_id": str(domain_id)},
    )
    row = result.fetchone()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied to domain {domain_id}",
        )

    if role_hierarchy.get(row.role, -1) < role_hierarchy.get(required_role, 0):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Insufficient role. Required: {required_role}, has: {row.role}",
        )

    return current_user
