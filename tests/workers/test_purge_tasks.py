"""The purge task and how delete hands documents to it."""

from typing import Any
from uuid import UUID, uuid4

import pytest

from app.workers import dispatch
from app.workers.celery_app import celery_app
from app.workers.tasks import purge_tasks


def test_enqueue_purge_sends_one_job(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple[str, list[Any]]] = []

    def send_task(name: str, args: list[Any]) -> None:
        sent.append((name, args))

    monkeypatch.setattr(dispatch.celery_app, "send_task", send_task)
    document_uuid = uuid4()

    dispatch.enqueue_purge(document_uuid)

    assert sent == [("purge_document", [str(document_uuid)])]


def test_purge_is_registered_on_the_default_queue() -> None:
    assert "purge_document" in celery_app.tasks
    assert celery_app.conf.task_routes["purge_document"] == {"queue": "default"}


def test_temporary_error_is_retried_then_given_up(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    attempts: list[UUID] = []

    async def always_down(document_uuid: UUID) -> None:
        attempts.append(document_uuid)
        raise ConnectionError("qdrant down")

    monkeypatch.setattr(purge_tasks, "_purge", always_down)
    document_uuid = uuid4()

    # Run in-process: Celery repeats each retry at once instead of waiting.
    purge_tasks.purge_document.apply(args=[str(document_uuid)])

    assert len(attempts) == 6  # the first try and 5 retries
    assert f"Purge of {document_uuid} failed after 6 attempts" in caplog.text


def test_success_after_a_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts: list[UUID] = []

    async def down_once(document_uuid: UUID) -> None:
        attempts.append(document_uuid)
        if len(attempts) == 1:
            raise ConnectionError("qdrant down")

    monkeypatch.setattr(purge_tasks, "_purge", down_once)

    purge_tasks.purge_document.apply(args=[str(uuid4())])

    assert len(attempts) == 2
