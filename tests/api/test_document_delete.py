"""DELETE /api/v1/documents/{document_uuid} against a real Postgres."""

from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.database.dependency import get_db
from app.constants import DocumentStatus
from app.helpers import get_current_user
from app.services import document_service
from tests.api.test_document_read import (
    LIST_URL,
    OTHER_USER_ID,
    URL,
    USER,
    add_document,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def purged() -> list[UUID]:
    """Documents sent for purging, instead of real Celery jobs."""
    return []


@pytest.fixture
def delete_app(
    app: FastAPI,
    db_session: AsyncSession,
    purged: list[UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> FastAPI:
    """The app with a fixed user, the test session and a recorded purge."""

    async def test_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = test_db
    app.dependency_overrides[get_current_user] = lambda: USER
    monkeypatch.setattr(document_service, "enqueue_purge", purged.append)
    return app


@pytest.mark.usefixtures("delete_app")
async def test_delete_marks_it_deleted_and_queues_the_purge(
    client: AsyncClient, db_session: AsyncSession, purged: list[UUID]
) -> None:
    document = await add_document(db_session, "report.pdf", DocumentStatus.READY)

    response = await client.delete(f"{URL}/{document.uuid}")

    assert response.status_code == 202
    assert response.json()["payload"] == {
        "document_uuid": str(document.uuid),
        "status": DocumentStatus.DELETED,
    }
    await db_session.refresh(document)
    assert document.status == DocumentStatus.DELETED
    assert purged == [document.uuid]


@pytest.mark.usefixtures("delete_app")
async def test_deleted_document_disappears_from_every_endpoint(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    document = await add_document(db_session, "report.pdf", DocumentStatus.READY)

    await client.delete(f"{URL}/{document.uuid}")

    assert (await client.get(LIST_URL)).json()["payload"] == {"documents": []}
    assert (await client.get(f"{URL}/{document.uuid}/status")).status_code == 404
    assert (await client.delete(f"{URL}/{document.uuid}")).status_code == 404


@pytest.mark.usefixtures("delete_app")
async def test_another_users_document_is_not_found_and_kept(
    client: AsyncClient, db_session: AsyncSession, purged: list[UUID]
) -> None:
    theirs = await add_document(
        db_session, "theirs.pdf", DocumentStatus.READY, user_uuid=OTHER_USER_ID
    )

    response = await client.delete(f"{URL}/{theirs.uuid}")

    assert response.status_code == 404
    assert response.json()["message"] == "Document not found"
    await db_session.refresh(theirs)
    assert theirs.status == DocumentStatus.READY
    assert purged == []


@pytest.mark.usefixtures("delete_app")
async def test_unknown_document_is_not_found(
    client: AsyncClient, purged: list[UUID]
) -> None:
    response = await client.delete(f"{URL}/{uuid4()}")

    assert response.status_code == 404
    assert purged == []


async def test_delete_requires_login(client: AsyncClient) -> None:
    response = await client.delete(f"{URL}/{uuid4()}")

    assert response.status_code == 401
