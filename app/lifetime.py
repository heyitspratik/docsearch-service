"""Application lifecycle management."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.clients.database.client import db_client
from app.clients.redis.client import redis_client
from app.log import get_logger
from app.settings import Settings, get_settings

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application lifespan events.

    Each client is opened only when its settings group is enabled, so a
    service that owns no data runs with ``DB_ENABLED=false`` and never
    connects to a database.

    Args:
        app: FastAPI application instance

    Yields:
        None
    """
    settings: Settings = getattr(app.state, "settings", None) or get_settings()
    logger.info("Starting application lifespan")

    # Startup
    if settings.DB_ENABLED:
        await db_client.init_db()
        logger.info("Database connection established")
    if settings.REDIS_ENABLED:
        await redis_client.init_redis()
        logger.info("Redis connection established")

    try:
        yield
    finally:
        # Shutdown in reverse order, and always: a failed startup or a
        # terminated process must not leave connections dangling.
        if settings.REDIS_ENABLED:
            await redis_client.close()
            logger.info("Redis connection closed")
        if settings.DB_ENABLED:
            await db_client.close()
            logger.info("Database connection closed")
