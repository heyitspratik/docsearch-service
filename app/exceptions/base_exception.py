"""Base exception module.

Provides the base exception class every application error inherits from.
"""

from typing import Any

from fastapi import status

from app.constants import ErrorCode, ErrorMessages


class BaseError(Exception):
    """Base class for every expected application failure.

    Raise these from services rather than ``HTTPException``, so business logic
    carries no HTTP knowledge. Clients branch on ``error_code``, never on the
    message, which is free to change.
    """

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    error_code: str = ErrorCode.INTERNAL_ERROR
    message: str = ErrorMessages.INTERNAL_SERVER_ERROR

    def __init__(
        self,
        message: str | None = None,
        *,
        error_code: str | None = None,
        status_code: int | None = None,
        details: Any = None,
    ) -> None:
        """Initialize the exception.

        Args:
            message: Human-readable summary. Defaults to the class message.
            error_code: Stable code clients branch on.
            status_code: HTTP status to return.
            details: Extra structured context for the caller.
        """
        self.message = message or type(self).message
        self.error_code = error_code or type(self).error_code
        self.status_code = status_code or type(self).status_code
        self.details = details
        super().__init__(self.message)

    def __str__(self) -> str:
        """Return the human-readable message."""
        return self.message
