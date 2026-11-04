"""Ingestion task, on the ``ingest`` queue."""

import asyncio
from uuid import UUID

from app.clients.database.client import db_client
from app.services.ingestion_service import IngestionService
from app.workers.celery_app import celery_app
from app.workers.worker_clients import worker_clients


@celery_app.task(name="ingest_document")  # type: ignore[untyped-decorator]
def ingest_document(document_uuid: str) -> None:
    """Ingest one document. Synchronous: Celery runs plain functions."""
    asyncio.run(_ingest(UUID(document_uuid)))


async def _ingest(document_uuid: UUID) -> None:
    """Open the clients, run the service in one transaction, close them."""
    async with worker_clients():
        async for session in db_client.get_session():
            await IngestionService(session).ingest(document_uuid)
