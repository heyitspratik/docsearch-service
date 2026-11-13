"""Chunk vectors in Qdrant, written through the collection alias."""

from collections.abc import Sequence
from http import HTTPStatus
from itertools import batched

from qdrant_client import AsyncQdrantClient, models
from qdrant_client.http.exceptions import UnexpectedResponse

from app.constants import (
    DENSE_VECTOR_NAME,
    HNSW_EF_CONSTRUCT,
    HNSW_M,
    PAYLOAD_INDEX_FIELDS,
    SPARSE_VECTOR_NAME,
    UPSERT_BATCH_SIZE,
    QdrantMessages,
)
from app.helpers.model_spec_helper import ModelSpec
from app.helpers.vector_store_helper import ChunkPoint, collection_name
from app.log import get_logger

logger = get_logger(__name__)


class QdrantVectorStore:
    """The vector store on Qdrant.

    Takes the client instead of using the ``qdrant_client`` singleton, so a
    Celery task can pass the connection it opened for itself.
    """

    def __init__(self, client: AsyncQdrantClient, alias: str) -> None:
        self.client = client
        self.alias = alias

    async def ensure_collection(self, spec: ModelSpec) -> None:
        """Create the model's collection and alias if missing; refuse a mismatch.

        Raises:
            RuntimeError: The alias points to another model's collection.
        """
        expected = collection_name(self.alias, spec.name)
        current = await self._alias_target()
        if current == expected:
            return
        if current is not None:
            raise RuntimeError(
                QdrantMessages.ALIAS_MODEL_MISMATCH.format(
                    alias=self.alias,
                    current=current,
                    model=spec.name,
                    expected=expected,
                )
            )

        await self._create_collection(expected, spec)
        # Creating an alias that already exists is not an error, so two
        # processes starting together both succeed.
        await self.client.update_collection_aliases(
            change_aliases_operations=[
                models.CreateAliasOperation(
                    create_alias=models.CreateAlias(
                        collection_name=expected, alias_name=self.alias
                    )
                )
            ]
        )
        logger.info(f"Qdrant alias {self.alias} now points to {expected}")

    async def upsert(self, points: Sequence[ChunkPoint]) -> None:
        """Add the points, replacing any with the same ID."""
        for batch in batched(points, UPSERT_BATCH_SIZE):
            await self.client.upsert(
                collection_name=self.alias,
                points=[_to_point_struct(point) for point in batch],
                # Return only once the points are searchable.
                wait=True,
            )

    async def _alias_target(self) -> str | None:
        """The collection the alias points to, or None if there is no alias."""
        response = await self.client.get_aliases()
        for alias in response.aliases:
            if alias.alias_name == self.alias:
                return alias.collection_name
        return None

    async def _create_collection(self, name: str, spec: ModelSpec) -> None:
        """Create the collection and its payload indexes, unless it already exists."""
        try:
            await self.client.create_collection(
                collection_name=name,
                vectors_config={
                    DENSE_VECTOR_NAME: models.VectorParams(
                        size=spec.dimensions,
                        distance=models.Distance.COSINE,
                        hnsw_config=models.HnswConfigDiff(
                            m=HNSW_M, ef_construct=HNSW_EF_CONSTRUCT
                        ),
                    )
                },
                sparse_vectors_config={
                    # Qdrant works out each word's rarity (IDF) across all chunks.
                    SPARSE_VECTOR_NAME: models.SparseVectorParams(
                        modifier=models.Modifier.IDF
                    )
                },
            )
        except UnexpectedResponse as e:
            # Another worker process created it first.
            if e.status_code != HTTPStatus.CONFLICT:
                raise
        for field in PAYLOAD_INDEX_FIELDS:
            await self.client.create_payload_index(
                collection_name=name,
                field_name=field,
                field_schema=models.PayloadSchemaType.KEYWORD,
            )
        logger.info(f"Qdrant collection {name} ready ({spec.dimensions} dimensions)")


def _to_point_struct(point: ChunkPoint) -> models.PointStruct:
    """A chunk point in the shape the Qdrant client sends."""
    return models.PointStruct(
        id=point.id,
        vector={
            DENSE_VECTOR_NAME: point.dense,
            SPARSE_VECTOR_NAME: models.SparseVector(
                indices=point.sparse.indices, values=point.sparse.values
            ),
        },
        payload=point.payload.model_dump(mode="json"),
    )
