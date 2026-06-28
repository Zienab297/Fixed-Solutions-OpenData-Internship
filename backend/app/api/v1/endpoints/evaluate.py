"""Evaluation status and scores for completed query responses."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import delete, desc, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.db.models import AuditLog, Chunk, Document, Domain, DomainRole, EvaluationResult, User

router = APIRouter(prefix="/evaluate", tags=["evaluate"])


class ModerationUpdate(BaseModel):
    status: str
    reviewer_rationale: str | None = None


@router.get("/quality/summary")
async def quality_summary(
    domain_id: UUID | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    visible_domain_ids = await _visible_admin_domain_ids(current_user, db)
    if visible_domain_ids is not None and not visible_domain_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Quality metrics are visible to domain admins only",
        )

    if domain_id and visible_domain_ids is not None and domain_id not in visible_domain_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions for this domain",
        )

    filter_domain_ids = [str(domain_id)] if domain_id else (
        [str(item) for item in visible_domain_ids] if visible_domain_ids is not None else None
    )

    query = """
        WITH domain_scope AS (
            SELECT
                d.id AS domain_id,
                d.name AS domain_name
            FROM rag.domains d
            WHERE d.status = 'active'
              AND (:domain_filter_disabled OR d.id::text = ANY(:domain_ids))
        ),
        expanded AS (
            SELECT
                domain_id,
                d.name AS domain_name,
                er.query_id,
                COALESCE(al.llm_route, 'unknown') AS llm_route,
                er.faithfulness_score,
                er.relevance_score,
                er.completeness_score,
                er.citation_accuracy_score,
                er.flagged,
                er.created_at
            FROM rag.evaluation_results er
            JOIN rag.audit_logs al ON er.audit_log_id = al.id
            CROSS JOIN LATERAL unnest(al.domains_queried) AS domain_id
            JOIN rag.domains d ON d.id = domain_id
            WHERE (:domain_filter_disabled OR domain_id::text = ANY(:domain_ids))
        )
        SELECT
            ds.domain_id,
            ds.domain_name,
            COALESCE(e.llm_route, 'none') AS llm_route,
            COUNT(e.query_id) AS evaluation_count,
            AVG(e.faithfulness_score) AS faithfulness,
            AVG(e.relevance_score) AS relevance,
            AVG(e.completeness_score) AS completeness,
            AVG(e.citation_accuracy_score) AS citation_accuracy,
            SUM(CASE WHEN e.flagged THEN 1 ELSE 0 END) AS flagged_count,
            MAX(e.created_at) AS last_evaluated_at
        FROM domain_scope ds
        LEFT JOIN expanded e ON e.domain_id = ds.domain_id
        GROUP BY ds.domain_id, ds.domain_name, e.llm_route
        ORDER BY ds.domain_name ASC, e.llm_route ASC
    """

    rows = (
        await db.execute(
            text(query),
            {
                "domain_filter_disabled": filter_domain_ids is None,
                "domain_ids": filter_domain_ids or [],
            },
        )
    ).fetchall()

    summaries: dict[str, dict] = {}
    for row in rows:
        domain_key = str(row.domain_id)
        summary = summaries.setdefault(
            domain_key,
            {
                "domain_id": domain_key,
                "domain_name": row.domain_name,
                "evaluation_count": 0,
                "flagged_count": 0,
                "scores": {
                    "faithfulness": 0.0,
                    "relevance": 0.0,
                    "completeness": 0.0,
                    "citation_accuracy": 0.0,
                },
                "route_breakdown": [],
                "last_evaluated_at": None,
            },
        )

        count = int(row.evaluation_count or 0)
        route_scores = {
            "faithfulness": _float_or_zero(row.faithfulness),
            "relevance": _float_or_zero(row.relevance),
            "completeness": _float_or_zero(row.completeness),
            "citation_accuracy": _float_or_zero(row.citation_accuracy),
        }
        previous_count = summary["evaluation_count"]
        next_count = previous_count + count
        for key, value in route_scores.items():
            summary["scores"][key] = (
                (summary["scores"][key] * previous_count) + (value * count)
            ) / next_count if next_count else 0.0
        summary["evaluation_count"] = next_count
        summary["flagged_count"] += int(row.flagged_count or 0)
        if row.last_evaluated_at and (
            summary["last_evaluated_at"] is None
            or row.last_evaluated_at > summary["last_evaluated_at"]
        ):
            summary["last_evaluated_at"] = row.last_evaluated_at
        if count > 0:
            summary["route_breakdown"].append(
                {
                    "llm_route": row.llm_route,
                    "evaluation_count": count,
                    "scores": route_scores,
                    "flagged_count": int(row.flagged_count or 0),
                }
            )

    return {
        "domains": [
            {
                **summary,
                "last_evaluated_at": summary["last_evaluated_at"].isoformat()
                if summary["last_evaluated_at"]
                else None,
            }
            for summary in summaries.values()
        ]
    }


@router.get("/quality/domains/{domain_id}")
async def quality_domain_detail(
    domain_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_domain_admin_access(domain_id, current_user, db)

    domain = (
        await db.execute(select(Domain).where(Domain.id == domain_id))
    ).scalar_one_or_none()
    if domain is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Domain not found")

    history_rows = (
        await db.execute(
            text(
                """
                SELECT
                    al.id AS audit_log_id,
                    al.query_id,
                    al.query_text,
                    al.answer_text,
                    al.llm_route,
                    al.confidence_score,
                    al.created_at AS asked_at,
                    er.id AS evaluation_result_id,
                    er.judge_model,
                    er.faithfulness_score,
                    er.relevance_score,
                    er.completeness_score,
                    er.citation_accuracy_score,
                    er.judge_rationale,
                    er.flagged,
                    er.created_at AS evaluated_at
                FROM rag.audit_logs al
                LEFT JOIN LATERAL (
                    SELECT *
                    FROM rag.evaluation_results er
                    WHERE er.audit_log_id = al.id
                    ORDER BY er.created_at DESC
                    LIMIT 1
                ) er ON TRUE
                WHERE CAST(:domain_id AS uuid) = ANY(al.domains_queried)
                ORDER BY al.created_at DESC
                LIMIT 100
                """
            ),
            {"domain_id": str(domain_id)},
        )
    ).fetchall()

    document_rows = (
        await db.execute(
            text(
                """
                SELECT
                    d.id,
                    d.title,
                    d.source_type,
                    d.source_url,
                    d.ingest_status,
                    d.ocr_used,
                    d.language,
                    d.metadata AS document_metadata,
                    d.created_at,
                    d.updated_at,
                    COUNT(c.id) AS chunk_count
                FROM rag.documents d
                LEFT JOIN rag.chunks c ON c.document_id = d.id
                WHERE d.domain_id = :domain_id
                GROUP BY d.id
                ORDER BY d.created_at DESC
                """
            ),
            {"domain_id": str(domain_id)},
        )
    ).fetchall()

    flagged_rows = (
        await db.execute(
            text(
                """
                SELECT
                    mq.id,
                    mq.audit_log_id,
                    mq.evaluation_result_id,
                    mq.status,
                    mq.reviewer_rationale,
                    mq.created_at,
                    mq.reviewed_at,
                    er.query_id,
                    er.judge_model,
                    er.faithfulness_score,
                    er.relevance_score,
                    er.completeness_score,
                    er.citation_accuracy_score,
                    er.judge_rationale,
                    er.flagged,
                    er.created_at AS evaluated_at,
                    al.query_text,
                    al.answer_text,
                    al.llm_route,
                    al.confidence_score
                FROM rag.moderation_queue mq
                JOIN rag.evaluation_results er ON er.id = mq.evaluation_result_id
                JOIN rag.audit_logs al ON al.id = mq.audit_log_id
                WHERE mq.domain_id = :domain_id
                ORDER BY mq.created_at DESC
                LIMIT 100
                """
            ),
            {"domain_id": str(domain_id)},
        )
    ).fetchall()

    return {
        "domain": {
            "id": str(domain.id),
            "name": domain.name,
            "description": domain.description,
            "status": domain.status,
            "llm_route": domain.llm_route,
        },
        "history": [_history_item(row) for row in history_rows],
        "documents": [
            {
                "id": str(row.id),
                "title": row.title,
                "source_type": row.source_type,
                "source_url": row.source_url,
                "ingest_status": row.ingest_status,
                "ocr_used": row.ocr_used,
                "language": row.language,
                "metadata": row.document_metadata or {},
                "chunk_count": int(row.chunk_count or 0),
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }
            for row in document_rows
        ],
        "flagged": [_moderation_item(row, domain_id=domain_id, domain_name=domain.name) for row in flagged_rows],
    }


@router.delete("/quality/domains/{domain_id}/documents/{document_id}")
async def delete_domain_document(
    domain_id: UUID,
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_domain_admin_access(domain_id, current_user, db)

    document = (
        await db.execute(
            select(Document).where(
                Document.id == document_id,
                Document.domain_id == domain_id,
            )
        )
    ).scalar_one_or_none()
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    chunk_ids = list(
        (
            await db.execute(
                select(Chunk.id).where(
                    Chunk.document_id == document_id,
                    Chunk.domain_id == domain_id,
                )
            )
        ).scalars().all()
    )
    await _delete_qdrant_points(domain_id, chunk_ids)
    await db.execute(delete(Document).where(Document.id == document_id))
    await db.commit()

    return {
        "document_id": str(document_id),
        "deleted": True,
        "deleted_chunk_count": len(chunk_ids),
    }


@router.get("/moderation")
async def list_moderation_items(
    status_filter: str = "pending",
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    visible_domain_ids = await _visible_admin_domain_ids(current_user, db)
    if visible_domain_ids is not None and not visible_domain_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Moderation queue is visible to domain admins only",
        )

    if status_filter not in {"pending", "accepted", "rejected", "all"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="status_filter must be pending, accepted, rejected, or all",
        )

    domain_ids = [str(item) for item in visible_domain_ids] if visible_domain_ids is not None else None
    rows = (
        await db.execute(
            text(
                """
                SELECT
                    mq.id,
                    mq.audit_log_id,
                    mq.evaluation_result_id,
                    mq.domain_id,
                    d.name AS domain_name,
                    mq.status,
                    mq.reviewer_rationale,
                    mq.created_at,
                    er.query_id,
                    er.judge_model,
                    er.faithfulness_score,
                    er.relevance_score,
                    er.completeness_score,
                    er.citation_accuracy_score,
                    er.judge_rationale,
                    er.flagged,
                    er.created_at AS evaluated_at,
                    al.query_text,
                    al.answer_text,
                    al.llm_route,
                    al.confidence_score
                FROM rag.moderation_queue mq
                JOIN rag.evaluation_results er
                    ON er.id = mq.evaluation_result_id
                JOIN rag.audit_logs al
                    ON al.id = mq.audit_log_id
                LEFT JOIN rag.domains d
                    ON d.id = mq.domain_id
                WHERE (:domain_filter_disabled OR mq.domain_id::text = ANY(:domain_ids))
                  AND (:status_filter = 'all' OR mq.status = :status_filter)
                ORDER BY mq.created_at DESC
                LIMIT 100
                """
            ),
            {
                "domain_filter_disabled": domain_ids is None,
                "domain_ids": domain_ids or [],
                "status_filter": status_filter,
            },
        )
    ).fetchall()

    return {
        "items": [_moderation_item(row) for row in rows]
    }


@router.patch("/moderation/{item_id}")
async def update_moderation_item(
    item_id: UUID,
    payload: ModerationUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if payload.status not in {"accepted", "rejected", "pending"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="status must be accepted, rejected, or pending",
        )

    visible_domain_ids = await _visible_admin_domain_ids(current_user, db)
    result = await db.execute(
        text(
            """
            SELECT id, domain_id
            FROM rag.moderation_queue
            WHERE id = :item_id
            """
        ),
        {"item_id": str(item_id)},
    )
    row = result.fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Moderation item not found")
    if visible_domain_ids is not None and row.domain_id not in visible_domain_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions for this moderation item",
        )

    await db.execute(
        text(
            """
            UPDATE rag.moderation_queue
            SET status = :status,
                reviewer_rationale = :reviewer_rationale,
                reviewed_by = :reviewed_by,
                reviewed_at = NOW()
            WHERE id = :item_id
            """
        ),
        {
            "status": payload.status,
            "reviewer_rationale": payload.reviewer_rationale,
            "reviewed_by": str(current_user.id),
            "item_id": str(item_id),
        },
    )
    await db.commit()
    return {"id": str(item_id), "status": payload.status}


@router.get("/{query_id}")
async def get_evaluation(
    query_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    audit_result = await db.execute(
        select(AuditLog)
        .where(AuditLog.query_id == query_id)
        .order_by(desc(AuditLog.created_at))
        .limit(1)
    )
    audit_log = audit_result.scalar_one_or_none()
    if audit_log is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Query not found")

    if not await _can_view_evaluation(current_user, audit_log, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions for this evaluation",
        )

    evaluation_result = await db.execute(
        select(EvaluationResult)
        .where(
            EvaluationResult.query_id == query_id,
            EvaluationResult.audit_log_id == audit_log.id,
        )
        .order_by(desc(EvaluationResult.created_at))
        .limit(1)
    )
    evaluation = evaluation_result.scalar_one_or_none()
    if evaluation is None:
        return {"query_id": str(query_id), "status": "pending", "evaluation": None}

    return {
        "query_id": str(query_id),
        "status": "completed",
        "evaluation": {
            "id": str(evaluation.id),
            "audit_log_id": str(evaluation.audit_log_id),
            "judge_model": evaluation.judge_model,
            "faithfulness": evaluation.faithfulness_score,
            "relevance": evaluation.relevance_score,
            "completeness": evaluation.completeness_score,
            "citation_accuracy": evaluation.citation_accuracy_score,
            "rationale": evaluation.judge_rationale or {},
            "flagged": evaluation.flagged,
            "created_at": evaluation.created_at.isoformat()
            if evaluation.created_at
            else None,
        },
    }


async def _can_view_evaluation(
    current_user: User,
    audit_log: AuditLog,
    db: AsyncSession,
) -> bool:
    if audit_log.user_id == current_user.id:
        return True
    if current_user.email == settings.ADMIN_EMAIL:
        return True
    if not audit_log.domains_queried:
        return False

    roles = await db.execute(
        select(DomainRole).where(
            DomainRole.user_id == current_user.id,
            DomainRole.domain_id.in_(audit_log.domains_queried),
            DomainRole.role == "domain_admin",
        )
    )
    return roles.scalar_one_or_none() is not None


def _history_item(row) -> dict:
    evaluation = None
    if row.evaluation_result_id:
        evaluation = {
            "id": str(row.evaluation_result_id),
            "judge_model": row.judge_model,
            "faithfulness": row.faithfulness_score,
            "relevance": row.relevance_score,
            "completeness": row.completeness_score,
            "citation_accuracy": row.citation_accuracy_score,
            "rationale": row.judge_rationale or {},
            "flagged": row.flagged,
            "created_at": row.evaluated_at.isoformat() if row.evaluated_at else None,
        }

    return {
        "audit_log_id": str(row.audit_log_id),
        "query_id": str(row.query_id),
        "question": row.query_text,
        "answer": row.answer_text,
        "llm_route": row.llm_route,
        "confidence_score": row.confidence_score,
        "status": "completed" if evaluation else "pending",
        "evaluation": evaluation,
        "asked_at": row.asked_at.isoformat() if row.asked_at else None,
    }


def _moderation_item(row, domain_id: UUID | None = None, domain_name: str | None = None) -> dict:
    resolved_domain_id = domain_id if domain_id is not None else row.domain_id
    resolved_domain_name = domain_name if domain_name is not None else row.domain_name
    return {
        "id": str(row.id),
        "audit_log_id": str(row.audit_log_id),
        "evaluation_result_id": str(row.evaluation_result_id),
        "query_id": str(row.query_id),
        "question": row.query_text,
        "answer": row.answer_text,
        "domain_id": str(resolved_domain_id) if resolved_domain_id else None,
        "domain_name": resolved_domain_name,
        "status": row.status,
        "reviewer_rationale": row.reviewer_rationale,
        "judge_model": row.judge_model,
        "scores": {
            "faithfulness": row.faithfulness_score,
            "relevance": row.relevance_score,
            "completeness": row.completeness_score,
            "citation_accuracy": row.citation_accuracy_score,
        },
        "rationale": row.judge_rationale or {},
        "flagged": row.flagged,
        "llm_route": row.llm_route,
        "confidence_score": row.confidence_score,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "evaluated_at": row.evaluated_at.isoformat() if row.evaluated_at else None,
        "reviewed_at": row.reviewed_at.isoformat() if getattr(row, "reviewed_at", None) else None,
    }


async def _ensure_domain_admin_access(
    domain_id: UUID,
    current_user: User,
    db: AsyncSession,
) -> None:
    visible_domain_ids = await _visible_admin_domain_ids(current_user, db)
    if visible_domain_ids is not None and domain_id not in visible_domain_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions for this domain",
        )


async def _delete_qdrant_points(domain_id: UUID, chunk_ids: list[UUID]) -> None:
    if not chunk_ids:
        return

    from qdrant_client import AsyncQdrantClient
    from qdrant_client.models import PointIdsList

    collection = f"domain_{str(domain_id).replace('-', '_')}"
    client = AsyncQdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
    try:
        await client.delete(
            collection_name=collection,
            points_selector=PointIdsList(points=[str(chunk_id) for chunk_id in chunk_ids]),
        )
    except Exception as exc:
        message = str(exc)
        if "Not found" in message or "doesn't exist" in message or "does not exist" in message:
            return
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Could not delete document vectors from Qdrant: {exc}",
        ) from exc
    finally:
        await client.close()


async def _visible_admin_domain_ids(
    current_user: User,
    db: AsyncSession,
) -> list[UUID] | None:
    if current_user.email == settings.ADMIN_EMAIL:
        return None

    result = await db.execute(
        select(DomainRole.domain_id).where(
            DomainRole.user_id == current_user.id,
            DomainRole.role == "domain_admin",
        )
    )
    return list(result.scalars().all())


def _float_or_zero(value) -> float:
    return float(value) if value is not None else 0.0
