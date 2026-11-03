"""Reading and writing files in an S3 bucket."""

from botocore.exceptions import ClientError

from app.clients.s3.client import AioS3Client
from app.constants import S3Messages
from app.exceptions import NotFoundError


class S3Storage:
    """File storage on an S3 bucket (SeaweedFS locally).

    Takes the client instead of using the ``s3_client`` singleton, so a Celery
    task can pass the connection it opened for itself.
    """

    def __init__(self, client: AioS3Client, bucket: str) -> None:
        self.client = client
        self.bucket = bucket

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        """Save ``data`` under ``key``, replacing anything already there."""
        await self.client.put_object(
            Bucket=self.bucket, Key=key, Body=data, ContentType=content_type
        )

    async def get(self, key: str) -> bytes:
        """Return the bytes under ``key``, or raise ``NotFoundError``."""
        try:
            response = await self.client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey"):
                raise NotFoundError(f"{S3Messages.OBJECT_NOT_FOUND}: {key}") from e
            raise
        async with response["Body"] as body:
            data: bytes = await body.read()
        return data

    async def delete(self, key: str) -> None:
        """Remove ``key``. S3 already treats a missing key as deleted."""
        await self.client.delete_object(Bucket=self.bucket, Key=key)
