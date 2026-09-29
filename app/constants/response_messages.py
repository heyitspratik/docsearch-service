"""User-facing response messages.

Internal log messages stay next to the code that logs them.
"""


class ErrorMessages:
    """Default messages for the common exceptions."""

    BAD_REQUEST = "The request could not be processed"
    UNAUTHORIZED = "Authentication is required"
    FORBIDDEN = "You do not have permission to perform this action"
    NOT_FOUND = "The requested resource was not found"
    CONFLICT = "The request conflicts with the current state of the resource"
    UNPROCESSABLE_ENTITY = "The request could not be processed"
    TOO_MANY_REQUESTS = "Too many requests"
    EXTERNAL_SERVICE_ERROR = "An upstream service failed"
    SERVICE_UNAVAILABLE = "The service is temporarily unavailable"
    INTERNAL_SERVER_ERROR = "An unexpected error occurred"
    VALIDATION_ERROR = "Request validation failed"
    INVALID_VALUE = "Invalid value"


class HealthMessages:
    """Messages returned by the health endpoints."""

    DATABASE_CONNECTION_SUCCESSFUL = "Database connection successful"
    DATABASE_CONNECTION_FAILED = "Database connection failed"
    REDIS_CONNECTION_SUCCESSFUL = "Redis connection successful"
    REDIS_CONNECTION_FAILED = "Redis connection failed"
    DEPENDENCIES_UNREACHABLE = "One or more dependencies are unreachable"


class DatabaseMessages:
    """Messages raised by the database client and services."""

    ID_OR_UUID_REQUIRED = "At least one of id or uuid is required"
    ENGINE_NOT_INITIALIZED = "Database engine not initialized"
    SESSION_FACTORY_NOT_INITIALIZED = "Session factory not initialized"


class RedisMessages:
    """Messages raised by the redis client."""

    CLIENT_NOT_INITIALIZED = "Redis client not initialized"
    EXTRA_REQUIRED = (
        "REDIS_ENABLED=true requires the 'redis' extra: uv sync --extra redis"
    )
