"""Project-level custom exceptions."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from fastapi.responses import JSONResponse


class BaseHTTPException(HTTPException):
    """Base HTTP exception carrying a JSON body."""

    def __init__(self, status_code: int, detail: Any) -> None:  # noqa: D401
        super().__init__(status_code=status_code, detail=detail)

    @staticmethod
    def to_response(request, exc: "BaseHTTPException") -> JSONResponse:  # noqa: D401
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )
