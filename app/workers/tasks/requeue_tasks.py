"""Re-queue task, sent by beat on a schedule to the ``default`` queue."""

import asyncio

from app.clients.database.client import db_client
from app.services import DocumentService
from app.settings import get_settings
from app.workers.celery_app import celery_app
from app.workers.worker_clients import worker_clients


@celery_app.task(name="requeue_stuck_documents")  # type: ignore[untyped-decorator]
def requeue_stuck_documents() -> None:
    """Re-send documents stuck in ``queued``, e.g. uploaded while Redis was down.

    No retries: if this run fails, the next tick runs again anyway.
    """
    asyncio.run(_requeue())


async def _requeue() -> None:
    """Open the clients, find and re-send the stuck documents, close them."""
    minutes = get_settings().CELERY_REQUEUE_AFTER_MINUTES
    async with worker_clients():
        async for session in db_client.get_session():
            await DocumentService(session).requeue_stuck_documents(minutes)
