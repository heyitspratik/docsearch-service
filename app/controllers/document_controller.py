"""Document controller: upload (and later list, status and delete)."""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, File, UploadFile, status
from fastapi_utils.cbv import cbv

from app.clients.database.dependency import DBSession
from app.clients.s3.dependency import StorageDep
from app.constants import DocumentMessages
from app.helpers import CurrentUser
from app.schemas.response import BaseResponse, ErrorResponse, UploadedFileResult
from app.services import DocumentService

document_router = APIRouter()


@cbv(document_router)
class DocumentController:
    """HTTP layer for the document endpoints; the logic lives in ``DocumentService``."""

    @document_router.post(
        "/upload",
        status_code=status.HTTP_202_ACCEPTED,
        response_model=BaseResponse[list[UploadedFileResult]],
        responses={
            status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
            status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
        },
    )
    async def upload(
        self,
        user: CurrentUser,
        session: DBSession,
        storage: StorageDep,
        background_tasks: BackgroundTasks,
        files: Annotated[
            list[UploadFile],
            File(
                description="PDF, DOCX or TXT",
                json_schema_extra={"items": {"type": "string", "format": "binary"}},
            ),
        ],
    ) -> BaseResponse[list[UploadedFileResult]]:
        """Upload one or more files for ingestion.

        Returns 202: accepted files are saved and queued, not yet searchable.
        Follow each one with its ``document_uuid``. Returns 400 only when no
        file at all could be accepted.

        Returns:
            BaseResponse[list[UploadedFileResult]]: One result per file.
        """
        document_service = DocumentService(session, storage, background_tasks)
        results = await document_service.upload(user, files)
        return BaseResponse(
            message=DocumentMessages.UPLOAD_ACCEPTED,
            payload=results,
            status=status.HTTP_202_ACCEPTED,
        )
