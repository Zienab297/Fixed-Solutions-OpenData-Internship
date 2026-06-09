from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, uuid5

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session
import jwt as pyjwt
from app.core.config import settings
from app.core.database import get_db
from app.models.user import User, Role


bearer_scheme = HTTPBearer()
_jwks_cache = None
LOCAL_AUTH_ISSUER = "sprint1-local-auth"


def local_user_id(email: str) -> str:
    normalized = email.strip().lower()
    return f"local:{uuid5(NAMESPACE_URL, normalized)}"


def create_access_token(
    keycloak_id: str,
    email: str,
    role: Role,
    expires_minutes: int = 60 * 24,
) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
    payload = {
        "sub": keycloak_id,
        "email": email,
        "role": role.value,
        "realm_access": {"roles": [role.value]},
        "iss": LOCAL_AUTH_ISSUER,
        "exp": expires_at,
    }
    return pyjwt.encode(payload, settings.APP_SECRET_KEY, algorithm="HS256")

def get_or_create_user(db: Session, keycloak_id: str, email: str, role: Role) -> User:
    user = db.query(User).filter(User.keycloak_id == keycloak_id).first()
    if not user:
        user = User(keycloak_id=keycloak_id, email=email, role=role)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def _decode_local_token(token: str) -> dict | None:
    try:
        return pyjwt.decode(
            token,
            settings.APP_SECRET_KEY,
            algorithms=["HS256"],
            issuer=LOCAL_AUTH_ISSUER,
        )
    except pyjwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
        ) from exc
    except pyjwt.PyJWTError:
        return None


def decode_token(token: str) -> dict:
    local_payload = _decode_local_token(token)
    if local_payload is not None:
        return local_payload

    # PyJWT can use the JWKS directly
    jwks_client = pyjwt.PyJWKClient(
        f"{settings.KEYCLOAK_URL}/realms/{settings.KEYCLOAK_REALM}/protocol/openid-connect/certs"
    )
    try:
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        return pyjwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            options={"verify_aud": False}
        )
    except pyjwt.PyJWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {e}"
        )

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db)
) -> User:
    payload = decode_token(credentials.credentials)
    keycloak_id = payload.get("sub")
    email = payload.get("email", "")
    realm_roles = payload.get("realm_access", {}).get("roles", [])
    role_value = payload.get("role")

    if not keycloak_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token: missing subject",
        )

    role = Role.reader
    if role_value in Role._value2member_map_:
        role = Role(role_value)
    elif "admin" in realm_roles:
        role = Role.admin
    elif "contributor" in realm_roles:
        role = Role.contributor

    return get_or_create_user(db, keycloak_id, email, role)

def require_role(*allowed_roles: Role):
    def checker(current_user: User = Depends(get_current_user)):
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions"
            )
        return current_user
    return checker
