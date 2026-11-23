"""GET /documents/search: real Postgres for ownership, in-memory Qdrant, fake models."""

from collections.abc import AsyncIterator
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from qdrant_client import AsyncQdrantClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.database.dependency import get_db
from app.clients.qdrant.dependency import get_vector_store
from app.clients.qdrant.service import QdrantVectorStore
from app.clients.redis.dependency import get_cache
from app.clients.redis.service import RedisCache
from app.constants import DocumentStatus, SearchType
from app.db.models import DocumentMaster
from app.db.services import DocumentDBService
from app.helpers import AuthenticatedUser, ModelSpec, get_current_user
from app.helpers.embedding_helper import get_dense_embedder, get_sparse_embedder
from app.helpers.rerank_helper import get_reranker
from tests.fakes import (
    InMemoryRedis,
    WordDenseEmbedder,
    WordReranker,
    WordSparseEmbedder,
    word_point,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.filterwarnings("ignore:Payload indexes have no effect"),
]

URL = "/api/v1/documents/search"
USER = AuthenticatedUser(id="user-a", username="a")
OTHER_USER = "user-b"
# Two dimensions, to match word_dense.
TINY = ModelSpec(name="test/tiny", dimensions=2, max_tokens=512)


@pytest.fixture
async def vectors() -> AsyncIterator[QdrantVectorStore]:
    client = AsyncQdrantClient(location=":memory:")
    store = QdrantVectorStore(client, "chunks")
    await store.ensure_collection(TINY)
    yield store
    await client.close()


@pytest.fixture
def search_app(
    app: FastAPI, db_session: AsyncSession, vectors: QdrantVectorStore
) -> FastAPI:
    """The app with a fixed user, the test session, in-memory Qdrant and fakes."""

    async def test_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = test_db
    app.dependency_overrides[get_current_user] = lambda: USER
    app.dependency_overrides[get_vector_store] = lambda: vectors
    app.dependency_overrides[get_dense_embedder] = WordDenseEmbedder
    app.dependency_overrides[get_sparse_embedder] = WordSparseEmbedder
    app.dependency_overrides[get_reranker] = WordReranker
    # One cache for the whole test, so repeat searches can hit it.
    cache = RedisCache(cast(Any, InMemoryRedis()))
    app.dependency_overrides[get_cache] = lambda: cache
    return app


async def add_document(
    session: AsyncSession,
    vectors: QdrantVectorStore,
    text: str,
    status: DocumentStatus = DocumentStatus.READY,
    user_uuid: str = USER.id,
) -> DocumentMaster:
    """A document row plus one indexed chunk, as ingestion leaves them."""
    document_uuid = uuid4()
    document = DocumentMaster(
        uuid=document_uuid,
        user_uuid=user_uuid,
        filename=f"{text[:10]}.txt",
        mime_type="text/plain",
        size_bytes=len(text),
        storage_key=f"documents/{user_uuid}/{document_uuid}/original.txt",
        status=status,
    )
    session.add(document)
    await session.flush()
    await vectors.upsert([word_point(user_uuid, document_uuid, 0, text)])
    return document


@pytest.mark.usefixtures("search_app")
async def test_returns_hits_without_internal_fields(
    client: AsyncClient, db_session: AsyncSession, vectors: QdrantVectorStore
) -> None:
    document = await add_document(db_session, vectors, "Staff get annual leave.")

    response = await client.get(URL, params={"query": "annual leave"})

    assert response.status_code == 200
    payload = response.json()["payload"]
    assert payload["type"] == "hybrid"
    assert payload["score_kind"] == "rerank"
    assert payload["hits"] == [
        {
            "document_uuid": str(document.uuid),
            "filename": f"{document.uuid}.txt",
            "page_start": None,
            "page_end": None,
            "chunk_type": "text",
            "text": "Staff get annual leave.",
            "score": pytest.approx(0.9),
        }
    ]


