# syntax=docker/dockerfile:1.7
FROM python:3.12-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Optional extras to install, space separated:
#   docker build --build-arg EXTRAS="mysql redis" .
ARG EXTRAS="postgres redis"

# Dependencies resolve from the lockfile alone, so this layer stays cached
# until pyproject.toml or uv.lock actually change.
COPY pyproject.toml uv.lock ./
# $flags is unquoted on purpose: it must split into separate --extra arguments.
# hadolint ignore=SC2086
RUN --mount=type=cache,target=/root/.cache/uv \
    flags=""; for extra in $EXTRAS; do flags="$flags --extra $extra"; done; \
    uv sync --frozen --no-install-project --no-dev $flags

COPY . .
# hadolint ignore=SC2086
RUN --mount=type=cache,target=/root/.cache/uv \
    flags=""; for extra in $EXTRAS; do flags="$flags --extra $extra"; done; \
    uv sync --frozen --no-dev $flags

FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 1001 app \
    && useradd --system --uid 1001 --gid app --create-home app

WORKDIR /app

COPY --from=builder --chown=app:app /app /app

# Numeric so Kubernetes runAsNonRoot can verify it; same user as "app" above.
USER 1001:1001

EXPOSE 8000

# Liveness only: gating container health on a dependency would restart every
# replica during a brief database blip. Shell form is needed for "|| exit 1":
# Docker treats only exit code 1 as unhealthy, and curl --fail exits with 22.
# hadolint ignore=DL3025
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl --fail --silent http://localhost:8000/health || exit 1

CMD ["python", "main.py"]
