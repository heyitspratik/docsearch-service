"""Response models for the document endpoints."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.constants import DocumentStatus


class UploadedFileResponse(BaseModel):
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


_STATUS_HELP = (
    "1 queued, 2 extracting, 3 chunking, 4 embedding, 5 indexing, 6 ready, 7 failed"
)


class DocumentStatusResponse(BaseModel):
    """Where one document is in ingestion."""

    document_uuid: UUID
    status: DocumentStatus = Field(description=_STATUS_HELP)
    error: str | None = Field(description="Why it failed; set only when failed")
    updated_at: datetime


class DocumentSummaryResponse(BaseModel):
    """One document in the list."""

    document_uuid: UUID
    filename: str
    status: DocumentStatus = Field(description=_STATUS_HELP)
    error: str | None = Field(description="Why it failed; set only when failed")
    created_at: datetime


class DocumentListResponse(BaseModel):
    """The user's documents, newest first (GET /documents/list)."""

    documents: list[DocumentSummaryResponse]


class DocumentMetadataResponse(DocumentSummaryResponse):
    """One document's details."""

    mime_type: str
    size_bytes: int
    page_count: int | None = Field(description="Null for TXT and DOCX")
    chunk_count: int | None = Field(description="Set when ready")
    embedding_model: str | None = Field(description="Set when ready")
    updated_at: datetime
