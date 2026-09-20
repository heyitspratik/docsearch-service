"""CLI entrypoint for the FastAPI application."""

import uvicorn

from app.settings import settings


def main() -> None:  # noqa: D401
    """Run uvicorn using settings from the project."""
    uvicorn.run(
        "app.application:get_app",
        factory=True,
        workers=settings.workers_count,
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
        log_level=settings.log_level.value.lower(),
    )


if __name__ == "__main__":
    main()
