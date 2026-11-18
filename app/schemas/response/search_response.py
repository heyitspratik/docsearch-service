"""Response models for search."""

from pydantic import BaseModel

from app.constants import ScoreKind
from app.helpers.vector_store_helper import SearchHit


class SearchResponse(BaseModel):
    """The hits, best first, and what their scores mean."""

    score_kind: ScoreKind
    hits: list[SearchHit]
