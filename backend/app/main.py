"""
RAG System — FastAPI Application Entry Point
Multi-User Multi-Domain RAG System MVP
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from app.core.config import settings
from app.api.v1.endpoints import query, ingest, domains, audit, evaluate


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Starting RAG System API...")
    yield
    print("Shutting down RAG System API...")


app = FastAPI(
    title="Multi-User Multi-Domain RAG System",
    description="Self-hosted RAG with RBAC, hybrid retrieval, and Judge LLM evaluation",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.APP_ENV != "production" else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Instrumentator().instrument(app).expose(app)

app.include_router(query.router, prefix="/api/v1")
app.include_router(ingest.router, prefix="/api/v1")
app.include_router(domains.router, prefix="/api/v1")
app.include_router(audit.router, prefix="/api/v1")
app.include_router(evaluate.router, prefix="/api/v1")


@app.get("/health", tags=["health"])
async def health() -> dict:
    return {
        "status": "ok",
        "version": "0.1.0",
        "environment": settings.APP_ENV,
        "mock_llm_responses": str(settings.MOCK_LLM_RESPONSES).lower(),
    }