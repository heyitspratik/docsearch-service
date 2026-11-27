"""Uploaded document and its ingestion status."""

from sqlalchemy import BigInteger, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.constants import DocumentStatus
from app.db.models.base_model import BaseModel


class DocumentMaster(BaseModel):
    """One uploaded file, owned by one user."""

    __tablename__ = "document_master"
    __table_args__ = (
        # One live copy of a file per user; a failed or deleted one can come back.
        Index(
            "uq_document_master_user_uuid_content_hash",
            "user_uuid",
            "content_hash",
            unique=True,
            postgresql_where=text(
                f"status NOT IN ({DocumentStatus.FAILED.value}, "
                f"{DocumentStatus.DELETED.value})"
            ),
        ),
    )

    # Keycloak user ID (the token's `sub`). Every query filters on it.
    user_uuid: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(127), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    # SHA-256 of the file bytes, hex. Null for documents uploaded before 3.7.
    content_hash: Mapped[str | None] = mapped_column(String(64))
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
