"""
Seed the system admin user on first run.
Call this from main.py startup event.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import hash_password
from app.models.db.models import User


async def seed_admin(db: AsyncSession) -> None:
    result = await db.execute(select(User).where(User.email == settings.ADMIN_EMAIL))
    existing = result.scalar_one_or_none()
    if existing:
        return

    admin = User(
        keycloak_id="system-admin-001",
        email=settings.ADMIN_EMAIL,
        user_pool="internal",
        password_hash=hash_password(settings.ADMIN_PASSWORD),
    )
    db.add(admin)
    await db.flush()
    print(f"[seed] Created system admin: {settings.ADMIN_EMAIL}")