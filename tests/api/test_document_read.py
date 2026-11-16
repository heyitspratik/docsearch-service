"""GET list, metadata and status against a real Postgres (see ``db_session``)."""

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.database.dependency import get_db
from app.constants import DocumentStatus
from app.db.models import DocumentMaster
from app.helpers import AuthenticatedUser, get_current_user

pytestmark = pytest.mark.integration

URL = "/api/v1/documents"
LIST_URL = f"{URL}/list"
USER = AuthenticatedUser(id="user-1", username="demo")
OTHER_USER_ID = "user-2"


@pytest.fixture
def read_app(app: FastAPI, db_session: AsyncSession) -> FastAPI:
    """The app with a fixed user and the test session."""

    async def test_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = test_db
    app.dependency_overrides[get_current_user] = lambda: USER
    return app


async def add_document(
    session: AsyncSession,
    filename: str,
    status: DocumentStatus = DocumentStatus.QUEUED,
    user_uuid: str = USER.id,
    **values: object,
) -> DocumentMaster:
    document_uuid = uuid4()
    document = DocumentMaster(
        uuid=document_uuid,
        user_uuid=user_uuid,
        filename=filename,
        mime_type="application/pdf",
        size_bytes=1234,
        storage_key=f"documents/{user_uuid}/{document_uuid}/original.pdf",
        status=status,
        **values,
    )
    session.add(document)
    await session.flush()
    return document


@pytest.mark.usefixtures("read_app")
async def test_list_shows_only_own_documents_newest_first(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    older = await add_document(db_session, "older.pdf", DocumentStatus.READY)
    newer = await add_document(db_session, "newer.pdf")
    await add_document(db_session, "gone.pdf", DocumentStatus.DELETED)
    await add_document(db_session, "theirs.pdf", user_uuid=OTHER_USER_ID)

    response = await client.get(LIST_URL)

    assert response.status_code == 200
    documents = response.json()["payload"]["documents"]
    assert [d["document_uuid"] for d in documents] == [
        str(newer.uuid),
        str(older.uuid),
    ]
    assert documents[1]["filename"] == "older.pdf"
    assert documents[1]["status"] == DocumentStatus.READY


@pytest.mark.usefixtures("read_app")
async def test_list_is_empty_for_a_new_user(client: AsyncClient) -> None:
    response = await client.get(LIST_URL)

    assert response.status_code == 200
    assert response.json()["payload"] == {"documents": []}


@pytest.mark.usefixtures("read_app")
async def test_metadata_has_the_details(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    document = await add_document(
        db_session,
        "report.pdf",
        DocumentStatus.READY,
        page_count=19,
        chunk_count=30,
        embedding_model="BAAI/bge-base-en-v1.5",
    )

    response = await client.get(f"{URL}/{document.uuid}/metadata")

    assert response.status_code == 200
    payload = response.json()["payload"]
    assert payload["document_uuid"] == str(document.uuid)
    assert payload["mime_type"] == "application/pdf"
    assert payload["size_bytes"] == 1234
    assert (payload["page_count"], payload["chunk_count"]) == (19, 30)
    assert payload["embedding_model"] == "BAAI/bge-base-en-v1.5"


@pytest.mark.usefixtures("read_app")
async def test_status_of_a_failed_document_has_its_error(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    document = await add_document(
        db_session,
        "blank.txt",
        DocumentStatus.FAILED,
        error="No text was found in the file",
    )

    response = await client.get(f"{URL}/{document.uuid}/status")

    assert response.status_code == 200
    payload = response.json()["payload"]
    assert payload["status"] == DocumentStatus.FAILED
    assert payload["error"] == "No text was found in the file"


@pytest.mark.usefixtures("read_app")
@pytest.mark.parametrize("endpoint", ["metadata", "status"])
async def test_another_users_document_is_not_found(
    client: AsyncClient, db_session: AsyncSession, endpoint: str
) -> None:
    theirs = await add_document(db_session, "theirs.pdf", user_uuid=OTHER_USER_ID)

    response = await client.get(f"{URL}/{theirs.uuid}/{endpoint}")

    assert response.status_code == 404
    assert response.json()["message"] == "Document not found"


@pytest.mark.usefixtures("read_app")
@pytest.mark.parametrize("endpoint", ["metadata", "status"])
async def test_deleted_or_unknown_document_is_not_found(
    client: AsyncClient, db_session: AsyncSession, endpoint: str
) -> None:
    deleted = await add_document(db_session, "gone.pdf", DocumentStatus.DELETED)

    for document_uuid in (deleted.uuid, uuid4()):
        response = await client.get(f"{URL}/{document_uuid}/{endpoint}")
        assert response.status_code == 404


@pytest.mark.usefixtures("read_app")
async def test_invalid_id_is_rejected(client: AsyncClient) -> None:
    response = await client.get(f"{URL}/not-a-uuid/status")

    assert response.status_code == 422


async def test_requires_login(client: AsyncClient) -> None:
    response = await client.get(LIST_URL)

    assert response.status_code == 401
