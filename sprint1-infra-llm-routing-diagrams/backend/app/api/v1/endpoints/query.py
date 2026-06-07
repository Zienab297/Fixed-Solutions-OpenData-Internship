from fastapi import APIRouter

from app.schemas.query import QueryRequest, QueryResponse
from app.services.llm.router import LLMRouter


router = APIRouter(prefix="/query", tags=["query"])


@router.post("", response_model=QueryResponse)
async def query(request: QueryRequest) -> QueryResponse:
    router_service = LLMRouter()
    result = await router_service.generate(
        query=request.query,
        context=request.context,
        domain_ids=request.domain_ids,
        domain_routes=request.domain_routes,
    )

    return QueryResponse(
        answer=result.answer,
        llm_route=result.llm_route,
        language_detected=result.language_detected,
        citations=[],
    )
