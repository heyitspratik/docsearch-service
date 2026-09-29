"""ORM models.

Import every model here. Alembic autogenerate only sees tables attached to
``BaseModel.metadata`` at import time, so a model missing from this file is
silently absent from generated migrations.

Example:
    from app.db.models.document import Document  # noqa: F401
"""

from app.db.models.base_model import BaseModel

__all__ = ["BaseModel"]
