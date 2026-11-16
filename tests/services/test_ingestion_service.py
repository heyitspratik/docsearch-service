"""IngestionService against real Postgres (see ``db_session``) and in-memory Qdrant."""

import json
import logging
from collections.abc import Sequence
from typing import Any
from uuid import UUID, uuid4

import pytest
from qdrant_client import AsyncQdrantClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.qdrant.service import QdrantVectorStore
from app.constants import DocumentStatus, ExtractionMessages, IngestionMessages
from app.db.models import DocumentChunk, DocumentMaster
from app.helpers import extracted_key
from app.helpers.vector_store_helper import ChunkPoint, point_id
from app.services.ingestion_service import IngestionService
from tests.fakes import FakeDenseEmbedder, FakeSparseEmbedder, InMemoryStorage

pytestmark = [
    pytest.mark.integration,
    # In-memory Qdrant ignores payload indexes and warns; the server uses them.
    pytest.mark.filterwarnings("ignore:Payload indexes have no effect"),
]

NOTES = b"# Leave policy\n\nStaff get twenty days.\n"


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
    assert f"Document {document.uuid} ready: 1 chunks indexed" in caplog.text

    data, content_type = storage.objects[extracted_key("user-1", str(document.uuid))]
    assert content_type == "application/json"
    texts = [item["text"] for item in json.loads(data)["texts"]]
    assert texts == ["Leave policy", "Staff get twenty days."]


async def test_unreadable_file_is_marked_failed(
    db_session: AsyncSession, vectors: QdrantVectorStore
) -> None:
    storage = InMemoryStorage()
    document = await add_document(
        db_session, storage, DocumentStatus.QUEUED, data=b"\n  \n"
    )

    await make_service(db_session, storage, vectors).ingest(document.uuid)

    await db_session.refresh(document)
    assert document.status == DocumentStatus.FAILED
    assert document.error == ExtractionMessages.NO_TEXT


async def test_missing_original_is_marked_failed(
    db_session: AsyncSession, vectors: QdrantVectorStore
) -> None:
    storage = InMemoryStorage()
    document = await add_document(db_session, storage, DocumentStatus.QUEUED)
    storage.objects.clear()

    await make_service(db_session, storage, vectors).ingest(document.uuid)

    await db_session.refresh(document)
    assert document.status == DocumentStatus.FAILED
    assert document.error == IngestionMessages.FILE_MISSING


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


async def test_ready_document_has_its_counts_and_chunk_rows(
    db_session: AsyncSession, vectors: QdrantVectorStore
) -> None:
    storage = InMemoryStorage()
    document = await add_document(db_session, storage, DocumentStatus.QUEUED)

    await make_service(db_session, storage, vectors).ingest(document.uuid)

    await db_session.refresh(document)
    assert document.status == DocumentStatus.READY
    assert (document.chunk_count, document.page_count) == (1, None)
    assert document.embedding_model == "BAAI/bge-base-en-v1.5"
    assert document.error is None
    [row] = await chunk_rows(db_session, document)
    assert (row.chunk_index, row.content) == (0, "Staff get twenty days.")
    assert row.heading_path == ["Leave policy"]


async def test_temporary_error_is_raised_and_keeps_the_stage(
    db_session: AsyncSession, vectors: QdrantVectorStore, qdrant: AsyncQdrantClient
) -> None:
    storage = InMemoryStorage()
    document = await add_document(db_session, storage, DocumentStatus.QUEUED)

    with pytest.raises(ConnectionError):
        await make_service(db_session, storage, vectors, BrokenDense()).ingest(
            document.uuid
        )

    await db_session.refresh(document)
    assert document.status == DocumentStatus.EMBEDDING
    assert (await qdrant.count("chunks")).count == 0


