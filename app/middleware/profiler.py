"""Simple profiling middleware to log request processing time."""

from __future__ import annotations

import logging
import time
from typing import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


class ProfilerMiddleware(BaseHTTPMiddleware):
    """Middleware that measures and logs request processing time."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:  # type: ignore[override]
        start_time = time.perf_counter()
        response = await call_next(request)
        duration = (time.perf_counter() - start_time) * 1000
        logger.info(
            "%s %s completed in %.2f ms", request.method, request.url.path, duration
        )
        response.headers["X-Process-Time"] = str(duration)
        return response
