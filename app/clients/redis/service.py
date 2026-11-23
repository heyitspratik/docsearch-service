"""A cache on Redis that never fails its caller."""

from typing import TYPE_CHECKING

from redis.exceptions import RedisError

from app.log import get_logger

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = get_logger(__name__)


class RedisCache:
    """Get and set strings in Redis. With no client every call is a quiet miss.

    Takes the client instead of using the ``redis_client`` singleton, so tests
    can pass a fake one.
    """

    def __init__(self, client: "Redis | None") -> None:
        self.client = client

    async def get(self, key: str) -> str | None:
        """The cached value, or None when missing or Redis is unreachable."""
        if self.client is None:
            return None
        try:
            value = await self.client.get(key)
        except RedisError as e:
            logger.warning(f"Cache read skipped: {e!s}")
            return None
        return value if isinstance(value, str) else None

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        """Store the value for ``ttl_seconds``; a Redis error is logged, not raised."""
        if self.client is None:
            return
        try:
            await self.client.set(key, value, ex=ttl_seconds)
        except RedisError as e:
            logger.warning(f"Cache write skipped: {e!s}")
