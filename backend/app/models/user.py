from sqlalchemy import Column, String, Enum as PgEnum
from sqlalchemy.orm import relationship
from app.core.database import Base
import enum

class Role(str, enum.Enum):
    admin = "admin"
    contributor = "contributor"
    reader = "reader"

class User(Base):
    __tablename__ = "users"

    keycloak_id = Column(String, primary_key=True)  # sub from JWT
    email = Column(String, unique=True, nullable=False)
    role = Column(PgEnum(Role), nullable=False, default=Role.reader)

    created_domains = relationship("Domain", backref="creator")
    domain_memberships = relationship("UserDomainRole", backref="user")