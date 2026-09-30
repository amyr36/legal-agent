import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base


DATABASE_URL = os.getenv("DATABASE_URL")

# read from docker compose
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is not set")

engine_kwargs = {}
if DATABASE_URL.startswith("sqlite"):
    # FastAPI runs sync endpoints in a threadpool, so pooled sqlite
    # connections must be usable across threads.
    engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, **engine_kwargs)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()