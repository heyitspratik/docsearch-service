"""Response models for search."""

from uuid import UUID

from pydantic import BaseModel, Field

from app.constants import ChunkType, ScoreKind, SearchType


class SearchHitResponse(BaseModel):
    """One chunk found, with where it came from."""

    document_uuid: UUID
    filename: str
    page_start: int | None = Field(description="None for TXT and DOCX")
    page_end: int | None
    chunk_type: ChunkType
    text: str
    score: float


class SearchResponse(BaseModel):
    """The hits, best first, and what their scores mean."""

    type: SearchType
    score_kind: ScoreKind = Field(
        description="bm25: unbounded, compare within one search only; rerank: 0 to 1"
    )
    hits: list[SearchHitResponse]
