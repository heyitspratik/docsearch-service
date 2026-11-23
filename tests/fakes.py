"""Test stand-ins for the app's interfaces."""

from collections.abc import Sequence
from uuid import UUID

from redis.exceptions import ConnectionError as RedisConnectionError

from app.constants import ChunkType
from app.exceptions import NotFoundError
from app.helpers.embedding_helper import SparseVector
from app.helpers.vector_store_helper import ChunkPayload, ChunkPoint, point_id


class InMemoryStorage:
    """``ObjectStorage`` backed by a dict, so tests need no S3 server."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = (data, content_type)

    async def get(self, key: str) -> bytes:
        if key not in self.objects:
            raise NotFoundError(key)
        return self.objects[key][0]

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)


class FakeDenseEmbedder:
    """``DenseEmbedder`` that returns tiny vectors, so tests load no model."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [[float(len(text)), 1.0] for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return [float(len(text)), 1.0]


class FakeSparseEmbedder:
    """``SparseEmbedder`` that weighs every text the same."""

    def embed_passages(self, texts: Sequence[str]) -> list[SparseVector]:
        return [SparseVector(indices=[1], values=[1.0]) for _ in texts]

    def embed_query(self, text: str) -> SparseVector:
        return SparseVector(indices=[1], values=[1.0])


# --- Word-based search fakes: predictable rankings without real models ---

# Each known word is one sparse index; its topic is one dense axis.
VOCAB = {"annual": 1, "leave": 2, "holiday": 3, "salary": 4, "paid": 5, "month": 6}
LEAVE_WORDS = {"annual", "leave", "holiday"}
PAY_WORDS = {"salary", "paid", "month"}


def words(text: str) -> set[str]:
    return {w.strip(".,?").lower() for w in text.split()}


def word_dense(text: str) -> list[float]:
    """[leave words, pay words]; a small base keeps it non-zero, as cosine needs."""
    found = words(text)
    return [len(found & LEAVE_WORDS) + 0.1, len(found & PAY_WORDS) + 0.1]


def word_sparse(text: str) -> SparseVector:
    """Which vocabulary words appear, each weighing 1."""
    indices = sorted(VOCAB[w] for w in words(text) if w in VOCAB)
    return SparseVector(indices=indices, values=[1.0] * len(indices))


class WordDenseEmbedder:
    """``DenseEmbedder`` built on ``word_dense``; records each query it embeds."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        return [word_dense(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        return word_dense(text)


class WordSparseEmbedder:
    """``SparseEmbedder`` built on ``word_sparse``; records each query it embeds."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    def embed_passages(self, texts: Sequence[str]) -> list[SparseVector]:
        return [word_sparse(t) for t in texts]

    def embed_query(self, text: str) -> SparseVector:
        self.queries.append(text)
        return word_sparse(text)


class WordReranker:
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


def word_point(user: str, document: UUID, index: int, text: str) -> ChunkPoint:
    """A chunk point embedded with the word fakes."""
    return ChunkPoint(
        id=point_id(document, index),
        dense=word_dense(text),
        sparse=word_sparse(text),
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


# --- Redis stand-ins for the search cache ---


class InMemoryRedis:
    """The ``get``/``set`` part of ``redis.asyncio.Redis``; records each TTL."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, ex: int) -> None:
        self.values[key] = value
        self.ttls[key] = ex


class DownRedis:
    """A Redis that is unreachable: every call fails like a lost connection."""

    async def get(self, key: str) -> str | None:
        raise RedisConnectionError("Connection refused")

    async def set(self, key: str, value: str, ex: int) -> None:
        raise RedisConnectionError("Connection refused")
