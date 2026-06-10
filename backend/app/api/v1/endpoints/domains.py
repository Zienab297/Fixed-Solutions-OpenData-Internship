from uuid import UUID
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.models.db.models import User
from app.core.security import get_current_user, require_domain_role
from app.services import domain_service
from app.schemas.domain import (
    DomainCreate, DomainOut, DomainArchive,
    MembershipCreate, MembershipOut,
)
from typing import List

router = APIRouter(prefix="/domains", tags=["domains"])


@router.post("/", response_model=DomainOut)
async def create_domain(
    data: DomainCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await domain_service.create_domain(db, data, created_by_user=current_user)


@router.get("/", response_model=List[DomainOut])
async def list_domains(
    include_archived: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await domain_service.get_all_domains(db, include_archived)


@router.get("/my", response_model=List[MembershipOut])
async def my_domains(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await domain_service.get_user_domains(db, current_user.id)


@router.get("/{domain_id}", response_model=DomainOut)
async def get_domain(
    domain_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await domain_service.get_domain(db, domain_id)


@router.patch("/{domain_id}/archive", response_model=DomainOut)
async def archive_domain(
    domain_id: UUID,
    data: DomainArchive,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_domain_role("domain_admin")
    ),
):
    return await domain_service.set_domain_status(db, domain_id, archived=data.archived)


@router.post("/{domain_id}/members", response_model=MembershipOut)
async def add_member(
    domain_id: UUID,
    data: MembershipCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_domain_role("domain_admin")
    ),
):
    return await domain_service.add_member(db, domain_id, data, granted_by=current_user)


@router.get("/{domain_id}/members", response_model=List[MembershipOut])
async def list_members(
    domain_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await domain_service.get_domain_members(db, domain_id)