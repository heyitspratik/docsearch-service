"""Monitoring and health-check endpoints."""

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

monitor_router = APIRouter(tags=["monitor"])


@monitor_router.get("/health", status_code=status.HTTP_200_OK)
async def health() -> JSONResponse:  # noqa: D401
    """Simple health check endpoint."""
    return JSONResponse(content={"status": "ok"})
