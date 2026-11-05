"""Fixed values. Plain data only: nothing here may import a library module."""

# --- Settings ---
ASYNC_DRIVERS = ("+asyncpg", "+aiomysql", "+asyncmy", "+aiosqlite", "+psycopg")

# --- Database ---
# Explicit names so Alembic can generate reversible constraint drops.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# --- Logging ---
# LogRecord's own attributes; anything else on a record is an ``extra`` field.
LOG_RECORD_RESERVED_ATTRS: frozenset[str] = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
        "taskName",
        "request_id",
    }
)

# --- Request context ---
REQUEST_ID_HEADER = "x-request-id"
PROCESS_TIME_HEADER = "x-process-time"
#: Key under which the correlation id is stored on the ASGI scope.
SCOPE_REQUEST_ID_KEY = "app_request_id"

# --- Auth ---
# Keycloak signs access tokens with RS256 by default. Pinning the algorithm
# stops a token from choosing a weaker one, such as "none" or HS256.
JWT_ALGORITHMS = ["RS256"]
JWT_REQUIRED_CLAIMS = ["exp", "iat", "iss", "aud", "sub"]
JWKS_TIMEOUT_SECONDS = 5.0

# --- Documents ---
#: Same length as ``document_master.filename``.
MAX_FILENAME_LENGTH = 255
# Docling reads plain text through its Markdown reader.
DOCLING_EXTENSIONS = {".txt": ".md"}
