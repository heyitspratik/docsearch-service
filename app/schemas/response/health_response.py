"""Response models for the health endpoints."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.constants import HealthStatus


class ComponentHealth(BaseModel):
    """Reachability of a single dependency."""

    status: Literal[HealthStatus.HEALTHY, HealthStatus.UNHEALTHY]
    message: str


class HealthResponse(BaseModel):
    """Liveness: the process is running."""

    service: str
    timestamp: datetime


class DetailedHealthResponse(BaseModel):
    """Readiness: the process can serve traffic."""

    service: str
    timestamp: datetime
    components: dict[str, ComponentHealth] = Field(default_factory=dict)


class VersionResponse(BaseModel):
    """Build and environment identity."""

    name: str
    version: str
    environment: str
