"""What a re-index run reads and what it did, for the script to print."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ReadyDocument(BaseModel):
    """A ready document's columns that re-indexing needs, read fresh each time."""

    model_config = ConfigDict(frozen=True)

    id: int
    uuid: UUID
    user_uuid: str
    filename: str
    updated_at: datetime


class ReindexResult(BaseModel):
    """The collections involved and how much was indexed."""

    model: str
    old_collection: str | None
    new_collection: str
    documents: int
    chunks: int
    #: Documents that became ready while the run was going.
    caught_up: int
    #: Documents indexed but deleted or failed before the switch.
    removed: int
    old_collection_kept: bool
