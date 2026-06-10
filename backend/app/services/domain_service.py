from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException, status
from app.models.db.models import Domain, DomainRole, User
from app.schemas.domain import DomainCreate, MembershipCreate


# ---------------------------------------------------------------------------
# Domain operations
# ---------------------------------------------------------------------------

async def create_domain(db: AsyncSession, data: DomainCreate, created_by_user: User) -> Domain:
    result = await db.execute(select(Domain).where(Domain.name == data.name))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Domain '{data.name}' already exists",
        )

    domain = Domain(
        name=data.name,
        description=data.description,
        llm_route=data.llm_route or "auto",
        confidence_threshold=data.confidence_threshold or 0.7,
        chunk_size=data.chunk_size or 512,
        chunk_overlap=data.chunk_overlap or 64,
        supported_languages=data.supported_languages or ["en"],
    )
    db.add(domain)
    await db.flush()  # get domain.id without committing

    # Creator automatically gets domain_admin role
    role = DomainRole(
        user_id=created_by_user.id,
        domain_id=domain.id,
        role="domain_admin",
        granted_by=created_by_user.id,
    )
    db.add(role)
    await db.refresh(domain)

    # Provision a Qdrant collection for this domain.
    # Done eagerly so the collection exists before the first document is
    # ingested. The DocumentProcessor also creates it idempotently on
    # upsert, so a failure here is non-fatal.
    try:
        from app.services.retrieval.vector_search import VectorSearchService
        vs = VectorSearchService()
        await vs.create_domain_collection(domain.id)
    except Exception as exc:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "Could not provision Qdrant collection for domain %s: %s",
            domain.id, exc,
        )

    return domain


async def get_domain(db: AsyncSession, domain_id: UUID) -> Domain:
    result = await db.execute(select(Domain).where(Domain.id == domain_id))
    domain = result.scalar_one_or_none()
    if not domain:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Domain not found")
    return domain


async def get_all_domains(db: AsyncSession, include_archived: bool = False):
    query = select(Domain)
    if not include_archived:
        query = query.where(Domain.status == "active")
    result = await db.execute(query)
    return result.scalars().all()


async def set_domain_status(db: AsyncSession, domain_id: UUID, archived: bool) -> Domain:
    domain = await get_domain(db, domain_id)
    domain.status = "archived" if archived else "active"
    await db.refresh(domain)
    return domain


# ---------------------------------------------------------------------------
# Membership / RBAC operations
# ---------------------------------------------------------------------------

async def add_member(db: AsyncSession, domain_id: UUID, data: MembershipCreate, granted_by: User) -> DomainRole:
    result = await db.execute(
        select(DomainRole).where(
            DomainRole.domain_id == domain_id,
            DomainRole.user_id == data.user_id,
        )
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is already a member of this domain",
        )

    membership = DomainRole(
        user_id=data.user_id,
        domain_id=domain_id,
        role=data.role,
        granted_by=granted_by.id,
    )
    db.add(membership)
    await db.flush()
    await db.refresh(membership)
    return membership


async def get_domain_members(db: AsyncSession, domain_id: UUID):
    result = await db.execute(
        select(DomainRole).where(DomainRole.domain_id == domain_id)
    )
    return result.scalars().all()


async def get_user_domains(db: AsyncSession, user_id: UUID):
    result = await db.execute(
        select(DomainRole).where(DomainRole.user_id == user_id)
    )
    return result.scalars().all()


async def get_user_domain_role(db: AsyncSession, domain_id: UUID, user_id: UUID) -> str | None:
    result = await db.execute(
        select(DomainRole).where(
            DomainRole.domain_id == domain_id,
            DomainRole.user_id == user_id,
        )
    )
    dr = result.scalar_one_or_none()
    return dr.role if dr else None