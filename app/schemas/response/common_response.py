"""Standard response envelopes."""

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


class ErrorBody(BaseModel):
    """The error payload."""

    code: str = Field(description="Stable error code; branch on this, not the message")
    message: str = Field(description="Human-readable summary")
    details: list[ErrorDetail] | Any | None = Field(default=None)


class ErrorResponse(BaseModel):
    """Every non-2xx response this service produces."""

    error: ErrorBody
    request_id: str | None = Field(
        default=None, description="Correlation id; quote this when reporting a problem"
    )
