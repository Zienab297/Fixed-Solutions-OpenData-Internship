from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException, status
from app.models.domain import Domain, UserDomainRole
from app.schemas.domain import DomainCreate, MembershipCreate
from app.models.user import Role


# --- Domain operations ---

async def create_domain(db: AsyncSession, data: DomainCreate, created_by: str) -> Domain:
    result = await db.execute(select(Domain).where(Domain.name == data.name))
    existing = result.scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Domain '{data.name}' already exists"
        )

    domain = Domain(
        name=data.name,
        description=data.description,
        created_by=created_by
    )
    db.add(domain)
    await db.commit()
    await db.refresh(domain)

    # Creator automatically gets admin role in their domain
    await add_member(db, domain_id=domain.id, data=MembershipCreate(
        user_id=created_by,
        role=Role.admin
    ))

    return domain


async def get_domain(db: AsyncSession, domain_id: str) -> Domain:
    result = await db.execute(select(Domain).where(Domain.id == domain_id))
    domain = result.scalar_one_or_none()
    if not domain:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Domain not found"
        )
    return domain


async def get_all_domains(db: AsyncSession, include_archived: bool = False):
    query = select(Domain)
    if not include_archived:
        query = query.where(Domain.is_archived == False)
    result = await db.execute(query)
    return result.scalars().all()


async def archive_domain(db: AsyncSession, domain_id: str, is_archived: bool) -> Domain:
    domain = await get_domain(db, domain_id)
    domain.is_archived = is_archived
    await db.commit()
    await db.refresh(domain)
    return domain


# --- Membership operations ---

async def add_member(db: AsyncSession, domain_id: str, data: MembershipCreate) -> UserDomainRole:
    result = await db.execute(
        select(UserDomainRole).where(
            UserDomainRole.domain_id == domain_id,
            UserDomainRole.user_id == data.user_id
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is already a member of this domain"
        )

    membership = UserDomainRole(
        user_id=data.user_id,
        domain_id=domain_id,
        role=data.role
    )
    db.add(membership)
    await db.commit()
    await db.refresh(membership)
    return membership


async def get_user_domain_role(db: AsyncSession, domain_id: str, user_id: str) -> Role | None:
    result = await db.execute(
        select(UserDomainRole).where(
            UserDomainRole.domain_id == domain_id,
            UserDomainRole.user_id == user_id
        )
    )
    membership = result.scalar_one_or_none()
    return membership.role if membership else None


async def get_user_domains(db: AsyncSession, user_id: str):
    result = await db.execute(
        select(UserDomainRole).where(UserDomainRole.user_id == user_id)
    )
    return result.scalars().all()