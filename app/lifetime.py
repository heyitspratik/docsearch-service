"""Application startup/shutdown event handlers."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI


def register_startup_event(app: FastAPI) -> None:
    """Register startup event with resource initialisation."""

    @app.on_event("startup")
    async def _startup() -> None:  # noqa: WPS430
        pass


def register_shutdown_event(app: FastAPI) -> None:
    """Register shutdown event with resource cleanup."""

    @app.on_event("shutdown")
    async def _shutdown() -> None:  # noqa: WPS430
        pass
