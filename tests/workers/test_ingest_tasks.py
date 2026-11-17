"""The ingest task and how upload hands documents to it."""

import logging
import subprocess
import sys
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.workers import dispatch
from app.workers.tasks import ingest_tasks


class FakeLock:
    """A non-blocking lock kept in a set, so tests need no Redis."""

    def __init__(self, held: set[UUID], document_uuid: UUID) -> None:
        self.held = held
        self.document_uuid = document_uuid

    def acquire(self) -> bool:
        if self.document_uuid in self.held:
            return False
        self.held.add(self.document_uuid)
        return True

    def release(self) -> None:
        self.held.remove(self.document_uuid)

    def seconds_left(self) -> int:
        return 2699


@pytest.fixture(autouse=True)
def held(monkeypatch: pytest.MonkeyPatch) -> set[UUID]:
    """Documents whose ingest lock is taken."""
    taken: set[UUID] = set()
    monkeypatch.setattr(ingest_tasks, "IngestLock", lambda uuid: FakeLock(taken, uuid))
    return taken


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


def test_api_does_not_load_the_model_libraries() -> None:
    """Docling, PyTorch and transformers cost 3 s and 400 MB; only the worker pays."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, app.application; "
            "loaded = {'docling', 'docling_core', 'torch', 'transformers'}"
            " & set(sys.modules); "
            "sys.exit(f'loaded: {sorted(loaded)}' if loaded else 0)",
        ],
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

    class FakeStore:
        def __init__(self, client: object, alias: str) -> None:
            assert alias == "chunks"

        async def ensure_collection(self, spec: object) -> None:
            events.append("collection ensured")

    store: Any = None

    def make_store(client: object, alias: str) -> FakeStore:
        nonlocal store
        store = FakeStore(client, alias)
        return store

    @asynccontextmanager
    async def fake_clients() -> AsyncGenerator[None, None]:
        events.append("clients open")
        yield
        events.append("clients closed")

    async def fake_get_session() -> AsyncIterator[object]:
        yield session

    class FakeIngestionService:
        def __init__(
            self,
            given: object,
            storage: object,
            dense: object,
            sparse: object,
            vectors: object,
        ) -> None:
            assert given is session
            assert storage is not None
            assert (dense, sparse) == ("dense", "sparse")
            assert vectors is store

        async def ingest(self, document_uuid: UUID) -> None:
            events.append(f"ingest {document_uuid}")

    monkeypatch.setattr(ingest_tasks, "worker_clients", fake_clients)
    monkeypatch.setattr(ingest_tasks.db_client, "get_session", fake_get_session)
    monkeypatch.setattr(ingest_tasks, "s3_client", SimpleNamespace(client=object()))
    monkeypatch.setattr(ingest_tasks, "qdrant_client", SimpleNamespace(client=object()))
    monkeypatch.setattr(ingest_tasks, "QdrantVectorStore", make_store)
    monkeypatch.setattr(ingest_tasks, "get_dense_embedder", lambda: "dense")
    monkeypatch.setattr(ingest_tasks, "get_sparse_embedder", lambda: "sparse")
    monkeypatch.setattr(ingest_tasks, "IngestionService", FakeIngestionService)
    document_uuid = uuid4()

    ingest_tasks.ingest_document(str(document_uuid))

    assert events == [
        "clients open",
        "collection ensured",
        f"ingest {document_uuid}",
        "clients closed",
    ]


def test_temporary_error_is_retried_then_marked_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[UUID] = []
    failed: list[tuple[UUID, str]] = []

    async def always_down(document_uuid: UUID) -> None:
        attempts.append(document_uuid)
        raise ConnectionError("qdrant down")

    async def mark_failed(document_uuid: UUID, error: str) -> None:
        failed.append((document_uuid, error))

    monkeypatch.setattr(ingest_tasks, "_ingest", always_down)
    monkeypatch.setattr(ingest_tasks, "_mark_failed", mark_failed)
    document_uuid = uuid4()

    # Run in-process: Celery repeats each retry at once instead of waiting.
    ingest_tasks.ingest_document.apply(args=[str(document_uuid)])

    assert len(attempts) == 6  # the first try and 5 retries
    assert failed == [
        (document_uuid, "Processing failed after 6 attempts. Upload it again")
    ]


def test_success_after_a_retry_is_not_marked_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[UUID] = []

    async def down_once(document_uuid: UUID) -> None:
        attempts.append(document_uuid)
        if len(attempts) == 1:
            raise ConnectionError("qdrant down")

    async def mark_failed(document_uuid: UUID, error: str) -> None:
        raise AssertionError("must not be called")

    monkeypatch.setattr(ingest_tasks, "_ingest", down_once)
    monkeypatch.setattr(ingest_tasks, "_mark_failed", mark_failed)

    ingest_tasks.ingest_document.apply(args=[str(uuid4())])

    assert len(attempts) == 2


def test_a_held_lock_sends_the_job_again_for_after_it_expires(
    monkeypatch: pytest.MonkeyPatch,
    held: set[UUID],
    caplog: pytest.LogCaptureFixture,
) -> None:
    sent: list[tuple[list[str], int]] = []

    async def must_not_run(document_uuid: UUID) -> None:
        raise AssertionError("must not run")

    def apply_async(args: list[str], countdown: int) -> None:
        sent.append((args, countdown))

    monkeypatch.setattr(ingest_tasks, "_ingest", must_not_run)
    monkeypatch.setattr(ingest_tasks.ingest_document, "apply_async", apply_async)
    document_uuid = uuid4()
    held.add(document_uuid)

    with caplog.at_level(logging.INFO):
        ingest_tasks.ingest_document(str(document_uuid))

    assert sent == [([str(document_uuid)], 2704)]  # 2699 s left + 5 s margin
    assert f"Document {document_uuid} is being ingested; checking again" in caplog.text
    assert held == {document_uuid}  # still the other run's lock


def test_the_lock_is_held_during_the_run_and_released_after(
    monkeypatch: pytest.MonkeyPatch, held: set[UUID]
) -> None:
    during: list[bool] = []

    async def run(document_uuid: UUID) -> None:
        during.append(document_uuid in held)

    monkeypatch.setattr(ingest_tasks, "_ingest", run)

    ingest_tasks.ingest_document(str(uuid4()))

    assert during == [True]
    assert held == set()


def test_each_retry_takes_the_lock_and_it_is_released_at_the_end(
    monkeypatch: pytest.MonkeyPatch, held: set[UUID]
) -> None:
    attempts: list[bool] = []

    async def always_down(document_uuid: UUID) -> None:
        attempts.append(document_uuid in held)
        raise ConnectionError("qdrant down")

    async def mark_failed(document_uuid: UUID, error: str) -> None:
        assert document_uuid in held  # marked failed before letting others in

    monkeypatch.setattr(ingest_tasks, "_ingest", always_down)
    monkeypatch.setattr(ingest_tasks, "_mark_failed", mark_failed)

    ingest_tasks.ingest_document.apply(args=[str(uuid4())])

    assert attempts == [True] * 6  # no retry was skipped as a duplicate
    assert held == set()
