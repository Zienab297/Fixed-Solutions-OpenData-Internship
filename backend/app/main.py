from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.endpoints import ingest, query, auth
from app.api.v1.endpoints.domains import router as domains_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: nothing heavy needed — DB schema is created by init.sql
    yield
    # Shutdown
    pass


app = FastAPI(title="RAG Platform", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/v1")
app.include_router(domains_router, prefix="/api/v1")
app.include_router(ingest.router, prefix="/api/v1")
app.include_router(query.router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok"}