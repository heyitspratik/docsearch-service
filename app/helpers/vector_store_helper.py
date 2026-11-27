"""Vector store: collection names, point IDs and the records indexed."""

from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict

from app.constants import ChunkType
from app.helpers.embedding_helper import SparseVector


def collection_name(alias: str, model_name: str) -> str:
    """Versioned collection for a model, e.g. ``chunks__bge-base-en-v1.5``.

    One collection per model, so a new model is indexed next to the old one
    and the alias is switched over once it is complete.
    """
    return f"{alias}__{model_name.rsplit('/', 1)[-1]}"


def point_id(document_uuid: UUID, chunk_index: int) -> str:
    """Same document and index give the same ID, so re-indexing overwrites."""
    return str(uuid5(document_uuid, str(chunk_index)))


class ChunkPayload(BaseModel):
    """What Qdrant stores next to a chunk's vectors, returned with each hit."""

    model_config = ConfigDict(frozen=True)

    user_uuid: str
    document_id: str
    filename: str
    chunk_index: int
    page_start: int | None
    page_end: int | None
    chunk_type: ChunkType
    text: str
    embedding_model: str


class ChunkPoint(BaseModel):
    """One chunk as Qdrant holds it: an ID, both vectors and the payload."""

    model_config = ConfigDict(frozen=True)

    id: str
    dense: list[float]
    sparse: SparseVector
    payload: ChunkPayload


class SearchHit(BaseModel):
    """One chunk a search found, with its score from that search."""

    model_config = ConfigDict(frozen=True)

    id: str
    score: float
    payload: ChunkPayload
    # The chunk's meaning vector, when the search asked for it (MMR needs it).
    dense: list[float] | None = None
