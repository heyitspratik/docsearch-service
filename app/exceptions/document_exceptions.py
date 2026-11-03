"""Errors raised while uploading and managing documents."""

from app.exceptions.common_exceptions import BadRequestError


class FileValidationError(BadRequestError):
    """An uploaded file was rejected. The message says why, for that one file."""
