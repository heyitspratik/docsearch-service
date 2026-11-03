"""ORM models.

Import every model here. Alembic autogenerate only sees tables attached to
``BaseModel.metadata`` at import time, so a model missing from this file is
silently absent from generated migrations.
"""

from app.db.models.base_model import BaseModel
from app.db.models.document import DocumentMaster
from app.db.models.document_chunk import DocumentChunk

__all__ = ["BaseModel", "DocumentChunk", "DocumentMaster"]
