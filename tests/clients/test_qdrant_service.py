"""QdrantVectorStore against Qdrant's in-memory mode, so no server is needed."""

import re
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from qdrant_client import AsyncQdrantClient

from app.clients.qdrant.service import QdrantVectorStore
from app.constants import DENSE_VECTOR_NAME, SPARSE_VECTOR_NAME, ChunkType
from app.helpers import get_model_spec
from app.helpers.embedding_helper import SparseVector
from app.helpers.vector_store_helper import ChunkPayload, ChunkPoint, point_id

# In-memory Qdrant ignores payload indexes and warns; the server uses them.
pytestmark = pytest.mark.filterwarnings("ignore:Payload indexes have no effect")

SMALL = get_model_spec("BAAI/bge-small-en-v1.5")


@pytest.fixture
async def client() -> AsyncIterator[AsyncQdrantClient]:
    client = AsyncQdrantClient(location=":memory:")
    yield client
    await client.close()


def make_point(chunk_index: int, text: str = "Staff get twenty days.") -> ChunkPoint:
    document_uuid = uuid4()
    return ChunkPoint(
        id=point_id(document_uuid, chunk_index),
        dense=[0.1] * SMALL.dimensions,
        sparse=SparseVector(indices=[7, 42], values=[1.2, 0.8]),
        payload=ChunkPayload(
            user_uuid="user-1",
            document_id=str(document_uuid),
            filename="notes.txt",
            chunk_index=chunk_index,
            page_start=None,
            page_end=None,
            chunk_type=ChunkType.TEXT,
            text=text,
            embedding_model=SMALL.name,
        ),
    )


async def test_creates_the_collection_behind_the_alias(
    client: AsyncQdrantClient,
) -> None:
    await QdrantVectorStore(client, "chunks").ensure_collection(SMALL)

    aliases = (await client.get_aliases()).aliases
    assert [(a.alias_name, a.collection_name) for a in aliases] == [
        ("chunks", "chunks__bge-small-en-v1.5")
    ]
    config = (await client.get_collection("chunks__bge-small-en-v1.5")).config.params
    assert isinstance(config.vectors, dict)
    assert config.vectors[DENSE_VECTOR_NAME].size == 384
    assert config.sparse_vectors is not None
    assert SPARSE_VECTOR_NAME in config.sparse_vectors


async def test_ensure_twice_is_harmless(client: AsyncQdrantClient) -> None:
    store = QdrantVectorStore(client, "chunks")

    await store.ensure_collection(SMALL)
    await store.ensure_collection(SMALL)

    assert len((await client.get_collections()).collections) == 1


async def test_refuses_a_different_model(client: AsyncQdrantClient) -> None:
    await QdrantVectorStore(client, "chunks").ensure_collection(SMALL)

    with pytest.raises(RuntimeError, match=re.escape("chunks__bge-small-en-v1.5")):
        await QdrantVectorStore(client, "chunks").ensure_collection(
            get_model_spec("BAAI/bge-base-en-v1.5")
        )


async def test_upsert_writes_through_the_alias(client: AsyncQdrantClient) -> None:
    store = QdrantVectorStore(client, "chunks")
    await store.ensure_collection(SMALL)
    point = make_point(0)

    await store.upsert([point])

    [stored] = await client.retrieve("chunks", [point.id])
    assert stored.payload == point.payload.model_dump(mode="json")


async def test_upsert_again_replaces_instead_of_adding(
    client: AsyncQdrantClient,
) -> None:
    store = QdrantVectorStore(client, "chunks")
    await store.ensure_collection(SMALL)
    first = make_point(0, "Old text.")
    again = first.model_copy(
        update={"payload": first.payload.model_copy(update={"text": "New text."})}
    )

    await store.upsert([first])
    await store.upsert([again])

    assert (await client.count("chunks")).count == 1
    [stored] = await client.retrieve("chunks", [first.id])
    assert stored.payload is not None
    assert stored.payload["text"] == "New text."
