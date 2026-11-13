"""The ingest task and how upload hands documents to it."""

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
