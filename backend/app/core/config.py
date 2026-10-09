from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


# core/config.py  →  core/  →  app/  →  backend/   (inside Docker: /app)
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent

SOURCES_DIR = os.environ.get("STORAGE_DIR", os.path.join(BACKEND_DIR, "storage"))

ANALYSIS_DIR = Path(os.environ.get("ANALYSIS_STORAGE_DIR", BACKEND_DIR / "analysis_storage"))
ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)

RESULTS_PATH = str(ANALYSIS_DIR / "analysis_results.jsonl")

DOCUMENT_SLOTS = {
    "A": {
        "context_path": os.path.join(SOURCES_DIR, "context_A.jsonl"),
        "temp_dir": os.path.join(SOURCES_DIR, "temp", "document_A"),
    },
    "B": {
        "context_path": os.path.join(SOURCES_DIR, "context_B.jsonl"),
        "temp_dir": os.path.join(SOURCES_DIR, "temp", "document_B"),
    },
}

CHECKPOINT_DB = os.environ.get("LEGAL_SIM_CHECKPOINT_DB", str(ANALYSIS_DIR / "checkpoints.sqlite"))
CANDIDATES_PATH = str(ANALYSIS_DIR / "candidates.jsonl")
MAX_MISSING_RATIO = 0.0

# ---------------------------------------------------------------------------
# Embedding model
# ---------------------------------------------------------------------------

EMBEDDING_MODEL = "myrkur/sentence-transformer-parsbert-fa-2.0"

# ---------------------------------------------------------------------------
# Record schema
# ---------------------------------------------------------------------------

METADATA_FIELDS = [
    "id",
    "law_seq",
    "category",
    "law",
    "book",
    "chapter",
    "subchapter",
    "type",
    "number_raw",
    "number",
    "parent_number",
    "breadcrumb",
]

# internal-only key added to Document.metadata so we can recover the record index
RECORD_INDEX_KEY = "_record_index"

# ---------------------------------------------------------------------------
# Retrieval / LLM tunables
# ---------------------------------------------------------------------------

TOP_K = 2
LLM_BATCH_SIZE = 5
LLM_MAX_RETRIES = 2
MAX_CONCURRENT_REQUESTS = 2

# ---------------------------------------------------------------------------
# Chat model config
# ---------------------------------------------------------------------------

CHAT_MODEL_BASE_URL = "https://api.apmix.ai/v1"
CHAT_MODEL_API_KEY = "apx_live_1eEKs5DnQOq282Rl3JXfO0fXyg9UqlsnW2YA9GFz"
CHAT_MODEL_NAME = "deepseek-v4-flash-free"
EFFORT_ON = False
EFFORT_LEVEL = "high"

# ---------------------------------------------------------------------------
# Legal relation taxonomy
# ---------------------------------------------------------------------------

RELATION_VALUES = ["مشابه", "متناقض"]

RELATION_TYPE_VALUES = ["تکرار مقرراتی", "اقتباس", "تکمیل", "تخصیص", "تعارض", "نسخ صریح", "نسخ ضمنی", "ابهام تفسیری", "ناسازگاری"]


# ---------------------------------------------------------------------------
# crud branch
# ---------------------------------------------------------------------------


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATABASE_URL = "sqlite:///./legal_agent.db"


class Settings(BaseSettings):
    """Application settings loaded from environment variables or the root .env."""
    
    SECRET_KEY: SecretStr = SecretStr("change-me")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    APP_NAME: str = "Legal Agent"
    DEBUG: bool = False
    AUTO_CREATE_TABLES: bool = True
    API_PREFIX: str = "/api/v1"
    CORS_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"

    DATABASE_URL: str = DEFAULT_DATABASE_URL
    STORAGE_DIR: str = "/app/storage"

    LLM_PROVIDER: str = "avalai"
    AVALAI_API_KEY: str | None = None
    AVALAI_BASE_URL: str = "https://api.avalai.ir/v1"
    AVALAI_MODEL: str | None = None
    STRUCTURE_MODEL: str | None = None

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def use_default_database_for_blank_value(cls, value: object) -> object:
        if value is None or (isinstance(value, str) and not value.strip()):
            return DEFAULT_DATABASE_URL
        return value

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
