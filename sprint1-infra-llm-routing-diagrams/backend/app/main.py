from fastapi import FastAPI

from app.api.v1.endpoints.query import router as query_router
from app.core.config import settings


app = FastAPI(
    title="Multi-User Multi-Domain RAG Sprint 1",
    description="Walking skeleton for auth, retrieval, LLM routing, and generation.",
    version="0.1.0",
    docs_url="/docs" if settings.APP_ENV != "production" else None,
)

app.include_router(query_router, prefix="/api/v1")


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "environment": settings.APP_ENV,
        "mock_llm_responses": str(settings.MOCK_LLM_RESPONSES).lower(),
    }
