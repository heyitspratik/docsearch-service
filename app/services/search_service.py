"""Search: find the chunks that best answer a question, by words, meaning or both."""

import asyncio
import json
from datetime import datetime
from uuid import UUID

from opentelemetry import trace
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.qdrant.service import QdrantVectorStore
from app.clients.redis.service import RedisCache
from app.constants import ScoreKind, SearchType
from app.db.services import DocumentDBService
from app.helpers import AuthenticatedUser
from app.helpers.cache_helper import normalize_query, result_key, vector_key
from app.helpers.embedding_helper import DenseEmbedder, SparseEmbedder, SparseVector
from app.helpers.rerank_helper import Reranker
from app.helpers.vector_store_helper import SearchHit
from app.log import get_logger, log_duration
from app.schemas.request import SearchRequest
from app.schemas.response import SearchHitResponse, SearchResponse
from app.settings import get_settings

logger = get_logger(__name__)
# A no-op until OpenTelemetry is configured (Phase 7.1); then spans are exported.
tracer = trace.get_tracer(__name__)


class SearchService:
    """Runs one search over a user's ``ready`` documents.

    ``keyword``: BM25 → top k. ``semantic``: dense → candidates → rerank → top k.
    ``hybrid``: dense + BM25 candidates fused with RRF → rerank → top k.

    Query vectors and results are cached in Redis; keys come from ``cache_helper``.
    """

    def __init__(
        self,
        session: AsyncSession,
        dense: DenseEmbedder,
        sparse: SparseEmbedder,
        reranker: Reranker,
        vectors: QdrantVectorStore,
        cache: RedisCache,
    ) -> None:
        self.document_db = DocumentDBService(session)
        self.dense = dense
        self.sparse = sparse
        self.reranker = reranker
        self.vectors = vectors
        self.cache = cache

    @log_duration("Search")
    async def search(
        self, user: AuthenticatedUser, request: SearchRequest
    ) -> SearchResponse:
        """The best chunks for the query, best first, from the user's chunks only."""
        score_kind = (
            ScoreKind.BM25 if request.type is SearchType.KEYWORD else ScoreKind.RERANK
        )
        # Queued, failed or deleted documents can still have points in Qdrant.
        ready = await self.document_db.list_ready(user.id, request.document_ids)
        if not ready:
            return SearchResponse(type=request.type, score_kind=score_kind, hits=[])

        normalized = normalize_query(request.query)
        key = result_key(
            pipeline=self._pipeline(),
            user_uuid=user.id,
            search_type=request.type.value,
            document_ids=request.document_ids,
            fingerprint=self._fingerprint(ready),
            normalized_query=normalized,
        )
        cached = await self.cache.get(key)
        if cached is not None:
            logger.info(f"Search {request.type.value}: result cache hit")
            return SearchResponse.model_validate_json(cached)
        logger.info(f"Search {request.type.value}: result cache miss")

        ready_ids = [document_uuid for document_uuid, _ in ready]
        hits = await self._retrieve(
            user.id, request.query, normalized, request.type, ready_ids
        )
        response = SearchResponse(
            type=request.type,
            score_kind=score_kind,
            hits=[self._to_response(hit) for hit in hits],
        )
        await self.cache.set(
            key,
            response.model_dump_json(),
            get_settings().CACHE_SEARCH_RESULT_TTL_SECONDS,
        )
        return response

    @staticmethod
    def _pipeline() -> str:
        """Everything that shapes results; changing any of it makes old results miss."""
        s = get_settings()
        return (
            f"{s.EMBEDDING_DENSE_MODEL}|{s.EMBEDDING_SPARSE_MODEL}|{s.RERANKER_MODEL}"
            f"|{s.RERANKER_CANDIDATES}|{s.RERANKER_TOP_K}"
        )

    @staticmethod
    def _fingerprint(ready: list[tuple[UUID, datetime]]) -> str:
        """Count and newest change of the searched documents.

        A document becoming ready or being deleted changes it, so stale results
        are never served.
        """
        newest = max(updated_at for _, updated_at in ready)
        return f"{len(ready)}:{newest.isoformat()}"

    async def _retrieve(
        self,
        user_uuid: str,
        query: str,
        normalized: str,
        search_type: SearchType,
        ready: list[UUID],
    ) -> list[SearchHit]:
        """Run the search type's pipeline and keep the top k.

        Embedders get the normalized query (both lowercase anyway); the
        reranker is case-sensitive, so it gets the query as typed.
        """
        settings = get_settings()
        top_k, candidates = settings.RERANKER_TOP_K, settings.RERANKER_CANDIDATES
        query_filter = self.vectors.owner_filter(user_uuid, ready)

        if search_type is SearchType.KEYWORD:
            sparse = await self._sparse_query(normalized)
            return await self.vectors.search_sparse(sparse, query_filter, top_k)

        if search_type is SearchType.SEMANTIC:
            dense = await self._dense_query(normalized)
            hits = await self.vectors.search_dense(dense, query_filter, candidates)
        else:
            dense = await self._dense_query(normalized)
            sparse = await self._sparse_query(normalized)
            hits = await self.vectors.search_hybrid(
                dense,
                sparse,
                query_filter,
                prefetch_limit=candidates,
                limit=candidates,
            )

        if not hits:
            return []
        reranked = await self._rerank(query, hits)
        return reranked[:top_k]

    async def _dense_query(self, normalized: str) -> list[float]:
        """The question's meaning vector, from the cache when possible."""
        settings = get_settings()
        key = vector_key("dense", settings.EMBEDDING_DENSE_MODEL, normalized)
        cached = await self.cache.get(key)
        logger.info(f"Dense query vector: cache {'miss' if cached is None else 'hit'}")
        if cached is not None:
            vector: list[float] = json.loads(cached)
            return vector
        # Embedding is CPU work; a thread keeps the event loop free.
        vector = await asyncio.to_thread(self.dense.embed_query, normalized)
        await self.cache.set(
            key, json.dumps(vector), settings.CACHE_QUERY_VECTOR_TTL_SECONDS
        )
        return vector

    async def _sparse_query(self, normalized: str) -> SparseVector:
        """The question's BM25 weights, from the cache when possible."""
        settings = get_settings()
        key = vector_key("sparse", settings.EMBEDDING_SPARSE_MODEL, normalized)
        cached = await self.cache.get(key)
        logger.info(f"Sparse query vector: cache {'miss' if cached is None else 'hit'}")
        if cached is not None:
            return SparseVector.model_validate_json(cached)
        vector = await asyncio.to_thread(self.sparse.embed_query, normalized)
        await self.cache.set(
            key, vector.model_dump_json(), settings.CACHE_QUERY_VECTOR_TTL_SECONDS
        )
        return vector

    # The slowest stage (~5 s on CPU), and no library traces it for us.
    @log_duration("Rerank")
    @tracer.start_as_current_span("search.rerank")
    async def _rerank(self, query: str, hits: list[SearchHit]) -> list[SearchHit]:
        """Score each candidate against the question; best first."""
        trace.get_current_span().set_attribute("search.candidates", len(hits))
        # The cross-encoder is heavy CPU work; keep it off the event loop.
        scores = await asyncio.to_thread(
            self.reranker.rerank, query, [hit.payload.text for hit in hits]
        )
        rescored = [
            hit.model_copy(update={"score": score})
            for hit, score in zip(hits, scores, strict=True)
        ]
        return sorted(rescored, key=lambda hit: hit.score, reverse=True)

    @staticmethod
    def _to_response(hit: SearchHit) -> SearchHitResponse:
        """A hit without internal fields such as the owner and the point ID."""
        payload = hit.payload
        return SearchHitResponse(
            document_uuid=UUID(payload.document_id),
            filename=payload.filename,
            page_start=payload.page_start,
            page_end=payload.page_end,
            chunk_type=payload.chunk_type,
            text=payload.text,
            score=hit.score,
        )
