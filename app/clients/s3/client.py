"""S3 client for original files and Docling JSON (SeaweedFS locally)."""

from contextlib import AsyncExitStack
from typing import Any, Optional

import aioboto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.constants import S3Messages
from app.log import get_logger
from app.settings import get_settings

logger = get_logger(__name__)

#: aioboto3 ships no type information, so its S3 client is untyped.
AioS3Client = Any


class S3Client:
    """Singleton S3 client for managing the object storage connection.

    aioboto3 only hands out clients as ``async with`` blocks; the exit stack
    keeps one open from :meth:`init_s3` until :meth:`close`.
    """

    _instance: Optional["S3Client"] = None
    _client: AioS3Client | None = None
    _exit_stack: AsyncExitStack | None = None

    def __new__(cls) -> "S3Client":
        """Create or return the singleton instance."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @property
    def client(self) -> AioS3Client:
        """Get the S3 client instance."""
        if self._client is None:
            raise RuntimeError(S3Messages.CLIENT_NOT_INITIALIZED)
        return self._client

    async def init_s3(self) -> None:
        """Open the S3 client and create the bucket if it is missing."""
        settings = get_settings()
        session = aioboto3.Session()
        self._exit_stack = AsyncExitStack()
        self._client = await self._exit_stack.enter_async_context(
            session.client(
                "s3",
                endpoint_url=settings.S3_ENDPOINT_URL,
                region_name=settings.S3_REGION,
                aws_access_key_id=settings.S3_ACCESS_KEY_ID,
                aws_secret_access_key=settings.S3_SECRET_ACCESS_KEY,
                config=Config(
                    # SeaweedFS (and most self-hosted S3) only understands
                    # host/bucket/key, not bucket.host/key.
                    s3={"addressing_style": "path"},
                    retries={"max_attempts": settings.S3_MAX_ATTEMPTS, "mode": "standard"},
                ),
            )
        )
        try:
            await self._ensure_bucket(settings.S3_BUCKET)
        except Exception:
            # The lifespan only closes clients after a successful startup.
            await self.close()
            raise

    async def _ensure_bucket(self, bucket: str) -> None:
        """Create the bucket on first start; later starts find it."""
        try:
            await self.client.head_bucket(Bucket=bucket)
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") not in ("404", "NoSuchBucket"):
                raise
            await self.client.create_bucket(Bucket=bucket)
            logger.info(f"S3 bucket {bucket!r} created")

    async def health_check(self) -> bool:
        """Report whether the bucket is reachable. Never raises."""
        if self._client is None:
            return False
        try:
            await self._client.head_bucket(Bucket=get_settings().S3_BUCKET)
            return True
        except Exception as e:
            logger.warning(f"S3 health check failed: {e!s}")
            return False

    async def close(self) -> None:
        """Close the S3 client and cleanup resources."""
        if self._exit_stack is not None:
            await self._exit_stack.aclose()
        self._client = None
        self._exit_stack = None


# Create singleton instance
s3_client = S3Client()
