"""SearchService against in-memory Qdrant, with word-based fake models."""

from collections.abc import Sequence
from uuid import UUID, uuid4

import pytest

from app.clients.qdrant.service import QdrantVectorStore
from app.constants import ChunkType, ScoreKind, SearchType
from app.helpers.embedding_helper import SparseVector
from app.helpers.vector_store_helper import ChunkPayload, ChunkPoint, point_id
from app.services.search_service import SearchService

pytestmark = pytest.mark.filterwarnings("ignore:Payload indexes have no effect")

# Each known word is one sparse index; its topic is one dense axis.
VOCAB = {"annual": 1, "leave": 2, "holiday": 3, "salary": 4, "paid": 5, "month": 6}
LEAVE_WORDS = {"annual", "leave", "holiday"}
PAY_WORDS = {"salary", "paid", "month"}


def words(text: str) -> set[str]:
    return {w.strip(".,?").lower() for w in text.split()}


class WordEmbedder:
    """Dense: [leave words, pay words]. Sparse: which vocabulary words appear."""

    def dense(self, text: str) -> list[float]:
        found = words(text)
        # A small base keeps the vector non-zero, as cosine needs.
        return [len(found & LEAVE_WORDS) + 0.1, len(found & PAY_WORDS) + 0.1]

    def sparse(self, text: str) -> SparseVector:
        indices = sorted(VOCAB[w] for w in words(text) if w in VOCAB)
        return SparseVector(indices=indices, values=[1.0] * len(indices))


