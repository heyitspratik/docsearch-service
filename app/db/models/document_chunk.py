"""One chunk of a document, as indexed in Qdrant."""

from sqlalchemy import Enum, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.constants import ChunkType
from app.db.models.base_model import BaseModel


class DocumentChunk(BaseModel):
    """A piece of a document's text, or one whole table."""

    __tablename__ = "document_chunk"
    # Also serves as the index for "all chunks of a document".
    __table_args__ = (UniqueConstraint("document_id", "chunk_index"),)

    # Deleting a document row deletes its chunks in the database itself.
    document_id: Mapped[int] = mapped_column(
        ForeignKey("document_master.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_type: Mapped[ChunkType] = mapped_column(
        Enum(
            ChunkType,
            native_enum=False,
            length=16,
            values_callable=lambda enum: [member.value for member in enum],
        ),
        nullable=False,
    )
    # Null for TXT files, which have no pages.
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    # Headings above the chunk, outermost first, e.g. ["Report", "2. Costs"].
    heading_path: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default="{}", nullable=False
    )
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
