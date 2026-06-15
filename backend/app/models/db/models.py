"""
SQLAlchemy ORM models — mirrors the schema in init.sql exactly.
All tables live in the `rag` schema.
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import List, Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID as PGUUID
from sqlalchemy import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

class User(Base):
    __tablename__ = "users"
    __table_args__ = {"schema": "rag"}

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    keycloak_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    user_pool: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        # DB-level constraint mirrors init.sql CHECK
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("user_pool IN ('internal', 'external')", name="chk_user_pool"),
        {"schema": "rag"},
    )

    # relationships
    # relationships
    domain_roles: Mapped[List["DomainRole"]] = relationship(
        back_populates="user", foreign_keys="[DomainRole.user_id]"
    )
    documents: Mapped[List["Document"]] = relationship(
        back_populates="ingested_by_user", foreign_keys="[Document.ingested_by]"
    )


# ---------------------------------------------------------------------------
# Domains
# ---------------------------------------------------------------------------

class Domain(Base):
    __tablename__ = "domains"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'archived')", name="chk_domain_status"),
        CheckConstraint("llm_route IN ('local', 'api', 'auto')", name="chk_domain_llm_route"),
        {"schema": "rag"},
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), server_default="active")
    llm_route: Mapped[str] = mapped_column(String(50), server_default="auto")
    confidence_threshold: Mapped[float] = mapped_column(Float, server_default="0.7")
    chunk_size: Mapped[int] = mapped_column(Integer, server_default="512")
    chunk_overlap: Mapped[int] = mapped_column(Integer, server_default="64")
    supported_languages: Mapped[List[str]] = mapped_column(
        ARRAY(Text), server_default="{en}"
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # relationships
    documents: Mapped[List["Document"]] = relationship(back_populates="domain")
    chunks: Mapped[List["Chunk"]] = relationship(back_populates="domain")
    domain_roles: Mapped[List["DomainRole"]] = relationship(back_populates="domain")
    crawl_config: Mapped[Optional["CrawlConfig"]] = relationship(back_populates="domain")


# ---------------------------------------------------------------------------
# Domain Roles (RBAC)
# ---------------------------------------------------------------------------

class DomainRole(Base):
    __tablename__ = "domain_roles"
    __table_args__ = (
        CheckConstraint(
            "role IN ('domain_admin', 'contributor', 'reader')", name="chk_domain_role"
        ),
        UniqueConstraint("user_id", "domain_id", name="uq_user_domain"),
        {"schema": "rag"},
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("rag.users.id", ondelete="CASCADE")
    )
    domain_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("rag.domains.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    granted_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    granted_by: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("rag.users.id")
    )

    # relationships
    user: Mapped["User"] = relationship(
        back_populates="domain_roles", foreign_keys=[user_id]
    )
    domain: Mapped["Domain"] = relationship(back_populates="domain_roles")


# ---------------------------------------------------------------------------
# API Keys
# ---------------------------------------------------------------------------

class APIKey(Base):
    __tablename__ = "api_keys"
    __table_args__ = (
        CheckConstraint("role IN ('contributor', 'reader')", name="chk_api_key_role"),
        {"schema": "rag"},
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    key_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("rag.users.id")
    )
    allowed_domains: Mapped[Optional[List[UUID]]] = mapped_column(ARRAY(PGUUID(as_uuid=True)))
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    rate_limit_per_day: Mapped[int] = mapped_column(Integer, server_default="1000")
    expires_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    last_used_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(
            "source_type IN ('pdf', 'docx', 'csv', 'xlsx', 'webpage', 'database')",
            name="chk_document_source_type",
        ),
        CheckConstraint(
            "ingest_status IN ('pending', 'processing', 'completed', 'failed')",
            name="chk_document_ingest_status",
        ),
        # Duplicate-detection: same content_hash + same domain = duplicate
        UniqueConstraint("content_hash", "domain_id", name="uq_document_hash_domain"),
        Index("idx_documents_domain", "domain_id"),
        {"schema": "rag"},
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    domain_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("rag.domains.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_url: Mapped[Optional[str]] = mapped_column(Text)
    author: Mapped[Optional[str]] = mapped_column(String(255))
    ingest_status: Mapped[str] = mapped_column(String(50), server_default="pending")
    ocr_used: Mapped[bool] = mapped_column(Boolean, server_default="false")
    language: Mapped[Optional[str]] = mapped_column(String(10))

    # SHA-256 hex digest of raw file bytes — used to detect duplicate uploads
    # documents are 
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), index=True)

    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, server_default="{}")
    ingested_by: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("rag.users.id")
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # relationships
    domain: Mapped["Domain"] = relationship(back_populates="documents")
    ingested_by_user: Mapped[Optional["User"]] = relationship(
        back_populates="documents", foreign_keys=[ingested_by]
    )
    chunks: Mapped[List["Chunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )

    @staticmethod
    def hash_content(file_bytes: bytes) -> str:
        """SHA-256 hex digest of raw file bytes."""
        return hashlib.sha256(file_bytes).hexdigest()


# ---------------------------------------------------------------------------
# Chunks
# ---------------------------------------------------------------------------

class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        Index("idx_chunks_domain", "domain_id"),
        Index("idx_chunks_document", "document_id"),
        {"schema": "rag"},
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("rag.documents.id", ondelete="CASCADE"), nullable=False
    )
    domain_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("rag.domains.id", ondelete="CASCADE"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    page_number: Mapped[Optional[int]] = mapped_column(Integer)
    section: Mapped[Optional[str]] = mapped_column(String(255))
    embedding_model: Mapped[str] = mapped_column(String(255), nullable=False)
    embedding_version: Mapped[int] = mapped_column(Integer, server_default="1")
    # Qdrant point IDs / AGE node IDs stored here for cross-DB linking
    graph_node_ids: Mapped[Optional[List[UUID]]] = mapped_column(ARRAY(PGUUID(as_uuid=True)))
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())

    # relationships
    document: Mapped["Document"] = relationship(back_populates="chunks")
    domain: Mapped["Domain"] = relationship(back_populates="chunks")


# ---------------------------------------------------------------------------
# Structured Table Rows
# ---------------------------------------------------------------------------

class TableRow(Base):
    __tablename__ = "table_rows"
    __table_args__ = (
        UniqueConstraint("document_id", "row_number", name="uq_table_rows_document_row"),
        Index("idx_table_rows_domain", "domain_id"),
        Index("idx_table_rows_document", "document_id"),
        Index("idx_table_rows_chunk", "chunk_id"),
        {"schema": "rag"},
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("rag.documents.id", ondelete="CASCADE"), nullable=False
    )
    domain_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("rag.domains.id", ondelete="CASCADE"), nullable=False
    )
    chunk_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("rag.chunks.id", ondelete="SET NULL")
    )
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    row_data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())


# ---------------------------------------------------------------------------
# Audit Logs (append-only — never update rows)
# ---------------------------------------------------------------------------

class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("idx_audit_user", "user_id"),
        Index("idx_audit_created", "created_at"),
        {"schema": "rag"},
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    query_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    user_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("rag.users.id")
    )
    api_key_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("rag.api_keys.id")
    )
    domains_queried: Mapped[List[UUID]] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=False
    )
    retrieved_chunk_ids: Mapped[Optional[List[UUID]]] = mapped_column(ARRAY(PGUUID(as_uuid=True)))
    graph_nodes_traversed: Mapped[Optional[List[UUID]]] = mapped_column(
        ARRAY(PGUUID(as_uuid=True))
    )
    llm_route: Mapped[Optional[str]] = mapped_column(String(50))
    confidence_score: Mapped[Optional[float]] = mapped_column(Float)
    faithfulness_score: Mapped[Optional[float]] = mapped_column(Float)
    relevance_score: Mapped[Optional[float]] = mapped_column(Float)
    completeness_score: Mapped[Optional[float]] = mapped_column(Float)
    citation_accuracy_score: Mapped[Optional[float]] = mapped_column(Float)
    judge_rationale: Mapped[Optional[dict]] = mapped_column(JSONB)
    flagged: Mapped[bool] = mapped_column(Boolean, server_default="false")
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())


# ---------------------------------------------------------------------------
# Golden Dataset
# ---------------------------------------------------------------------------

class GoldenDataset(Base):
    __tablename__ = "golden_dataset"
    __table_args__ = {"schema": "rag"}

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    domain_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("rag.domains.id", ondelete="CASCADE"), nullable=False
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    expected_answer: Mapped[str] = mapped_column(Text, nullable=False)
    expected_chunk_ids: Mapped[Optional[List[UUID]]] = mapped_column(ARRAY(PGUUID(as_uuid=True)))
    created_by: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("rag.users.id")
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())


# ---------------------------------------------------------------------------
# Moderation Queue
# ---------------------------------------------------------------------------

class ModerationQueue(Base):
    __tablename__ = "moderation_queue"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'accepted', 'rejected')", name="chk_moderation_status"
        ),
        {"schema": "rag"},
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    audit_log_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("rag.audit_logs.id")
    )
    domain_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("rag.domains.id")
    )
    status: Mapped[str] = mapped_column(String(50), server_default="pending")
    reviewed_by: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("rag.users.id")
    )
    reviewer_rationale: Mapped[Optional[str]] = mapped_column(Text)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())


# ---------------------------------------------------------------------------
# Web Crawl Config
# ---------------------------------------------------------------------------

class CrawlConfig(Base):
    __tablename__ = "crawl_configs"
    __table_args__ = {"schema": "rag"}

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    domain_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("rag.domains.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    seed_urls: Mapped[List[str]] = mapped_column(ARRAY(Text), nullable=False)
    url_whitelist: Mapped[List[str]] = mapped_column(ARRAY(Text), nullable=False)
    max_depth: Mapped[int] = mapped_column(Integer, server_default="2")
    crawl_schedule: Mapped[str] = mapped_column(String(100), server_default="0 2 * * *")
    last_crawled_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")

    domain: Mapped["Domain"] = relationship(back_populates="crawl_config")
