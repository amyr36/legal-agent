from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text, select
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional


from app.api.routers import document_router, analyses_router, auth_router

from app.core.config import settings
from app.db.base import Base
from app.db.database import engine, SessionLocal

# Register all SQLAlchemy models at startup so Base.metadata sees every table.
from app.models import (
    Analysis,
    Doc,
    DocRelationship,
    Domain,
    Organization,
    RelationshipType,
    Role,
    User,
)


class AnalyzeRequest(BaseModel):
    document_a: Optional[List[Dict[str, Any]]]
    document_b: Optional[List[Dict[str, Any]]]
    rebuild: bool = Field(default=False, description="rebuild Chunks and VectorDatabase")


class AnalyzeResponse(BaseModel):
    count: int
    relations: List[Dict[str, Any]]



@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        # سازمان پیش‌فرض
        if db.scalar(select(Organization).limit(1)) is None:
            db.add(Organization(organization_id=1, name="majles"))
        # نقش‌های پیش‌فرض
        if db.scalar(select(Role).limit(1)) is None:
            db.add_all([Role(role_id=1, title="user"), Role(role_id=2, title="admin")])
        db.commit()
    yield
    engine.dispose()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"],
    allow_headers=["Accept", "Content-Type"],
)
app.include_router(analyses_router.router)
app.include_router(auth_router.router, prefix=settings.API_PREFIX)
app.include_router(document_router.router, prefix=settings.API_PREFIX)


@app.get("/", tags=["system"])
def root() -> dict[str, str]:
    return {"name": settings.APP_NAME, "status": "ok"}


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok"}
