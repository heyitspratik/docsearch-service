"""Search cache keys: what makes two searches share an entry, and what never does."""

from typing import Any
from uuid import uuid4

import pytest

from app.helpers.cache_helper import normalize_query, result_key, vector_key

DOC_1, DOC_2 = uuid4(), uuid4()


def key(**changes: Any) -> str:
    """A result key; ``changes`` replaces one part of the default."""
    parts: dict[str, Any] = {
        "pipeline": "bge|bm25|reranker|20|5",
        "user_uuid": "user-a",
        "search_type": "hybrid",
        "document_ids": None,
        "fingerprint": "2:2026-11-20T10:00:00+00:00",
        "normalized_query": "annual leave",
    }
    return result_key(**(parts | changes))


@pytest.mark.parametrize(
    "query", ["Annual Leave", "  annual   leave ", "ANNUAL\tleave\n"]
)
def test_normalize_query_ignores_case_and_spacing(query: str) -> None:
    assert normalize_query(query) == "annual leave"


def test_vector_key_depends_on_model_and_query_only() -> None:
    assert vector_key("dense", "bge", "annual leave") == vector_key(
        "dense", "bge", "annual leave"
    )
    assert vector_key("dense", "bge", "annual leave") != vector_key(
        "dense", "other-model", "annual leave"
    )
    assert vector_key("dense", "bge", "x") != vector_key("sparse", "bge", "x")


@pytest.mark.parametrize(
    "change",
    [
        {"user_uuid": "user-b"},
        {"search_type": "keyword"},
        {"document_ids": [DOC_1]},
        {"fingerprint": "3:2026-11-20T10:05:00+00:00"},
        {"normalized_query": "salary"},
        {"pipeline": "bge|bm25|reranker|10|5"},
    ],
)
def test_result_key_changes_with_each_part(change: dict[str, Any]) -> None:
    assert key(**change) != key()


def test_result_key_ignores_document_id_order() -> None:
    assert key(document_ids=[DOC_1, DOC_2]) == key(document_ids=[DOC_2, DOC_1])


def test_keys_never_contain_the_query_text() -> None:
    assert "annual" not in key()
    assert "annual" not in vector_key("dense", "bge", "annual leave")
