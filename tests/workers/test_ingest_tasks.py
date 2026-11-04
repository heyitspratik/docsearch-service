"""The ingest task and how upload hands documents to it."""

import subprocess
import sys
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.workers import dispatch
from app.workers.tasks import ingest_tasks


def test_enqueue_sends_one_job_per_document(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple[str, list[Any]]] = []

    def send_task(name: str, args: list[Any]) -> None:
        sent.append((name, args))

    monkeypatch.setattr(dispatch.celery_app, "send_task", send_task)
    first, second = uuid4(), uuid4()

    dispatch.enqueue_ingestion([first, second])

    assert sent == [
        ("ingest_document", [str(first)]),
        ("ingest_document", [str(second)]),
    ]


def test_worker_entry_point_imports_without_a_cycle() -> None:
    """The worker imports the tasks first; a fresh interpreter proves the order."""
    result = subprocess.run(
        [sys.executable, "-c", "import app.workers.tasks.ingest_tasks"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_task_opens_clients_and_calls_the_ingestion_service(
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

    class FakeIngestionService:
        def __init__(self, given: object) -> None:
            assert given is session

        async def ingest(self, document_uuid: UUID) -> None:
            events.append(f"ingest {document_uuid}")

    monkeypatch.setattr(ingest_tasks, "worker_clients", fake_clients)
    monkeypatch.setattr(ingest_tasks.db_client, "get_session", fake_get_session)
    monkeypatch.setattr(ingest_tasks, "IngestionService", FakeIngestionService)
    document_uuid = uuid4()

    ingest_tasks.ingest_document(str(document_uuid))

    assert events == ["clients open", f"ingest {document_uuid}", "clients closed"]
