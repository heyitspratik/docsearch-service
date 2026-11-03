"""Business logic for documents: upload (and later list and delete)."""

from collections.abc import Sequence
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import DocumentStatus, UploadMessages
from app.db.services import DocumentDBService
from app.exceptions import BadRequestError, FileValidationError
from app.helpers import (
    AuthenticatedUser,
    ObjectStorage,
    clean_filename,
    file_extension,
    original_key,
    validate_file,
)
from app.schemas.response import ErrorDetail, UploadedFileResult
from app.settings import get_settings


class DocumentService:
    """Everything the API does with documents."""

    def __init__(self, session: AsyncSession, storage: ObjectStorage) -> None:
        self.document_db = DocumentDBService(session)
        self.storage = storage

    async def upload(
        self, user: AuthenticatedUser, files: Sequence[UploadFile]
    ) -> list[UploadedFileResult]:
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
            await self._upload_one(user, file, settings.upload_max_file_size_bytes)
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
        return results

    async def _upload_one(
        self, user: AuthenticatedUser, file: UploadFile, max_size_bytes: int
    ) -> UploadedFileResult:
        """One file: a rejected file is reported, never raised."""
        filename = clean_filename(file.filename)
        # One byte over the limit is enough to know it is too large, without
        # reading the rest of a huge file into memory.
        data = await file.read(max_size_bytes + 1)
        try:
            mime_type = validate_file(filename, data, max_size_bytes)
        except FileValidationError as e:
            return UploadedFileResult(
                filename=filename, accepted=False, error=e.message
            )

        document_uuid = uuid4()
        storage_key = original_key(
            user.id, str(document_uuid), file_extension(filename)
        )
        await self.storage.put(storage_key, data, mime_type)
        document = await self.document_db.create_document(
            uuid=document_uuid,
            user_uuid=user.id,
            filename=filename,
            mime_type=mime_type,
            size_bytes=len(data),
            storage_key=storage_key,
        )
        return UploadedFileResult(
            filename=filename,
            accepted=True,
            document_uuid=document.uuid,
            status=DocumentStatus(document.status),
        )
