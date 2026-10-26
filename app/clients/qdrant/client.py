"""Qdrant client for storing and searching chunk vectors."""

from typing import Optional

from qdrant_client import AsyncQdrantClient

from app.constants import QdrantMessages
from app.log import get_logger
from app.settings import get_settings

logger = get_logger(__name__)


class QdrantClient:
    """Singleton Qdrant client for managing the Qdrant connection.

    The client is created in :meth:`init_qdrant` rather than at import time, so
    importing this module never opens a connection.
    """

    _instance: Optional["QdrantClient"] = None
    _client: AsyncQdrantClient | None = None

    def __new__(cls) -> "QdrantClient":
        """Create or return the singleton instance."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @property
    def client(self) -> AsyncQdrantClient:
        """Get the Qdrant client instance."""
        if self._client is None:
            raise RuntimeError(QdrantMessages.CLIENT_NOT_INITIALIZED)
        return self._client

    async def init_qdrant(self) -> None:
        """Init the Qdrant connection and fail fast if the server is down."""
        settings = get_settings()
        self._client = AsyncQdrantClient(
            url=settings.qdrant_url,
            api_key=settings.QDRANT_API_KEY or None,
            timeout=settings.QDRANT_TIMEOUT,
            # The built-in check makes a blocking request in the constructor;
            # the server version is logged below instead.
            check_compatibility=False,
        )
        try:
            info = await self._client.info()
        except Exception:
            # The lifespan only closes clients after a successful startup.
            await self.close()
            raise
        logger.info(f"Qdrant server version {info.version}")

    async def health_check(self) -> bool:
        """Report whether Qdrant is reachable. Never raises."""
        if self._client is None:
            return False
        try:
            await self._client.info()
            return True
        except Exception as e:
            logger.warning(f"Qdrant health check failed: {e!s}")
            return False

    async def close(self) -> None:
        """Close the Qdrant connection and cleanup resources."""
        if self._client is not None:
            await self._client.close()
        self._client = None


# Create singleton instance
qdrant_client = QdrantClient()