@pytest.mark.usefixtures("search_app")
@pytest.mark.parametrize("search_type", list(SearchType))
async def test_user_never_sees_another_users_chunks(
    client: AsyncClient,
    db_session: AsyncSession,
    vectors: QdrantVectorStore,
    search_type: SearchType,
) -> None:
    mine = await add_document(db_session, vectors, "annual leave rules")
    theirs = await add_document(
        db_session, vectors, "annual leave holiday", user_uuid=OTHER_USER
    )

    response = await client.get(
        URL,
        params={
            "query": "annual leave holiday",
            "type": search_type.value,
            # Asking for their document by ID must not help.
            "document_ids": [str(mine.uuid), str(theirs.uuid)],
        },
    )

    assert response.status_code == 200
    hits = response.json()["payload"]["hits"]
    assert [hit["document_uuid"] for hit in hits] == [str(mine.uuid)]


@pytest.mark.usefixtures("search_app")
@pytest.mark.parametrize(
    "status",
    [
        DocumentStatus.QUEUED,
        DocumentStatus.INDEXING,
        DocumentStatus.FAILED,
        DocumentStatus.DELETED,
    ],
)
async def test_only_ready_documents_are_searched(
    client: AsyncClient,
    db_session: AsyncSession,
    vectors: QdrantVectorStore,
    status: DocumentStatus,
) -> None:
    ready = await add_document(db_session, vectors, "annual leave")
    await add_document(db_session, vectors, "annual leave holiday", status=status)

    response = await client.get(URL, params={"query": "annual leave holiday"})

    hits = response.json()["payload"]["hits"]
    assert [hit["document_uuid"] for hit in hits] == [str(ready.uuid)]


@pytest.mark.usefixtures("search_app")
async def test_document_ids_narrow_the_search(
    client: AsyncClient, db_session: AsyncSession, vectors: QdrantVectorStore
) -> None:
    await add_document(db_session, vectors, "annual leave")
    pay = await add_document(db_session, vectors, "salary paid monthly")

    response = await client.get(
        URL, params={"query": "annual leave", "document_ids": [str(pay.uuid)]}
    )

    hits = response.json()["payload"]["hits"]
    assert {hit["document_uuid"] for hit in hits} <= {str(pay.uuid)}


@pytest.mark.usefixtures("search_app")
async def test_keyword_scores_are_bm25(
    client: AsyncClient, db_session: AsyncSession, vectors: QdrantVectorStore
) -> None:
    await add_document(db_session, vectors, "annual leave")

    response = await client.get(URL, params={"query": "leave", "type": "keyword"})

    assert response.json()["payload"]["score_kind"] == "bm25"


@pytest.mark.usefixtures("search_app")
async def test_no_documents_gives_no_hits(client: AsyncClient) -> None:
    response = await client.get(URL, params={"query": "annual leave"})

    assert response.status_code == 200
    assert response.json()["payload"]["hits"] == []


@pytest.mark.usefixtures("search_app")
@pytest.mark.parametrize(
    "params",
    [
        {},
        {"query": "   "},
        {"query": "x" * 1001},
        {"query": "leave", "type": "fuzzy"},
        {"query": "leave", "document_ids": "not-a-uuid"},
    ],
)
async def test_rejects_bad_parameters(
    client: AsyncClient, params: dict[str, str]
) -> None:
    response = await client.get(URL, params=params)

    assert response.status_code == 422


async def hit_ids(client: AsyncClient, query: str) -> list[str]:
    response = await client.get(URL, params={"query": query, "type": "keyword"})
    return [hit["document_uuid"] for hit in response.json()["payload"]["hits"]]


@pytest.mark.usefixtures("search_app")
async def test_cached_results_follow_status_changes(
    client: AsyncClient, db_session: AsyncSession, vectors: QdrantVectorStore
) -> None:
    documents = DocumentDBService(db_session)
    leave = await add_document(db_session, vectors, "annual leave")
    pay = await add_document(
        db_session, vectors, "salary paid", status=DocumentStatus.INDEXING
    )
    assert await hit_ids(client, "salary") == []

    # One leaves and one arrives: the count stays 1, only updated_at moves.
    await documents.update_document(leave.uuid, status=DocumentStatus.DELETED)
    await documents.update_document(pay.uuid, status=DocumentStatus.READY)

    assert await hit_ids(client, "salary") == [str(pay.uuid)]
