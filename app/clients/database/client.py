"""Database client for managing async database connections."""

from collections.abc import AsyncGenerator
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.constants import DatabaseMessages
from app.log import get_logger
from app.settings import get_settings

logger = get_logger(__name__)


class DatabaseClient:
    """Singleton database client for managing database connections.

    The engine is created in :meth:`init_db` rather than at import time, so
    importing this module never opens a connection.
    """

    _instance: Optional["DatabaseClient"] = None
    _engine: AsyncEngine | None = None
    _session_factory: async_sessionmaker[AsyncSession] | None = None

    def __new__(cls) -> "DatabaseClient":
        """Create or return the singleton instance."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @property
    def engine(self) -> AsyncEngine:
        """Get the database engine instance."""
        if self._engine is None:
            raise RuntimeError(DatabaseMessages.ENGINE_NOT_INITIALIZED)
        return self._engine

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        """Get the session factory instance."""
        if self._session_factory is None:
            raise RuntimeError(DatabaseMessages.SESSION_FACTORY_NOT_INITIALIZED)
        return self._session_factory

    async def init_db(self) -> None:
        """Init the database connection."""
        settings = get_settings()
        kwargs: dict[str, Any] = {
            "echo": settings.DB_ECHO,
            "pool_pre_ping": settings.DB_POOL_PRE_PING,
            "future": True,
        }
        # SQLite's async driver uses a non-queue pool that rejects these.
        if "sqlite" not in settings.DB_DRIVER:
            kwargs["pool_size"] = settings.DB_POOL_SIZE
            kwargs["max_overflow"] = settings.DB_MAX_OVERFLOW

        try:
            self._engine = create_async_engine(settings.db_dsn, **kwargs)
            self._session_factory = async_sessionmaker(
                self._engine,
                class_=AsyncSession,
                expire_on_commit=False,
                autoflush=False,
            )
            async with self.session_factory() as session:
                await session.execute(text("SELECT 1"))
        except Exception as e:
            logger.error(f"Failed to get db connection status: {e!s}")
            raise e

    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """Get a database session.

        Yields:
            AsyncSession: A session that commits on success, rolls back on
            error, and is always closed.
        """
        async with self.session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception as e:
                logger.error(f"Error committing session: {e!s}")
                await session.rollback()
                raise e
            finally:
                await session.close()

    async def health_check(self) -> bool:
        """Report whether the database is reachable. Never raises."""
        if self._engine is None:
            return False
        try:
            async with self.session_factory() as session:
                await session.execute(text("SELECT 1"))
        except Exception as e:
            logger.warning(f"Database health check failed: {e!s}")
            return False
        return True

    async def close(self) -> None:
        """Close the database engine and cleanup resources."""
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None


# Create singleton instance
db_client = DatabaseClient()
