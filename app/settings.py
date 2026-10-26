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

    # --- Qdrant ---
    QDRANT_ENABLED: bool = False
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = Field(default=6333, ge=1, le=65535)
    QDRANT_API_KEY: str | None = None
    QDRANT_TIMEOUT: int = Field(default=10, ge=1)
    QDRANT_COLLECTION_ALIAS: str = "chunks"

    # --- MongoDB ---
    MONGO_ENABLED: bool = False
    MONGO_HOST: str = "localhost"
    MONGO_PORT: int = Field(default=27017, ge=1, le=65535)
    MONGO_USER: str = ""
    MONGO_PASSWORD: str = ""
    MONGO_DB: str = "docsearch"
    MONGO_MAX_POOL_SIZE: int = Field(default=10, ge=1)
    MONGO_TIMEOUT_MS: int = Field(default=5000, ge=1)

    # --- S3 (SeaweedFS locally) ---
    S3_ENABLED: bool = False
    S3_ENDPOINT_URL: str = "http://localhost:8333"
    S3_REGION: str = "us-east-1"
    S3_ACCESS_KEY_ID: str = ""
    S3_SECRET_ACCESS_KEY: str = ""
    S3_BUCKET: str = "docsearch"
    # Total tries per request, including the first; botocore backs off between.
    S3_MAX_ATTEMPTS: int = Field(default=3, ge=1)

    # --- Keycloak ---
    # KEYCLOAK_URL is where the API fetches the signing keys (inside Docker:
    # http://keycloak:8080). KEYCLOAK_PUBLIC_URL is the address the browser
    # uses, which Keycloak writes into each token's issuer; empty means same.
    KEYCLOAK_URL: str = "http://localhost:8080"
    KEYCLOAK_PUBLIC_URL: str = ""
    KEYCLOAK_REALM: str = "docsearch"
    KEYCLOAK_AUDIENCE: str = "docsearch-api"
    KEYCLOAK_JWKS_CACHE_SECONDS: int = Field(default=300, ge=0)

    # --- Celery ---
    # Broker shares the Redis server above, on its own database number.
    CELERY_REDIS_DB: int = Field(default=1, ge=0)
    CELERY_MAX_RETRIES: int = Field(default=5, ge=0)
    CELERY_REQUEUE_AFTER_MINUTES: int = Field(default=5, ge=1)

    # --- Embeddings ---
    EMBEDDING_DENSE_MODEL: str = "BAAI/bge-base-en-v1.5"
    EMBEDDING_SPARSE_MODEL: str = "Qdrant/bm25"
    EMBEDDING_BM25_LANGUAGE: str = "english"
    EMBEDDING_BATCH_SIZE: int = Field(default=32, ge=1)
    # Where fastembed keeps downloaded models; None uses its temp-dir default.
    EMBEDDING_CACHE_DIR: str | None = None

    # --- Reranker ---
    RERANKER_MODEL: str = "BAAI/bge-reranker-base"
    RERANKER_CANDIDATES: int = Field(default=20, ge=1)
    RERANKER_TOP_K: int = Field(default=5, ge=1)

    # --- LLM ---
    LLM_ANTHROPIC_API_KEY: str | None = None
    LLM_OPENAI_API_KEY: str | None = None
    LLM_OLLAMA_BASE_URL: str = "http://localhost:11434/v1"
    LLM_TIMEOUT: float = Field(default=120.0, gt=0)
    LLM_MAX_OUTPUT_TOKENS: int = Field(default=2048, ge=1)
    LLM_CONTEXT_TOKEN_BUDGET: int = Field(default=6000, ge=1)
    LLM_HISTORY_MESSAGES: int = Field(default=6, ge=0)

    # --- Upload ---
    UPLOAD_MAX_FILE_SIZE_MB: int = Field(default=50, ge=1)
    UPLOAD_MAX_FILES: int = Field(default=10, ge=1)
    UPLOAD_OCR_LANGUAGE: str = "en"

    # --- Cache ---
    CACHE_ENABLED: bool = True
    CACHE_QUERY_VECTOR_TTL_SECONDS: int = Field(default=7 * 24 * 3600, ge=1)
    CACHE_SEARCH_RESULT_TTL_SECONDS: int = Field(default=3600, ge=1)

    # --- OpenTelemetry ---
    # Names match the standard OTEL_* variables. No endpoint prints spans
    # to the console instead of exporting them.
    OTEL_ENABLED: bool = False
    OTEL_SERVICE_NAME: str = "docsearch-api"
    OTEL_EXPORTER_OTLP_ENDPOINT: str | None = None

    # --- Langfuse ---
    # Switched on when both keys are set.
    LANGFUSE_PUBLIC_KEY: str | None = None
    LANGFUSE_SECRET_KEY: str | None = None
    LANGFUSE_HOST: str = "https://cloud.langfuse.com"

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

    @model_validator(mode="after")
    def _require_s3_credentials(self) -> Settings:
        """Without keys, aioboto3 fails on the first request, not at boot."""
        if self.S3_ENABLED and not (
            self.S3_ACCESS_KEY_ID and self.S3_SECRET_ACCESS_KEY
        ):
            raise ValueError(
                "S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY required when S3_ENABLED=true"
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

    @property
    def celery_broker_url(self) -> str:
        """Redis URL for Celery: the Redis server above, its own database."""
        auth = f":{quote_plus(self.REDIS_PASSWORD)}@" if self.REDIS_PASSWORD else ""
        return (
            f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.CELERY_REDIS_DB}"
        )

    @property
    def qdrant_url(self) -> str:
        """Qdrant REST address."""
        return f"http://{self.QDRANT_HOST}:{self.QDRANT_PORT}"

    @property
    def mongo_dsn(self) -> str:
        """MongoDB connection string, with credentials escaped when set."""
        if not self.MONGO_USER:
            return f"mongodb://{self.MONGO_HOST}:{self.MONGO_PORT}"
        user = quote_plus(self.MONGO_USER)
        password = quote_plus(self.MONGO_PASSWORD)
        return f"mongodb://{user}:{password}@{self.MONGO_HOST}:{self.MONGO_PORT}"

    @property
    def keycloak_issuer(self) -> str:
        """The ``iss`` claim tokens must carry: the browser-facing realm URL."""
        base = self.KEYCLOAK_PUBLIC_URL or self.KEYCLOAK_URL
        return f"{base.rstrip('/')}/realms/{self.KEYCLOAK_REALM}"

    @property
    def keycloak_jwks_url(self) -> str:
        """Where the API downloads the realm's public signing keys."""
        return (
            f"{self.KEYCLOAK_URL.rstrip('/')}/realms/{self.KEYCLOAK_REALM}"
            "/protocol/openid-connect/certs"
        )

    @property
    def upload_max_file_size_bytes(self) -> int:
        """Per-file upload limit in bytes."""
        return self.UPLOAD_MAX_FILE_SIZE_MB * 1024 * 1024

    @property
    def langfuse_enabled(self) -> bool:
        """Langfuse tracing runs only when both keys are set."""
        return bool(self.LANGFUSE_PUBLIC_KEY and self.LANGFUSE_SECRET_KEY)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
