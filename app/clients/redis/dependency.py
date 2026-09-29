"""Redis dependency for getting the shared client."""

from typing import TYPE_CHECKING, Annotated

from fastapi import Depends

from app.clients.redis.client import redis_client

if TYPE_CHECKING:
    from redis.asyncio import Redis


def get_redis() -> "Redis":
    """Dependency for getting the shared Redis client."""
    return redis_client.client


#: Annotate handler parameters with this instead of repeating ``Depends``.
RedisDep = Annotated["Redis", Depends(get_redis)]
