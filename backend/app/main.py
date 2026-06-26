import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from app.api.v1.endpoints import evaluate, ingest, query, auth
from app.api.v1.endpoints.domains import router as domains_router
from app.core.database import AsyncSessionLocal, Base, engine
from app.core.logging_config import configure_json_logging
from app.utils.seed import seed_admin

configure_json_logging(service_name="rag-api")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from sqlalchemy import text  
    
    logger.info("Creating database schema 'rag' if it does not exist...")
    async with engine.begin() as conn:
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS rag;"))
        
    logger.info("Creating database tables if they do not exist...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
    logger.info("Seeding system admin...")
    async with AsyncSessionLocal() as db:
        await seed_admin(db)
        await db.commit()
        
    logger.info("rag-api startup complete")
    yield


app = FastAPI(title="RAG Platform", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Observability (§6.2) -------------------------------------------------
# Instrumentator auto-exposes per-route HTTP request duration/count as
# Prometheus histograms (http_request_duration_seconds with P50/P95
# derivable via histogram_quantile in PromQL) and serves them on
# GET /metrics. This covers generic HTTP-level latency; the
# rag-pipeline-specific metrics (retrieval signals, graph latency,
# judge queue depth, eval latency) are recorded explicitly in
# query.py / workers/tasks.py via app/core/metrics.py.
Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

app.include_router(auth.router, prefix="/api/v1")
app.include_router(domains_router, prefix="/api/v1")
app.include_router(ingest.router, prefix="/api/v1")
app.include_router(query.router, prefix="/api/v1")
app.include_router(evaluate.router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "healthy"}