"""POST /api/v1/documents/upload against a real Postgres (see ``db_session``)."""

import hashlib
from collections.abc import AsyncIterator, Iterable
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.database.dependency import get_db
from app.clients.s3.dependency import get_storage
from app.constants import DocumentStatus
from app.db.models import DocumentMaster
from app.db.services import DocumentDBService
from app.helpers import AuthenticatedUser, get_current_user
from app.services import document_service
from app.settings import Settings
from tests.fakes import InMemoryStorage

URL = "/api/v1/documents/upload"
USER = AuthenticatedUser(id="94008daa-a0a9-44d6-bb8a-08c0e7ab45cf", username="demo")
OTHER_USER = AuthenticatedUser(
    id="0b3c7e52-1f4a-4d9e-8c6b-2a7d5e9f1c34", username="other"
)
PDF = b"%PDF-1.7\n%%EOF"


@pytest.fixture
def storage() -> InMemoryStorage:
    return InMemoryStorage()


@pytest.fixture
def enqueued() -> list[UUID]:
    """Documents the upload sent for ingestion, instead of real Celery jobs."""
    return []


@pytest.fixture
def upload_app(
    app: FastAPI,
    db_session: AsyncSession,
    storage: InMemoryStorage,
    enqueued: list[UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> FastAPI:
    """The app with a fixed user, the test session, fake storage, small limits."""

    async def test_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = test_db
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_current_user] = lambda: USER
    limits = Settings(_env_file=None, UPLOAD_MAX_FILES=3, UPLOAD_MAX_FILE_SIZE_MB=1)
    monkeypatch.setattr(document_service, "get_settings", lambda: limits)

    def record(document_uuids: Iterable[UUID]) -> None:
        enqueued.extend(document_uuids)

    monkeypatch.setattr(document_service, "enqueue_ingestion", record)
    return app


@pytest.mark.integration
async def test_accepts_valid_files_and_reports_rejected_ones(
    upload_app: FastAPI,
    client: AsyncClient,
    db_session: AsyncSession,
    storage: InMemoryStorage,
    enqueued: list[UUID],
) -> None:
    response = await client.post(
        URL,
        files=[
            ("files", ("report.pdf", PDF, "application/pdf")),
            ("files", ("setup.exe", b"MZ", "application/pdf")),
        ],
    )

    assert response.status_code == 202
    accepted, rejected = response.json()["payload"]
    assert accepted["accepted"] is True
    assert accepted["status"] == DocumentStatus.QUEUED
    assert rejected == {
        "filename": "setup.exe",
        "accepted": False,
        "document_uuid": None,
        "status": None,
        "error": "Unsupported file type. Allowed: .docx, .pdf, .txt",
    }

    document = await db_session.scalar(
        select(DocumentMaster).where(DocumentMaster.uuid == accepted["document_uuid"])
    )
    assert document is not None
    assert document.user_uuid == USER.id
    assert document.filename == "report.pdf"
    assert document.mime_type == "application/pdf"
    assert document.size_bytes == len(PDF)
    assert document.status == DocumentStatus.QUEUED
    assert storage.objects[document.storage_key] == (PDF, "application/pdf")
    # Only the accepted file is sent for ingestion.
    assert enqueued == [UUID(accepted["document_uuid"])]


@pytest.mark.integration
async def test_every_file_rejected_is_a_400_with_a_reason_per_file(
    upload_app: FastAPI,
    client: AsyncClient,
    storage: InMemoryStorage,
    enqueued: list[UUID],
) -> None:
    response = await client.post(
        URL,
        files=[
            ("files", ("empty.pdf", b"", "application/pdf")),
            ("files", ("fake.pdf", b"not a pdf", "application/pdf")),
        ],
    )

    assert response.status_code == 400
    body = response.json()
    assert body["message"] == "None of the files could be accepted"
    assert body["detail"]["errors"] == [
        {"field": "empty.pdf", "message": "File is empty", "type": None},
        {"field": "fake.pdf", "message": "File is not a valid .pdf file", "type": None},
    ]
    assert storage.objects == {}
    assert enqueued == []


@pytest.mark.integration
async def test_too_many_files_is_a_400(
    upload_app: FastAPI, client: AsyncClient, storage: InMemoryStorage
) -> None:
    files = [("files", (f"{n}.pdf", PDF, "application/pdf")) for n in range(4)]

    response = await client.post(URL, files=files)

    assert response.status_code == 400
    assert "At most 3 files" in response.json()["message"]
    assert storage.objects == {}


@pytest.mark.integration
async def test_file_over_the_size_limit_is_rejected(
    upload_app: FastAPI, client: AsyncClient
) -> None:
    too_big = PDF + b"0" * (1024 * 1024)

    response = await client.post(
        URL, files=[("files", ("big.pdf", too_big, "application/pdf"))]
    )

    assert response.status_code == 400
    assert response.json()["detail"]["errors"][0]["message"] == (
        "File is larger than 1 MB"
    )


@pytest.mark.integration
async def test_folder_part_of_a_filename_is_dropped(
    upload_app: FastAPI, client: AsyncClient
) -> None:
    response = await client.post(
        URL,
        files=[("files", ("C:\\Users\\me\\report.pdf", PDF, "application/pdf"))],
    )

    assert response.json()["payload"][0]["filename"] == "report.pdf"


TXT = b"Staff get twenty days of paid leave."


async def upload(client: AsyncClient, *files: tuple[str, bytes, str]) -> list[Any]:
    """POST the files; the per-file results (202) or the error details (400)."""
    response = await client.post(URL, files=[("files", file) for file in files])
    body = response.json()
    if response.status_code == 202:
        return list(body["payload"])
    return list(body["detail"]["errors"])


async def rows_with(db_session: AsyncSession, content: bytes) -> list[DocumentMaster]:
    """Every document row holding exactly these bytes, any user or status."""
    digest = hashlib.sha256(content).hexdigest()
    result = await db_session.scalars(
        select(DocumentMaster).where(DocumentMaster.content_hash == digest)
    )
    return list(result)


@pytest.mark.integration
async def test_same_file_again_is_rejected_as_a_duplicate(
    upload_app: FastAPI,
    client: AsyncClient,
    db_session: AsyncSession,
    storage: InMemoryStorage,
    enqueued: list[UUID],
) -> None:
    [first] = await upload(client, ("report.pdf", PDF, "application/pdf"))

    # Renamed, but the same bytes; the only file, so the upload is a 400.
    [error] = await upload(client, ("report-copy.pdf", PDF, "application/pdf"))

    assert error["message"] == "Already uploaded as report.pdf"
    assert [row.uuid for row in await rows_with(db_session, PDF)] == [
        UUID(first["document_uuid"])
    ]
    assert len(storage.objects) == 1
    assert enqueued == [UUID(first["document_uuid"])]


@pytest.mark.integration
async def test_duplicate_next_to_a_new_file_points_at_the_existing_document(
    upload_app: FastAPI, client: AsyncClient, enqueued: list[UUID]
) -> None:
    [first] = await upload(client, ("report.pdf", PDF, "application/pdf"))

    duplicate, new = await upload(
        client,
        ("report-copy.pdf", PDF, "application/pdf"),
        ("notes.txt", TXT, "text/plain"),
    )

    assert duplicate == {
        "filename": "report-copy.pdf",
        "accepted": False,
        "document_uuid": first["document_uuid"],
        "status": None,
        "error": "Already uploaded as report.pdf",
    }
    assert new["accepted"] is True
    # The duplicate is not sent for ingestion again.
    assert enqueued == [UUID(first["document_uuid"]), UUID(new["document_uuid"])]


@pytest.mark.integration
async def test_same_file_twice_in_one_upload_is_kept_once(
    upload_app: FastAPI,
    client: AsyncClient,
    db_session: AsyncSession,
    storage: InMemoryStorage,
) -> None:
    first, second = await upload(
        client,
        ("report.pdf", PDF, "application/pdf"),
        ("report (1).pdf", PDF, "application/pdf"),
    )

    assert first["accepted"] is True
    assert second["accepted"] is False
    assert second["document_uuid"] == first["document_uuid"]
    assert len(await rows_with(db_session, PDF)) == 1
    assert len(storage.objects) == 1


@pytest.mark.integration
@pytest.mark.parametrize("status", [DocumentStatus.FAILED, DocumentStatus.DELETED])
async def test_file_can_be_uploaded_again_after_it_failed_or_was_deleted(
    upload_app: FastAPI,
    client: AsyncClient,
    db_session: AsyncSession,
    status: DocumentStatus,
) -> None:
    [first] = await upload(client, ("report.pdf", PDF, "application/pdf"))
    await db_session.execute(
        update(DocumentMaster)
        .where(DocumentMaster.uuid == UUID(first["document_uuid"]))
        .values(status=status)
    )

    [again] = await upload(client, ("report.pdf", PDF, "application/pdf"))

    assert again["accepted"] is True
    assert again["document_uuid"] != first["document_uuid"]


@pytest.mark.integration
async def test_another_user_may_upload_the_same_file(
    upload_app: FastAPI, client: AsyncClient
) -> None:
    [mine] = await upload(client, ("report.pdf", PDF, "application/pdf"))
    upload_app.dependency_overrides[get_current_user] = lambda: OTHER_USER

    [theirs] = await upload(client, ("report.pdf", PDF, "application/pdf"))

    assert mine["accepted"] is theirs["accepted"] is True


@pytest.mark.integration
async def test_upload_losing_a_race_is_a_duplicate_and_leaves_no_file(
    upload_app: FastAPI,
    client: AsyncClient,
    db_session: AsyncSession,
    storage: InMemoryStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    [winner] = await upload(client, ("report.pdf", PDF, "application/pdf"))
    files_before = set(storage.objects)
    lookup = DocumentDBService.get_live_by_hash
    checks: list[str] = []

    async def miss_the_first_check(self: DocumentDBService, *args: Any) -> Any:
        """The first check runs before the winner's row exists, as in a race."""
        checks.append("check")
        return None if len(checks) == 1 else await lookup(self, *args)

    monkeypatch.setattr(DocumentDBService, "get_live_by_hash", miss_the_first_check)

    loser, other = await upload(
        client,
        ("report.pdf", PDF, "application/pdf"),
        ("notes.txt", TXT, "text/plain"),
    )

    assert loser["accepted"] is False
    assert loser["document_uuid"] == winner["document_uuid"]
    # Only the loser's insert was undone; the other file still went through.
    assert other["accepted"] is True
    assert len(await rows_with(db_session, PDF)) == 1
    assert set(storage.objects) - files_before == {
        key for key in storage.objects if key.endswith(".txt")
    }


async def test_upload_without_a_token_is_a_401(client: AsyncClient) -> None:
    response = await client.post(
        URL, files=[("files", ("report.pdf", PDF, "application/pdf"))]
    )

    assert response.status_code == 401
