"""Qdrant dependency for getting the shared client."""

from typing import Annotated

from fastapi import Depends
from qdrant_client import AsyncQdrantClient

from app.clients.qdrant.client import qdrant_client


def get_qdrant() -> AsyncQdrantClient:
    """Dependency for getting the shared Qdrant client."""
    return qdrant_client.client


#: Annotate handler parameters with this instead of repeating ``Depends``.
QdrantDep = Annotated[AsyncQdrantClient, Depends(get_qdrant)]
