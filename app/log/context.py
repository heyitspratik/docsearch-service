"""Request-scoped logging context."""

from __future__ import annotations

import logging
import uuid
from contextvars import ContextVar, Token

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


def new_request_id() -> str:
    """Generate a correlation id for a request that arrived without one."""
    return uuid.uuid4().hex


def get_request_id() -> str | None:
    """Return the current request's correlation id, if any."""
    return request_id_var.get()


def set_request_id(request_id: str) -> Token[str | None]:
    """Bind a correlation id to the current context."""
    return request_id_var.set(request_id)


def reset_request_id(token: Token[str | None]) -> None:
    """Restore the previous correlation id."""
    request_id_var.reset(token)


class RequestContextFilter(logging.Filter):
    """Attach the current correlation id to every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Always passes the record through, after tagging it."""
        # An explicit extra={"request_id": ...} wins over the contextvar.
        existing = getattr(record, "request_id", None)
        if not existing or existing == "-":
            record.request_id = request_id_var.get() or "-"
        return True
