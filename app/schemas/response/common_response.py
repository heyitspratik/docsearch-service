"""Standard response envelopes.

Success and error responses share the keys ``message``, ``payload``,
``status`` and ``detail``. On an error, ``payload`` is null and ``detail``
says what went wrong.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class BaseResponse[PayloadT](BaseModel):
    """Envelope for every successful response."""

    message: str
    payload: PayloadT
    status: int
    detail: str | None = None


class ErrorDetail(BaseModel):
    """A single field-level problem."""

    field: str | None = Field(default=None, description="Dotted path to the field")
    message: str = Field(description="What is wrong with it")
    type: str | None = Field(default=None, description="Machine-readable error type")


class ErrorInfo(BaseModel):
    """The ``detail`` of an error response."""

    code: str = Field(description="Stable error code; branch on this, not the message")
    errors: list[ErrorDetail] | Any | None = Field(
        default=None, description="Per-field problems, when there are any"
    )
    request_id: str | None = Field(
        default=None, description="Correlation id; quote this when reporting a problem"
    )


class ErrorResponse(BaseModel):
    """Every non-2xx response this service produces."""

    message: str = Field(description="Human-readable summary")
    payload: None = None
    status: int
    detail: ErrorInfo
