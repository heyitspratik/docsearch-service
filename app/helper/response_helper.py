"""Helper functions for consistent API responses."""

from __future__ import annotations

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class BaseResponse:  # noqa: D401
    @staticmethod
    async def request_exception_response(exc: RequestValidationError) -> JSONResponse:  # noqa: D401
        errors = exc.errors()
        return JSONResponse(status_code=422, content={"detail": errors})
