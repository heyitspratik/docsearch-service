"""Document controller: upload, list, metadata and status (delete later)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, File, UploadFile, status
from fastapi_utils.cbv import cbv

from app.clients.database.dependency import DBSession
from app.clients.s3.dependency import StorageDep
from app.constants import DocumentMessages
from app.helpers import CurrentUser
from app.schemas.response import (
    BaseResponse,
    DocumentListResponse,
    DocumentMetadataResponse,
    DocumentStatusResponse,
    ErrorResponse,
    UploadedFileResponse,
)
from app.services import DocumentService

document_router = APIRouter()


@cbv(document_router)
class DocumentController:
    """HTTP layer for the document endpoints; the logic lives in ``DocumentService``."""

    @document_router.post(
        "/upload",
        status_code=status.HTTP_202_ACCEPTED,
        response_model=BaseResponse[list[UploadedFileResponse]],
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
    ) -> BaseResponse[list[UploadedFileResponse]]:
        """Upload one or more files for ingestion.

        Returns 202: accepted files are saved and queued, not yet searchable.
        Follow each one with its ``document_uuid``. Returns 400 only when no
        file at all could be accepted.

        Returns:
            BaseResponse[list[UploadedFileResponse]]: One result per file.
        """
        document_service = DocumentService(session)
        results = await document_service.upload(user, files, storage, background_tasks)
        return BaseResponse(
            message=DocumentMessages.UPLOAD_ACCEPTED,
            payload=results,
            status=status.HTTP_202_ACCEPTED,
        )

    @document_router.get(
        "/list",
        response_model=BaseResponse[DocumentListResponse],
        responses={status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse}},
    )
    async def list_documents(
        self, user: CurrentUser, session: DBSession
    ) -> BaseResponse[DocumentListResponse]:
        """List the logged-in user's documents, newest first.

        Returns:
            BaseResponse[DocumentListResponse]: Each document with its status.
        """
        documents = await DocumentService(session).list_documents(user)
        return BaseResponse(
            message=DocumentMessages.LIST_FETCHED,
            payload=documents,
            status=status.HTTP_200_OK,
        )

    @document_router.get(
        "/{document_uuid}/metadata",
        response_model=BaseResponse[DocumentMetadataResponse],
        responses={
            status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
            status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        },
    )
    async def get_document_metadata(
        self, document_uuid: UUID, user: CurrentUser, session: DBSession
    ) -> BaseResponse[DocumentMetadataResponse]:
        """One document's details: size, pages, chunks, model and status.

        Returns:
            BaseResponse[DocumentMetadataResponse]: The document; 404 if not yours.
        """
        metadata = await DocumentService(session).get_document_metadata(
            user, document_uuid
        )
        return BaseResponse(
            message=DocumentMessages.METADATA_FETCHED,
            payload=metadata,
            status=status.HTTP_200_OK,
        )

    @document_router.get(
        "/{document_uuid}/status",
        response_model=BaseResponse[DocumentStatusResponse],
        responses={
            status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
            status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        },
    )
    async def get_document_status(
        self, document_uuid: UUID, user: CurrentUser, session: DBSession
    ) -> BaseResponse[DocumentStatusResponse]:
        """Where a document is in ingestion, or ``failed`` with its error.

        Returns:
            BaseResponse[DocumentStatusResponse]: The status; 404 if it is not yours.
        """
        result = await DocumentService(session).get_document_status(user, document_uuid)
        return BaseResponse(
            message=DocumentMessages.STATUS_FETCHED,
            payload=result,
            status=status.HTTP_200_OK,
        )
