from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.user import User, Role
from app.api.v1.dependencies.auth import get_current_user, require_role
from app.services import domain_service
from app.schemas.domain import (
    DomainCreate, DomainOut, DomainArchive,
    MembershipCreate, MembershipOut
)
from typing import List

router = APIRouter(prefix="/domains", tags=["domains"])

@router.post("/", response_model=DomainOut)
def create_domain(
    data: DomainCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.admin))
):
    return domain_service.create_domain(db, data, created_by=current_user.keycloak_id)

@router.get("/", response_model=List[DomainOut])
def list_domains(
    include_archived: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return domain_service.get_all_domains(db, include_archived)

@router.get("/my", response_model=List[MembershipOut])
def my_domains(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return domain_service.get_user_domains(db, current_user.keycloak_id)

@router.get("/{domain_id}", response_model=DomainOut)
def get_domain(
    domain_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return domain_service.get_domain(db, domain_id)

@router.patch("/{domain_id}/archive", response_model=DomainOut)
def archive_domain(
    domain_id: str,
    data: DomainArchive,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.admin))
):
    return domain_service.archive_domain(db, domain_id, data.is_archived)

@router.post("/{domain_id}/members", response_model=MembershipOut)
def add_member(
    domain_id: str,
    data: MembershipCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.admin))
):
    return domain_service.add_member(db, domain_id, data)

@router.get("/{domain_id}/members", response_model=List[MembershipOut])
def list_members(
    domain_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return domain_service.get_user_domains(db, domain_id)