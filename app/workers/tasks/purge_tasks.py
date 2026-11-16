"""Purge task, on the ``default`` queue: removes a deleted document's data."""

import asyncio
from uuid import UUID

from celery import Task

from app.clients.database.client import db_client
from app.clients.qdrant.client import qdrant_client
from app.clients.qdrant.service import QdrantVectorStore
from app.clients.s3.client import s3_client
from app.clients.s3.service import S3Storage
from app.constants import INGEST_RETRY_BASE_SECONDS
from app.log import get_logger
from app.services import DocumentService
from app.settings import get_settings
from app.workers.celery_app import celery_app
from app.workers.worker_clients import worker_clients

logger = get_logger(__name__)


@celery_app.task(  # type: ignore[untyped-decorator]
    name="purge_document", bind=True, max_retries=get_settings().CELERY_MAX_RETRIES
)
def purge_document(self: Task, document_uuid: str) -> None:
    """Remove the points, files and chunk rows of one deleted document.

    A temporary error is retried after 10 s, 20 s, 40 s …, like ingestion.
    """
    uuid = UUID(document_uuid)
    try:
        asyncio.run(_purge(uuid))
    except Exception as e:
        attempt = self.request.retries + 1
        if self.request.retries >= self.max_retries:
            # The row stays deleted, so the user never sees it; only data is left.
            logger.exception(f"Purge of {uuid} failed after {attempt} attempts")
            return
        delay = INGEST_RETRY_BASE_SECONDS * 2**self.request.retries
        logger.warning(f"Purge of {uuid} failed on attempt {attempt}: {e!r}")
        raise self.retry(exc=e, countdown=delay) from e


async def _purge(document_uuid: UUID) -> None:
    """Open the clients, run the purge, close them."""
    settings = get_settings()
    async with worker_clients():
        storage = S3Storage(s3_client.client, settings.S3_BUCKET)
        vectors = QdrantVectorStore(
            qdrant_client.client, settings.QDRANT_COLLECTION_ALIAS
        )
        async for session in db_client.get_session():
            await DocumentService(session).purge_document(
                document_uuid, storage, vectors
            )
