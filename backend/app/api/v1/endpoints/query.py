"""
/query endpoint — full RAG pipeline.
Retrieval (vector + BM25 + graph) → LLM generation → async judge evaluation.
"""
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.api.v1.dependencies.auth import get_current_user, require_domain_access
from app.models.schemas.auth import CurrentUser
from app.schemas.query import QueryRequest, QueryResponse, Citation
from app.services.retrieval.pipeline import RetrievalPipeline
from app.services.llm.router import LLMRouter

router = APIRouter(prefix="/query", tags=["Query"])


@router.post("", response_model=QueryResponse)
async def query(
    request: QueryRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> QueryResponse:
    # RBAC — verify access to all requested domains
    domain_uuids = []
    domain_routes = {}
    for domain_id_str in request.domain_ids:
        domain_id = UUID(domain_id_str)
        await require_domain_access(domain_id, "reader", current_user, db)
        domain_uuids.append(domain_id)

        # Fetch domain's llm_route for the router
        from sqlalchemy import text
        result = await db.execute(
            text("SELECT llm_route FROM rag.domains WHERE id = :id"),
            {"id": str(domain_id)},
        )
        row = result.fetchone()
        if row:
            domain_routes[domain_id_str] = row.llm_route if row.llm_route != "auto" else "local"

    # Retrieval
    pipeline = RetrievalPipeline(db)
    retrieval_result = await pipeline.retrieve(
        query=request.query,
        domain_ids=domain_uuids,
        top_k=request.top_k,
    )

    # Build ContextChunks for LLMRouter
    from app.schemas.query import ContextChunk
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
    generation = await llm_router.generate(
        query=request.query,
        context=context_chunks,
        domain_ids=request.domain_ids,
        domain_routes=domain_routes,
    )

    # Async judge evaluation — fire and forget, never blocks response
    query_id = str(uuid4())
    _fire_judge_task(
        query_id=query_id,
        query=request.query,
        context=[c.model_dump() for c in context_chunks],
        answer=generation.answer,
        user_id=current_user.id,
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