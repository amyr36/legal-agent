from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import settings


def _create_engine() -> Engine:
    connect_args: dict[str, object] = {}
    if settings.DATABASE_URL.startswith("sqlite"):
        # FastAPI executes sync dependencies in a thread pool, so SQLite
        # connections must be allowed to move between worker threads.
        connect_args["check_same_thread"] = False

    return create_engine(
        settings.DATABASE_URL,
        connect_args=connect_args,
        pool_pre_ping=True,
    )


engine = _create_engine()
SessionLocal = sessionmaker(
    bind=engine,
    class_=Session,
    autoflush=False,
    expire_on_commit=False,
)


def get_db() -> Generator[Session, None, None]:
    """Provide one database session per request and always close it."""

    with SessionLocal() as session:
        yield session
