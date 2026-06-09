from enum import Enum

from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Role(str, Enum):
    admin = "admin"
    contributor = "contributor"
    reader = "reader"


class User(Base):
    __tablename__ = "users"

    keycloak_id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[Role] = mapped_column(
        SQLAlchemyEnum(Role, name="user_role"),
        default=Role.reader,
        nullable=False,
    )
