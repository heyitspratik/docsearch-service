"""FastAPI application factory."""

from __future__ import annotations

import logging.config
from pathlib import Path

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.requests import Request
from fastapi.responses import UJSONResponse
from fastapi.staticfiles import StaticFiles

from app.controllers.monitor_controller import monitor_router
from app.exception.custom import BaseHTTPException
from app.helper.response_helper import BaseResponse  # will stub later
from app.lifetime import register_shutdown_event, register_startup_event
from app.middleware.profiler import ProfilerMiddleware
from app.router import api_router

APP_ROOT = Path(__file__).resolve().parent.parent
logging.config.fileConfig(APP_ROOT / "logging.conf", disable_existing_loggers=False)  # type: ignore[arg-type]


def get_app() -> FastAPI:
    """Build and return the FastAPI app instance."""
    app = FastAPI(
        title="FastAPI Boilerplate",
        description="Production-ready FastAPI boilerplate project",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/api/openapi.json",
        default_response_class=UJSONResponse,
        exception_handlers={BaseHTTPException: BaseHTTPException.to_response},
    )

    # Custom validation error formatting
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(  # noqa: D401
        request: Request, exc: RequestValidationError
    ):
        return await BaseResponse.request_exception_response(exc)  # type: ignore[arg-type]

    # Lifecycle events
    register_startup_event(app)
    register_shutdown_event(app)

    # Middleware
    app.add_middleware(ProfilerMiddleware)

    # Routers
    app.include_router(api_router, prefix="/api")
    app.include_router(monitor_router)

    # Static files (Swagger UI assets etc.)
    app.mount("/static", StaticFiles(directory=APP_ROOT / "static"), name="static")

    return app
