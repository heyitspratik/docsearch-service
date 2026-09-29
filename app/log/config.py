"""Logging setup."""

from __future__ import annotations

import logging
import logging.config
import sys
from typing import Any

from app.settings import Settings


def build_logging_config(settings: Settings) -> dict[str, Any]:
    """Build the ``dictConfig`` payload for the given settings."""
    use_json = settings.APP_LOG_FORMAT == "json"
    level = settings.APP_LOG_LEVEL.value

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "request_context": {"()": "app.log.context.RequestContextFilter"},
        },
        "formatters": {
            "json": {"()": "app.log.formatters.JsonFormatter"},
            "console": {
                "()": "app.log.formatters.ConsoleFormatter",
                "use_colour": sys.stderr.isatty(),
            },
            # Same layout without the logger name, so uvicorn's startup lines
            # are not labelled "uvicorn.error" at INFO level.
            "uvicorn": {
                "()": "app.log.formatters.ConsoleFormatter",
                "use_colour": sys.stderr.isatty(),
                "show_name": False,
            },
        },
        "handlers": {
            "default": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "formatter": "json" if use_json else "console",
                "filters": ["request_context"],
            },
            "uvicorn": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "formatter": "json" if use_json else "uvicorn",
                "filters": ["request_context"],
            },
        },
        "root": {"handlers": ["default"], "level": level},
        "loggers": {
            # Silenced: RequestContextMiddleware already logs every request.
            "uvicorn.access": {"handlers": [], "propagate": False, "level": "WARNING"},
            "uvicorn.error": {
                "handlers": ["uvicorn"],
                "propagate": False,
                "level": level,
            },
            "uvicorn": {"handlers": ["uvicorn"], "propagate": False, "level": level},
        },
    }


def configure_logging(settings: Settings) -> None:
    """Apply the logging configuration for this process."""
    logging.config.dictConfig(build_logging_config(settings))
    logging.captureWarnings(capture=True)
