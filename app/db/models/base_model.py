"""Base model for all database models using SQLAlchemy ORM."""

import uuid as uuid_module
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, Integer, MetaData, Uuid, func, inspect
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

# Explicit names so Alembic can generate reversible constraint drops.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class BaseModel(DeclarativeBase):
    """Base class for all models."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    @declared_attr.directive
    def __tablename__(cls) -> str:  # noqa: N805
        """Default the table name to the lowercased class name."""
        return cls.__name__.lower()

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    # Exposed externally instead of `id`, so ids can be minted before insert
    # and row counts are not leaked in URLs.
    uuid: Mapped[uuid_module.UUID] = mapped_column(
        Uuid(as_uuid=True),
        default=uuid_module.uuid4,
        unique=True,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    def to_dict(self, with_id: bool = True, **kwargs: Any) -> dict[str, Any]:
        """Convert model instance to dictionary."""
        result: dict[str, Any] = {}
        for column in inspect(self.__class__).columns:
            if not with_id and column.name == "id":
                continue
            result[column.name] = getattr(self, column.name)
        return result

    def update(self, **kwargs: Any) -> None:
        """Update model instance with given attributes."""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)

    def __repr__(self) -> str:
        """Identify the model and its primary key."""
        return f"<{type(self).__name__} id={getattr(self, 'id', None)!r}>"
