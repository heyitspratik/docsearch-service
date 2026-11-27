"""mmr_select: relevant and different candidates, copies never picked."""

from app.helpers.mmr_helper import mmr_select

# Unit-length 2-D vectors: cos(A, A_COPY) ≈ 0.99, cos(A, B) ≈ 0.71, cos(A, C) = 0.
A = [1.0, 0.0]
A_COPY = [0.99, 0.14]
B = [0.71, 0.71]
C = [0.0, 1.0]


def select(
    scores: list[float],
    vectors: list[list[float]],
    k: int,
    lambda_: float = 0.7,
    duplicate_similarity: float = 0.88,
) -> list[int]:
    return mmr_select(
        scores,
        vectors,
        k,
        lambda_=lambda_,
        duplicate_similarity=duplicate_similarity,
    )


def test_no_candidates_gives_nothing() -> None:
    assert select([], [], 5) == []


def test_most_relevant_is_picked_first() -> None:
    assert select([0.2, 0.9, 0.5], [A, B, C], 1) == [1]


def test_a_copy_is_never_picked_even_when_highly_relevant() -> None:
    picked = select([0.90, 0.89, 0.30], [A, A_COPY, C], 3)

    assert picked == [0, 2]


def test_variety_can_beat_a_slightly_more_relevant_similar_chunk() -> None:
    # B is a bit more relevant than C but much closer to the first pick A.
    assert select([1.0, 0.8, 0.7], [A, B, C], 2, lambda_=0.5) == [0, 2]


def test_lambda_one_is_plain_relevance_order() -> None:
    assert select([0.5, 0.9, 0.7], [A, B, C], 3, lambda_=1.0) == [1, 2, 0]


def test_stops_at_k() -> None:
    assert len(select([0.9, 0.8, 0.7], [A, B, C], 2)) == 2


def test_score_scale_does_not_matter() -> None:
    cosine = select([0.90, 0.80, 0.70], [A, B, C], 3)
    rrf = select([0.0300, 0.0290, 0.0280], [A, B, C], 3)

    assert cosine == rrf


def test_equal_scores_keep_qdrant_order_first() -> None:
    assert select([0.5, 0.5, 0.5], [A, B, C], 1) == [0]


def test_a_zero_vector_does_not_break_it() -> None:
    assert select([0.9, 0.5], [A, [0.0, 0.0]], 2) == [0, 1]
