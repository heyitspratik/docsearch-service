"""Search: find the chunks that best answer a question, by words, meaning or both."""

import asyncio
import time
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.qdrant.service import QdrantVectorStore
from app.constants import ScoreKind, SearchType
from app.db.services import DocumentDBService
from app.helpers import AuthenticatedUser
from app.helpers.embedding_helper import DenseEmbedder, SparseEmbedder
from app.helpers.rerank_helper import Reranker
from app.helpers.vector_store_helper import SearchHit
from app.log import get_logger
from app.schemas.request import SearchRequest
from app.schemas.response import SearchHitResponse, SearchResponse
from app.settings import get_settings

logger = get_logger(__name__)


class SearchService:
    """Runs one search over a user's ``ready`` documents.

    ``keyword``: BM25 → top k. ``semantic``: dense → candidates → rerank → top k.
    ``hybrid``: dense + BM25 candidates fused with RRF → rerank → top k.
    """

    def __init__(
        self,
        session: AsyncSession,
        dense: DenseEmbedder,
        sparse: SparseEmbedder,
        reranker: Reranker,
        vectors: QdrantVectorStore,
    ) -> None:
        self.document_db = DocumentDBService(session)
        self.dense = dense
        self.sparse = sparse
        self.reranker = reranker
        self.vectors = vectors

    async def search(
        self, user: AuthenticatedUser, request: SearchRequest
    ) -> SearchResponse:
        """The best chunks for the query, best first, from the user's chunks only."""
        score_kind = (
            ScoreKind.BM25 if request.type is SearchType.KEYWORD else ScoreKind.RERANK
        )
        # Queued, failed or deleted documents can still have points in Qdrant.
        ready = await self.document_db.list_ready_uuids(user.id, request.document_ids)
        if not ready:
            return SearchResponse(type=request.type, score_kind=score_kind, hits=[])

        hits = await self._retrieve(user.id, request.query, request.type, ready)
        return SearchResponse(
            type=request.type,
            score_kind=score_kind,
            hits=[self._to_response(hit) for hit in hits],
        )

    async def _retrieve(
        self, user_uuid: str, query: str, search_type: SearchType, ready: list[UUID]
    ) -> list[SearchHit]:
        """Run the search type's pipeline and keep the top k."""
        settings = get_settings()
        top_k, candidates = settings.RERANKER_TOP_K, settings.RERANKER_CANDIDATES
        query_filter = self.vectors.owner_filter(user_uuid, ready)

        # Embedding is CPU work; a thread keeps the event loop free.
        if search_type is SearchType.KEYWORD:
            sparse = await asyncio.to_thread(self.sparse.embed_query, query)
            return await self.vectors.search_sparse(sparse, query_filter, top_k)

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
        return reranked[:top_k]

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
