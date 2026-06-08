from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from app.models.domain import Domain, UserDomainRole
from app.schemas.domain import DomainCreate, MembershipCreate
from app.models.user import Role, User

# --- Domain operations ---

def create_domain(db: Session, data: DomainCreate, created_by: str) -> Domain:
    # check if domain name already exists
    existing = db.query(Domain).filter(Domain.name == data.name).first()
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
    db.commit()
    db.refresh(domain)

    # creator automatically gets admin role in their domain
    add_member(db, domain_id=domain.id, data=MembershipCreate(
        user_id=created_by,
        role=Role.admin
    ))

    return domain

def get_domain(db: Session, domain_id: str) -> Domain:
    domain = db.query(Domain).filter(Domain.id == domain_id).first()
    if not domain:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Domain not found"
        )
    return domain

def get_all_domains(db: Session, include_archived: bool = False):
    query = db.query(Domain)
    if not include_archived:
        query = query.filter(Domain.is_archived == False)
    return query.all()

def archive_domain(db: Session, domain_id: str, is_archived: bool) -> Domain:
    domain = get_domain(db, domain_id)
    domain.is_archived = is_archived
    db.commit()
    db.refresh(domain)
    return domain

# --- Membership operations ---

def add_member(db: Session, domain_id: str, data: MembershipCreate) -> UserDomainRole:
    # check user isn't already a member
    existing = db.query(UserDomainRole).filter(
        UserDomainRole.domain_id == domain_id,
        UserDomainRole.user_id == data.user_id
    ).first()
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
    db.commit()
    db.refresh(membership)
    return membership

def get_user_domain_role(db: Session, domain_id: str, user_id: str) -> Role | None:
    membership = db.query(UserDomainRole).filter(
        UserDomainRole.domain_id == domain_id,
        UserDomainRole.user_id == user_id
    ).first()
    return membership.role if membership else None

def get_user_domains(db: Session, user_id: str):
    return db.query(UserDomainRole).filter(
        UserDomainRole.user_id == user_id
    ).all()
