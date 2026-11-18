"""The reranker wrapper, with a stand-in cross-encoder so no model is downloaded."""

from collections.abc import Iterable, Iterator
from typing import Any, ClassVar

import pytest

from app.helpers import rerank_helper
from app.helpers.rerank_helper import FastEmbedReranker, sigmoid


def test_sigmoid_maps_logits_into_zero_to_one() -> None:
    assert sigmoid(0.0) == 0.5
    assert sigmoid(8.0) > 0.99
    assert sigmoid(-8.0) < 0.01


class StubCrossEncoder:
    """Stands in for fastembed's TextCrossEncoder and records what it is given."""

    received: ClassVar[list[tuple[str, list[str]]]] = []

    def __init__(self, model_name: str, **_: Any) -> None:
        self.model_name = model_name

    def rerank(
        self, query: str, documents: Iterable[str], batch_size: int
    ) -> Iterator[float]:
        texts = list(documents)
        StubCrossEncoder.received.append((query, texts))
        # Raw logits, as the real model returns: any size, any sign.
        return iter([4.0, -4.0, 0.0][: len(texts)])


@pytest.fixture
def reranker(monkeypatch: pytest.MonkeyPatch) -> FastEmbedReranker:
    StubCrossEncoder.received = []
    monkeypatch.setattr(rerank_helper, "TextCrossEncoder", StubCrossEncoder)
    return FastEmbedReranker("test/reranker", cache_dir=None)


def test_returns_sigmoid_scores_in_input_order(reranker: FastEmbedReranker) -> None:
    scores = reranker.rerank("How many days?", ["twenty days", "salary", "leave"])

    assert scores == [sigmoid(4.0), sigmoid(-4.0), 0.5]
    assert StubCrossEncoder.received == [
        ("How many days?", ["twenty days", "salary", "leave"])
    ]


def test_no_texts_skips_the_model(reranker: FastEmbedReranker) -> None:
    assert reranker.rerank("How many days?", []) == []
    assert StubCrossEncoder.received == []
