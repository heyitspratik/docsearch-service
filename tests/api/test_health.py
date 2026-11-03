"""Health, readiness and version endpoints."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.application import Application
from app.clients.database.client import db_client
from app.clients.mongo.client import mongo_client
from app.clients.qdrant.client import qdrant_client
from app.clients.s3.client import s3_client
from app.constants import Environment
from app.settings import Settings


async def test_health_never_touches_dependencies(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["message"] == "Service is healthy"
    assert body["status"] == 200
    assert body["detail"] is None
    assert body["payload"]["service"] == "Test Service"


async def test_detailed_health_reports_only_enabled_clients(
    client: AsyncClient,
) -> None:
    """Both clients are disabled in the test settings, so nothing is probed."""
    response = await client.get("/health/detailed")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == 200
    assert body["payload"]["components"] == {}


async def test_detailed_health_is_503_when_a_dependency_is_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failing probe must return 503 so the replica leaves the load balancer."""

    async def unreachable() -> bool:
        return False

    monkeypatch.setattr(db_client, "health_check", unreachable)
    settings = Settings(
        _env_file=None,
        APP_ENVIRONMENT=Environment.TEST,
        DB_ENABLED=True,
        DB_USER="test",
        DB_PASSWORD="test",
        DB_NAME="test",
    )
    app = Application.get_app(settings)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health/detailed")

    assert response.status_code == 503
    body = response.json()
    assert body["message"] == "Service is degraded"
    assert body["status"] == 503
    assert body["detail"] == "One or more dependencies are unreachable"
    assert body["payload"]["components"]["database"]["status"] == "unhealthy"


async def test_detailed_health_reports_new_clients_and_503_if_one_is_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Qdrant, MongoDB and S3 are probed like the database and Redis."""

    async def reachable() -> bool:
        return True

    async def unreachable() -> bool:
        return False

    monkeypatch.setattr(qdrant_client, "health_check", reachable)
    monkeypatch.setattr(mongo_client, "health_check", unreachable)
    monkeypatch.setattr(s3_client, "health_check", reachable)
    settings = Settings(
        _env_file=None,
        APP_ENVIRONMENT=Environment.TEST,
        QDRANT_ENABLED=True,
        MONGO_ENABLED=True,
        S3_ENABLED=True,
        S3_ACCESS_KEY_ID="test",
        S3_SECRET_ACCESS_KEY="test",
    )
    app = Application.get_app(settings)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health/detailed")

    assert response.status_code == 503
    assert response.json()["payload"]["components"] == {
        "qdrant": {"status": "healthy", "message": "Qdrant connection successful"},
        "mongo": {"status": "unhealthy", "message": "MongoDB connection failed"},
        "s3": {"status": "healthy", "message": "S3 bucket reachable"},
    }


async def test_version_reports_configured_identity(client: AsyncClient) -> None:
    response = await client.get("/version")
    assert response.status_code == 200
    assert response.json() == {
        "message": "Version fetched successfully",
        "payload": {
            "name": "Test Service",
            "version": "0.0.0-test",
            "environment": "test",
        },
        "status": 200,
        "detail": None,
    }
