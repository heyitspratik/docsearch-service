"""Search: find the chunks that best answer a question, by words, meaning or both."""

import asyncio
from collections.abc import Sequence
from uuid import UUID

from app.clients.qdrant.service import QdrantVectorStore
from app.constants import SearchType
from app.helpers.embedding_helper import DenseEmbedder, SparseEmbedder
from app.helpers.vector_store_helper import SearchHit
from app.log import get_logger
from app.settings import get_settings

logger = get_logger(__name__)


class SearchService:
    """Runs one search over a user's chunks.

    ``keyword``: BM25 → top k. ``semantic``: dense → candidates → top k.
    ``hybrid``: dense + BM25 candidates fused with RRF → top k.
    """

    def __init__(
        self,
        dense: DenseEmbedder,
        sparse: SparseEmbedder,
        vectors: QdrantVectorStore,
    ) -> None:
        self.dense = dense
        self.sparse = sparse
        self.vectors = vectors

    async def search(
        self,
        user_uuid: str,
        query: str,
        search_type: SearchType,
        document_ids: Sequence[UUID] | None = None,
    ) -> list[SearchHit]:
        """The best chunks for ``query``, best first, from the user's chunks only."""
        settings = get_settings()
        top_k, candidates = settings.RERANKER_TOP_K, settings.RERANKER_CANDIDATES
        query_filter = self.vectors.owner_filter(user_uuid, document_ids)

        # Embedding is CPU work; a thread keeps the event loop free.
        if search_type is SearchType.KEYWORD:
            sparse = await asyncio.to_thread(self.sparse.embed_query, query)
            hits = await self.vectors.search_sparse(sparse, query_filter, top_k)
        elif search_type is SearchType.SEMANTIC:
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

        logger.info(
            f"Search {search_type.value}: {len(hits)} candidates for user {user_uuid}"
        )
        # Step 3.2 reranks the candidates here before keeping the top k.
        return hits[:top_k]
