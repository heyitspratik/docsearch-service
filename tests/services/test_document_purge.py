"""DocumentService.purge_document against real Postgres and in-memory Qdrant."""

import logging
from uuid import uuid4

import pytest
from qdrant_client import AsyncQdrantClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.qdrant.service import QdrantVectorStore
from app.constants import DocumentStatus
from app.services import DocumentService
from tests.fakes import InMemoryStorage
from tests.services.test_ingestion_service import (
    add_document,
    chunk_rows,
    make_service,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.filterwarnings("ignore:Payload indexes have no effect"),
]


async def test_purge_removes_points_files_and_chunks_but_keeps_the_row(
    db_session: AsyncSession, vectors: QdrantVectorStore, qdrant: AsyncQdrantClient
) -> None:
    storage = InMemoryStorage()
    document = await add_document(db_session, storage, DocumentStatus.QUEUED)
    await make_service(db_session, storage, vectors).ingest(document.uuid)
    assert len(storage.objects) == 2  # original + extracted.json
    service = DocumentService(db_session)
    await service.document_db.update_document(
        document.uuid, status=DocumentStatus.DELETED
    )

    await service.purge_document(document.uuid, storage, vectors)

    assert (await qdrant.count("chunks")).count == 0
    assert storage.objects == {}
    assert await chunk_rows(db_session, document) == []
    await db_session.refresh(document)
    assert document.status == DocumentStatus.DELETED


async def test_purging_twice_is_fine(
    db_session: AsyncSession, vectors: QdrantVectorStore
) -> None:
    storage = InMemoryStorage()
    document = await add_document(db_session, storage, DocumentStatus.DELETED)
    service = DocumentService(db_session)

    await service.purge_document(document.uuid, storage, vectors)
    await service.purge_document(document.uuid, storage, vectors)

    assert storage.objects == {}


async def test_a_document_that_is_not_deleted_is_left_alone(
    db_session: AsyncSession,
    vectors: QdrantVectorStore,
    qdrant: AsyncQdrantClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    storage = InMemoryStorage()
    document = await add_document(db_session, storage, DocumentStatus.QUEUED)
    await make_service(db_session, storage, vectors).ingest(document.uuid)

    with caplog.at_level(logging.WARNING):
        await DocumentService(db_session).purge_document(
            document.uuid, storage, vectors
        )

    assert f"Document {document.uuid} is not deleted" in caplog.text
    assert (await qdrant.count("chunks")).count == 1
    assert len(storage.objects) == 2


async def test_missing_document_is_skipped(
    db_session: AsyncSession,
    vectors: QdrantVectorStore,
    caplog: pytest.LogCaptureFixture,
) -> None:
    missing = uuid4()

    with caplog.at_level(logging.WARNING):
        await DocumentService(db_session).purge_document(
            missing, InMemoryStorage(), vectors
        )

    assert f"Document {missing} not found; nothing to purge" in caplog.text
