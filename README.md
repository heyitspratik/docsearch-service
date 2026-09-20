# FastAPI Boilerplate

Production-ready FastAPI skeleton with async SQLAlchemy, Redis cache, Keycloak authentication, Alembic migrations, Docker, CI and pre-commit hooks.

## Features

* FastAPI 0.116 with `uvicorn` runner
* Modular folder structure (services, controllers, middleware…)
* Pre-commit hooks (black, isort, flake8, mypy, safety)
* Dockerfile
* GitHub Actions workflow (lint + tests)
* Health-check endpoint at `/health`

## Quick start

```bash
git clone /path/to/python-fastapi-boilerplate my-project
cd my-project

# Install dependencies (uv is a super-fast pip replacement)
pip install uv
uv pip install -r requirements.txt -r requirements-dev.txt  # only for development

# Optional: create .env and override settings

# Launch services
docker compose up --build
```

Access API at http://localhost:8000. Swagger UI served at `/docs` once you mount static files.

## Development

```bash
pre-commit install

uv pip install -r requirements.txt -r requirements-dev.txt

python main.py  # runs uvicorn
```

---
Feel free to customise modules, add routers & models as required.
