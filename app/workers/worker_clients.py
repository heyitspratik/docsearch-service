"""Async clients for one Celery task, opened and closed on that task's event loop."""

from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager

from app.clients.database.client import db_client
from app.clients.mongo.client import mongo_client
from app.clients.qdrant.client import qdrant_client
from app.clients.s3.client import s3_client
from app.settings import get_settings


@asynccontextmanager
async def worker_clients() -> AsyncGenerator[None, None]:
    """Open every enabled client for one task and close them when it ends.

    Each task runs its own ``asyncio.run``, so clients made for one task's
    event loop are never reused on another's.
    """
    settings = get_settings()
    opened: list[Callable[[], Awaitable[None]]] = []
    try:
        if settings.DB_ENABLED:
            await db_client.init_db()
            opened.append(db_client.close)
        if settings.QDRANT_ENABLED:
            await qdrant_client.init_qdrant()
            opened.append(qdrant_client.close)
        if settings.MONGO_ENABLED:
            await mongo_client.init_mongo()
            opened.append(mongo_client.close)
        if settings.S3_ENABLED:
            await s3_client.init_s3()
            opened.append(s3_client.close)
        yield
    finally:
        for close in reversed(opened):
            await close()
