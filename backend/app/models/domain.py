import datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Enum as SQLAlchemyEnum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.user import Role


class Domain(Base):
    __tablename__ = "domains"

    id: Mapped[str] = mapped_column(
        String,
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime,
        default=datetime.datetime.utcnow,
        nullable=False,
    )


class UserDomainRole(Base):
    __tablename__ = "user_domain_roles"

    id: Mapped[str] = mapped_column(
        String,
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    domain_id: Mapped[str] = mapped_column(
        ForeignKey("domains.id"),
        nullable=False,
        index=True,
    )
    role: Mapped[Role] = mapped_column(
        SQLAlchemyEnum(Role, name="domain_role"),
        nullable=False,
    )
