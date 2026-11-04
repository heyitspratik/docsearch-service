"""Sending jobs to the worker by task name, without importing the tasks.

The tasks import the services, so the services cannot import the tasks back.
"""

from collections.abc import Iterable
from uuid import UUID

from app.workers.celery_app import celery_app


def enqueue_ingestion(document_uuids: Iterable[UUID]) -> None:
    """Send one ``ingest_document`` job per document to Redis."""
    for document_uuid in document_uuids:
        celery_app.send_task("ingest_document", args=[str(document_uuid)])
