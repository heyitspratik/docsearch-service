"""Reranker: reads the question and each chunk together and scores the match."""

import math
from collections.abc import Sequence
from functools import cache
from typing import Annotated, Protocol

from fastapi import Depends
from fastembed.rerank.cross_encoder import TextCrossEncoder

from app.settings import get_settings


class Reranker(Protocol):
    """Scores chunks against a question. fastembed in the app, a fake in tests."""

    def rerank(self, query: str, texts: Sequence[str]) -> list[float]:
        """One score from 0 to 1 per text, in the same order; higher is better."""
        ...


def sigmoid(logit: float) -> float:
    """Squeeze a raw model score into 0..1, so scores read the same for any query."""
    return 1 / (1 + math.exp(-logit))


class FastEmbedReranker:
    """A cross-encoder run by fastembed on ONNX Runtime."""

    def __init__(self, model_name: str, cache_dir: str | None) -> None:
        self._model = TextCrossEncoder(model_name, cache_dir=cache_dir)

    def rerank(self, query: str, texts: Sequence[str]) -> list[float]:
        """Sigmoid of the model's raw score for each (query, text) pair."""
        if not texts:
            return []
        logits = self._model.rerank(query, list(texts), batch_size=len(texts))
        return [sigmoid(logit) for logit in logits]


@cache
def get_reranker() -> Reranker:
    """One reranker per process; loading it takes a few seconds."""
    settings = get_settings()
    return FastEmbedReranker(settings.RERANKER_MODEL, settings.EMBEDDING_CACHE_DIR)


RerankerDep = Annotated[Reranker, Depends(get_reranker)]
