"""Application configuration settings.

These settings can be overridden via environment variables or a .env file.
"""

from __future__ import annotations

import enum
from pathlib import Path
from tempfile import gettempdir

from pydantic_settings import BaseSettings
from yarl import URL

TEMP_DIR = Path(gettempdir())


class LogLevel(str, enum.Enum):
    NOTSET = "NOTSET"
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    FATAL = "FATAL"


class Settings(BaseSettings):
    """Main application settings container."""

    # --- App ---
    host: str = "0.0.0.0"
    port: int = 8000
    workers_count: int = 1
    reload: bool = False
    environment: str = "dev"
    log_level: LogLevel = LogLevel.INFO

    class Config:  # noqa: D106, WPS306
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()
