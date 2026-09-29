"""Common database service for shared operations."""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import DatabaseMessages
from app.exceptions import BadRequestError, NotFoundError
from app.log import get_logger

logger = get_logger(__name__)


class CommonDBService:
    """Service for common database operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_schema_ids(
        self, schema: Any, id: int | None = None, uuid: UUID | None = None
    ) -> tuple[int, UUID]:
        """Resolve a row's id and uuid from whichever one you have.

        Args:
            schema: SQLAlchemy model to query.
            id: Primary key, if known.
            uuid: Public uuid, if known.

        Returns:
            The row's ``(id, uuid)`` pair.

        Raises:
            BadRequestError: If neither ``id`` nor ``uuid`` was given.
            NotFoundError: If no row matches.
        """
        if not any([id, uuid]):
            raise BadRequestError(DatabaseMessages.ID_OR_UUID_REQUIRED)

        key, value = ("id", id) if id else ("uuid", uuid)
        query = select(schema.id, schema.uuid).where(getattr(schema, key) == value)

        result = await self.session.execute(query)
        data = result.fetchone()
        if not data:
            raise NotFoundError(f"No {schema.__tablename__} with {key} {value}")
        return data.id, data.uuid

    async def get_row_by_key(
        self,
        table: Any,
        key: str,
        value: Any,
        column_names: list[str],
        multi: bool = False,
    ) -> Any:
        """Fetch row(s) from any table on a single key-value condition.

        Args:
            table: SQLAlchemy model to query.
            key: Column name used in the WHERE condition.
            value: Value to match. A list when ``multi`` is true.
            column_names: Columns to return.
            multi: Fetch every match instead of the first.

        Returns:
            A dict for a single row, a list of dicts when ``multi`` is true,
            or ``None`` when nothing matches.
        """
        logger.info(
            f"Fetching from {table.__tablename__}, {key}={value}, "
            f"columns={column_names}"
        )

        columns = [getattr(table, column) for column in column_names]

        if multi:
            if not isinstance(value, list | tuple | set):
                value = [value]
            result = await self.session.execute(
                select(*columns).where(getattr(table, key).in_(value))
            )
            return [dict(row._mapping) for row in result.fetchall()]

        result = await self.session.execute(
            select(*columns).where(getattr(table, key) == value)
        )
        row = result.fetchone()
        return dict(row._mapping) if row else None
