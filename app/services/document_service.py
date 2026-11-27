"""Business logic for documents: upload, list, metadata, status and delete."""

import hashlib
from collections.abc import Sequence
from uuid import UUID, uuid4

from fastapi import BackgroundTasks, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.qdrant.service import QdrantVectorStore
from app.constants import DocumentMessages, DocumentStatus, UploadMessages
from app.db.models import DocumentMaster
from app.db.services import CommonDBService, DocumentDBService
from app.exceptions import BadRequestError, FileValidationError, NotFoundError
from app.helpers import (
    AuthenticatedUser,
    ObjectStorage,
    clean_filename,
    extracted_key,
    file_extension,
    original_key,
    validate_file,
)
from app.log import get_logger
from app.schemas.response import (
    DocumentDeleteResponse,
    DocumentListResponse,
    DocumentMetadataResponse,
    DocumentStatusResponse,
    DocumentSummaryResponse,
    ErrorDetail,
    UploadedFileResponse,
)
from app.settings import get_settings
from app.workers.dispatch import enqueue_ingestion, enqueue_purge

logger = get_logger(__name__)


class DocumentService:
    """Everything the API does with documents, and the worker's purge."""

    def __init__(self, session: AsyncSession) -> None:
        self.common_db = CommonDBService(session)
        self.document_db = DocumentDBService(session)

    async def upload(
        self,
        user: AuthenticatedUser,
        files: Sequence[UploadFile],
        storage: ObjectStorage,
        background_tasks: BackgroundTasks,
    ) -> list[UploadedFileResponse]:
        """Validate, store and record each file; report what happened to each.

        Raises:
            BadRequestError: Too many files, or every file was rejected.
        """
        settings = get_settings()
        if len(files) > settings.UPLOAD_MAX_FILES:
            raise BadRequestError(
                UploadMessages.TOO_MANY_FILES.format(
                    max_files=settings.UPLOAD_MAX_FILES
                )
            )

        results = [
            await self._upload_one(
                user, file, settings.upload_max_file_size_bytes, storage
            )
            for file in files
        ]

        if not any(result.accepted for result in results):
            raise BadRequestError(
                UploadMessages.ALL_FILES_REJECTED,
                details=[
                    ErrorDetail(field=result.filename, message=result.error or "")
                    for result in results
                ],
            )

        accepted = [
            result.document_uuid
            for result in results
            if result.accepted and result.document_uuid
        ]
        # Runs after the commit (DBSession is function-scoped), so the rows exist.
        background_tasks.add_task(enqueue_ingestion, accepted)
        return results

    async def list_documents(self, user: AuthenticatedUser) -> DocumentListResponse:
        """The user's documents, newest first."""
        documents = await self.document_db.list_documents(user.id)
        return DocumentListResponse(
            documents=[
                DocumentSummaryResponse(
                    document_uuid=document.uuid,
                    filename=document.filename,
                    status=DocumentStatus(document.status),
                    error=document.error,
                    created_at=document.created_at,
                )
                for document in documents
            ]
        )

    async def get_document_metadata(
        self, user: AuthenticatedUser, document_uuid: UUID
    ) -> DocumentMetadataResponse:
        """One document's details.

        Raises:
            NotFoundError: No such document for this user, or it was deleted.
        """
        document = await self._get_own_document(user, document_uuid)
        return DocumentMetadataResponse(
            document_uuid=document.uuid,
            filename=document.filename,
            status=DocumentStatus(document.status),
            error=document.error,
            created_at=document.created_at,
            mime_type=document.mime_type,
            size_bytes=document.size_bytes,
            page_count=document.page_count,
            chunk_count=document.chunk_count,
            embedding_model=document.embedding_model,
            updated_at=document.updated_at,
        )

    async def get_document_status(
        self, user: AuthenticatedUser, document_uuid: UUID
    ) -> DocumentStatusResponse:
        """Where one document is in ingestion.

        Raises:
            NotFoundError: No such document for this user, or it was deleted.
        """
        document = await self._get_own_document(user, document_uuid)
        return DocumentStatusResponse(
            document_uuid=document.uuid,
            status=DocumentStatus(document.status),
            error=document.error,
            updated_at=document.updated_at,
        )

    async def delete_document(
        self,
        user: AuthenticatedUser,
        document_uuid: UUID,
        background_tasks: BackgroundTasks,
    ) -> DocumentDeleteResponse:
        """Mark the document ``deleted`` and queue the removal of its data.

        Raises:
            NotFoundError: No such document for this user, or it was deleted.
        """
        document = await self._get_own_document(user, document_uuid)
        await self.document_db.update_document(
            document.uuid, status=DocumentStatus.DELETED
        )
        # Runs after the commit, so the worker sees the row as deleted.
        background_tasks.add_task(enqueue_purge, document.uuid)
        return DocumentDeleteResponse(
            document_uuid=document.uuid, status=DocumentStatus.DELETED
        )

    async def purge_document(
        self,
        document_uuid: UUID,
        storage: ObjectStorage,
        vectors: QdrantVectorStore,
    ) -> None:
        """Remove a deleted document's points, files and chunk rows; keep its row.

        Safe to run twice. A document that is not ``deleted`` is left alone.
        """
        document = await self.common_db.get_row_by_key(
            DocumentMaster,
            "uuid",
            document_uuid,
            ["id", "user_uuid", "storage_key", "status"],
        )
        if document is None:
            logger.warning(f"Document {document_uuid} not found; nothing to purge")
            return
        if document["status"] != DocumentStatus.DELETED:
            logger.warning(f"Document {document_uuid} is not deleted; not purging")
            return

        await vectors.delete_document(document_uuid)
        await storage.delete(document["storage_key"])
        await storage.delete(extracted_key(document["user_uuid"], str(document_uuid)))
        await self.document_db.delete_chunks(document["id"])
        logger.info(f"Document {document_uuid} purged: points, files and chunks")

    async def requeue_stuck_documents(self, minutes: int) -> list[UUID]:
        """Send ingestion jobs again for documents ``queued`` longer than ``minutes``.

        Their first job most likely never reached Redis. Sending one twice is
        safe: a duplicate waits for the lock or finds the document ``ready``.
        """
        stuck = await self.document_db.list_stuck_queued(minutes)
        if stuck:
            enqueue_ingestion(stuck)
            logger.info(f"Re-queued {len(stuck)} documents stuck in queued")
        return stuck

    async def _get_own_document(
        self, user: AuthenticatedUser, document_uuid: UUID
    ) -> DocumentMaster:
        """The document, or 404. Another user's document is also a 404, not 403.

        A 403 would tell the caller that the ID exists.
        """
        document = await self.document_db.get_document(user.id, document_uuid)
        if document is None:
            raise NotFoundError(DocumentMessages.NOT_FOUND)
        return document

    async def _upload_one(
        self,
        user: AuthenticatedUser,
        file: UploadFile,
        max_size_bytes: int,
        storage: ObjectStorage,
    ) -> UploadedFileResponse:
        """One file: a rejected file is reported, never raised."""
        filename = clean_filename(file.filename)
        # One byte over the limit is enough to know it is too large, without
        # reading the rest of a huge file into memory.
        data = await file.read(max_size_bytes + 1)
        try:
            mime_type = validate_file(filename, data, max_size_bytes)
        except FileValidationError as e:
            return UploadedFileResponse(
                filename=filename, accepted=False, error=e.message
            )

        content_hash = hashlib.sha256(data).hexdigest()
        # Also sees rows flushed earlier in this request: a file sent twice is caught.
        existing = await self.document_db.get_live_by_hash(user.id, content_hash)
        if existing is not None:
            return self._duplicate(filename, existing)

        document_uuid = uuid4()
        storage_key = original_key(
            user.id, str(document_uuid), file_extension(filename)
        )
        # Row before file: losing a race to the same file leaves nothing in S3.
        try:
            document = await self.document_db.create_document(
                uuid=document_uuid,
                user_uuid=user.id,
                filename=filename,
                mime_type=mime_type,
                size_bytes=len(data),
                storage_key=storage_key,
                content_hash=content_hash,
            )
        except IntegrityError:
            existing = await self.document_db.get_live_by_hash(user.id, content_hash)
            if existing is None:
                raise
            return self._duplicate(filename, existing)
        await storage.put(storage_key, data, mime_type)
        return UploadedFileResponse(
            filename=filename,
            accepted=True,
            document_uuid=document.uuid,
            status=DocumentStatus(document.status),
        )

    @staticmethod
    def _duplicate(filename: str, existing: DocumentMaster) -> UploadedFileResponse:
        """A rejected file that the user already has, pointing at that document."""
        logger.info(f"Upload {filename}: duplicate of document {existing.uuid}")
        return UploadedFileResponse(
            filename=filename,
            accepted=False,
            document_uuid=existing.uuid,
            error=UploadMessages.DUPLICATE.format(filename=existing.filename),
        )
