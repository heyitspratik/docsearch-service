"""Redis client for caching and shared state."""

from typing import TYPE_CHECKING, Optional

from app.constants import RedisMessages
from app.log import get_logger
from app.settings import get_settings

if TYPE_CHECKING:
    from redis.asyncio import ConnectionPool, Redis

logger = get_logger(__name__)


class RedisClient:
    """Singleton Redis client for managing Redis connections.

    The pool is created in :meth:`init_redis` rather than at import time, so
    importing this module never opens a connection.
    """

    _instance: Optional["RedisClient"] = None
    _pool: Optional["ConnectionPool"] = None
    _client: Optional["Redis"] = None

    def __new__(cls) -> "RedisClient":
        """Create or return the singleton instance."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @property
    def client(self) -> "Redis":
        """Get the Redis client instance."""
        if self._client is None:
            raise RuntimeError(RedisMessages.CLIENT_NOT_INITIALIZED)
        return self._client

    async def init_redis(self) -> None:
        """Init redis connections."""
        try:
            from redis.asyncio import ConnectionPool, Redis
        except ImportError as e:  # pragma: no cover - depends on install extras
            raise RuntimeError(RedisMessages.EXTRA_REQUIRED) from e

        settings = get_settings()
        self._pool = ConnectionPool.from_url(
            settings.redis_dsn,
            max_connections=settings.REDIS_MAX_CONNECTIONS,
            socket_timeout=settings.REDIS_SOCKET_TIMEOUT,
            decode_responses=True,
        )
        self._client = Redis(connection_pool=self._pool)
        await self._client.ping()

    async def health_check(self) -> bool:
        """Report whether Redis is reachable. Never raises."""
        if self._client is None:
            return False
        try:
            return bool(await self._client.ping())
        except Exception as e:
            logger.warning(f"Redis health check failed: {e!s}")
            return False

    async def close(self) -> None:
        """Close the Redis connection pool and cleanup resources."""
        if self._client is not None:
            await self._client.aclose()
        if self._pool is not None:
            await self._pool.disconnect()
        self._client = None
        self._pool = None


# Create singleton instance
redis_client = RedisClient()
