"""Common exceptions for the application.

These cover the HTTP-shaped conditions every service needs. Per-feature
exceptions belong in their own module and should inherit from these, so the
status code is declared once.

Example:
    class DocumentNotFoundException(NotFoundError):
        def __init__(self, document_id: int) -> None:
            super().__init__(f"No document with id {document_id}")
"""

from fastapi import status

from app.constants import ErrorCode, ErrorMessages
from app.exceptions.base_exception import BaseError


class BadRequestError(BaseError):
    """The request is malformed or semantically invalid."""

    status_code = status.HTTP_400_BAD_REQUEST
    error_code = ErrorCode.BAD_REQUEST
    message = ErrorMessages.BAD_REQUEST


class UnauthorizedError(BaseError):
    """No credentials, or credentials that could not be verified."""

    status_code = status.HTTP_401_UNAUTHORIZED
    error_code = ErrorCode.UNAUTHORIZED
    message = ErrorMessages.UNAUTHORIZED


class ForbiddenError(BaseError):
    """Authenticated, but not permitted to perform this action."""

    status_code = status.HTTP_403_FORBIDDEN
    error_code = ErrorCode.FORBIDDEN
    message = ErrorMessages.FORBIDDEN


class NotFoundError(BaseError):
    """The requested resource does not exist."""

    status_code = status.HTTP_404_NOT_FOUND
    error_code = ErrorCode.NOT_FOUND
    message = ErrorMessages.NOT_FOUND


class ConflictError(BaseError):
    """The request conflicts with current state, such as a duplicate key."""

    status_code = status.HTTP_409_CONFLICT
    error_code = ErrorCode.CONFLICT
    message = ErrorMessages.CONFLICT


class UnprocessableEntityError(BaseError):
    """Well-formed request that fails a business rule."""

    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    error_code = ErrorCode.UNPROCESSABLE_ENTITY
    message = ErrorMessages.UNPROCESSABLE_ENTITY


class TooManyRequestsError(BaseError):
    """The caller exceeded a rate limit or quota."""

    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    error_code = ErrorCode.TOO_MANY_REQUESTS
    message = ErrorMessages.TOO_MANY_REQUESTS


class ExternalServiceError(BaseError):
    """A dependency this service calls failed or misbehaved."""

    status_code = status.HTTP_502_BAD_GATEWAY
    error_code = ErrorCode.EXTERNAL_SERVICE_ERROR
    message = ErrorMessages.EXTERNAL_SERVICE_ERROR


class ServiceUnavailableError(BaseError):
    """A dependency this service needs is unavailable or disabled."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    error_code = ErrorCode.SERVICE_UNAVAILABLE
    message = ErrorMessages.SERVICE_UNAVAILABLE
