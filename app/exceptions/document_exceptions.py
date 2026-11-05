"""Errors raised while uploading and managing documents."""

from app.exceptions.common_exceptions import BadRequestError, UnprocessableEntityError


class FileValidationError(BadRequestError):
    """An uploaded file was rejected. The message says why, for that one file."""


class ExtractionError(UnprocessableEntityError):
    """A stored file could not be read, so retrying will not help."""
