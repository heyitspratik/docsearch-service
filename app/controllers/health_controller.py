"""Health check controller for the application.

``/health`` is a liveness probe and never touches a dependency: if it did, a
brief database blip would restart every replica at once. ``/health/detailed``
is the readiness probe and does check them, so a degraded replica is pulled
from the load balancer but left alive to recover.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Request, Response, status

from app.clients.database.client import db_client
from app.clients.redis.client import redis_client
from app.constants import HealthMessages, HealthStatus
from app.schemas.response import (
    ComponentHealth,
    DetailedHealthResponse,
    HealthResponse,
    VersionResponse,
)
from app.settings import Settings

health_router = APIRouter(tags=["Health"])


def _settings(request: Request) -> Settings:
    """Read the settings this application was built with."""
    return request.app.state.settings  # type: ignore[no-any-return]


@health_router.get("/health", response_model=HealthResponse)
async def health_check(request: Request) -> HealthResponse:
    """Basic health check endpoint.

    Returns:
        HealthResponse: Indicates the process is able to serve a request.
    """
    return HealthResponse(
        service=_settings(request).APP_NAME,
        timestamp=datetime.now(UTC),
    )


@health_router.get(
    "/health/detailed",
    response_model=DetailedHealthResponse,
    responses={
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "description": HealthMessages.DEPENDENCIES_UNREACHABLE
        }
    },
)
async def detailed_health_check(
    request: Request, response: Response
) -> DetailedHealthResponse:
    """Detailed health check that verifies connectivity to dependencies.

    Only enabled clients are probed: a dependency the service opted out of
    cannot be unhealthy.

    Returns:
        DetailedHealthResponse: Per-dependency status, 503 when degraded.
    """
    settings = _settings(request)
    components: dict[str, ComponentHealth] = {}

    if settings.DB_ENABLED:
        healthy = await db_client.health_check()
        components["database"] = ComponentHealth(
            status=HealthStatus.HEALTHY if healthy else HealthStatus.UNHEALTHY,
            message=HealthMessages.DATABASE_CONNECTION_SUCCESSFUL
            if healthy
            else HealthMessages.DATABASE_CONNECTION_FAILED,
        )

    if settings.REDIS_ENABLED:
        healthy = await redis_client.health_check()
        components["redis"] = ComponentHealth(
            status=HealthStatus.HEALTHY if healthy else HealthStatus.UNHEALTHY,
            message=HealthMessages.REDIS_CONNECTION_SUCCESSFUL
            if healthy
            else HealthMessages.REDIS_CONNECTION_FAILED,
        )

    overall_healthy = all(c.status == HealthStatus.HEALTHY for c in components.values())
    if not overall_healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return DetailedHealthResponse(
        status=HealthStatus.HEALTHY if overall_healthy else HealthStatus.DEGRADED,
        service=settings.APP_NAME,
        timestamp=datetime.now(UTC),
        components=components,
    )


@health_router.get("/version", response_model=VersionResponse)
async def version(request: Request) -> VersionResponse:
    """Report the service name, version and environment.

    Returns:
        VersionResponse: Build and environment identity.
    """
    settings = _settings(request)
    return VersionResponse(
        name=settings.APP_NAME,
        version=settings.APP_VERSION,
        environment=settings.APP_ENVIRONMENT.value,
    )
