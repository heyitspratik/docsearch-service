"""Correlation id, timing and access logging.

Pure ASGI rather than ``BaseHTTPMiddleware``, which breaks streaming responses
and background tasks.
"""

from __future__ import annotations

import logging
import time

from starlette import status
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.log import new_request_id, reset_request_id, set_request_id

logger = logging.getLogger("app.access")

REQUEST_ID_HEADER = "x-request-id"
PROCESS_TIME_HEADER = "x-process-time"

#: Key under which the correlation id is stored on the ASGI scope.
SCOPE_REQUEST_ID_KEY = "app_request_id"


class RequestContextMiddleware:
    """Bind a correlation id to each request and log how it finished."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        header_name: str = REQUEST_ID_HEADER,
        exclude_paths: frozenset[str] = frozenset(),
    ) -> None:
        self.app = app
        self.header_name = header_name.lower()
        self.exclude_paths = exclude_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Process one connection."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Reuse an upstream id so a trace spans the whole request chain.
        incoming = Headers(scope=scope).get(self.header_name)
        request_id = incoming or new_request_id()
        token = set_request_id(request_id)
        # The scope outlives the contextvar reset below, which is how the
        # catch-all handler can still label an unhandled 500.
        scope[SCOPE_REQUEST_ID_KEY] = request_id

        path: str = scope.get("path", "")
        method: str = scope.get("method", "")
        started = time.perf_counter()
        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = MutableHeaders(scope=message)
                headers[self.header_name] = request_id
                elapsed_ms = (time.perf_counter() - started) * 1000
                headers[PROCESS_TIME_HEADER] = f"{elapsed_ms:.2f}"
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            self._log(method, path, status.HTTP_500_INTERNAL_SERVER_ERROR, started)
            raise
        else:
            if path not in self.exclude_paths:
                self._log(method, path, status_code, started)
        finally:
            reset_request_id(token)

    @staticmethod
    def _log(method: str, path: str, status_code: int, started: float) -> None:
        elapsed_ms = (time.perf_counter() - started) * 1000
        level = (
            logging.WARNING
            if status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR
            else logging.INFO
        )
        logger.log(
            level,
            "%s %s %s %.2fms",
            method,
            path,
            status_code,
            elapsed_ms,
            extra={
                "http_method": method,
                "http_path": path,
                "http_status": status_code,
                "duration_ms": round(elapsed_ms, 2),
            },
        )
