"""Application errors and their HTTP rendering."""

from app.exceptions.base_exception import BaseError
from app.exceptions.common_exceptions import (
    BadRequestError,
    ConflictError,
    ExternalServiceError,
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
    TooManyRequestsError,
    UnauthorizedError,
    UnprocessableEntityError,
)
from app.exceptions.handlers import register_exception_handlers

__all__ = [
    "BadRequestError",
    "BaseError",
    "ConflictError",
    "ExternalServiceError",
    "ForbiddenError",
    "NotFoundError",
    "ServiceUnavailableError",
    "TooManyRequestsError",
    "UnauthorizedError",
    "UnprocessableEntityError",
    "register_exception_handlers",
]
