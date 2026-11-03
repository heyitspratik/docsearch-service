"""MongoDB client lifecycle, without a running server."""

from collections.abc import AsyncIterator

import pytest

from app.clients.mongo import client as mongo_module
from app.clients.mongo.client import mongo_client
from app.settings import Settings


@pytest.fixture(autouse=True)
async def reset_client() -> AsyncIterator[None]:
    """The client is a process-wide singleton; never leak one between tests."""
    yield
    await mongo_client.close()


async def test_client_and_database_before_init_raise() -> None:
    with pytest.raises(RuntimeError, match="not initialized"):
        _ = mongo_client.client
    with pytest.raises(RuntimeError, match="not initialized"):
        _ = mongo_client.database


async def test_health_check_before_init_is_false() -> None:
    assert await mongo_client.health_check() is False


async def test_init_fails_fast_and_cleans_up_when_server_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unreachable = Settings(_env_file=None, MONGO_PORT=1, MONGO_TIMEOUT_MS=200)
    monkeypatch.setattr(mongo_module, "get_settings", lambda: unreachable)

    with pytest.raises(Exception):  # noqa: B017 - pymongo raises ServerSelectionTimeoutError
        await mongo_client.init_mongo()

    # Nothing half-open is left behind for the lifespan to miss.
    assert mongo_client._client is None
