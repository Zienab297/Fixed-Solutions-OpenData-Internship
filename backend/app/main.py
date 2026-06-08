from fastapi import FastAPI
from app.core.database import Base, engine
from app.api.v1.endpoints import domains

# import models so SQLAlchemy registers them
from app.models import user, domain

Base.metadata.create_all(bind=engine)

app = FastAPI(title="RAG Platform")

app.include_router(domains.router, prefix="/api/v1")
app.include_router(domains.router, prefix="/api/v1")