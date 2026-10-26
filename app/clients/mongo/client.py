"""MongoDB client for chats and their messages."""

from typing import Any, Optional

from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from app.constants import MongoMessages
from app.log import get_logger
from app.settings import get_settings

logger = get_logger(__name__)

MongoDocument = dict[str, Any]


class MongoClient:
    """Singleton MongoDB client for managing the MongoDB connection pool.

    The client is created in :meth:`init_mongo` rather than at import time, so
    importing this module never opens a connection.
    """

    _instance: Optional["MongoClient"] = None
    _client: AsyncMongoClient[MongoDocument] | None = None
    _database: AsyncDatabase[MongoDocument] | None = None

    def __new__(cls) -> "MongoClient":
        """Create or return the singleton instance."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @property
    def client(self) -> AsyncMongoClient[MongoDocument]:
        """Get the MongoDB client instance."""
        if self._client is None:
            raise RuntimeError(MongoMessages.CLIENT_NOT_INITIALIZED)
        return self._client

    @property
    def database(self) -> AsyncDatabase[MongoDocument]:
        """Get the application database (``MONGO_DB``)."""
        if self._database is None:
            raise RuntimeError(MongoMessages.CLIENT_NOT_INITIALIZED)
        return self._database

    async def init_mongo(self) -> None:
        """Init the MongoDB connection pool and fail fast if the server is down."""
        settings = get_settings()
        self._client = AsyncMongoClient(
            settings.mongo_dsn,
            maxPoolSize=settings.MONGO_MAX_POOL_SIZE,
            serverSelectionTimeoutMS=settings.MONGO_TIMEOUT_MS,
            # Return datetimes as timezone-aware UTC, matching the rest of the app.
            tz_aware=True,
        )
        self._database = self._client[settings.MONGO_DB]
        try:
            await self._client.admin.command("ping")
        except Exception:
            # The lifespan only closes clients after a successful startup.
            await self.close()
            raise

    async def health_check(self) -> bool:
        """Report whether MongoDB is reachable. Never raises."""
        if self._client is None:
            return False
        try:
            await self._client.admin.command("ping")
            return True
        except Exception as e:
            logger.warning(f"MongoDB health check failed: {e!s}")
            return False

    async def close(self) -> None:
        """Close the MongoDB connection pool and cleanup resources."""
        if self._client is not None:
            await self._client.close()
        self._client = None
        self._database = None


# Create singleton instance
mongo_client = MongoClient()
