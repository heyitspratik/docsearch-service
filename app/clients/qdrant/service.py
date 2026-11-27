"""Chunk vectors in Qdrant, written through the collection alias."""

from collections.abc import Sequence
from http import HTTPStatus
from itertools import batched
from typing import cast
from uuid import UUID

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
from app.helpers.embedding_helper import SparseVector
from app.helpers.model_spec_helper import ModelSpec
from app.helpers.vector_store_helper import (
    ChunkPayload,
    ChunkPoint,
    SearchHit,
    collection_name,
)
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

    @staticmethod
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

    async def ensure_collection(self, spec: ModelSpec) -> None:
        """Create the model's collection and alias if missing; refuse a mismatch.

        Raises:
            RuntimeError: The alias points to another model's collection.
        """
        expected = collection_name(self.alias, spec.name)
        current = await self.alias_target()
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

        await self.create_collection(expected, spec)
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
                points=[self._to_point_struct(point) for point in batch],
                # Return only once the points are searchable.
                wait=True,
            )

    async def delete_document(self, document_uuid: UUID) -> None:
        """Remove every point of one document. A document with none is fine."""
        await self.client.delete(
            collection_name=self.alias,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="document_id",
                            match=models.MatchValue(value=str(document_uuid)),
                        )
                    ]
                )
            ),
            wait=True,
        )

    @staticmethod
    def owner_filter(
        user_uuid: str, document_ids: Sequence[UUID] | None = None
    ) -> models.Filter:
        """Only the user's chunks; ``document_ids`` can narrow that, never widen it."""
        must: list[models.Condition] = [
            models.FieldCondition(
                key="user_uuid", match=models.MatchValue(value=user_uuid)
            )
        ]
        if document_ids:
            must.append(
                models.FieldCondition(
                    key="document_id",
                    match=models.MatchAny(any=[str(d) for d in document_ids]),
                )
            )
        return models.Filter(must=must)

    async def search_sparse(
        self, vector: SparseVector, query_filter: models.Filter, limit: int
    ) -> list[SearchHit]:
        """Keyword search: BM25 weights, scored with Qdrant's IDF."""
        response = await self.client.query_points(
            collection_name=self.alias,
            query=models.SparseVector(indices=vector.indices, values=vector.values),
            using=SPARSE_VECTOR_NAME,
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
        )
        return self._to_hits(response.points)

    async def search_dense(
        self, vector: list[float], query_filter: models.Filter, limit: int
    ) -> list[SearchHit]:
        """Semantic search: nearest meaning vectors (cosine) through HNSW.

        Hits carry their dense vector, for MMR.
        """
        response = await self.client.query_points(
            collection_name=self.alias,
            query=vector,
            using=DENSE_VECTOR_NAME,
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
            with_vectors=[DENSE_VECTOR_NAME],
        )
        return self._to_hits(response.points)

    async def search_hybrid(
        self,
        dense: list[float],
        sparse: SparseVector,
        query_filter: models.Filter,
        prefetch_limit: int,
        limit: int,
    ) -> list[SearchHit]:
        """Both searches in one call, merged by rank with RRF.

        Hits carry their dense vector, for MMR.
        """
        response = await self.client.query_points(
            collection_name=self.alias,
            prefetch=[
                # Filter each prefetch too: no other user's chunk can be a candidate.
                models.Prefetch(
                    query=dense,
                    using=DENSE_VECTOR_NAME,
                    filter=query_filter,
                    limit=prefetch_limit,
                ),
                models.Prefetch(
                    query=models.SparseVector(
                        indices=sparse.indices, values=sparse.values
                    ),
                    using=SPARSE_VECTOR_NAME,
                    filter=query_filter,
                    limit=prefetch_limit,
                ),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
            with_vectors=[DENSE_VECTOR_NAME],
        )
        return self._to_hits(response.points)

    @staticmethod
    def _to_hits(points: Sequence[models.ScoredPoint]) -> list[SearchHit]:
        """Qdrant's scored points as hits, best first, with the dense vector if sent."""
        return [
            SearchHit(
                id=str(point.id),
                score=point.score,
                payload=ChunkPayload.model_validate(point.payload),
                dense=QdrantVectorStore._dense_of(point),
            )
            for point in points
        ]

    @staticmethod
    def _dense_of(point: models.ScoredPoint) -> list[float] | None:
        """The point's dense vector, or None if the search did not ask for it."""
        if not isinstance(point.vector, dict):
            return None
        dense = point.vector.get(DENSE_VECTOR_NAME)
        # Our dense vector is a plain list of floats (not sparse, not multi-vector).
        return cast(list[float], dense) if isinstance(dense, list) else None

    async def alias_target(self) -> str | None:
        """The collection the alias points to, or None if there is no alias."""
        response = await self.client.get_aliases()
        for alias in response.aliases:
            if alias.alias_name == self.alias:
                return alias.collection_name
        return None

    async def switch_alias(self, collection: str) -> None:
        """Point the alias at ``collection`` in one step, so it is never missing."""
        await self.client.update_collection_aliases(
            change_aliases_operations=[
                models.DeleteAliasOperation(
                    delete_alias=models.DeleteAlias(alias_name=self.alias)
                ),
                models.CreateAliasOperation(
                    create_alias=models.CreateAlias(
                        collection_name=collection, alias_name=self.alias
                    )
                ),
            ]
        )
        logger.info(f"Qdrant alias {self.alias} now points to {collection}")

    async def delete_collection(self, name: str) -> None:
        """Drop a collection and its points. A missing one is fine."""
        await self.client.delete_collection(name)
        logger.info(f"Qdrant collection {name} deleted")

    async def create_collection(self, name: str, spec: ModelSpec) -> None:
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
