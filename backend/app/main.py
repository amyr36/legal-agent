from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text, select

from app.api.routers import document_router
from app.api.routers import auth_router
from app.core.config import settings
from app.db.base import Base
from app.db.database import engine, SessionLocal

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

@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)

    with SessionLocal() as db:
        # سازمان پیش‌فرض
        if db.scalar(select(Organization).limit(1)) is None:
            db.add(Organization(
                organization_id=1,
                name="majles",
            ))

        # نقش‌های پیش‌فرض
        if db.scalar(select(Role).limit(1)) is None:
            db.add_all([
                Role(role_id=1, title="user"),
                Role(role_id=2, title="admin"),
            ])

        db.commit()

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
#app.include_router(analyses.router, prefix=settings.API_PREFIX)
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
