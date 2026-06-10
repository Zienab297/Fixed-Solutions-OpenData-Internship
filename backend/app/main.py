from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.endpoints.audit import router as audit_router
from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.domains import router as domains_router
from app.api.v1.endpoints.evaluate import router as evaluate_router
from app.api.v1.endpoints.main import router as pdf_processing_router
from app.api.v1.endpoints.query import router as query_router
from app.core.config import settings
from app.core.database import Base, engine
from app.ingestion.models import IngestionJob
from app.ingestion.router import router as ingestion_router
from app.models import domain, user


Base.metadata.create_all(bind=engine)


app = FastAPI(
    title="Multi-User Multi-Domain RAG Sprint 1",
    description="Walking skeleton for auth, retrieval, LLM routing, and generation.",
    version="0.1.0",
    docs_url="/docs" if settings.APP_ENV != "production" else None,
)

frontend_origins = [
    origin.strip()
    for origin in settings.FRONTEND_ORIGINS.split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=frontend_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(query_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(domains_router, prefix="/api/v1")
app.include_router(ingestion_router, prefix="/api/v1")
app.include_router(pdf_processing_router, prefix="/api/v1")
app.include_router(audit_router, prefix="/api/v1")
app.include_router(evaluate_router, prefix="/api/v1")


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "environment": settings.APP_ENV,
        "mock_llm_responses": str(settings.MOCK_LLM_RESPONSES).lower(),
    }
