"""Collection names and point IDs."""

from uuid import UUID

from app.helpers.vector_store_helper import collection_name, point_id

DOCUMENT = UUID("8603a4ed-e548-408d-8ac3-402b860a62bc")


def test_collection_is_named_after_the_model() -> None:
    assert collection_name("chunks", "BAAI/bge-base-en-v1.5") == (
        "chunks__bge-base-en-v1.5"
    )


def test_point_id_is_stable() -> None:
    assert point_id(DOCUMENT, 3) == point_id(DOCUMENT, 3)
    UUID(point_id(DOCUMENT, 3))


def test_point_id_differs_per_chunk_and_document() -> None:
    other = UUID("00000000-0000-0000-0000-000000000001")

    assert point_id(DOCUMENT, 0) != point_id(DOCUMENT, 1)
    assert point_id(DOCUMENT, 0) != point_id(other, 0)
