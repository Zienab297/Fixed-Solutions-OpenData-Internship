"""
RAG System — FastAPI Application Entry Point
Multi-User Multi-Domain RAG System MVP
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from prometheus_fastapi_instrumentator import Instrumentator

from app.core.config import settings
from app.api.v1.endpoints import query, ingest, domains, audit, evaluate


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # Startup: verify DB connections, warm embedding model
    print("Starting RAG System API...")
    yield
    # Shutdown: cleanup
    print("Shutting down RAG System API...")


app = FastAPI(
    title="Multi-User Multi-Domain RAG System",
    description="Self-hosted RAG with RBAC, hybrid retrieval, and Judge LLM evaluation",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.APP_ENV != "production" else None,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Prometheus metrics instrumentation (§6.2)
Instrumentator().instrument(app).expose(app)

# Register routers — all under /api/v1
app.include_router(query.router, prefix="/api/v1")
app.include_router(ingest.router, prefix="/api/v1")
app.include_router(domains.router, prefix="/api/v1")
app.include_router(audit.router, prefix="/api/v1")
app.include_router(evaluate.router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}
