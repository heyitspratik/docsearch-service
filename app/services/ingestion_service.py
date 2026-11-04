"""The ingest pipeline: extract, chunk, embed and index one document."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import DocumentStatus
from app.db.models import DocumentMaster
from app.db.services import CommonDBService
from app.log import get_logger

logger = get_logger(__name__)


class IngestionService:
    """Turns an uploaded document into searchable chunks.

    Until step 2.10 it only confirms the worker can read the document.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.common_db = CommonDBService(session)

    async def ingest(self, document_uuid: UUID) -> None:
        """Process one document. A missing or deleted document is skipped."""
        document = await self.common_db.get_row_by_key(
            DocumentMaster, "uuid", document_uuid, ["id", "filename", "status"]
        )
        if document is None:
            logger.warning(f"Document {document_uuid} not found; nothing to ingest")
            return

        status = DocumentStatus(document["status"])
        if status is DocumentStatus.DELETED:
            logger.info(f"Document {document_uuid} was deleted; skipping ingest")
            return

        logger.info(
            f"Ingest received for document {document_uuid} "
            f"({document['filename']}, status {status.name})"
        )
