"""S3 client lifecycle, without a running server."""

from collections.abc import AsyncIterator

import pytest

from app.clients.s3 import client as s3_module
from app.clients.s3.client import s3_client
from app.settings import Settings


@pytest.fixture(autouse=True)
async def reset_client() -> AsyncIterator[None]:
    """The client is a process-wide singleton; never leak one between tests."""
    yield
    await s3_client.close()


async def test_client_before_init_raises() -> None:
    with pytest.raises(RuntimeError, match="not initialized"):
        _ = s3_client.client


async def test_health_check_before_init_is_false() -> None:
    assert await s3_client.health_check() is False


async def test_init_fails_fast_and_cleans_up_when_server_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unreachable = Settings(
        _env_file=None,
        S3_ENDPOINT_URL="http://localhost:1",
        S3_ACCESS_KEY_ID="key",
        S3_SECRET_ACCESS_KEY="secret",
        S3_MAX_ATTEMPTS=1,
    )
    monkeypatch.setattr(s3_module, "get_settings", lambda: unreachable)

    with pytest.raises(Exception):  # noqa: B017 - botocore EndpointConnectionError
        await s3_client.init_s3()

    # Nothing half-open is left behind for the lifespan to miss.
    assert s3_client._client is None
