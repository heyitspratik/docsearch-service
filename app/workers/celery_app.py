"""The Celery app shared by the worker, beat and the API, which sends it jobs.

Run a worker with:
    celery -A app.workers.celery_app worker -Q ingest,default
Run the scheduler (exactly one) with:
    celery -A app.workers.celery_app beat
"""

from typing import Any

from celery import Celery, signals
from kombu import Queue

from app.constants import REQUEUE_CHECK_SECONDS, TaskQueue
from app.log import configure_logging
from app.settings import get_settings

settings = get_settings()

celery_app = Celery(
    "docsearch",
    broker=settings.celery_broker_url,
    include=[
        "app.workers.tasks.ingest_tasks",
        "app.workers.tasks.purge_tasks",
        "app.workers.tasks.requeue_tasks",
    ],
)
celery_app.conf.update(
    # Each queue needs its own routing key, or a job is copied into both.
    task_queues=[
        Queue(TaskQueue.INGEST, routing_key=TaskQueue.INGEST),
        Queue(TaskQueue.DEFAULT, routing_key=TaskQueue.DEFAULT),
    ],
    task_default_queue=TaskQueue.DEFAULT,
    task_routes={
        "ingest_document": {"queue": TaskQueue.INGEST},
        "purge_document": {"queue": TaskQueue.DEFAULT},
        "requeue_stuck_documents": {"queue": TaskQueue.DEFAULT},
    },
    beat_schedule={
        "requeue-stuck-documents": {
            "task": "requeue_stuck_documents",
            "schedule": REQUEUE_CHECK_SECONDS,
            # A tick nobody ran before the next one is dropped, not piled up.
            "options": {"expires": REQUEUE_CHECK_SECONDS},
        },
    },
    # Remove a job from Redis only after it finishes, so a crash cannot lose it.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Each process reserves one job at a time, so others are not held waiting.
    worker_prefetch_multiplier=1,
    task_serializer="json",
    accept_content=["json"],
    # Progress lives in document_master.status, so no result backend.
    task_ignore_result=True,
    timezone="UTC",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
)


def _configure_logging(**_: Any) -> None:
    """Use the app's log format instead of Celery's own."""
    configure_logging(get_settings())


signals.setup_logging.connect(_configure_logging)
