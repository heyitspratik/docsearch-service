"""IngestionService against real Postgres (see ``db_session``) and in-memory Qdrant."""

import json
import logging
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from qdrant_client import AsyncQdrantClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.qdrant.service import QdrantVectorStore
from app.constants import DocumentStatus
from app.db.models import DocumentMaster
from app.exceptions import ExtractionError
from app.helpers import ModelSpec, extracted_key
from app.helpers.vector_store_helper import point_id
from app.services.ingestion_service import IngestionService
from tests.fakes import FakeDenseEmbedder, FakeSparseEmbedder, InMemoryStorage

pytestmark = [
    pytest.mark.integration,
    # In-memory Qdrant ignores payload indexes and warns; the server uses them.
    pytest.mark.filterwarnings("ignore:Payload indexes have no effect"),
]

NOTES = b"# Leave policy\n\nStaff get twenty days.\n"


# Two dimensions, to match FakeDenseEmbedder's [len(text), 1.0].
TINY = ModelSpec(name="test/tiny", dimensions=2, max_tokens=512)


@pytest.fixture
async def qdrant() -> AsyncIterator[AsyncQdrantClient]:
    client = AsyncQdrantClient(location=":memory:")
    yield client
    await client.close()


@pytest.fixture
async def vectors(qdrant: AsyncQdrantClient) -> QdrantVectorStore:
    store = QdrantVectorStore(qdrant, "chunks")
    await store.ensure_collection(TINY)
    return store


def make_service(
    session: AsyncSession,
    storage: InMemoryStorage,
    vectors: QdrantVectorStore,
    dense: FakeDenseEmbedder | None = None,
) -> IngestionService:
    return IngestionService(
        session, storage, dense or FakeDenseEmbedder(), FakeSparseEmbedder(), vectors
    )


async def add_document(
    session: AsyncSession,
    storage: InMemoryStorage,
    status: DocumentStatus,
    data: bytes = NOTES,
) -> DocumentMaster:
    document_uuid = uuid4()
    storage_key = f"documents/user-1/{document_uuid}/original.txt"
    await storage.put(storage_key, data, "text/plain")
    document = DocumentMaster(
        uuid=document_uuid,
        user_uuid="user-1",
        filename="notes.txt",
        mime_type="text/plain",
        size_bytes=len(data),
        storage_key=storage_key,
        status=status,
    )
    session.add(document)
    await session.flush()
    return document


async def test_extracts_saves_the_json_and_chunks(
    db_session: AsyncSession,
    vectors: QdrantVectorStore,
    caplog: pytest.LogCaptureFixture,
) -> None:
    storage = InMemoryStorage()
    document = await add_document(db_session, storage, DocumentStatus.QUEUED)

    with caplog.at_level(logging.INFO):
        await make_service(db_session, storage, vectors).ingest(document.uuid)

    assert f"Chunked document {document.uuid}: 1 chunks" in caplog.text
    assert f"Embedded document {document.uuid}: 1 dense and 1 sparse" in caplog.text
    assert f"Indexed document {document.uuid}: 1 points" in caplog.text

    data, content_type = storage.objects[extracted_key("user-1", str(document.uuid))]
    assert content_type == "application/json"
    texts = [item["text"] for item in json.loads(data)["texts"]]
    assert texts == ["Leave policy", "Staff get twenty days."]


async def test_unreadable_file_raises(
    db_session: AsyncSession, vectors: QdrantVectorStore
) -> None:
    storage = InMemoryStorage()
    document = await add_document(
        db_session, storage, DocumentStatus.QUEUED, data=b"\n  \n"
    )

    with pytest.raises(ExtractionError):
        await make_service(db_session, storage, vectors).ingest(document.uuid)


async def test_missing_document_is_skipped(
    db_session: AsyncSession,
    vectors: QdrantVectorStore,
    caplog: pytest.LogCaptureFixture,
) -> None:
    missing = uuid4()

    with caplog.at_level(logging.INFO):
        await make_service(db_session, InMemoryStorage(), vectors).ingest(missing)

    assert f"Document {missing} not found" in caplog.text


async def test_deleted_document_is_skipped(
    db_session: AsyncSession, vectors: QdrantVectorStore
) -> None:
    storage = InMemoryStorage()
    document = await add_document(db_session, storage, DocumentStatus.DELETED)

    await make_service(db_session, storage, vectors).ingest(document.uuid)

    assert extracted_key("user-1", str(document.uuid)) not in storage.objects


async def test_embeds_the_heading_with_the_text(
    db_session: AsyncSession, vectors: QdrantVectorStore
) -> None:
    storage, dense = InMemoryStorage(), FakeDenseEmbedder()
    document = await add_document(db_session, storage, DocumentStatus.QUEUED)

    await make_service(db_session, storage, vectors, dense).ingest(document.uuid)

    assert dense.calls == [["Leave policy\nStaff get twenty days."]]


async def test_indexes_one_point_per_chunk(
    db_session: AsyncSession, vectors: QdrantVectorStore, qdrant: AsyncQdrantClient
) -> None:
    storage = InMemoryStorage()
    document = await add_document(db_session, storage, DocumentStatus.QUEUED)

    await make_service(db_session, storage, vectors).ingest(document.uuid)

    [point] = await qdrant.retrieve(
        "chunks", [point_id(document.uuid, 0)], with_vectors=True
    )
    assert isinstance(point.vector, dict)
    # len("Leave policy\nStaff get twenty days.") is 35; Qdrant normalises for cosine.
    assert point.vector["dense"] == pytest.approx([0.99959, 0.02856], abs=1e-4)
    assert point.payload == {
        "user_uuid": "user-1",
        "document_id": str(document.uuid),
        "filename": "notes.txt",
        "chunk_index": 0,
        "page_start": None,
        "page_end": None,
        "chunk_type": "text",
        "text": "Staff get twenty days.",
        "embedding_model": "BAAI/bge-base-en-v1.5",
    }


async def test_ingesting_twice_keeps_one_point_per_chunk(
    db_session: AsyncSession, vectors: QdrantVectorStore, qdrant: AsyncQdrantClient
) -> None:
    storage = InMemoryStorage()
    document = await add_document(db_session, storage, DocumentStatus.QUEUED)
    service = make_service(db_session, storage, vectors)

    await service.ingest(document.uuid)
    await service.ingest(document.uuid)

    assert (await qdrant.count("chunks")).count == 1
