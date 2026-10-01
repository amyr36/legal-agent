from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


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