class FakeDense(WordEmbedder):
    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        return [self.dense(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self.dense(text)


class FakeSparse(WordEmbedder):
    def embed_passages(self, texts: Sequence[str]) -> list[SparseVector]:
        return [self.sparse(t) for t in texts]

    def embed_query(self, text: str) -> SparseVector:
        return self.sparse(text)


class FakeReranker:
    """Scores the share of query words a text contains; ``favourite`` always wins."""

    def __init__(self, favourite: str | None = None) -> None:
        self.favourite = favourite
        self.calls: list[list[str]] = []

    def rerank(self, query: str, texts: Sequence[str]) -> list[float]:
        self.calls.append(list(texts))
        asked = words(query)
        return [
            1.0
            if self.favourite and self.favourite in text
            else len(asked & words(text)) / len(asked) * 0.9
            for text in texts
        ]


USER_A, USER_B = "user-a", "user-b"
LEAVE_DOC, PAY_DOC, OTHER_USER_DOC = uuid4(), uuid4(), uuid4()


def make_point(user: str, document: UUID, index: int, text: str) -> ChunkPoint:
    embedder = WordEmbedder()
    return ChunkPoint(
        id=point_id(document, index),
        dense=embedder.dense(text),
        sparse=embedder.sparse(text),
        payload=ChunkPayload(
            user_uuid=user,
            document_id=str(document),
            filename=f"{document}.txt",
            chunk_index=index,
            page_start=None,
            page_end=None,
            chunk_type=ChunkType.TEXT,
            text=text,
            embedding_model="test/tiny",
        ),
    )


@pytest.fixture
async def service(vectors: QdrantVectorStore) -> SearchService:
    await vectors.upsert(
        [
            make_point(USER_A, LEAVE_DOC, 0, "Staff get annual leave every year."),
            make_point(USER_A, PAY_DOC, 0, "The salary is paid each month."),
            make_point(USER_B, OTHER_USER_DOC, 0, "Annual leave and holiday rules."),
        ]
    )
    return SearchService(FakeDense(), FakeSparse(), FakeReranker(), vectors)


@pytest.mark.parametrize("search_type", list(SearchType))
async def test_best_match_comes_first(
    service: SearchService, search_type: SearchType
) -> None:
    hits = (await service.search(USER_A, "annual leave", search_type)).hits

    assert hits[0].payload.document_id == str(LEAVE_DOC)


@pytest.mark.parametrize("search_type", list(SearchType))
async def test_never_returns_another_users_chunks(
    service: SearchService, search_type: SearchType
) -> None:
    hits = (await service.search(USER_A, "annual leave holiday", search_type)).hits

    assert hits
    assert {hit.payload.user_uuid for hit in hits} == {USER_A}


async def test_keyword_finds_only_chunks_sharing_a_word(
    service: SearchService,
) -> None:
    hits = (await service.search(USER_A, "salary", SearchType.KEYWORD)).hits

    assert [hit.payload.document_id for hit in hits] == [str(PAY_DOC)]


@pytest.mark.parametrize("search_type", list(SearchType))
async def test_document_ids_narrow_the_search(
    service: SearchService, search_type: SearchType
) -> None:
    hits = (await service.search(USER_A, "annual leave", search_type, [PAY_DOC])).hits

    assert {hit.payload.document_id for hit in hits} <= {str(PAY_DOC)}


@pytest.mark.parametrize("search_type", list(SearchType))
async def test_document_ids_cannot_reach_another_users_document(
    service: SearchService, search_type: SearchType
) -> None:
    result = await service.search(USER_A, "annual leave", search_type, [OTHER_USER_DOC])

    assert result.hits == []


@pytest.mark.parametrize("search_type", list(SearchType))
async def test_keeps_at_most_top_k(
    vectors: QdrantVectorStore, search_type: SearchType
) -> None:
    document = uuid4()
    await vectors.upsert(
        [make_point(USER_A, document, i, f"annual leave rule {i}") for i in range(8)]
    )

    result = await SearchService(
        FakeDense(), FakeSparse(), FakeReranker(), vectors
    ).search(USER_A, "annual leave", search_type)

    assert len(result.hits) == 5


async def test_keyword_is_not_reranked(vectors: QdrantVectorStore) -> None:
    await vectors.upsert([make_point(USER_A, LEAVE_DOC, 0, "annual leave")])
    reranker = FakeReranker()

    result = await SearchService(FakeDense(), FakeSparse(), reranker, vectors).search(
        USER_A, "annual leave", SearchType.KEYWORD
    )

    assert result.score_kind is ScoreKind.BM25
    assert reranker.calls == []


@pytest.mark.parametrize("search_type", [SearchType.SEMANTIC, SearchType.HYBRID])
async def test_reranker_scores_replace_qdrant_scores(
    service: SearchService, search_type: SearchType
) -> None:
    result = await service.search(USER_A, "annual leave", search_type)

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
        [make_point(USER_A, document, i, f"annual leave rule {i}") for i in range(8)]
        # Qdrant ranks this last: it shares no word with the question.
        + [make_point(USER_A, PAY_DOC, 0, "The salary is paid each month.")]
    )
    reranker = FakeReranker(favourite="salary")

    result = await SearchService(FakeDense(), FakeSparse(), reranker, vectors).search(
        USER_A, "annual leave", search_type
    )

    assert result.hits[0].payload.document_id == str(PAY_DOC)
    assert len(reranker.calls[0]) == 9


@pytest.mark.parametrize("search_type", [SearchType.SEMANTIC, SearchType.HYBRID])
async def test_reranks_at_most_the_candidate_count(
    vectors: QdrantVectorStore, search_type: SearchType
) -> None:
    document = uuid4()
    await vectors.upsert(
        [make_point(USER_A, document, i, f"annual leave rule {i}") for i in range(25)]
    )
    reranker = FakeReranker()

    await SearchService(FakeDense(), FakeSparse(), reranker, vectors).search(
        USER_A, "annual leave", search_type
    )

    assert len(reranker.calls[0]) == 20


async def test_no_candidates_skips_the_reranker(vectors: QdrantVectorStore) -> None:
    reranker = FakeReranker()

    result = await SearchService(FakeDense(), FakeSparse(), reranker, vectors).search(
        USER_A, "annual leave", SearchType.HYBRID
    )

    assert result.hits == []
    assert reranker.calls == []
