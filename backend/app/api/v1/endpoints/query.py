"""
/query endpoint — full RAG pipeline.
Retrieval (vector + BM25 + graph) → LLM generation → async judge evaluation.
"""
import time
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select

from app.core.config import settings
from app.core.database import get_db
from app.core.metrics import LLM_ROUTE_TOTAL, RAG_QUERY_LATENCY
from app.core.security import get_current_user
from app.models.db.models import AuditLog, User, DomainRole
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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> QueryResponse:
    """
    Thin timing wrapper around _query_impl (§6.2: end-to-end query
    latency, P50/P95; model routing distribution). _query_impl has
    several early-return paths (table lookup hit, no-context fallback,
    normal generation path) plus an HTTPException path on local-LLM
    timeout, so latency/route metrics are recorded here in a
    try/finally rather than duplicated at each return site.
    """
    start = time.perf_counter()
    llm_route_for_metric = "unknown"
    try:
        response = await _query_impl(request, current_user, db)
        llm_route_for_metric = response.llm_route
        return response
    except HTTPException as exc:
        # Local LLM timeout (504) still routed through "local"; any
        # other HTTPException (403 RBAC, etc.) is left as "unknown"
        # since no route was actually selected.
        if exc.status_code == 504:
            llm_route_for_metric = "local"
        raise
    finally:
        elapsed = time.perf_counter() - start
        RAG_QUERY_LATENCY.labels(llm_route=llm_route_for_metric).observe(elapsed)
        if llm_route_for_metric in ("local", "api"):
            LLM_ROUTE_TOTAL.labels(llm_route=llm_route_for_metric).inc()


async def _query_impl(
    request: QueryRequest,
    # FIX: get_current_user returns a User ORM object, not CurrentUser Pydantic model
    current_user: User,
    db: AsyncSession,
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
        query_id = await _record_query_and_enqueue_judge(
            db=db,
            current_user=current_user,
            domain_uuids=domain_uuids,
            request_domain_ids=request.domain_ids,
            retrieval_chunks=table_result.chunks,
            graph_citations=[],
            query_text=request.query,
            answer_text=table_result.answer,
            llm_route="local",
            confidence_score=table_result.confidence_score,
        )
        return QueryResponse(
            query_id=query_id,
            answer=table_result.answer,
            llm_route="local",
            language_detected=detect_language(request.query),
            citations=citations,
            confidence_score=table_result.confidence_score,
            signals_used=table_result.signals_used or ["table"],
            evaluation=None,
        )

    # Retrieval — pipeline receives db so BM25 + Graph can query Postgres.
    # user_id is required so the pipeline can re-derive which of the
    # already-RBAC-checked domain_uuids the user holds a role in, for
    # NER label selection + graph traversal scoping (see
    # domain_resolver.get_accessible_domain_names). The per-domain
    # _check_domain_access loop above already guarantees every UUID in
    # domain_uuids is one the user can read, so this is a second,
    # independent resolution (UUID -> ontology key) rather than a
    # second permission check.
    pipeline = RetrievalPipeline(db)
    retrieval_result = await pipeline.retrieve(
        query=request.query,
        domain_ids=domain_uuids,
        user_id=current_user.id,
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
            fallback_answer = "I don't have enough information in the selected documents to answer that."
            query_id = await _record_query_and_enqueue_judge(
                db=db,
                current_user=current_user,
                domain_uuids=domain_uuids,
                request_domain_ids=request.domain_ids,
                retrieval_chunks=[],
                graph_citations=[],
                query_text=request.query,
                answer_text=fallback_answer,
                llm_route=llm_route,
                confidence_score=0.0,
            )
            return QueryResponse(
                query_id=query_id,
                answer=fallback_answer,
                llm_route=llm_route,
                language_detected=detect_language(request.query),
                citations=[],
                confidence_score=0.0,
                signals_used=retrieval_result.signals_used,
                evaluation=None,
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

    query_id = await _record_query_and_enqueue_judge(
        db=db,
        current_user=current_user,
        domain_uuids=domain_uuids,
        request_domain_ids=request.domain_ids,
        retrieval_chunks=retrieval_result.chunks,
        graph_citations=retrieval_result.graph_citations or [],
        query_text=request.query,
        answer_text=generation.answer,
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
        query_id=query_id,
        answer=generation.answer,
        llm_route=generation.llm_route,
        language_detected=generation.language_detected,
        citations=citations,
        confidence_score=retrieval_result.confidence_score,
        signals_used=retrieval_result.signals_used,
        evaluation=None,
    )


async def _record_query_and_enqueue_judge(
    db: AsyncSession,
    current_user: User,
    domain_uuids: list[UUID],
    request_domain_ids: list[str],
    retrieval_chunks: list[dict],
    graph_citations: list[dict],
    query_text: str,
    answer_text: str,
    llm_route: str,
    confidence_score: float,
) -> UUID:
    # Immutable per-query audit record. Judge results are stored separately.
    query_id = uuid4()
    audit_log = AuditLog(
        query_id=query_id,
        query_text=query_text,
        answer_text=answer_text,
        user_id=current_user.id,
        domains_queried=domain_uuids,
        retrieved_chunk_ids=_uuid_list(c.get("id") for c in retrieval_chunks),
        graph_nodes_traversed=_uuid_list(
            g.get("node_id") or g.get("node_uuid") for g in graph_citations
        ),
        llm_route=llm_route,
        confidence_score=confidence_score,
    )
    db.add(audit_log)
    await db.flush()
    await db.commit()

    _fire_judge_task(
        query_id=str(query_id),
        audit_log_id=str(audit_log.id),
        query=query_text,
        context=_build_judge_context(retrieval_chunks),
        graph_context=graph_citations,
        answer=answer_text,
        user_id=str(current_user.id),
        domain_ids=request_domain_ids,
        llm_route=llm_route,
        confidence_score=confidence_score,
    )
    return query_id


def _fire_judge_task(
    query_id,
    audit_log_id,
    query,
    context,
    graph_context,
    answer,
    user_id,
    domain_ids,
    llm_route,
    confidence_score,
):
    try:
        from app.workers.tasks import run_judge_evaluation
        run_judge_evaluation.delay(
            query_id=query_id,
            audit_log_id=audit_log_id,
            query=query,
            context=context,
            graph_context=graph_context,
            answer=answer,
            user_id=user_id,
            domain_ids=domain_ids,
            llm_route=llm_route,
            confidence_score=confidence_score,
        )
    except Exception:
        pass  # never block the response for judge failures

def _build_judge_context(chunks: list[dict]) -> list[dict]:
    return [
        {
            "source_number": index,
            "chunk_id": str(c.get("id", "")),
            "document_title": c.get("document_title", "Unknown"),
            "page_number": c.get("page_number"),
            "section": c.get("section"),
            "domain_id": str(c.get("domain_id", "")),
            "domain_name": c.get("domain_name", ""),
            "relevance_score": c.get("score", 0.0),
            "content": c.get("content", ""),
        }
        for index, c in enumerate(chunks, start=1)
    ]


def _uuid_list(values) -> list[UUID]:
    result = []
    for value in values:
        if not value:
            continue
        try:
            result.append(UUID(str(value)))
        except (TypeError, ValueError):
            continue
    return result
