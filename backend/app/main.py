from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.core.database import Base, engine
from app.api.v1.endpoints import domains, auth

# Import models so SQLAlchemy registers them
from app.models import user, domain


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(title="RAG Platform", lifespan=lifespan)

app.include_router(auth.router, prefix="/api/v1")
app.include_router(domains.router, prefix="/api/v1")