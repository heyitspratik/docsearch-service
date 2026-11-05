"""The ingest pipeline: extract, chunk, embed and index one document."""

import asyncio
import json
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import DocumentStatus
from app.db.models import DocumentMaster
from app.db.services import CommonDBService
from app.helpers import ObjectStorage, extracted_key
from app.helpers.extraction_helper import extract
from app.log import get_logger

logger = get_logger(__name__)


class IngestionService:
    """Turns an uploaded document into searchable chunks.

    Extraction is done; chunking, embedding, indexing and status updates
    follow in steps 2.7 to 2.10.
    """

    def __init__(self, session: AsyncSession, storage: ObjectStorage) -> None:
        self.common_db = CommonDBService(session)
        self.storage = storage

    async def ingest(self, document_uuid: UUID) -> None:
        """Process one document. A missing or deleted document is skipped.

        Raises:
            ExtractionError: The file is corrupt or has no text.
        """
        document = await self.common_db.get_row_by_key(
            DocumentMaster,
            "uuid",
            document_uuid,
            ["id", "user_uuid", "filename", "storage_key", "status"],
        )
        if document is None:
            logger.warning(f"Document {document_uuid} not found; nothing to ingest")
            return

        if DocumentStatus(document["status"]) is DocumentStatus.DELETED:
            logger.info(f"Document {document_uuid} was deleted; skipping ingest")
            return

        data = await self.storage.get(document["storage_key"])
        # Docling blocks for seconds to minutes; a thread keeps the event loop free.
        extracted = await asyncio.to_thread(extract, document["filename"], data)
        await self.storage.put(
            extracted_key(document["user_uuid"], str(document_uuid)),
            json.dumps(extracted.export_to_dict()).encode(),
            "application/json",
        )
        logger.info(
            f"Extracted document {document_uuid}: {len(extracted.pages)} pages, "
            f"{len(extracted.tables)} tables"
        )
