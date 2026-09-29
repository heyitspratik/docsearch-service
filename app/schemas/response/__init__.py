"""Response schemas.

``common_response.py`` holds the shapes shared by every endpoint; per-feature
responses go in their own ``<feature>_response.py``.
"""

from app.schemas.response.common_response import (
    ErrorBody,
    ErrorDetail,
    ErrorResponse,
)
from app.schemas.response.health_response import (
    ComponentHealth,
    DetailedHealthResponse,
    HealthResponse,
    VersionResponse,
)

__all__ = [
    "ComponentHealth",
    "DetailedHealthResponse",
    "ErrorBody",
    "ErrorDetail",
    "ErrorResponse",
    "HealthResponse",
    "VersionResponse",
]
