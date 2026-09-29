"""Database dependency for getting async database sessions."""

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.database.client import db_client


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for getting async database sessions.

    One transaction per request: the session commits on success and rolls back
    on any exception, so a handler should not commit itself.

    Yields:
        AsyncSession: A database session that will be automatically closed.
    """
    async for session in db_client.get_session():
        yield session


#: Annotate handler parameters with this instead of repeating ``Depends``.
DBSession = Annotated[AsyncSession, Depends(get_db)]
