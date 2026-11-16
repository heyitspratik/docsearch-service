"""Business logic for documents: upload, list, metadata and status (delete later)."""

from collections.abc import Sequence
from uuid import UUID, uuid4

from fastapi import BackgroundTasks, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import DocumentMessages, DocumentStatus, UploadMessages
from app.db.models import DocumentMaster
from app.db.services import DocumentDBService
from app.exceptions import BadRequestError, FileValidationError, NotFoundError
from app.helpers import (
    AuthenticatedUser,
    ObjectStorage,
    clean_filename,
    file_extension,
    original_key,
    validate_file,
)
from app.schemas.response import (
    DocumentListResponse,
    DocumentMetadataResponse,
    DocumentStatusResponse,
    DocumentSummaryResponse,
    ErrorDetail,
    UploadedFileResponse,
)
from app.settings import get_settings
from app.workers.dispatch import enqueue_ingestion


class DocumentService:
    """Everything the API does with documents."""

    def __init__(self, session: AsyncSession) -> None:
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

        accepted = [result.document_uuid for result in results if result.document_uuid]
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

        document_uuid = uuid4()
        storage_key = original_key(
            user.id, str(document_uuid), file_extension(filename)
        )
        await storage.put(storage_key, data, mime_type)
        document = await self.document_db.create_document(
            uuid=document_uuid,
            user_uuid=user.id,
            filename=filename,
            mime_type=mime_type,
            size_bytes=len(data),
            storage_key=storage_key,
        )
        return UploadedFileResponse(
            filename=filename,
            accepted=True,
            document_uuid=document.uuid,
            status=DocumentStatus(document.status),
        )
