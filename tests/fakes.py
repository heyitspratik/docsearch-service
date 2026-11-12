"""Test stand-ins for the app's interfaces."""

from collections.abc import Sequence

from app.exceptions import NotFoundError
from app.helpers.embedding_helper import SparseVector


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


class FakeSparseEmbedder:
    """``SparseEmbedder`` that weighs every text the same."""

    def embed_passages(self, texts: Sequence[str]) -> list[SparseVector]:
        return [SparseVector(indices=[1], values=[1.0]) for _ in texts]
