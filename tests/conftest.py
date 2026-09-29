"""Shared test fixtures."""

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.application import Application
from app.constants import Environment
from app.settings import Settings


@pytest.fixture
def settings() -> Settings:
    """Settings for a service with no external dependencies.

    ``_env_file=None`` keeps the suite independent of a developer's local
    .env, so tests do not pass or fail depending on the machine.
    """
    return Settings(
        _env_file=None,
        APP_NAME="Test Service",
        APP_VERSION="0.0.0-test",
        APP_ENVIRONMENT=Environment.TEST,
        DB_ENABLED=False,
        REDIS_ENABLED=False,
    )


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    """An application instance wired from the test settings."""
    return Application.get_app(settings)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """HTTP client driving the app in-process, with the lifespan running.

    The real lifespan runs, so startup bugs surface here rather than in
    production.
    """
    async with (
        app.router.lifespan_context(app),
        AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as http_client,
    ):
        yield http_client
