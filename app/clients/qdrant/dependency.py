"""Qdrant dependencies: the shared client, and the vector store built on it."""

from typing import Annotated

from fastapi import Depends
from qdrant_client import AsyncQdrantClient

from app.clients.qdrant.client import qdrant_client
from app.clients.qdrant.service import QdrantVectorStore
from app.settings import get_settings


async def get_qdrant() -> AsyncQdrantClient:
    """Dependency for getting the shared Qdrant client."""
    return qdrant_client.client


#: Annotate handler parameters with this instead of repeating ``Depends``.
QdrantDep = Annotated[AsyncQdrantClient, Depends(get_qdrant)]


async def get_vector_store(qdrant: QdrantDep) -> QdrantVectorStore:
    """Dependency for the chunk vector store. Tests override it with a fake."""
    return QdrantVectorStore(qdrant, get_settings().QDRANT_COLLECTION_ALIAS)


VectorStoreDep = Annotated[QdrantVectorStore, Depends(get_vector_store)]
