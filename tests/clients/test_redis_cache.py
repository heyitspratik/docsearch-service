"""RedisCache with fake clients: a working Redis, none at all, and one that is down."""

from typing import Any, cast

import pytest

from app.clients.redis import dependency
from app.clients.redis.dependency import get_cache
from app.clients.redis.service import RedisCache
from app.settings import get_settings
from tests.fakes import DownRedis, InMemoryRedis


async def test_set_then_get_with_ttl() -> None:
    redis = InMemoryRedis()
    cache = RedisCache(cast(Any, redis))

    await cache.set("k", "v", ttl_seconds=60)

    assert await cache.get("k") == "v"
    assert redis.ttls == {"k": 60}


async def test_no_client_is_a_quiet_miss() -> None:
    cache = RedisCache(None)

    await cache.set("k", "v", ttl_seconds=60)

    assert await cache.get("k") is None


async def test_redis_down_is_a_miss_not_an_error() -> None:
    cache = RedisCache(cast(Any, DownRedis()))

    await cache.set("k", "v", ttl_seconds=60)

    assert await cache.get("k") is None


@pytest.mark.parametrize(
    ("cache_enabled", "redis_enabled"), [(False, True), (True, False)]
)
async def test_dependency_gives_a_no_op_cache_when_switched_off(
    monkeypatch: pytest.MonkeyPatch, cache_enabled: bool, redis_enabled: bool
) -> None:
    settings = get_settings().model_copy(
        update={"CACHE_ENABLED": cache_enabled, "REDIS_ENABLED": redis_enabled}
    )
    monkeypatch.setattr(dependency, "get_settings", lambda: settings)

    assert (await get_cache()).client is None
