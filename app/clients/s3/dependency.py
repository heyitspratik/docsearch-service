"""S3 dependencies: the shared client, and the file storage built on it."""

from typing import Annotated

from fastapi import Depends

from app.clients.s3.client import AioS3Client, s3_client
from app.clients.s3.service import S3Storage
from app.helpers.storage_helper import ObjectStorage
from app.settings import get_settings


async def get_s3() -> AioS3Client:
    """Dependency for getting the shared S3 client."""
    return s3_client.client


#: Annotate handler parameters with this instead of repeating ``Depends``.
S3Dep = Annotated[AioS3Client, Depends(get_s3)]


async def get_storage(s3: S3Dep) -> ObjectStorage:
    """Dependency for the app's file storage. Tests override it with a fake."""
    return S3Storage(s3, get_settings().S3_BUCKET)


#: What APIs and services use for files, instead of the raw ``S3Dep``.
StorageDep = Annotated[ObjectStorage, Depends(get_storage)]
