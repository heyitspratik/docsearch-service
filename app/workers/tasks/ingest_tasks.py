"""Ingestion task, on the ``ingest`` queue."""

import asyncio
from typing import Any
from uuid import UUID

from celery import signals

from app.clients.database.client import db_client
from app.clients.qdrant.client import qdrant_client
from app.clients.qdrant.service import QdrantVectorStore
from app.clients.s3.client import s3_client
from app.clients.s3.service import S3Storage
from app.helpers.chunking_helper import get_chunker
from app.helpers.embedding_helper import get_dense_embedder, get_sparse_embedder
from app.helpers.extraction_helper import load_models
from app.helpers.model_spec_helper import get_model_spec
from app.services.ingestion_service import IngestionService
from app.settings import get_settings
from app.workers.celery_app import celery_app
from app.workers.worker_clients import worker_clients


@celery_app.task(name="ingest_document")  # type: ignore[untyped-decorator]
def ingest_document(document_uuid: str) -> None:
    """Ingest one document. Synchronous: Celery runs plain functions."""
    asyncio.run(_ingest(UUID(document_uuid)))


async def _ingest(document_uuid: UUID) -> None:
    """Open the clients, run the service in one transaction, close them."""
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


def _load_models(**_: Any) -> None:
    """Load the models once per worker process, before its first job."""
    load_models()
    get_chunker(get_settings().EMBEDDING_DENSE_MODEL)
    get_dense_embedder()
    get_sparse_embedder()


# Here, not in celery_app.py: the API imports that file and must not load models.
signals.worker_process_init.connect(_load_models)
