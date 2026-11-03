"""Response models for the document endpoints."""

from uuid import UUID

from pydantic import BaseModel, Field

from app.constants import DocumentStatus


class UploadedFileResult(BaseModel):
    """What happened to one file of an upload."""

    filename: str
    accepted: bool
    document_uuid: UUID | None = Field(
        default=None, description="Set when accepted; use it to follow the status"
    )
    status: DocumentStatus | None = Field(
        default=None, description="Set when accepted: 1 (queued)"
    )
    error: str | None = Field(default=None, description="Why it was rejected")
