from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
import jwt as pyjwt
from app.core.config import settings
from app.core.database import get_db
from app.models.user import User, Role


bearer_scheme = HTTPBearer()
_jwks_cache = None

def get_or_create_user(db: Session, keycloak_id: str, email: str, role: Role) -> User:
    user = db.query(User).filter(User.keycloak_id == keycloak_id).first()
    if not user:
        user = User(keycloak_id=keycloak_id, email=email, role=role)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def decode_token(token: str) -> dict:
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

    role = Role.reader
    if "admin" in realm_roles:
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