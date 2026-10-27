"""S3 dependency for getting the shared client."""

from typing import Annotated

from fastapi import Depends

from app.clients.s3.client import AioS3Client, s3_client


async def get_s3() -> AioS3Client:
    """Dependency for getting the shared S3 client."""
    return s3_client.client


#: Annotate handler parameters with this instead of repeating ``Depends``.
S3Dep = Annotated[AioS3Client, Depends(get_s3)]
