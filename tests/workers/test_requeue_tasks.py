"""The re-queue task and its beat schedule."""

from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from app.workers.celery_app import celery_app
from app.workers.tasks import requeue_tasks


def test_beat_sends_the_requeue_every_five_minutes() -> None:
    entry = celery_app.conf.beat_schedule["requeue-stuck-documents"]
    assert entry["task"] == "requeue_stuck_documents"
    assert entry["schedule"] == 300
    # A tick nobody ran in time is dropped, so a stopped worker gets no backlog.
    assert entry["options"] == {"expires": 300}


def test_requeue_is_registered_on_the_default_queue() -> None:
    assert "requeue_stuck_documents" in celery_app.tasks
    route = celery_app.conf.task_routes["requeue_stuck_documents"]
    assert route == {"queue": "default"}


def test_task_opens_clients_and_calls_the_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    session = object()

    @asynccontextmanager
    async def fake_clients() -> AsyncGenerator[None, None]:
        events.append("clients open")
        yield
        events.append("clients closed")

    async def fake_get_session() -> AsyncIterator[object]:
        yield session

    class FakeDocumentService:
        def __init__(self, given: object) -> None:
            assert given is session

        async def requeue_stuck_documents(self, minutes: int) -> list[object]:
            events.append(f"requeue older than {minutes} min")
            return []

    monkeypatch.setattr(requeue_tasks, "worker_clients", fake_clients)
    monkeypatch.setattr(requeue_tasks.db_client, "get_session", fake_get_session)
    monkeypatch.setattr(requeue_tasks, "DocumentService", FakeDocumentService)
    monkeypatch.setattr(
        requeue_tasks,
        "get_settings",
        lambda: SimpleNamespace(CELERY_REQUEUE_AFTER_MINUTES=7),
    )

    requeue_tasks.requeue_stuck_documents()

    assert events == ["clients open", "requeue older than 7 min", "clients closed"]
