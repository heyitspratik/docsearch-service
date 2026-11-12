"""The embedders: real BM25 (a few small word lists), and a stand-in dense model."""

from collections.abc import Iterator, Sequence
from typing import Any, ClassVar

import numpy as np
import pytest

from app.helpers import embedding_helper
from app.helpers.embedding_helper import FastEmbedDense, FastEmbedSparse
from app.helpers.model_spec_helper import ModelSpec


@pytest.fixture(scope="module")
def bm25() -> FastEmbedSparse:
    return FastEmbedSparse("Qdrant/bm25", "english", cache_dir=None, batch_size=8)


def test_bm25_gives_the_same_word_the_same_id(bm25: FastEmbedSparse) -> None:
    first, second = bm25.embed_passages(["tantalum sheets", "tantalum fibers"])

    assert set(first.indices) & set(second.indices)


def test_bm25_stems_words_and_drops_stop_words(bm25: FastEmbedSparse) -> None:
    rolled, rolling, the = bm25.embed_passages(["rolled", "rolling", "the"])

    assert rolled.indices == rolling.indices
    assert the.indices == []


def test_bm25_returns_one_vector_per_text(bm25: FastEmbedSparse) -> None:
    vectors = bm25.embed_passages(["one", "two words", "three more words"])

    assert len(vectors) == 3
    assert all(len(v.indices) == len(v.values) for v in vectors)


class StubTextEmbedding:
    """Stands in for fastembed's TextEmbedding and records what it is given."""

    received: ClassVar[list[str]] = []

    def __init__(self, model_name: str, **_: Any) -> None:
        self.model_name = model_name

    def embed(self, documents: Sequence[str], batch_size: int) -> Iterator[Any]:
        StubTextEmbedding.received = list(documents)
        return iter(np.ones(3, dtype=np.float32) for _ in documents)


def test_dense_adds_the_passage_prefix_and_returns_lists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(embedding_helper, "TextEmbedding", StubTextEmbedding)
    spec = ModelSpec(
        name="test/model", dimensions=3, max_tokens=512, passage_prefix="passage: "
    )

    vectors = FastEmbedDense(spec, cache_dir=None, batch_size=4).embed_passages(
        ["Staff get twenty days."]
    )

    assert StubTextEmbedding.received == ["passage: Staff get twenty days."]
    assert vectors == [[1.0, 1.0, 1.0]]
