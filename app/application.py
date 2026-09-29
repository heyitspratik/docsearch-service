"""Main application class."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from app.controllers.health_controller import health_router
from app.exceptions import register_exception_handlers
from app.lifetime import lifespan
from app.log import configure_logging, get_logger
from app.middleware import (
    PROCESS_TIME_HEADER,
    REQUEST_ID_HEADER,
    RequestContextMiddleware,
)
from app.router import api_router
from app.settings import Settings, get_settings

logger = get_logger(__name__)


class Application:
    """Builds the configured FastAPI application."""

    @classmethod
    def get_app(cls, settings: Settings | None = None) -> FastAPI:
        """Get the FastAPI application instance.

        Settings are an argument so tests can build an app without patching
        module-level state.

        Returns:
            FastAPI: The configured FastAPI application instance.
        """
        settings = settings or get_settings()
        configure_logging(settings)

        show_docs = settings.expose_docs
        app = FastAPI(
            title=settings.APP_NAME,
            description=settings.APP_DESCRIPTION,
            version=settings.APP_VERSION,
            root_path=settings.APP_ROOT_PATH,
            lifespan=lifespan,
            openapi_url="/api/openapi.json" if show_docs else None,
            docs_url="/docs" if show_docs else None,
            redoc_url="/redoc" if show_docs else None,
        )

        # Published on app.state so the lifespan and route handlers use the
        # settings this app was built with, not the cached global singleton.
        app.state.settings = settings

        cls._configure_middleware(app)
        register_exception_handlers(app)
        cls._configure_routes(app, settings)

        return app

    @staticmethod
    def _configure_middleware(app: FastAPI) -> None:
        """Configure middleware for the application.

        Starlette applies middleware in reverse of registration, so the
        correlation id is registered first to make it outermost.
        """
        app.add_middleware(RequestContextMiddleware)
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=[REQUEST_ID_HEADER, PROCESS_TIME_HEADER],
        )

    @staticmethod
    def _configure_routes(app: FastAPI, settings: Settings) -> None:
        """Configure API routes.

        Health sits at the root rather than under the API prefix, so probes
        do not have to track the API version.
        """
        app.include_router(router=health_router)
        app.include_router(router=api_router, prefix=settings.APP_API_PREFIX)

        if settings.expose_docs:

            @app.get("/", include_in_schema=False)
            async def root() -> RedirectResponse:
                """Send the bare host to the API docs."""
                return RedirectResponse(url="/docs")


def get_app() -> FastAPI:
    """Get the FastAPI application instance.

    Returns:
        FastAPI: The configured FastAPI application instance.
    """
    return Application.get_app()
