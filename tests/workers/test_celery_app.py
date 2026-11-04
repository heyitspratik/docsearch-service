"""Celery configuration: queues, routing and delivery guarantees."""

from app.workers.celery_app import celery_app


def test_both_queues_exist_and_quick_jobs_go_to_default() -> None:
    conf = celery_app.conf
    assert {queue.name for queue in conf.task_queues} == {"ingest", "default"}
    assert conf.task_default_queue == "default"


def test_each_queue_has_its_own_routing_key() -> None:
    """A shared key would copy every job into both queues."""
    keys = {queue.name: queue.routing_key for queue in celery_app.conf.task_queues}
    assert keys == {"ingest": "ingest", "default": "default"}


def test_ingest_document_is_routed_to_the_ingest_queue() -> None:
    assert celery_app.conf.task_routes["ingest_document"] == {"queue": "ingest"}


def test_a_job_survives_a_worker_crash() -> None:
    conf = celery_app.conf
    assert conf.task_acks_late is True
    assert conf.task_reject_on_worker_lost is True
    assert conf.worker_prefetch_multiplier == 1


def test_ingest_task_is_registered() -> None:
    assert "ingest_document" in celery_app.tasks
