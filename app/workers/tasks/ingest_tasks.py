"""Ingestion task, on the ``ingest`` queue."""

import asyncio
from typing import Any
from uuid import UUID

from celery import Task, signals

from app.clients.database.client import db_client
from app.clients.qdrant.client import qdrant_client
from app.clients.qdrant.service import QdrantVectorStore
from app.clients.s3.client import s3_client
from app.clients.s3.service import S3Storage
from app.constants import (
    INGEST_RECHECK_MARGIN_SECONDS,
    INGEST_RETRY_BASE_SECONDS,
    IngestionMessages,
)
from app.helpers.chunking_helper import get_chunker
from app.helpers.embedding_helper import get_dense_embedder, get_sparse_embedder
from app.helpers.extraction_helper import load_models
from app.helpers.model_spec_helper import get_model_spec
from app.log import get_logger
from app.services.ingestion_service import IngestionService
from app.settings import get_settings
from app.workers.celery_app import celery_app
from app.workers.ingest_lock import IngestLock
from app.workers.worker_clients import worker_clients

logger = get_logger(__name__)


@celery_app.task(  # type: ignore[untyped-decorator]
    name="ingest_document", bind=True, max_retries=get_settings().CELERY_MAX_RETRIES
)
def ingest_document(self: Task, document_uuid: str) -> None:
    """Ingest one document. Synchronous: Celery runs plain functions.

    Only one run per document at a time. A message that finds the lock taken
    sends itself again for just after the lock expires: by then the other run
    has finished (the document is ``ready`` and skipped) or has died (its lock
    is gone and this run takes over).
    A temporary error (e.g. Qdrant down) is retried after 10 s, 20 s, 40 s …;
    once the retries run out, the document is marked ``failed``.
    """
    uuid = UUID(document_uuid)
    lock = IngestLock(uuid)
    if not lock.acquire():
        wait = lock.seconds_left() + INGEST_RECHECK_MARGIN_SECONDS
        logger.info(f"Document {uuid} is being ingested; checking again in {wait} s")
        # A new message, sent before this one is acked, so the job is never lost.
        self.apply_async(args=[document_uuid], countdown=wait)
        return
    try:
        asyncio.run(_ingest(uuid))
    except Exception as e:
        attempt = self.request.retries + 1
        if self.request.retries >= self.max_retries:
            logger.exception(f"Ingest of {uuid} failed after {attempt} attempts")
            error = IngestionMessages.RETRIES_EXHAUSTED.format(attempts=attempt)
            asyncio.run(_mark_failed(uuid, error))
            return
        delay = INGEST_RETRY_BASE_SECONDS * 2**self.request.retries
        logger.warning(f"Ingest of {uuid} failed on attempt {attempt}: {e!r}")
        failure = e
    else:
        return
    finally:
        lock.release()
    # After the release, so the retry can take the lock again.
    raise self.retry(exc=failure, countdown=delay) from failure


async def _ingest(document_uuid: UUID) -> None:
    """Open the clients, run the service, close them."""
    settings = get_settings()
    async with worker_clients():
        storage = S3Storage(s3_client.client, settings.S3_BUCKET)
        vectors = QdrantVectorStore(
            qdrant_client.client, settings.QDRANT_COLLECTION_ALIAS
        )
        # One request when it exists; creates it if this worker beat the API.
        await vectors.ensure_collection(get_model_spec(settings.EMBEDDING_DENSE_MODEL))
        async for session in db_client.get_session():
            await IngestionService(
                session, storage, get_dense_embedder(), get_sparse_embedder(), vectors
            ).ingest(document_uuid)


async def _mark_failed(document_uuid: UUID, error: str) -> None:
    """Record the final failure. Skips the collection check, which may be why."""
    settings = get_settings()
    async with worker_clients():
        storage = S3Storage(s3_client.client, settings.S3_BUCKET)
        vectors = QdrantVectorStore(
            qdrant_client.client, settings.QDRANT_COLLECTION_ALIAS
        )
        async for session in db_client.get_session():
            await IngestionService(
                session, storage, get_dense_embedder(), get_sparse_embedder(), vectors
            ).mark_failed(document_uuid, error)


def _load_models(**_: Any) -> None:
    """Load the models once per worker process, before its first job."""
    load_models()
    get_chunker(get_settings().EMBEDDING_DENSE_MODEL)
    get_dense_embedder()
    get_sparse_embedder()


# Here, not in celery_app.py: the API imports that file and must not load models.
signals.worker_process_init.connect(_load_models)
