# FastAPI Service Base

A starting point for FastAPI microservices. Clone it, name it, turn on what you
need, start writing endpoints.

**Everything external is opt-in.** A fresh clone boots and serves traffic with
no database and no cache running.

```bash
cp .env.example .env
uv sync --all-extras --group dev
uv run python main.py          # http://localhost:8000/docs
```

---

## Contents

- [First 15 minutes](#first-15-minutes)
- [Commands](#commands)
- [Configuration](#configuration)
- [Project layout](#project-layout)
- [Writing your first endpoint](#writing-your-first-endpoint)
- [Database](#database)
- [Redis](#redis)
- [Errors](#errors)
- [Logging and health](#logging-and-health)
- [Docker](#docker)
- [Deleting what you don't need](#deleting-what-you-dont-need)

---

## First 15 minutes

1. **Take a copy.** Use GitHub's *Use this template*, or clone and reset the
   history so your service does not inherit this one's commits:

   ```bash
   git clone <this-repo> my-service && cd my-service
   rm -rf .git && git init
   ```

2. **Name it.** In `pyproject.toml` set `name`, `description` and `authors`.
   In `.env` set `APP_NAME` and `APP_VERSION`.

3. **Install.**

   ```bash
   cp .env.example .env
   uv sync --all-extras --group dev
   uv run pre-commit install
   ```

4. **Turn on what you need** in `.env`: `DB_ENABLED`, `REDIS_ENABLED`. Leave
   the rest off.

5. **Check it works.**

   ```bash
   uv run pytest
   uv run python main.py
   ```

6. **Delete what you will never use** — see
   [Deleting what you don't need](#deleting-what-you-dont-need).

> Uses [uv](https://docs.astral.sh/uv/):
> `curl -LsSf https://astral.sh/uv/install.sh | sh`

---

## Commands

| Task | Command |
|---|---|
| Install | `uv sync --all-extras --group dev` |
| Run the API | `uv run python main.py` |
| Run tests | `uv run pytest` |
| Coverage | `uv run pytest --cov --cov-report=html` |
| Lint and format | `uv run ruff check --fix . && uv run ruff format .` |
| Type check | `uv run mypy app` |
| All pre-commit hooks | `uv run pre-commit run --all-files` |
| New migration | `uv run alembic revision --autogenerate -m "add users"` |
| Apply migrations | `uv run alembic upgrade head` |
| Roll back one | `uv run alembic downgrade -1` |
| Start the stack | `docker compose up --build -d` |
| Stop it | `docker compose down -v` |

---

## Configuration

All settings live in one `Settings` class. Defaults are in `.env.example`.

| Group | Turn on with |
|---|---|
| Application (`APP_*`) | always on |
| Database (`DB_*`) | `DB_ENABLED=true` |
| Redis (`REDIS_*`) | `REDIS_ENABLED=true` |

Field names in `app/settings.py` match the environment variables exactly, so
`DB_HOST` can be grepped for in both places.

Bad configuration fails at startup rather than at 3am: a synchronous `DB_DRIVER`
and an unknown `APP_ENVIRONMENT` are both rejected at boot, and interactive
docs are always off in production.

---

## Project layout

```
app/
├── application.py            factory: lifespan, middleware, handlers, routers
├── lifetime.py               opens and closes clients around the app's life
├── settings.py               one settings group per concern
├── router.py                 versioned aggregator -> /api/v1
├── clients/
│   ├── database/             client.py (engine + sessions) · dependency.py
│   └── redis/                client.py · dependency.py
├── db/
│   ├── models/base_model.py  declarative base: id, uuid, timestamps
│   └── services/             database services, one per area
├── controllers/              route handlers
├── schemas/                  request/ and response/ payload models
├── exceptions/               error hierarchy and handlers
├── middleware/               request id, timing, access log
└── log/                      JSON and console formatters
```

Classes are used where they earn it — clients, db services, middleware.
Route handlers stay functions, because FastAPI's dependency injection,
validation and OpenAPI generation all key off the function signature.

---

## Writing your first endpoint

```python
# app/db/models/document.py
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base_model import BaseModel


class Document(BaseModel):
    """A stored document."""

    title: Mapped[str] = mapped_column(index=True)
```

```python
# app/db/models/__init__.py  -- Alembic only sees models imported here
from app.db.models.document import Document  # noqa: F401
```

```python
# app/schemas/request/document_request.py
from pydantic import BaseModel


class DocumentCreateRequest(BaseModel):
    title: str
```

```python
# app/schemas/response/document_response.py
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uuid: UUID
    title: str
```

```python
# app/controllers/document_controller.py
from uuid import UUID

from fastapi import APIRouter, status

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.database.dependency import DBSession
from app.db.models.document import Document
from app.exceptions import NotFoundError
from app.schemas.request.document_request import DocumentCreateRequest
from app.schemas.response.document_response import DocumentResponse

document_router = APIRouter()


class DocumentDBService:
    """Database operations for documents."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **values: object) -> Document:
        document = Document(**values)
        self.session.add(document)
        await self.session.flush()
        await self.session.refresh(document)
        return document

    async def get_by_uuid(self, document_uuid: UUID) -> Document | None:
        result = await self.session.scalars(
            select(Document).where(Document.uuid == document_uuid)
        )
        return result.first()


@document_router.post(
    "", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED
)
async def create_document(
    payload: DocumentCreateRequest, session: DBSession
) -> Document:
    """Create a document."""
    return await DocumentDBService(session).create(**payload.model_dump())


@document_router.get("/{document_uuid}", response_model=DocumentResponse)
async def get_document(document_uuid: UUID, session: DBSession) -> Document:
    """Fetch a document by uuid."""
    document = await DocumentDBService(session).get_by_uuid(document_uuid)
    if document is None:
        raise NotFoundError(f"No document with uuid {document_uuid}")
    return document
```

```python
# app/router.py
from app.controllers.document_controller import document_router

v1_router.include_router(document_router, prefix="/documents", tags=["Documents"])
```

Then:

```bash
uv run alembic revision --autogenerate -m "add document"
uv run alembic upgrade head
uv run python main.py            # POST/GET /api/v1/documents
```

---

## Database

`DB_DRIVER` alone decides the engine — SQLAlchemy is the abstraction, so **no
application code changes between them**:

```bash
DB_DRIVER=postgresql+asyncpg    DB_PORT=5432    # uv sync --extra postgres
DB_DRIVER=mysql+aiomysql        DB_PORT=3306    # uv sync --extra mysql
```

The DSN is assembled from `DB_DRIVER`, `DB_HOST`, `DB_PORT`, `DB_USER`,
`DB_PASSWORD` and `DB_NAME`, with the credentials URL-escaped — so a password
containing `@` or `:` cannot corrupt it.

One transaction per request: the session commits on success and rolls back on
any exception. **Handlers should not commit** — a handler that commits and then
raises leaves the request half-applied.

`BaseModel` gives every table an `id`, a public `uuid`, `created_at` and
`updated_at`, and derives the table name from the class name.

Queries live in `app/db/services/`, one service per area, each taking a
session. `CommonDBService` holds the helpers that are not tied to one table:
`get_schema_ids()` to resolve an id/uuid pair, and `get_row_by_key()` to fetch
selected columns from any table.

### Migrations

```bash
uv run alembic revision --autogenerate -m "add document table"
uv run alembic upgrade head
```

`alembic/versions/` starts empty — your first migration is the first revision.
Alembic reads the URL from application settings, so the migration tool and the
service can never disagree about which database they point at.

**Import every model in `app/db/models/__init__.py`.** Autogenerate only sees
tables attached to `BaseModel.metadata` at import time, and a model missing
from that file is silently absent from the generated migration.

> **Do not run migrations on application startup.** With more than one replica
> they all read the same version row, all decide to migrate, and all but one
> crash on the duplicate key — a CrashLoopBackOff on every deploy. Run
> `alembic upgrade head` as its own step: an init container, a Job, or a CI
> stage.

---

## Redis

```python
from app.clients.redis.dependency import RedisDep


@router.get("/cached")
async def cached(redis: RedisDep) -> str | None:
    return await redis.get("some-key")
```

Any Redis-protocol server works, including Valkey and DragonflyDB — it is just
`REDIS_HOST` and the image.

---

## Errors

Raise from `app.exceptions`, never `HTTPException`, so business logic carries no
HTTP knowledge and is testable without a request:

```python
raise NotFoundError(f"No document with uuid {document_uuid}")
raise ConflictError("That slug is taken", details={"slug": slug})
```

Every failure returns the same shape, including unhandled ones:

```json
{
  "error": { "code": "not_found", "message": "No document with uuid ..." },
  "request_id": "3f9a1c2b4d5e"
}
```

Branch on `code`, never the message. Unexpected exceptions return a generic
message and log the traceback — exception text routinely contains connection
strings and internal paths. The `request_id` ties a user's report to that
traceback.

Available: `BadRequestError`, `UnauthorizedError`, `ForbiddenError`,
`NotFoundError`, `ConflictError`, `UnprocessableEntityError`,
`TooManyRequestsError`, `ExternalServiceError`, `ServiceUnavailableError`.

Per-feature exceptions go in their own module and inherit from these, so the
status code is declared once:

```python
# app/exceptions/document_exceptions.py
from app.exceptions.common_exceptions import NotFoundError


class DocumentNotFoundException(NotFoundError):
    def __init__(self, document_id: int) -> None:
        super().__init__(f"No document with id {document_id}")
```

---

## Logging and health

Every request gets a correlation id, reused from an inbound `X-Request-ID` so a
trace spans the whole call chain, or minted when this service is the entry
point. It flows into every log record, every error response, and the
`X-Request-ID` response header.

```bash
APP_LOG_FORMAT=json       # one object per line, for a log aggregator
APP_LOG_FORMAT=console    # readable and coloured, for local work
```

```json
{"timestamp":"2026-09-21T09:38:35Z","level":"INFO","logger":"app.access",
 "message":"GET /api/v1/documents 200 12.40ms","request_id":"a2835c3d3927",
 "http_status":200,"duration_ms":12.4}
```

| Endpoint | Purpose |
|---|---|
| `GET /health` | Is the process up? **Never touches dependencies.** |
| `GET /health/detailed` | Probes every enabled client; 503 when degraded |
| `GET /version` | Name, version, environment |

**Keep these separate.** If the liveness probe checked the database, a brief
database blip would restart every replica at once — turning a recoverable
dependency problem into a full outage. Readiness pulls a pod out of the load
balancer; liveness leaves it alive to recover.

---

## Docker

```bash
cp .env.example .env
docker compose up --build -d
docker compose logs -f api
docker compose down -v
```

The image is multi-stage (no compilers in the runtime layer), runs as a
non-root user, and its `HEALTHCHECK` points at **liveness**, never readiness.

It brings up three services: `api`, `postgres` and `redis`. Credentials and
ports come from `.env` (`POSTGRES_USER`, `POSTGRES_PORT`, …).

**Dependencies are cached.** The lockfile is installed before the source is
copied, so editing code rebuilds in about a second without reinstalling
anything.

**For MySQL instead of Postgres:** `docker-compose.yml` carries a commented
`mysql` service. Swap it in, point the api's `DB_HOST` at it, and build with
`--build-arg EXTRAS="mysql redis"` so `aiomysql` is installed. No application
code changes — SQLAlchemy handles the dialect.

> The api's `DB_HOST` in compose is `postgres`, not `localhost`: inside a
> container `localhost` is the container itself. That is why it is set in
> `docker-compose.yml` rather than read from `.env`.

---

## Deleting what you don't need

Each capability is one directory, one settings group, and a few lines in
`app/lifetime.py`.

| Not needed | Delete |
|---|---|
| Database | `app/clients/database/`, `app/db/`, `alembic/`, `alembic.ini`, `DatabaseSettings` |
| Redis | `app/clients/redis/`, `RedisSettings` |
| Docker | `Dockerfile`, `docker-compose.yml`, `.dockerignore` |

Then drop its block from `lifespan()` in `app/lifetime.py`, its field from
`Settings` in `app/settings.py`, and its branch in the health controller.
