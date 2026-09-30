# FastAPI Service Base

A starting point for FastAPI microservices. Clone it, name it, turn on what you
need, start writing endpoints.

**Everything external is opt-in.** A fresh clone runs with no database and no
Redis.

```bash
cp .env.example .env
uv sync --all-extras --group dev
uv run python main.py          # open http://localhost:8000/docs
```

> Needs [uv](https://docs.astral.sh/uv/):
> `curl -LsSf https://astral.sh/uv/install.sh | sh`

---

## Start a new service

1. **Copy it** with GitHub's *Use this template*, or clone and reset history:
   `git clone <this-repo> my-service && cd my-service && rm -rf .git && git init`
2. **Name it:** `name`, `description`, `authors` in `pyproject.toml`;
   `APP_NAME`, `APP_VERSION` in `.env`.
3. **Install:** `uv sync --all-extras --group dev && uv run pre-commit install`
4. **Turn on what you need** in `.env`: `DB_ENABLED`, `REDIS_ENABLED`.
5. **Check it works:** `uv run pytest`, then `uv run python main.py`.
6. **Delete what you won't use** — see [the last section](#deleting-what-you-dont-need).

---

## Commands

| Task | Command |
|---|---|
| Run the API | `uv run python main.py` |
| Run tests | `uv run pytest` |
| Lint and format | `uv run ruff check --fix . && uv run ruff format .` |
| Type check | `uv run mypy app` |
| All pre-commit hooks | `uv run pre-commit run --all-files` |
| New migration | `uv run alembic revision --autogenerate -m "add users"` |
| Apply migrations | `uv run alembic upgrade head` |
| Roll back one | `uv run alembic downgrade -1` |
| Start with Docker | `docker compose up --build -d` |
| Stop Docker | `docker compose down -v` |

---

## Configuration

All settings are in one class, `app/settings.py`, and every field name matches
its environment variable exactly (`DB_HOST` in code is `DB_HOST` in `.env`).
Defaults and descriptions are in `.env.example`.

Bad configuration stops the app at startup, not in the middle of the night:
a sync `DB_DRIVER` or missing DB credentials are rejected at boot. API docs are
always off in production.

---

## Project layout

```
app/
├── application.py      builds the app: middleware, error handlers, routers
├── lifetime.py         opens and closes DB/Redis around the app's life
├── settings.py         all configuration
├── router.py           mounts your routers under /api/v1
├── clients/            database/ and redis/ connections
├── db/                 models/ (tables) and services/ (queries)
├── controllers/        route handlers
├── schemas/            request/ and response/ models
├── constants/          enums and messages
├── exceptions/         error classes and handlers
├── middleware/         request id, timing, access log
└── log/                console and JSON log formats
```

---

## Adding an endpoint

Use `app/controllers/health_controller.py` as the reference pattern.

1. **Model** (if it needs a table): `app/db/models/<name>.py`, then import it in
   `app/db/models/__init__.py` — Alembic can't see models that aren't imported.
2. **Schemas:** `app/schemas/request/<name>_request.py` and
   `app/schemas/response/<name>_response.py`.
3. **Queries:** a service class in `app/db/services/<name>_db_service.py`.
4. **Controller:** `app/controllers/<name>_controller.py`. Take a session with
   `DBSession` or Redis with `RedisDep`, and return `BaseResponse[YourResponse]`.
5. **Mount it** in `app/router.py` (there's a commented example).
6. **Migrate:** `uv run alembic revision --autogenerate -m "add <name>"`,
   then `uv run alembic upgrade head`.

Every successful response has the same shape:

```json
{
  "message": "Service is healthy",
  "payload": { "service": "FastAPI Service", "timestamp": "2026-09-30T10:47:16Z" },
  "status": 200,
  "detail": null
}
```

---

## Database and Redis

- **Engine:** `DB_DRIVER` picks it — `postgresql+asyncpg` (`uv sync --extra postgres`)
  or `mysql+aiomysql` (`uv sync --extra mysql`). No code changes between them.
- **Transactions:** one per request. The session commits on success and rolls
  back on error, so **handlers should not commit**.
- **Tables:** every table gets `id`, `uuid`, `created_at` and `updated_at` from
  `BaseModel`.
- **Redis:** any Redis-compatible server works (Valkey, DragonflyDB).

> **Don't run migrations on app startup.** With several replicas they all try
> to migrate at once and crash. Run `alembic upgrade head` as its own deploy
> step.

---

## Errors

Raise the classes in `app/exceptions`, never `HTTPException`:
`BadRequestError`, `UnauthorizedError`, `ForbiddenError`, `NotFoundError`,
`ConflictError`, `UnprocessableEntityError`, `TooManyRequestsError`,
`ExternalServiceError`, `ServiceUnavailableError`.

Each error returns a stable `code` to branch on and a `request_id` to find its
log. Unexpected errors return a generic message, so internal details never
leak to the caller.

---

## Logging and health

Every request gets an id (reused from an incoming `X-Request-ID`), which shows
in every log line, every error and the response header. Set
`APP_LOG_FORMAT=json` for log tools, or `console` for local work.

| Endpoint | Purpose |
|---|---|
| `GET /health` | Liveness: is the process up? Never checks dependencies. |
| `GET /health/detailed` | Readiness: checks DB/Redis, returns 503 if one is down. |
| `GET /version` | Name, version, environment. |

> **Keep liveness and readiness separate.** If liveness checked the database, a
> short DB blip would restart every replica at once.

---

## Docker

`docker compose up --build -d` starts `api`, `postgres` and `redis`, with
credentials from `.env`.

- **Image:** multi-stage, runs as a non-root user, and its health check uses
  `/health`.
- **Rebuilds:** dependencies are cached, so code-only changes rebuild in about
  a second.
- **MySQL:** swap in the commented `mysql` service in `docker-compose.yml` and
  build with `--build-arg EXTRAS="mysql redis"`.

---

## Deleting what you don't need

| Not needed | Delete |
|---|---|
| Database | `app/clients/database/`, `app/db/`, `alembic/`, `alembic.ini` |
| Redis | `app/clients/redis/` |
| Docker | `Dockerfile`, `docker-compose.yml`, `.dockerignore` |

Then remove its `DB_*` or `REDIS_*` fields from `app/settings.py`, its block in
`app/lifetime.py`, and its check in `app/controllers/health_controller.py`.
