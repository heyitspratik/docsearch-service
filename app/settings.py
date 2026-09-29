"""Application configuration.

Field names match the environment variables exactly, so any setting can be
grepped for by the name used in ``.env``.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal
from urllib.parse import quote_plus

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.constants import Environment, LogLevel

ASYNC_DRIVERS = ("+asyncpg", "+aiomysql", "+asyncmy", "+aiosqlite", "+psycopg")


class Settings(BaseSettings):
    """All application configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Application ---
    APP_NAME: str = "FastAPI Service"
    APP_VERSION: str = "0.1.0"
    APP_DESCRIPTION: str = "FastAPI microservice"
    APP_ENVIRONMENT: Environment = Environment.LOCAL
    APP_HOST: str = "0.0.0.0"  # noqa: S104
    APP_PORT: int = Field(default=8000, ge=1, le=65535)
    APP_WORKERS: int = Field(default=1, ge=1)
    APP_RELOAD: bool = False
    APP_ROOT_PATH: str = ""
    APP_API_PREFIX: str = "/api"
    APP_DOCS_ENABLED: bool = True
    APP_LOG_LEVEL: LogLevel = LogLevel.INFO
    APP_LOG_FORMAT: Literal["console", "json"] = "console"

    # --- Database ---
    DB_ENABLED: bool = False
    DB_DRIVER: str = "postgresql+asyncpg"
    DB_HOST: str = "localhost"
    DB_PORT: int = Field(default=5432, ge=1, le=65535)
    DB_USER: str = ""
    DB_PASSWORD: str = ""
    DB_NAME: str = ""
    DB_POOL_SIZE: int = Field(default=10, ge=1)
    DB_MAX_OVERFLOW: int = Field(default=10, ge=0)
    DB_POOL_PRE_PING: bool = True
    DB_ECHO: bool = False

    # --- Redis ---
    REDIS_ENABLED: bool = False
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = Field(default=6379, ge=1, le=65535)
    REDIS_DB: int = Field(default=0, ge=0)
    REDIS_PASSWORD: str | None = None
    REDIS_MAX_CONNECTIONS: int = Field(default=10, ge=1)
    REDIS_SOCKET_TIMEOUT: float = 5.0

    @field_validator("DB_DRIVER")
    @classmethod
    def _require_async_driver(cls, value: str) -> str:
        """Reject sync drivers, which fail deep inside the engine."""
        if not any(driver in value for driver in ASYNC_DRIVERS):
            raise ValueError(f"DB_DRIVER must be async, one of {ASYNC_DRIVERS}")
        return value

    @model_validator(mode="after")
    def _require_db_credentials(self) -> Settings:
        """Empty credentials silently fall back to the OS user."""
        if self.DB_ENABLED and not (self.DB_USER and self.DB_PASSWORD and self.DB_NAME):
            raise ValueError(
                "DB_USER, DB_PASSWORD, DB_NAME required when DB_ENABLED=true"
            )
        return self

    @property
    def expose_docs(self) -> bool:
        """Whether interactive docs should be mounted. Never in production."""
        return self.APP_DOCS_ENABLED and not self.APP_ENVIRONMENT.is_production

    @property
    def db_dsn(self) -> str:
        """SQLAlchemy connection string, with credentials escaped."""
        user = quote_plus(self.DB_USER)
        password = quote_plus(self.DB_PASSWORD)
        return (
            f"{self.DB_DRIVER}://{user}:{password}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    @property
    def redis_dsn(self) -> str:
        """Redis connection string, with the password escaped."""
        auth = f":{quote_plus(self.REDIS_PASSWORD)}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
