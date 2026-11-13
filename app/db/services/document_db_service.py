"""Queries on document_master and document_chunk."""

from typing import Any
from uuid import UUID

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import DocumentStatus
from app.db.models import DocumentChunk, DocumentMaster


class DocumentDBService:
    """Reads and writes ``document_master`` rows. No business rules here."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_document(
        self,
        *,
        uuid: UUID,
        user_uuid: str,
        filename: str,
        mime_type: str,
        size_bytes: int,
        storage_key: str,
    ) -> DocumentMaster:
        """Insert a new document with status ``queued``.

        Flushes so the row gets its ``id``; the request's session commits it.
        """
        document = DocumentMaster(
            uuid=uuid,
            user_uuid=user_uuid,
            filename=filename,
            mime_type=mime_type,
            size_bytes=size_bytes,
            storage_key=storage_key,
        )
        self.session.add(document)
        await self.session.flush()
        return document

    async def update_document(self, document_uuid: UUID, **values: Any) -> bool:
        """Set columns on a document, unless it was deleted meanwhile.

        Returns:
            False when the document is deleted (or gone), so nothing changed.
        """
        result = await self.session.execute(
            update(DocumentMaster)
            .where(
                DocumentMaster.uuid == document_uuid,
                DocumentMaster.status != DocumentStatus.DELETED,
            )
            .values(**values)
        )
        return bool(result.rowcount)  # type: ignore[attr-defined]

    async def replace_chunks(
        self, document_id: int, chunks: list[DocumentChunk]
    ) -> None:
        """Delete a document's chunk rows and insert ``chunks`` in their place."""
        await self.session.execute(
            delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
        )
        self.session.add_all(chunks)
        await self.session.flush()
