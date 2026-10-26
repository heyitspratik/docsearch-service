"""Application lifecycle management."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.clients.database.client import db_client
from app.clients.mongo.client import mongo_client
from app.clients.qdrant.client import qdrant_client
from app.clients.redis.client import redis_client
from app.clients.s3.client import s3_client
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
    if settings.QDRANT_ENABLED:
        await qdrant_client.init_qdrant()
        logger.info("Qdrant connection established")
    if settings.MONGO_ENABLED:
        await mongo_client.init_mongo()
        logger.info("MongoDB connection established")
    if settings.S3_ENABLED:
        await s3_client.init_s3()
        logger.info("S3 connection established")

    if settings.APP_RELOAD:
        logger.info(
            f"Uvicorn Running on http://{settings.APP_HOST}:{settings.APP_PORT} "
            f"(Press CTRL+C to quit)"
        )

    try:
        yield
    finally:
        # Shutdown in reverse order, and always: a failed startup or a
        # terminated process must not leave connections dangling.
        if settings.S3_ENABLED:
            await s3_client.close()
            logger.info("S3 connection closed")
        if settings.MONGO_ENABLED:
            await mongo_client.close()
            logger.info("MongoDB connection closed")
        if settings.QDRANT_ENABLED:
            await qdrant_client.close()
            logger.info("Qdrant connection closed")
        if settings.REDIS_ENABLED:
            await redis_client.close()
            logger.info("Redis connection closed")
        if settings.DB_ENABLED:
            await db_client.close()
            logger.info("Database connection closed")
