"""Embedders: chunk text to dense vectors (meaning) and sparse vectors (keywords)."""

from collections.abc import Sequence
from functools import cache
from typing import Annotated, Protocol

from fastapi import Depends
from fastembed import SparseTextEmbedding, TextEmbedding
from pydantic import BaseModel, ConfigDict

from app.helpers.model_spec_helper import ModelSpec, get_model_spec
from app.settings import get_settings


class SparseVector(BaseModel):
    """BM25 weights for the words in one text, each word stored as a hashed ID."""

    model_config = ConfigDict(frozen=True)

    indices: list[int]
    values: list[float]


class DenseEmbedder(Protocol):
    """Turns passages into meaning vectors. fastembed in the app, a fake in tests."""

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        """One vector per text, in the same order."""
        ...

    def embed_query(self, text: str) -> list[float]:
        """One vector for a search question."""
        ...


class SparseEmbedder(Protocol):
    """Turns passages into keyword weights. fastembed in the app, a fake in tests."""

    def embed_passages(self, texts: Sequence[str]) -> list[SparseVector]:
        """One sparse vector per text, in the same order."""
        ...

    def embed_query(self, text: str) -> SparseVector:
        """Keyword weights for a search question."""
        ...


class FastEmbedDense:
    """A dense model from ``MODEL_SPECS``, run by fastembed on ONNX Runtime."""

    def __init__(self, spec: ModelSpec, cache_dir: str | None, batch_size: int) -> None:
        self.spec = spec
        self.batch_size = batch_size
        self._model = TextEmbedding(spec.name, cache_dir=cache_dir)

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        """One vector per text, with the spec's passage prefix added first."""
        # fastembed adds no prefix itself; the spec says which one the model expects.
        documents = [self.spec.passage_prefix + text for text in texts]
        vectors = self._model.embed(documents, batch_size=self.batch_size)
        return [vector.tolist() for vector in vectors]

    def embed_query(self, text: str) -> list[float]:
        """One vector for a question, with the spec's query prefix added first."""
        vector = next(
            iter(self._model.embed([self.spec.query_prefix + text], batch_size=1))
        )
        return list(vector.tolist())


class FastEmbedSparse:
    """BM25 run by fastembed: stems words, drops stop words and hashes the rest."""

    def __init__(
        self, model_name: str, language: str, cache_dir: str | None, batch_size: int
    ) -> None:
        self.batch_size = batch_size
        self._model = SparseTextEmbedding(
            model_name, cache_dir=cache_dir, language=language
        )

    def embed_passages(self, texts: Sequence[str]) -> list[SparseVector]:
        """One sparse vector per text, in the same order."""
        vectors = self._model.embed(list(texts), batch_size=self.batch_size)
        return [
            SparseVector(indices=vector.indices.tolist(), values=vector.values.tolist())
            for vector in vectors
        ]

    def embed_query(self, text: str) -> SparseVector:
        """Each query word weighs 1; Qdrant's IDF modifier adds the rarity."""
        vector = next(iter(self._model.query_embed(text)))
        return SparseVector(
            indices=vector.indices.tolist(), values=vector.values.tolist()
        )


@cache
def get_dense_embedder() -> DenseEmbedder:
    """One dense model per process; loading it takes a few seconds."""
    settings = get_settings()
    return FastEmbedDense(
        get_model_spec(settings.EMBEDDING_DENSE_MODEL),
        settings.EMBEDDING_CACHE_DIR,
        settings.EMBEDDING_BATCH_SIZE,
    )


@cache
def get_sparse_embedder() -> SparseEmbedder:
    """One BM25 model per process."""
    settings = get_settings()
    return FastEmbedSparse(
        settings.EMBEDDING_SPARSE_MODEL,
        settings.EMBEDDING_BM25_LANGUAGE,
        settings.EMBEDDING_CACHE_DIR,
        settings.EMBEDDING_BATCH_SIZE,
    )


# Sync dependencies run in a thread, so the first load does not block the API.
DenseEmbedderDep = Annotated[DenseEmbedder, Depends(get_dense_embedder)]
SparseEmbedderDep = Annotated[SparseEmbedder, Depends(get_sparse_embedder)]
