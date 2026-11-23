"""SearchService against in-memory Qdrant, with word-based fake models.

The ``ready`` lookup is faked here; ``tests/api/test_search.py`` runs it on Postgres.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.qdrant.service import QdrantVectorStore
from app.clients.redis.service import RedisCache
from app.constants import ScoreKind, SearchType
from app.helpers import AuthenticatedUser
from app.schemas.request import SearchRequest
from app.services.search_service import SearchService
from tests.fakes import (
    DownRedis,
    InMemoryRedis,
    WordDenseEmbedder,
    WordReranker,
    WordSparseEmbedder,
)
from tests.fakes import word_point as point

pytestmark = pytest.mark.filterwarnings("ignore:Payload indexes have no effect")

USER_A = AuthenticatedUser(id="user-a", username="a")
USER_B = AuthenticatedUser(id="user-b", username="b")
LEAVE_DOC, PAY_DOC, OTHER_USER_DOC = uuid4(), uuid4(), uuid4()
UPDATED_AT = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)


def make_service(
    vectors: QdrantVectorStore,
    ready: dict[str, list[UUID]],
    reranker: WordReranker | None = None,
    cache: RedisCache | None = None,
    dense: WordDenseEmbedder | None = None,
    sparse: WordSparseEmbedder | None = None,
) -> SearchService:
    """A service whose ``ready`` lookup answers from ``ready``, as Postgres would.

    ``ready`` is read on every search, so a test can change it between searches.
    """
    # No session is needed: the only query it makes is replaced below.
    service = SearchService(
        cast(AsyncSession, None),
        dense or WordDenseEmbedder(),
        sparse or WordSparseEmbedder(),
        reranker or WordReranker(),
        vectors,
        cache or RedisCache(None),
    )

    async def list_ready(
        user_uuid: str, document_uuids: Sequence[UUID] | None = None
    ) -> list[tuple[UUID, datetime]]:
        owned = ready.get(user_uuid, [])
        return [
            (d, UPDATED_AT) for d in owned if not document_uuids or d in document_uuids
        ]

    service.document_db.list_ready = list_ready  # type: ignore[method-assign]
    return service


def request(
    query: str,
    search_type: SearchType,
    document_ids: list[UUID] | None = None,
) -> SearchRequest:
    return SearchRequest(query=query, type=search_type, document_ids=document_ids)


@pytest.fixture
async def service(vectors: QdrantVectorStore) -> SearchService:
    await vectors.upsert(
        [
            point(USER_A.id, LEAVE_DOC, 0, "Staff get annual leave every year."),
            point(USER_A.id, PAY_DOC, 0, "The salary is paid each month."),
            point(USER_B.id, OTHER_USER_DOC, 0, "Annual leave and holiday rules."),
        ]
    )
    return make_service(
        vectors, {USER_A.id: [LEAVE_DOC, PAY_DOC], USER_B.id: [OTHER_USER_DOC]}
    )


@pytest.mark.parametrize("search_type", list(SearchType))
async def test_best_match_comes_first(
    service: SearchService, search_type: SearchType
) -> None:
    result = await service.search(USER_A, request("annual leave", search_type))

    assert result.type is search_type
    assert result.hits[0].document_uuid == LEAVE_DOC


@pytest.mark.parametrize("search_type", list(SearchType))
async def test_never_returns_another_users_chunks(
    service: SearchService, search_type: SearchType
) -> None:
    result = await service.search(USER_A, request("annual leave holiday", search_type))

    assert result.hits
    assert {hit.document_uuid for hit in result.hits} <= {LEAVE_DOC, PAY_DOC}


@pytest.mark.parametrize("search_type", list(SearchType))
async def test_qdrant_filter_blocks_another_user_even_if_lookup_is_wrong(
    vectors: QdrantVectorStore, search_type: SearchType
) -> None:
    await vectors.upsert([point(USER_B.id, OTHER_USER_DOC, 0, "annual leave")])
    # A broken lookup that hands user A someone else's document.
    service = make_service(vectors, {USER_A.id: [OTHER_USER_DOC]})

    result = await service.search(USER_A, request("annual leave", search_type))

    assert result.hits == []


@pytest.mark.parametrize("search_type", list(SearchType))
async def test_skips_documents_that_are_not_ready(
    vectors: QdrantVectorStore, search_type: SearchType
) -> None:
    not_ready = uuid4()
    await vectors.upsert(
        [
            point(USER_A.id, LEAVE_DOC, 0, "annual leave"),
            # Points left by a document that is still indexing or was deleted.
            point(USER_A.id, not_ready, 0, "annual leave holiday"),
        ]
    )
    service = make_service(vectors, {USER_A.id: [LEAVE_DOC]})

    result = await service.search(USER_A, request("annual leave", search_type))

    assert [hit.document_uuid for hit in result.hits] == [LEAVE_DOC]


async def test_no_ready_documents_skips_the_search(
    vectors: QdrantVectorStore,
) -> None:
    reranker = WordReranker()
    service = make_service(vectors, {}, reranker)

    result = await service.search(USER_A, request("annual leave", SearchType.HYBRID))

    assert result.hits == []
    assert result.score_kind is ScoreKind.RERANK
    assert reranker.calls == []


async def test_keyword_finds_only_chunks_sharing_a_word(
    service: SearchService,
) -> None:
    result = await service.search(USER_A, request("salary", SearchType.KEYWORD))

    assert [hit.document_uuid for hit in result.hits] == [PAY_DOC]


@pytest.mark.parametrize("search_type", list(SearchType))
async def test_document_ids_narrow_the_search(
    service: SearchService, search_type: SearchType
) -> None:
    result = await service.search(
        USER_A, request("annual leave", search_type, [PAY_DOC])
    )

    assert {hit.document_uuid for hit in result.hits} <= {PAY_DOC}


@pytest.mark.parametrize("search_type", list(SearchType))
async def test_document_ids_cannot_reach_another_users_document(
    service: SearchService, search_type: SearchType
) -> None:
    result = await service.search(
        USER_A, request("annual leave", search_type, [OTHER_USER_DOC])
    )

    assert result.hits == []


@pytest.mark.parametrize("search_type", list(SearchType))
async def test_keeps_at_most_top_k(
    vectors: QdrantVectorStore, search_type: SearchType
) -> None:
    document = uuid4()
    await vectors.upsert(
        [point(USER_A.id, document, i, f"annual leave rule {i}") for i in range(8)]
    )
    service = make_service(vectors, {USER_A.id: [document]})

    result = await service.search(USER_A, request("annual leave", search_type))

    assert len(result.hits) == 5


async def test_keyword_is_not_reranked(vectors: QdrantVectorStore) -> None:
    await vectors.upsert([point(USER_A.id, LEAVE_DOC, 0, "annual leave")])
    reranker = WordReranker()
    service = make_service(vectors, {USER_A.id: [LEAVE_DOC]}, reranker)

    result = await service.search(USER_A, request("annual leave", SearchType.KEYWORD))

    assert result.score_kind is ScoreKind.BM25
    assert reranker.calls == []


@pytest.mark.parametrize("search_type", [SearchType.SEMANTIC, SearchType.HYBRID])
async def test_reranker_scores_replace_qdrant_scores(
    service: SearchService, search_type: SearchType
) -> None:
    result = await service.search(USER_A, request("annual leave", search_type))

    assert result.score_kind is ScoreKind.RERANK
    scores = [hit.score for hit in result.hits]
    assert scores == sorted(scores, reverse=True)
    assert all(0 <= score <= 1 for score in scores)


@pytest.mark.parametrize("search_type", [SearchType.SEMANTIC, SearchType.HYBRID])
async def test_reranker_can_promote_a_low_candidate(
    vectors: QdrantVectorStore, search_type: SearchType
) -> None:
    document = uuid4()
    await vectors.upsert(
        [point(USER_A.id, document, i, f"annual leave rule {i}") for i in range(8)]
        # Qdrant ranks this last: it shares no word with the question.
        + [point(USER_A.id, PAY_DOC, 0, "The salary is paid each month.")]
    )
    reranker = WordReranker(favourite="salary")
    service = make_service(vectors, {USER_A.id: [document, PAY_DOC]}, reranker)

    result = await service.search(USER_A, request("annual leave", search_type))

    assert result.hits[0].document_uuid == PAY_DOC
    assert len(reranker.calls[0]) == 9


@pytest.mark.parametrize("search_type", [SearchType.SEMANTIC, SearchType.HYBRID])
async def test_reranks_at_most_the_candidate_count(
    vectors: QdrantVectorStore, search_type: SearchType
) -> None:
    document = uuid4()
    await vectors.upsert(
        [point(USER_A.id, document, i, f"annual leave rule {i}") for i in range(25)]
    )
    reranker = WordReranker()
    service = make_service(vectors, {USER_A.id: [document]}, reranker)

    await service.search(USER_A, request("annual leave", search_type))

    assert len(reranker.calls[0]) == 20


# --- Caching ---


@pytest.fixture
def redis() -> InMemoryRedis:
    return InMemoryRedis()


@pytest.fixture
async def indexed(vectors: QdrantVectorStore) -> QdrantVectorStore:
    await vectors.upsert(
        [
            point(USER_A.id, LEAVE_DOC, 0, "Staff get annual leave every year."),
            point(USER_A.id, PAY_DOC, 0, "The salary is paid each month."),
            point(USER_B.id, OTHER_USER_DOC, 0, "Annual leave and holiday rules."),
        ]
    )
    return vectors


@pytest.mark.parametrize("search_type", list(SearchType))
async def test_repeat_search_is_served_from_the_cache(
    indexed: QdrantVectorStore, redis: InMemoryRedis, search_type: SearchType
) -> None:
    dense, sparse, reranker = WordDenseEmbedder(), WordSparseEmbedder(), WordReranker()
    service = make_service(
        indexed,
        {USER_A.id: [LEAVE_DOC, PAY_DOC]},
        reranker,
        RedisCache(cast(Any, redis)),
        dense,
        sparse,
    )

    first = await service.search(USER_A, request("Annual leave", search_type))
    second = await service.search(USER_A, request("  annual   LEAVE ", search_type))

    assert second == first
    # The second search used no model at all.
    assert len(dense.queries) + len(sparse.queries) <= 2
    assert len(reranker.calls) <= 1


async def test_ttls_follow_the_settings(
    indexed: QdrantVectorStore, redis: InMemoryRedis
) -> None:
    service = make_service(
        indexed, {USER_A.id: [LEAVE_DOC]}, cache=RedisCache(cast(Any, redis))
    )

    await service.search(USER_A, request("annual leave", SearchType.HYBRID))

    ttls = {key.split(":")[2]: ttl for key, ttl in redis.ttls.items()}
    assert ttls == {"vec": 7 * 24 * 3600, "res": 3600}


async def test_a_document_becoming_ready_makes_old_results_miss(
    indexed: QdrantVectorStore, redis: InMemoryRedis
) -> None:
    ready = {USER_A.id: [LEAVE_DOC]}
    service = make_service(indexed, ready, cache=RedisCache(cast(Any, redis)))

    before = await service.search(USER_A, request("salary", SearchType.KEYWORD))
    ready[USER_A.id].append(PAY_DOC)
    after = await service.search(USER_A, request("salary", SearchType.KEYWORD))

    assert before.hits == []
    assert [hit.document_uuid for hit in after.hits] == [PAY_DOC]


async def test_a_deleted_document_makes_old_results_miss(
    indexed: QdrantVectorStore, redis: InMemoryRedis
) -> None:
    ready = {USER_A.id: [LEAVE_DOC, PAY_DOC]}
    service = make_service(indexed, ready, cache=RedisCache(cast(Any, redis)))

    before = await service.search(USER_A, request("salary", SearchType.KEYWORD))
    ready[USER_A.id].remove(PAY_DOC)
    after = await service.search(USER_A, request("salary", SearchType.KEYWORD))

    assert [hit.document_uuid for hit in before.hits] == [PAY_DOC]
    assert after.hits == []


async def test_results_are_never_shared_between_users(
    indexed: QdrantVectorStore, redis: InMemoryRedis
) -> None:
    service = make_service(
        indexed,
        {USER_A.id: [LEAVE_DOC, PAY_DOC], USER_B.id: [OTHER_USER_DOC]},
        cache=RedisCache(cast(Any, redis)),
    )

    mine = await service.search(USER_A, request("annual leave", SearchType.HYBRID))
    theirs = await service.search(USER_B, request("annual leave", SearchType.HYBRID))

    assert {hit.document_uuid for hit in mine.hits} <= {LEAVE_DOC, PAY_DOC}
    assert [hit.document_uuid for hit in theirs.hits] == [OTHER_USER_DOC]


async def test_query_vectors_are_shared_between_users(
    indexed: QdrantVectorStore, redis: InMemoryRedis
) -> None:
    dense = WordDenseEmbedder()
    service = make_service(
        indexed,
        {USER_A.id: [LEAVE_DOC], USER_B.id: [OTHER_USER_DOC]},
        cache=RedisCache(cast(Any, redis)),
        dense=dense,
    )

    await service.search(USER_A, request("annual leave", SearchType.SEMANTIC))
    await service.search(USER_B, request("Annual Leave", SearchType.SEMANTIC))

    assert dense.queries == ["annual leave"]


async def test_reranker_gets_the_query_as_typed(indexed: QdrantVectorStore) -> None:
    reranker = WordReranker()
    dense = WordDenseEmbedder()
    service = make_service(indexed, {USER_A.id: [LEAVE_DOC]}, reranker, dense=dense)

    await service.search(USER_A, request("  Annual  Leave ", SearchType.SEMANTIC))

    # Embedders lowercase anyway; the cross-encoder is case-sensitive.
    assert dense.queries == ["annual leave"]
    assert reranker.calls


@pytest.mark.parametrize("search_type", list(SearchType))
async def test_search_works_when_redis_is_down(
    indexed: QdrantVectorStore, search_type: SearchType
) -> None:
    service = make_service(
        indexed, {USER_A.id: [LEAVE_DOC]}, cache=RedisCache(cast(Any, DownRedis()))
    )

    result = await service.search(USER_A, request("annual leave", search_type))

    assert [hit.document_uuid for hit in result.hits] == [LEAVE_DOC]
