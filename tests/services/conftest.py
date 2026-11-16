"""In-memory Qdrant for the service tests."""

from collections.abc import AsyncIterator

import pytest
from qdrant_client import AsyncQdrantClient

from app.clients.qdrant.service import QdrantVectorStore
from app.helpers import ModelSpec

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
