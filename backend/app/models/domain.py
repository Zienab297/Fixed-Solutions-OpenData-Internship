 
from sqlalchemy import Column, String, Boolean, ForeignKey, Enum as PgEnum, DateTime
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.user import Role
import uuid
import datetime

def generate_uuid():
    return str(uuid.uuid4())

class Domain(Base):
    __tablename__ = "domains"

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, unique=True, nullable=False)
    description = Column(String, nullable=True)
    is_archived = Column(Boolean, default=False)
    created_by = Column(String, ForeignKey("users.keycloak_id"), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # relationships
    memberships = relationship("UserDomainRole", back_populates="domain")

class UserDomainRole(Base):
    __tablename__ = "user_domain_roles"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.keycloak_id"), nullable=False)
    domain_id = Column(String, ForeignKey("domains.id"), nullable=False)
    role = Column(PgEnum(Role), nullable=False, default=Role.reader)

    # relationships
    domain = relationship("Domain", back_populates="memberships")