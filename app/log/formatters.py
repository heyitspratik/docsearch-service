"""Log formatters."""

from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Any, ClassVar

_RESERVED: frozenset[str] = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
        "taskName",
        "request_id",
    }
)


class JsonFormatter(logging.Formatter):
    """Render records as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        """Serialise a record to a single-line JSON object."""
        payload: dict[str, Any] = {
            "timestamp": dt.datetime.fromtimestamp(
                record.created, tz=dt.UTC
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)

        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value

        return json.dumps(payload, default=str, ensure_ascii=False)


class ConsoleFormatter(logging.Formatter):
    """Readable single-line output with the correlation id inline."""

    _COLOURS: ClassVar[dict[str, str]] = {
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[1;31m",
    }
    _RESET = "\033[0m"

    def __init__(self, *, use_colour: bool = True) -> None:
        super().__init__(
            fmt="%(asctime)s %(levelname)-8s [%(request_id)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        self.use_colour = use_colour

    def format(self, record: logging.LogRecord) -> str:
        """Format a record, colouring the level name when attached to a TTY."""
        if not self.use_colour:
            return super().format(record)

        original = record.levelname
        colour = self._COLOURS.get(original, "")
        record.levelname = f"{colour}{original}{self._RESET}"
        try:
            return super().format(record)
        finally:
            record.levelname = original
