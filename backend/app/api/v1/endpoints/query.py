"""
/query endpoint — the main RAG pipeline entry point.
Handles hybrid retrieval, LLM routing, and response assembly.
"""
from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import uuid4
from datetime import datetime

from app.core.database import get_db
from app.api.v1.dependencies.auth import get_current_user, require_domain_access
from app.models.schemas.auth import CurrentUser
from app.models.schemas.query import QueryRequest, QueryResponse
from app.services.retrieval.pipeline import RetrievalPipeline
from app.services.llm.router import LLMRouter
from app.services.evaluation.judge import JudgeService
from app.workers.tasks import run_judge_evaluation

router = APIRouter(prefix="/query", tags=["Query"])


@router.post("", response_model=QueryResponse)
async def query(
    request: QueryRequest,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Main RAG query endpoint.
    1. Verify RBAC for all requested domains
    2. Run hybrid retrieval (vector + BM25 + graph)
    3. Route to appropriate LLM
    4. Return answer with citations and confidence score
    5. Trigger async judge evaluation in background
    """
    # Step 1 — RBAC: verify access to all requested domains
    for domain_id in request.domain_ids:
        await require_domain_access(domain_id, "reader", current_user, db)

    query_id = uuid4()

    # Step 2 — Hybrid retrieval
    pipeline = RetrievalPipeline(db=db)
    retrieval_result = await pipeline.retrieve(
        query=request.query,
        domain_ids=request.domain_ids,
        top_k=request.top_k,
    )

    # Step 3 — LLM routing and generation
    llm_router = LLMRouter()
    generation_result = await llm_router.generate(
        query=request.query,
        context=retrieval_result.chunks,
        domain_ids=request.domain_ids,
        db=db,
    )

    # Step 4 — Build response
    response = QueryResponse(
        query_id=query_id,
        answer=generation_result.answer,
        citations=retrieval_result.citations,
        graph_citations=retrieval_result.graph_citations,
        confidence_score=retrieval_result.confidence_score,
        llm_route=generation_result.llm_route,
        language_detected=generation_result.language_detected,
        evaluation=None,  # populated async by judge
        created_at=datetime.utcnow(),
    )

    # Step 5 — Async judge evaluation (non-blocking)
    background_tasks.add_task(
        run_judge_evaluation,
        query_id=str(query_id),
        query=request.query,
        context=retrieval_result.chunks,
        answer=generation_result.answer,
        user_id=current_user.id,
        domain_ids=[str(d) for d in request.domain_ids],
        llm_route=generation_result.llm_route,
        confidence_score=retrieval_result.confidence_score,
    )

    return response
