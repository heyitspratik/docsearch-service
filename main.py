"""CLI entrypoint for the FastAPI application."""

import uvicorn

from app.log import get_logger
from app.settings import get_settings

logger = get_logger(__name__)


def main() -> None:
    """Run uvicorn using settings from the project."""
    settings = get_settings()

    workers = settings.APP_WORKERS
    reload = settings.APP_RELOAD

    # uvicorn cannot do both: reload needs a single supervised process.
    if reload and workers > 1:
        logger.warning(
            f"APP_RELOAD=true is incompatible with APP_WORKERS={workers}; "
            f"running a single worker"
        )
        workers = 1

    uvicorn.run(
        "app.application:get_app",
        factory=True,
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        workers=None if reload else workers,
        reload=reload,
        log_config=None,
    )


if __name__ == "__main__":
    main()
