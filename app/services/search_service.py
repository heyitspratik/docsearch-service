"""Search: find the chunks that best answer a question, by words, meaning or both."""

import asyncio
import time
from collections.abc import Sequence
from uuid import UUID

from app.clients.qdrant.service import QdrantVectorStore
from app.constants import ScoreKind, SearchType
from app.helpers.embedding_helper import DenseEmbedder, SparseEmbedder
from app.helpers.rerank_helper import Reranker
from app.helpers.vector_store_helper import SearchHit
from app.log import get_logger
from app.schemas.response import SearchResponse
from app.settings import get_settings

logger = get_logger(__name__)


class SearchService:
    """Runs one search over a user's chunks.

    ``keyword``: BM25 → top k. ``semantic``: dense → candidates → rerank → top k.
    ``hybrid``: dense + BM25 candidates fused with RRF → rerank → top k.
    """

    def __init__(
        self,
        dense: DenseEmbedder,
        sparse: SparseEmbedder,
        reranker: Reranker,
        vectors: QdrantVectorStore,
    ) -> None:
        self.dense = dense
        self.sparse = sparse
        self.reranker = reranker
        self.vectors = vectors

    async def search(
        self,
        user_uuid: str,
        query: str,
        search_type: SearchType,
        document_ids: Sequence[UUID] | None = None,
    ) -> SearchResponse:
        """The best chunks for ``query``, best first, from the user's chunks only."""
        settings = get_settings()
        top_k, candidates = settings.RERANKER_TOP_K, settings.RERANKER_CANDIDATES
        query_filter = self.vectors.owner_filter(user_uuid, document_ids)

        # Embedding is CPU work; a thread keeps the event loop free.
        if search_type is SearchType.KEYWORD:
            sparse = await asyncio.to_thread(self.sparse.embed_query, query)
            hits = await self.vectors.search_sparse(sparse, query_filter, top_k)
            return SearchResponse(score_kind=ScoreKind.BM25, hits=hits)

        if search_type is SearchType.SEMANTIC:
            dense = await asyncio.to_thread(self.dense.embed_query, query)
            hits = await self.vectors.search_dense(dense, query_filter, candidates)
        else:
            dense = await asyncio.to_thread(self.dense.embed_query, query)
            sparse = await asyncio.to_thread(self.sparse.embed_query, query)
            hits = await self.vectors.search_hybrid(
                dense,
                sparse,
                query_filter,
                prefetch_limit=candidates,
                limit=candidates,
            )

        reranked = await self._rerank(query, hits)
        return SearchResponse(score_kind=ScoreKind.RERANK, hits=reranked[:top_k])

    async def _rerank(self, query: str, hits: list[SearchHit]) -> list[SearchHit]:
        """Score each candidate against the question; best first."""
        if not hits:
            return []
        started = time.perf_counter()
        # The cross-encoder is heavy CPU work; keep it off the event loop.
        scores = await asyncio.to_thread(
            self.reranker.rerank, query, [hit.payload.text for hit in hits]
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.info(f"Reranked {len(hits)} candidates in {elapsed_ms:.0f} ms")
        rescored = [
            hit.model_copy(update={"score": score})
            for hit, score in zip(hits, scores, strict=True)
        ]
        return sorted(rescored, key=lambda hit: hit.score, reverse=True)
