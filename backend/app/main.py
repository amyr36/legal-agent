from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.routers import analyses, documents
from app.core.config import settings
from app.db.base import Base
from app.db.database import engine

# Register all SQLAlchemy models at startup so Base.metadata sees every table.
from app.models import (
    Analysis,
    AnalysisKeyword,
    Doc,
    DocNode,
    DocRelationship,
    DocVersion,
    Domain,
    Keyword,
    NodeRelationship,
    Organization,
    RelationshipType,
    Role,
    User,
)
from backend.app.api.routers.system import auth_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Create the schema and optionally load the local sample at startup."""

    if settings.AUTO_CREATE_TABLES:
        Base.metadata.create_all(bind=engine)
    yield
    engine.dispose()


app = FastAPI(
    title=settings.APP_NAME,
    debug=settings.DEBUG,
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"],
    allow_headers=["Accept", "Content-Type"],
)
app.include_router(analyses.router, prefix=settings.API_PREFIX)
app.include_router(auth_router.router, prefix=settings.API_PREFIX)
app.include_router(documents.router, prefix=settings.API_PREFIX)


@app.get("/", tags=["system"])
def root() -> dict[str, str]:
    return {"name": settings.APP_NAME, "status": "ok"}


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok"}
