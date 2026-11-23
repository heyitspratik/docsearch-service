"""Queries on document_master and document_chunk."""

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select, update
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

    async def list_documents(self, user_uuid: str) -> Sequence[DocumentMaster]:
        """A user's documents, newest first. Deleted ones are left out."""
        result = await self.session.execute(
            select(DocumentMaster)
            .where(
                DocumentMaster.user_uuid == user_uuid,
                DocumentMaster.status != DocumentStatus.DELETED,
            )
            .order_by(DocumentMaster.created_at.desc(), DocumentMaster.id.desc())
        )
        return result.scalars().all()

    async def get_document(
        self, user_uuid: str, document_uuid: UUID
    ) -> DocumentMaster | None:
        """One document, only if this user owns it and it is not deleted."""
        result = await self.session.execute(
            select(DocumentMaster).where(
                DocumentMaster.uuid == document_uuid,
                DocumentMaster.user_uuid == user_uuid,
                DocumentMaster.status != DocumentStatus.DELETED,
            )
        )
        return result.scalar_one_or_none()

    async def list_ready(
        self, user_uuid: str, document_uuids: Sequence[UUID] | None = None
    ) -> list[tuple[UUID, datetime]]:
        """The user's ``ready`` documents as (uuid, updated_at), limited if given."""
        query = select(DocumentMaster.uuid, DocumentMaster.updated_at).where(
            DocumentMaster.user_uuid == user_uuid,
            DocumentMaster.status == DocumentStatus.READY,
        )
        if document_uuids:
            query = query.where(DocumentMaster.uuid.in_(document_uuids))
        result = await self.session.execute(query)
        return [(row.uuid, row.updated_at) for row in result]

    async def list_stuck_queued(self, minutes: int) -> list[UUID]:
        """Documents still ``queued`` ``minutes`` after their last update, oldest first.

        Compared with the database clock, so worker and database clocks may differ.
        """
        result = await self.session.execute(
            select(DocumentMaster.uuid)
            .where(
                DocumentMaster.status == DocumentStatus.QUEUED,
                DocumentMaster.updated_at < func.now() - timedelta(minutes=minutes),
            )
            .order_by(DocumentMaster.updated_at)
        )
        return list(result.scalars())

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
        await self.delete_chunks(document_id)
        self.session.add_all(chunks)
        await self.session.flush()

    async def delete_chunks(self, document_id: int) -> None:
        """Delete every chunk row of a document. None at all is fine."""
        await self.session.execute(
            delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
        )
