"""Redis dependencies: the shared client, and the cache built on it."""

from typing import TYPE_CHECKING, Annotated

from fastapi import Depends

from app.clients.redis.client import redis_client
from app.clients.redis.service import RedisCache
from app.settings import get_settings

if TYPE_CHECKING:
    from redis.asyncio import Redis


async def get_redis() -> "Redis":
    """Dependency for getting the shared Redis client."""
    return redis_client.client


#: Annotate handler parameters with this instead of repeating ``Depends``.
RedisDep = Annotated["Redis", Depends(get_redis)]


async def get_cache() -> RedisCache:
    """The cache on the shared client, or a no-op one when it is switched off."""
    settings = get_settings()
    if not (settings.CACHE_ENABLED and settings.REDIS_ENABLED):
        return RedisCache(None)
    return RedisCache(redis_client.client)


CacheDep = Annotated[RedisCache, Depends(get_cache)]
