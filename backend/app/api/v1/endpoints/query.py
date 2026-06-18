"""
/query endpoint — full RAG pipeline.
Retrieval (vector + BM25 + graph) → LLM generation → async judge evaluation.
"""
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select

from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.db.models import User, DomainRole
from app.schemas.query import QueryRequest, QueryResponse, Citation, ContextChunk
from app.services.retrieval.pipeline import RetrievalPipeline
from app.services.retrieval.table_lookup import CsvTableLookupService
from app.services.llm.router import LLMRouter
from app.services.llm.local_llm import LocalLLMTimeoutError
from app.services.llm.language_detector import detect_language

router = APIRouter(prefix="/query", tags=["Query"])


async def _check_domain_access(
    domain_id: UUID,
    required_role: str,
    current_user: User,
    db: AsyncSession,
) -> None:
    """
    Inline RBAC check: raises 403 if the user does not hold at least the
    required role on the given domain.

    Role hierarchy:  domain_admin ≥ contributor ≥ reader
    """
    from fastapi import HTTPException, status

    ROLE_LEVELS = {"reader": 0, "contributor": 1, "domain_admin": 2}
    required_level = ROLE_LEVELS.get(required_role, 0)

    if current_user.email == settings.ADMIN_EMAIL:
        return

    result = await db.execute(
        select(DomainRole).where(
            DomainRole.user_id == current_user.id,
            DomainRole.domain_id == domain_id,
        )
    )
    dr = result.scalar_one_or_none()

    if dr is None or ROLE_LEVELS.get(dr.role, -1) < required_level:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient domain permissions",
        )


@router.post("", response_model=QueryResponse)
async def query(
    request: QueryRequest,
    # FIX: get_current_user returns a User ORM object, not CurrentUser Pydantic model
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> QueryResponse:
    # RBAC — verify access to all requested domains
    domain_uuids = []
    domain_routes = {}
    for domain_id_str in request.domain_ids:
        domain_id = UUID(domain_id_str)
        # FIX: use inline helper with correct signature (domain_id, role, user, db)
        await _check_domain_access(domain_id, "reader", current_user, db)
        domain_uuids.append(domain_id)

        # Fetch domain's llm_route for the router
        result = await db.execute(
            text("SELECT llm_route FROM rag.domains WHERE id = :id"),
            {"id": str(domain_id)},
        )
        row = result.fetchone()
        if row:
            domain_routes[domain_id_str] = row.llm_route if row.llm_route != "auto" else "local"

    table_lookup = CsvTableLookupService()
    table_result = await table_lookup.lookup(
        query=request.query,
        domain_ids=domain_uuids,
        db=db,
    )
    if table_result:
        citations = [
            Citation(
                chunk_id=str(c["id"]),
                document_title=c.get("document_title", ""),
                page_number=c.get("page_number"),
                section=c.get("section"),
                domain_id=str(c.get("domain_id", "")),
                domain_name=c.get("domain_name", ""),
                relevance_score=c.get("score", 1.0),
            )
            for c in table_result.chunks
        ]
        return QueryResponse(
            answer=table_result.answer,
            llm_route="local",
            language_detected=detect_language(request.query),
            citations=citations,
            confidence_score=table_result.confidence_score,
            signals_used=table_result.signals_used or ["table"],
        )

    # Retrieval — pipeline receives db so BM25 + Graph can query Postgres
    pipeline = RetrievalPipeline(db)
    retrieval_result = await pipeline.retrieve(
        query=request.query,
        domain_ids=domain_uuids,
        top_k=request.top_k,
    )

    if not retrieval_result.chunks:
        fallback_chunks = await table_lookup.search_context(
            query=request.query,
            domain_ids=domain_uuids,
            db=db,
            top_k=request.top_k,
        )
        if fallback_chunks:
            retrieval_result.chunks = fallback_chunks
            retrieval_result.citations = pipeline._build_citations(fallback_chunks)
            retrieval_result.confidence_score = 0.85
            retrieval_result.signals_used = retrieval_result.signals_used + ["csv_row_fallback"]
        else:
            llm_route = LLMRouter().determine_route(request.domain_ids, domain_routes)
            return QueryResponse(
                answer="I don't have enough information in the selected documents to answer that.",
                llm_route=llm_route,
                language_detected=detect_language(request.query),
                citations=[],
                confidence_score=0.0,
                signals_used=retrieval_result.signals_used,
            )

    # Build ContextChunks for LLMRouter
    context_chunks = [
        ContextChunk(
            content=c["content"],
            document_title=c.get("document_title", "Unknown"),
            page_number=c.get("page_number"),
        )
        for c in retrieval_result.chunks
    ]

    # Generation
    llm_router = LLMRouter()
    try:
        generation = await llm_router.generate(
            query=request.query,
            context=context_chunks,
            domain_ids=request.domain_ids,
            domain_routes=domain_routes,
        )
    except LocalLLMTimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail=(
                "The local LLM timed out while generating an answer. "
                "Try a narrower question, select fewer documents, or use a smaller/faster Ollama model."
            ),
        ) from exc

    # Async judge evaluation — fire and forget, never blocks response
    query_id = str(uuid4())
    _fire_judge_task(
        query_id=query_id,
        query=request.query,
        context=[c.model_dump() for c in context_chunks],
        answer=generation.answer,
        # FIX: current_user is a User ORM object; .id is a UUID
        user_id=str(current_user.id),
        domain_ids=request.domain_ids,
        llm_route=generation.llm_route,
        confidence_score=retrieval_result.confidence_score,
    )

    citations = [
        Citation(
            chunk_id=str(c["id"]),
            document_title=c.get("document_title", ""),
            page_number=c.get("page_number"),
            section=c.get("section"),
            domain_id=str(c.get("domain_id", "")),
            domain_name=c.get("domain_name", ""),
            relevance_score=c.get("score", 0.0),
        )
        for c in retrieval_result.chunks
    ]

    return QueryResponse(
        answer=generation.answer,
        llm_route=generation.llm_route,
        language_detected=generation.language_detected,
        citations=citations,
        confidence_score=retrieval_result.confidence_score,
        signals_used=retrieval_result.signals_used,
    )


def _fire_judge_task(query_id, query, context, answer, user_id, domain_ids, llm_route, confidence_score):
    try:
        from app.workers.tasks import run_judge_evaluation
        run_judge_evaluation.delay(
            query_id=query_id,
            query=query,
            context=context,
            answer=answer,
            user_id=user_id,
            domain_ids=domain_ids,
            llm_route=llm_route,
            confidence_score=confidence_score,
        )
    except Exception:
        pass  # never block the response for judge failures
