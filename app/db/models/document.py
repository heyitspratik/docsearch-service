"""Uploaded document and its ingestion status."""

from sqlalchemy import BigInteger, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.constants import DocumentStatus
from app.db.models.base_model import BaseModel


class DocumentMaster(BaseModel):
    """One uploaded file, owned by one user."""

    __tablename__ = "document_master"

    # Keycloak user ID (the token's `sub`). Every query filters on it.
    user_uuid: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(127), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    # A DocumentStatus number (1 = queued … 8 = deleted).
    status: Mapped[int] = mapped_column(
        Integer,
        default=DocumentStatus.QUEUED,
        server_default=str(DocumentStatus.QUEUED.value),
        index=True,
        nullable=False,
    )
    error: Mapped[str | None] = mapped_column(Text)
    page_count: Mapped[int | None] = mapped_column(Integer)
    chunk_count: Mapped[int | None] = mapped_column(Integer)
    # The embedding model the chunks were indexed with, set when ready.
    embedding_model: Mapped[str | None] = mapped_column(String(255))
