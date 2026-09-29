"""Exception handlers producing one consistent error shape."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.constants import ErrorCode, ErrorMessages
from app.exceptions.base_exception import BaseError
from app.log import get_request_id
from app.middleware import SCOPE_REQUEST_ID_KEY
from app.schemas.response import ErrorBody, ErrorDetail, ErrorResponse

logger = logging.getLogger(__name__)


def _request_id(request: Request | None) -> str | None:
    """Resolve the correlation id from the scope, falling back to the context."""
    if request is not None:
        scoped = request.scope.get(SCOPE_REQUEST_ID_KEY)
        if scoped:
            return str(scoped)
    return get_request_id()


def _render(
    request: Request | None,
    status_code: int,
    code: str,
    message: str,
    details: object = None,
) -> JSONResponse:
    """Serialise an error into the standard envelope."""
    body = ErrorResponse(
        error=ErrorBody(code=code, message=message, details=details),
        request_id=_request_id(request),
    )
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(mode="json", exclude_none=True),
    )


def _as_details(errors: Sequence[Any]) -> list[ErrorDetail]:
    """Flatten pydantic errors into the response detail shape."""
    details: list[ErrorDetail] = []
    for error in errors:
        location = [str(part) for part in error.get("loc", ()) if part != "body"]
        details.append(
            ErrorDetail(
                field=".".join(location) or None,
                message=str(error.get("msg", ErrorMessages.INVALID_VALUE)),
                type=str(error.get("type")) if error.get("type") else None,
            )
        )
    return details


def register_exception_handlers(app: FastAPI) -> None:
    """Attach every handler to the application."""

    @app.exception_handler(BaseError)
    async def handle_app_error(request: Request, exc: BaseError) -> JSONResponse:
        """Expected failures raised by our own code."""
        # Only 5xx is our fault, so only 5xx gets a stack trace.
        if exc.status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
            logger.error("%s: %s", exc.error_code, exc.message, exc_info=exc)
        else:
            logger.info("%s: %s", exc.error_code, exc.message)
        return _render(
            request, exc.status_code, exc.error_code, exc.message, exc.details
        )

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Schema validation failures on incoming requests."""
        return _render(
            request,
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            ErrorCode.VALIDATION_ERROR,
            ErrorMessages.VALIDATION_ERROR,
            _as_details(exc.errors()),
        )

    @app.exception_handler(ValidationError)
    async def handle_response_validation(
        request: Request, exc: ValidationError
    ) -> JSONResponse:
        """Validation failures while building a response: our bug, not theirs."""
        logger.error("response validation failed", exc_info=exc)
        return _render(
            request,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            ErrorCode.INTERNAL_ERROR,
            ErrorMessages.INTERNAL_SERVER_ERROR,
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        """Framework-raised errors: 404 routing misses, 405s, manual raises."""
        code = {
            status.HTTP_401_UNAUTHORIZED: ErrorCode.UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN: ErrorCode.FORBIDDEN,
            status.HTTP_404_NOT_FOUND: ErrorCode.NOT_FOUND,
            status.HTTP_405_METHOD_NOT_ALLOWED: ErrorCode.METHOD_NOT_ALLOWED,
        }.get(exc.status_code, ErrorCode.HTTP_ERROR)
        response = _render(request, exc.status_code, code, str(exc.detail))
        # Preserves WWW-Authenticate, which the auth challenge flow needs.
        if exc.headers:
            response.headers.update(exc.headers)
        return response

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        """Anything we did not anticipate.

        The message is generic on purpose: exception text routinely contains
        connection strings, SQL and internal paths.
        """
        request_id = _request_id(request)
        logger.exception(
            "unhandled exception on %s %s",
            request.method,
            request.url.path,
            exc_info=exc,
            extra={"request_id": request_id or "-"},
        )
        return _render(
            request,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            ErrorCode.INTERNAL_ERROR,
            ErrorMessages.INTERNAL_SERVER_ERROR,
        )
