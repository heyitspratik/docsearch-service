"""Request models for search."""

from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints

from app.constants import SEARCH_QUERY_MAX_LENGTH, SearchType


class SearchRequest(BaseModel):
    """Query parameters of ``GET /documents/search``."""

    query: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, min_length=1, max_length=SEARCH_QUERY_MAX_LENGTH
        ),
    ] = Field(description="The question or words to search for")
    type: SearchType = Field(
        default=SearchType.HYBRID,
        description="keyword (words), semantic (meaning) or hybrid (both)",
    )
    document_ids: list[UUID] | None = Field(
        default=None,
        description="Search only these of your documents; repeat the parameter",
    )
