"""Queries on document_master."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DocumentMaster


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