async def test_retry_after_a_failure_leaves_no_duplicates(
    db_session: AsyncSession, vectors: QdrantVectorStore, qdrant: AsyncQdrantClient
) -> None:
    storage = InMemoryStorage()
    document = await add_document(db_session, storage, DocumentStatus.QUEUED)
    service = make_service(db_session, storage, vectors)
    await service.ingest(document.uuid)
    # As if the first attempt crashed after writing, before reaching ready.
    await service.document_db.update_document(
        document.uuid, status=DocumentStatus.INDEXING
    )

    await service.ingest(document.uuid)

    assert (await qdrant.count("chunks")).count == 1
    assert len(await chunk_rows(db_session, document)) == 1


async def test_ready_document_is_skipped(
    db_session: AsyncSession, vectors: QdrantVectorStore
) -> None:
    storage, dense = InMemoryStorage(), FakeDenseEmbedder()
    document = await add_document(db_session, storage, DocumentStatus.READY)

    await make_service(db_session, storage, vectors, dense).ingest(document.uuid)

    assert dense.calls == []


async def test_deleted_during_ingest_stops_before_indexing(
    db_session: AsyncSession,
    vectors: QdrantVectorStore,
    qdrant: AsyncQdrantClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = InMemoryStorage()
    document = await add_document(db_session, storage, DocumentStatus.QUEUED)
    service = make_service(db_session, storage, vectors)
    update = service.document_db.update_document

    async def delete_before_indexing(document_uuid: UUID, **values: Any) -> bool:
        if values.get("status") is DocumentStatus.INDEXING:
            await update(document_uuid, status=DocumentStatus.DELETED)
        return await update(document_uuid, **values)

    monkeypatch.setattr(service.document_db, "update_document", delete_before_indexing)

    await service.ingest(document.uuid)

    await db_session.refresh(document)
    assert document.status == DocumentStatus.DELETED
    assert (await qdrant.count("chunks")).count == 0
    assert await chunk_rows(db_session, document) == []


async def test_deleted_during_extraction_leaves_no_extracted_file(
    db_session: AsyncSession,
    vectors: QdrantVectorStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = InMemoryStorage()
    document = await add_document(db_session, storage, DocumentStatus.QUEUED)
    service = make_service(db_session, storage, vectors)
    update = service.document_db.update_document

    # As if the purge ran while Docling worked, before extracted.json was saved.
    async def delete_before_chunking(document_uuid: UUID, **values: Any) -> bool:
        if values.get("status") is DocumentStatus.CHUNKING:
            await update(document_uuid, status=DocumentStatus.DELETED)
        return await update(document_uuid, **values)

    monkeypatch.setattr(service.document_db, "update_document", delete_before_chunking)

    await service.ingest(document.uuid)

    assert extracted_key("user-1", str(document.uuid)) not in storage.objects


async def test_deleted_after_upsert_removes_the_points_and_rows(
    db_session: AsyncSession,
    vectors: QdrantVectorStore,
    qdrant: AsyncQdrantClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = InMemoryStorage()
    document = await add_document(db_session, storage, DocumentStatus.QUEUED)
    service = make_service(db_session, storage, vectors)
    upsert = vectors.upsert

    # The user deletes right after the upsert; the purge found no points yet.
    async def upsert_then_delete(points: Sequence[ChunkPoint]) -> None:
        await upsert(points)
        assert (await qdrant.count("chunks")).count == 1
        await service.document_db.update_document(
            document.uuid, status=DocumentStatus.DELETED
        )
        # The API commits its delete in its own transaction.
        await db_session.commit()

    monkeypatch.setattr(vectors, "upsert", upsert_then_delete)

    await service.ingest(document.uuid)

    await db_session.refresh(document)
    assert document.status == DocumentStatus.DELETED
    assert (await qdrant.count("chunks")).count == 0
    assert await chunk_rows(db_session, document) == []


class BrokenDense(FakeDenseEmbedder):
    """A dense model whose server is down."""

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        raise ConnectionError("model server down")


async def chunk_rows(
    session: AsyncSession, document: DocumentMaster
) -> list[DocumentChunk]:
    result = await session.execute(
        select(DocumentChunk).where(DocumentChunk.document_id == document.id)
    )
    return list(result.scalars())
