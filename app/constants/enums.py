"""Application enums."""

from enum import StrEnum


class Environment(StrEnum):
    """Deployment environment."""

    LOCAL = "local"
    TEST = "test"
    DEV = "dev"
    STAGING = "staging"
    PRODUCTION = "production"

    @property
    def is_production(self) -> bool:
        """Whether this environment holds real user data."""
        return self is Environment.PRODUCTION


class LogLevel(StrEnum):
    """Standard library log levels."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class HealthStatus(StrEnum):
    """Status reported by the health endpoints."""

    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    DEGRADED = "degraded"


class ErrorCode(StrEnum):
    """Stable codes clients branch on, returned in every error response."""

    BAD_REQUEST = "bad_request"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    METHOD_NOT_ALLOWED = "method_not_allowed"
    CONFLICT = "conflict"
    UNPROCESSABLE_ENTITY = "unprocessable_entity"
    VALIDATION_ERROR = "validation_error"
    TOO_MANY_REQUESTS = "too_many_requests"
    INTERNAL_ERROR = "internal_error"
    EXTERNAL_SERVICE_ERROR = "external_service_error"
    SERVICE_UNAVAILABLE = "service_unavailable"
    HTTP_ERROR = "http_error"
