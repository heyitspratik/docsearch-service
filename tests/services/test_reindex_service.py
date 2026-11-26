"""ReindexService against real Postgres, in-memory Qdrant and real Docling JSON.

Documents are first ingested into the live ``test/tiny`` collection, then
re-indexed for ``bge-small-en-v1.5`` (its real tokenizer, a fake embedder).
"""

from collections.abc import Sequence
from typing import Any
from uuid import UUID, uuid4

import pytest
from qdrant_client import AsyncQdrantClient, models
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.qdrant.service import QdrantVectorStore
from app.constants import DocumentStatus
from app.db.models import DocumentChunk, DocumentMaster
from app.db.services import DocumentDBService
from app.helpers import extracted_key, get_model_spec
from app.services.ingestion_service import IngestionService
from app.services.reindex_service import ReindexService
from tests.fakes import FakeDenseEmbedder, FakeSparseEmbedder, InMemoryStorage
from tests.services.conftest import TINY

pytestmark = [
    pytest.mark.integration,
    pytest.mark.filterwarnings("ignore:Payload indexes have no effect"),
]

SMALL = get_model_spec("BAAI/bge-small-en-v1.5")
OLD = "chunks__tiny"
NEW = "chunks__bge-small-en-v1.5"


class SmallDenseEmbedder:
    """Fake ``bge-small`` passages: 384 numbers, as its collection expects."""

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        return [[float(len(text))] + [1.0] * (SMALL.dimensions - 1) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_passages([text])[0]


async def ingest(
    session: AsyncSession,
    storage: InMemoryStorage,
    vectors: QdrantVectorStore,
    text: str = "# Leave policy\n\nStaff get twenty days.\n",
) -> UUID:
    """Upload and ingest one TXT document into the live collection; ready."""
    document_uuid = uuid4()
    storage_key = f"documents/user-1/{document_uuid}/original.txt"
    await storage.put(storage_key, text.encode(), "text/plain")
    session.add(
        DocumentMaster(
            uuid=document_uuid,
            user_uuid="user-1",
            filename="notes.txt",
            mime_type="text/plain",
            size_bytes=len(text),
            storage_key=storage_key,
            status=DocumentStatus.QUEUED,
        )
    )
    await session.flush()
    await IngestionService(
        session, storage, FakeDenseEmbedder(), FakeSparseEmbedder(), vectors
    ).ingest(document_uuid)
    return document_uuid


def make_service(
    session: AsyncSession, storage: InMemoryStorage, vectors: QdrantVectorStore
) -> ReindexService:
    return ReindexService(
        session, storage, SmallDenseEmbedder(), FakeSparseEmbedder(), vectors
    )


async def points_of(qdrant: AsyncQdrantClient, document_uuid: UUID) -> int:
    """How many points the new collection holds for one document."""
    result = await qdrant.count(
        collection_name=NEW,
        count_filter=models.Filter(
            must=[
                models.FieldCondition(
                    key="document_id",
                    match=models.MatchValue(value=str(document_uuid)),
                )
            ]
        ),
    )
    return result.count


async def collections(qdrant: AsyncQdrantClient) -> set[str]:
    return {c.name for c in (await qdrant.get_collections()).collections}


async def test_builds_the_new_collection_and_switches_the_alias(
    db_session: AsyncSession, qdrant: AsyncQdrantClient, vectors: QdrantVectorStore
) -> None:
    storage = InMemoryStorage()
    first = await ingest(db_session, storage, vectors)
    second = await ingest(db_session, storage, vectors, "# Pay\n\nSalary is monthly.\n")

    result = await make_service(db_session, storage, vectors).run(SMALL)

    assert await vectors.alias_target() == NEW
    assert await collections(qdrant) == {NEW}
    assert result.old_collection == OLD
    assert result.documents == 2
    assert await points_of(qdrant, first) == await points_of(qdrant, second) == 1
    rows = (await db_session.execute(select(DocumentMaster))).scalars().all()
    assert {row.embedding_model for row in rows if row.uuid in (first, second)} == {
        SMALL.name
    }


async def test_new_points_carry_the_new_model(
    db_session: AsyncSession, qdrant: AsyncQdrantClient, vectors: QdrantVectorStore
) -> None:
    storage = InMemoryStorage()
    await ingest(db_session, storage, vectors)

    await make_service(db_session, storage, vectors).run(SMALL)

    points, _ = await qdrant.scroll(NEW, with_vectors=True)
    assert points[0].payload is not None
    assert points[0].payload["embedding_model"] == SMALL.name
    assert isinstance(points[0].vector, dict)
    assert len(points[0].vector["dense"]) == SMALL.dimensions  # type: ignore[arg-type]


async def test_keep_old_leaves_the_old_collection_for_a_rollback(
    db_session: AsyncSession, qdrant: AsyncQdrantClient, vectors: QdrantVectorStore
) -> None:
    storage = InMemoryStorage()
    await ingest(db_session, storage, vectors)

    result = await make_service(db_session, storage, vectors).run(SMALL, keep_old=True)

    assert result.old_collection_kept
    assert await collections(qdrant) == {OLD, NEW}
    assert await vectors.alias_target() == NEW


async def test_only_ready_documents_are_indexed(
    db_session: AsyncSession, qdrant: AsyncQdrantClient, vectors: QdrantVectorStore
) -> None:
    storage = InMemoryStorage()
    ready = await ingest(db_session, storage, vectors)
    failed = await ingest(db_session, storage, vectors)
    await DocumentDBService(db_session).update_document(
        failed, status=DocumentStatus.FAILED
    )

    result = await make_service(db_session, storage, vectors).run(SMALL)

    assert result.documents == 1
    assert await points_of(qdrant, ready) == 1
    assert await points_of(qdrant, failed) == 0


async def test_refuses_the_model_already_in_use(
    db_session: AsyncSession, vectors: QdrantVectorStore
) -> None:
    with pytest.raises(ValueError, match="already points to chunks__tiny"):
        await make_service(db_session, InMemoryStorage(), vectors).run(TINY)


async def test_document_ready_during_the_run_is_caught_up(
    db_session: AsyncSession,
    qdrant: AsyncQdrantClient,
    vectors: QdrantVectorStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = InMemoryStorage()
    await ingest(db_session, storage, vectors)
    service = make_service(db_session, storage, vectors)
    uploaded: list[UUID] = []
    index_document = service._index_document

    async def upload_during_the_run(*args: Any) -> Any:
        """The first document's indexing is when a new upload becomes ready."""
        if not uploaded:
            uploaded.append(await ingest(db_session, storage, vectors))
        return await index_document(*args)

    monkeypatch.setattr(service, "_index_document", upload_during_the_run)

    result = await service.run(SMALL)

    assert result.caught_up == 1
    assert result.documents == 2
    assert await points_of(qdrant, uploaded[0]) == 1


async def test_document_deleted_during_the_run_is_left_out(
    db_session: AsyncSession,
    qdrant: AsyncQdrantClient,
    vectors: QdrantVectorStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = InMemoryStorage()
    kept = await ingest(db_session, storage, vectors)
    deleted = await ingest(db_session, storage, vectors)
    service = make_service(db_session, storage, vectors)
    index_document = service._index_document

    async def delete_after_indexing(row: Any, *args: Any) -> Any:
        chunks = await index_document(row, *args)
        if row.uuid == deleted:
            await DocumentDBService(db_session).update_document(
                deleted, status=DocumentStatus.DELETED
            )
        return chunks

    monkeypatch.setattr(service, "_index_document", delete_after_indexing)

    result = await service.run(SMALL)

    assert result.removed == 1
    assert result.documents == 1
    assert await points_of(qdrant, kept) == 1
    assert await points_of(qdrant, deleted) == 0


async def test_missing_extraction_stops_before_the_switch(
    db_session: AsyncSession, qdrant: AsyncQdrantClient, vectors: QdrantVectorStore
) -> None:
    storage = InMemoryStorage()
    document = await ingest(db_session, storage, vectors)
    del storage.objects[extracted_key("user-1", str(document))]

    with pytest.raises(RuntimeError, match="the alias was not switched"):
        await make_service(db_session, storage, vectors).run(SMALL)

    # Searches still use the old collection, untouched.
    assert await vectors.alias_target() == OLD
    assert OLD in await collections(qdrant)


async def test_document_updated_after_indexing_is_indexed_again(
    db_session: AsyncSession,
    qdrant: AsyncQdrantClient,
    vectors: QdrantVectorStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = InMemoryStorage()
    document = await ingest(db_session, storage, vectors)
    service = make_service(db_session, storage, vectors)
    index_document = service._index_document

    async def rename_after_first_indexing(row: Any, *args: Any) -> Any:
        chunks = await index_document(row, *args)
        if row.filename == "notes.txt":
            # Any update bumps updated_at, as a future rename feature would.
            await DocumentDBService(db_session).update_document(
                document, filename="renamed.txt"
            )
        return chunks

    monkeypatch.setattr(service, "_index_document", rename_after_first_indexing)

    result = await service.run(SMALL)

    assert result.caught_up == 1
    points, _ = await qdrant.scroll(NEW)
    assert [point.payload["filename"] for point in points if point.payload] == [
        "renamed.txt"
    ]


async def test_missing_extraction_restored_during_the_run_is_retried(
    db_session: AsyncSession,
    qdrant: AsyncQdrantClient,
    vectors: QdrantVectorStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = InMemoryStorage()
    document = await ingest(db_session, storage, vectors)
    key = extracted_key("user-1", str(document))
    saved = storage.objects.pop(key)
    service = make_service(db_session, storage, vectors)
    index_document = service._index_document

    async def restore_after_first_try(row: Any, *args: Any) -> Any:
        chunks = await index_document(row, *args)
        if chunks is None:
            storage.objects[key] = saved
            await DocumentDBService(db_session).update_document(
                document, filename="restored.txt"
            )
        return chunks

    monkeypatch.setattr(service, "_index_document", restore_after_first_try)

    result = await service.run(SMALL)

    assert result.documents == 1
    assert result.caught_up == 1
    assert await points_of(qdrant, document) == 1
    assert await vectors.alias_target() == NEW


async def test_a_second_run_after_a_stop_starts_clean(
    db_session: AsyncSession, qdrant: AsyncQdrantClient, vectors: QdrantVectorStore
) -> None:
    storage = InMemoryStorage()
    kept = await ingest(db_session, storage, vectors)
    gone = await ingest(db_session, storage, vectors)
    broken = await ingest(db_session, storage, vectors)
    key = extracted_key("user-1", str(broken))
    saved = storage.objects.pop(key)
    with pytest.raises(RuntimeError):
        await make_service(db_session, storage, vectors).run(SMALL)
    # The stopped run left gone's points in the new collection.
    assert await points_of(qdrant, gone) == 1
    await DocumentDBService(db_session).update_document(
        gone, status=DocumentStatus.DELETED
    )
    storage.objects[key] = saved

    result = await make_service(db_session, storage, vectors).run(SMALL)

    assert result.documents == 2
    assert await vectors.alias_target() == NEW
    assert await points_of(qdrant, kept) == await points_of(qdrant, broken) == 1
    assert await points_of(qdrant, gone) == 0


async def test_chunk_rows_are_replaced_with_the_new_chunking(
    db_session: AsyncSession, vectors: QdrantVectorStore
) -> None:
    storage = InMemoryStorage()
    document = await ingest(db_session, storage, vectors)

    await make_service(db_session, storage, vectors).run(SMALL)

    rows = (
        (
            await db_session.execute(
                select(DocumentChunk)
                .join(DocumentMaster)
                .where(DocumentMaster.uuid == document)
            )
        )
        .scalars()
        .all()
    )
    assert [row.content for row in rows] == ["Staff get twenty days."]
