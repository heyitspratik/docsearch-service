"""The ingest pipeline: extract, chunk, embed and index one document."""

import asyncio
import json
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.qdrant.service import QdrantVectorStore
from app.constants import DocumentStatus, IngestionMessages
from app.db.models import DocumentChunk, DocumentMaster
from app.db.services import CommonDBService, DocumentDBService
from app.exceptions import ExtractionError, NotFoundError
from app.helpers import ObjectStorage, extracted_key
from app.helpers.chunking_helper import Chunk, chunk_document
from app.helpers.embedding_helper import DenseEmbedder, SparseEmbedder
from app.helpers.extraction_helper import extract
from app.helpers.vector_store_helper import ChunkPayload, ChunkPoint, point_id
from app.log import get_logger
from app.settings import get_settings

logger = get_logger(__name__)


class IngestionService:
    """Turns an uploaded document into searchable chunks.

    Status flow: queued → extracting → chunking → embedding → indexing → ready,
    or failed. Each stage is committed, so the status endpoint shows progress.
    """

    def __init__(
        self,
        session: AsyncSession,
        storage: ObjectStorage,
        dense: DenseEmbedder,
        sparse: SparseEmbedder,
        vectors: QdrantVectorStore,
    ) -> None:
        self.session = session
        self.common_db = CommonDBService(session)
        self.document_db = DocumentDBService(session)
        self.storage = storage
        self.dense = dense
        self.sparse = sparse
        self.vectors = vectors

    @staticmethod
    def _chunk_row(document_id: int, chunk: Chunk) -> DocumentChunk:
        """A chunk as its ``document_chunk`` row."""
        return DocumentChunk(
            document_id=document_id,
            chunk_index=chunk.index,
            content=chunk.text,
            chunk_type=chunk.chunk_type,
            page_start=chunk.page_start,
            page_end=chunk.page_end,
            heading_path=chunk.heading_path,
            token_count=chunk.token_count,
        )

    async def ingest(self, document_uuid: UUID) -> None:
        """Process one document. Missing, deleted and ready documents are skipped.

        A corrupt, empty or missing file is marked ``failed``: retrying cannot
        help. Any other error is raised, so the task retries it.
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

        status = DocumentStatus(document["status"])
        if status in (DocumentStatus.DELETED, DocumentStatus.READY):
            logger.info(f"Document {document_uuid} is {status.name}; skipping ingest")
            return

        try:
            await self._process(document_uuid, document)
        except (ExtractionError, NotFoundError) as e:
            # NotFoundError can only come from storage: the original is gone.
            await self.session.rollback()
            error = (
                e.message
                if isinstance(e, ExtractionError)
                else IngestionMessages.FILE_MISSING
            )
            logger.warning(f"Document {document_uuid} failed: {error}")
            await self.mark_failed(document_uuid, error)

    async def mark_failed(self, document_uuid: UUID, error: str) -> None:
        """Set status ``failed`` with the reason, unless it was deleted meanwhile."""
        await self.document_db.update_document(
            document_uuid, status=DocumentStatus.FAILED, error=error
        )
        await self.session.commit()

    async def _process(self, document_uuid: UUID, document: dict[str, Any]) -> None:
        """Run the stages, stopping early if the document is deleted meanwhile."""
        if not await self._set_stage(document_uuid, DocumentStatus.EXTRACTING):
            return
        data = await self.storage.get(document["storage_key"])
        # Docling blocks for seconds to minutes; a thread keeps the event loop free.
        extracted = await asyncio.to_thread(extract, document["filename"], data)
        json_key = extracted_key(document["user_uuid"], str(document_uuid))
        await self.storage.put(
            json_key,
            json.dumps(extracted.export_to_dict()).encode(),
            "application/json",
        )
        logger.info(
            f"Extracted document {document_uuid}: {len(extracted.pages)} pages, "
            f"{len(extracted.tables)} tables"
        )

        if not await self._set_stage(document_uuid, DocumentStatus.CHUNKING):
            # Deleted while extracting: the purge may have run before this save.
            await self.storage.delete(json_key)
            return
        model = get_settings().EMBEDDING_DENSE_MODEL
        chunks = await asyncio.to_thread(chunk_document, extracted, model)
        logger.info(
            f"Chunked document {document_uuid}: {len(chunks)} chunks, "
            f"largest {max((c.token_count for c in chunks), default=0)} tokens"
        )

        if not await self._set_stage(document_uuid, DocumentStatus.EMBEDDING):
            return
        texts = [chunk.embed_text for chunk in chunks]
        dense_vectors = await asyncio.to_thread(self.dense.embed_passages, texts)
        sparse_vectors = await asyncio.to_thread(self.sparse.embed_passages, texts)
        logger.info(
            f"Embedded document {document_uuid}: {len(dense_vectors)} dense and "
            f"{len(sparse_vectors)} sparse vectors"
        )

        if not await self._set_stage(document_uuid, DocumentStatus.INDEXING):
            return
        points = [
            ChunkPoint(
                id=point_id(document_uuid, chunk.index),
                dense=dense_vector,
                sparse=sparse_vector,
                payload=ChunkPayload(
                    user_uuid=document["user_uuid"],
                    document_id=str(document_uuid),
                    filename=document["filename"],
                    chunk_index=chunk.index,
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    chunk_type=chunk.chunk_type,
                    text=chunk.text,
                    embedding_model=model,
                ),
            )
            for chunk, dense_vector, sparse_vector in zip(
                chunks, dense_vectors, sparse_vectors, strict=True
            )
        ]
        # An earlier, failed attempt may have left points; start clean.
        await self.vectors.delete_document(document_uuid)
        await self.vectors.upsert(points)
        await self.document_db.replace_chunks(
            document["id"], [self._chunk_row(document["id"], chunk) for chunk in chunks]
        )
        ready = await self.document_db.update_document(
            document_uuid,
            status=DocumentStatus.READY,
            error=None,
            # TXT and DOCX have no pages.
            page_count=len(extracted.pages) or None,
            chunk_count=len(chunks),
            embedding_model=model,
        )
        if not ready:
            # Deleted while indexing: drop the chunk rows and points just written.
            await self.session.rollback()
            await self.vectors.delete_document(document_uuid)
            logger.info(f"Document {document_uuid} was deleted during ingest")
            return
        await self.session.commit()
        logger.info(f"Document {document_uuid} ready: {len(points)} chunks indexed")

    async def _set_stage(self, document_uuid: UUID, status: DocumentStatus) -> bool:
        """Commit the new stage so it is visible at once; False if deleted."""
        updated = await self.document_db.update_document(document_uuid, status=status)
        await self.session.commit()
        if not updated:
            logger.info(f"Document {document_uuid} was deleted; stopping ingest")
        return updated
