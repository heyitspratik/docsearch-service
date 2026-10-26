"""Qdrant client lifecycle, without a running server."""

from collections.abc import AsyncIterator

import pytest
from qdrant_client import AsyncQdrantClient

from app.clients.qdrant import client as qdrant_module
from app.clients.qdrant.client import qdrant_client
from app.settings import Settings


@pytest.fixture(autouse=True)
async def reset_client() -> AsyncIterator[None]:
    """The client is a process-wide singleton; never leak one between tests."""
    yield
    await qdrant_client.close()


async def test_client_before_init_raises() -> None:
    with pytest.raises(RuntimeError, match="not initialized"):
        _ = qdrant_client.client


async def test_health_check_before_init_is_false() -> None:
    assert await qdrant_client.health_check() is False


async def test_init_fails_fast_and_cleans_up_when_server_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unreachable = Settings(_env_file=None, QDRANT_PORT=1, QDRANT_TIMEOUT=1)
    monkeypatch.setattr(qdrant_module, "get_settings", lambda: unreachable)

    with pytest.raises(Exception):  # noqa: B017 - transport error type varies
        await qdrant_client.init_qdrant()

    # Nothing half-open is left behind for the lifespan to miss.
    assert qdrant_client._client is None


async def test_health_check_true_when_reachable() -> None:
    qdrant_client._client = AsyncQdrantClient(location=":memory:")

    assert await qdrant_client.health_check() is True


async def test_close_resets_client() -> None:
    qdrant_client._client = AsyncQdrantClient(location=":memory:")

    await qdrant_client.close()

    assert await qdrant_client.health_check() is False
