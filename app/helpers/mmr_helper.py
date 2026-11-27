"""MMR (maximal marginal relevance): pick candidates that are relevant and different."""

from collections.abc import Sequence

import numpy as np


def mmr_select(
    scores: Sequence[float],
    vectors: Sequence[Sequence[float]],
    k: int,
    *,
    lambda_: float,
    duplicate_similarity: float,
) -> list[int]:
    """Indexes of up to ``k`` candidates, in the order they were picked.

    Each pick maximises ``lambda_ * relevance - (1 - lambda_) * similarity`` to
    the closest already-picked candidate. Relevance is ``scores`` rescaled to
    0..1, so any score works (cosine, RRF); similarity is the vectors' cosine. A
    candidate at ``duplicate_similarity`` or above to a picked one is a copy and
    is never picked, so fewer than ``k`` can come back.
    """
    if not scores or k <= 0:
        return []
    relevance = _rescale(np.asarray(scores, dtype=np.float64))
    matrix = np.asarray(vectors, dtype=np.float64)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    unit = matrix / np.where(norms == 0, 1.0, norms)
    similarity = unit @ unit.T

    # The most relevant goes first; argmax keeps the earlier one on a tie.
    picked = [int(np.argmax(relevance))]
    closest = similarity[picked[0]].copy()
    while len(picked) < k:
        mmr = lambda_ * relevance - (1 - lambda_) * closest
        mmr[picked] = -np.inf
        mmr[closest >= duplicate_similarity] = -np.inf
        best = int(np.argmax(mmr))
        if mmr[best] == -np.inf:
            break
        picked.append(best)
        closest = np.maximum(closest, similarity[best])
    return picked


def _rescale(scores: np.ndarray) -> np.ndarray:
    """Scores to 0..1 (best = 1); all equal gives all 1."""
    low, high = float(scores.min()), float(scores.max())
    if high == low:
        return np.ones_like(scores)
    rescaled: np.ndarray = (scores - low) / (high - low)
    return rescaled
