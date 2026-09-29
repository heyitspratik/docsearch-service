"""Health, readiness and version endpoints."""

from httpx import AsyncClient


async def test_health_never_touches_dependencies(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert body["service"] == "Test Service"


async def test_detailed_health_reports_only_enabled_clients(
    client: AsyncClient,
) -> None:
    """Both clients are disabled in the test settings, so nothing is probed."""
    response = await client.get("/health/detailed")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert body["components"] == {}


async def test_version_reports_configured_identity(client: AsyncClient) -> None:
    response = await client.get("/version")
    assert response.status_code == 200
    assert response.json() == {
        "name": "Test Service",
        "version": "0.0.0-test",
        "environment": "test",
    }
