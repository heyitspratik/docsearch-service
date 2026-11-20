"""Search controller: keyword, semantic and hybrid search over your documents."""

from typing import Annotated

from fastapi import APIRouter, Query, status
from fastapi_utils.cbv import cbv

from app.clients.database.dependency import DBSession
from app.clients.qdrant.dependency import VectorStoreDep
from app.constants import SearchMessages
from app.helpers import CurrentUser
from app.helpers.embedding_helper import DenseEmbedderDep, SparseEmbedderDep
from app.helpers.rerank_helper import RerankerDep
from app.schemas.request import SearchRequest
from app.schemas.response import BaseResponse, ErrorResponse, SearchResponse
from app.services import SearchService

search_router = APIRouter()


@cbv(search_router)
class SearchController:
    """HTTP layer for search; the logic lives in ``SearchService``."""

    @search_router.get(
        "/search",
        response_model=BaseResponse[SearchResponse],
        responses={status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse}},
    )
    async def search(
        self,
        request: Annotated[SearchRequest, Query()],
        user: CurrentUser,
        session: DBSession,
        dense: DenseEmbedderDep,
        sparse: SparseEmbedderDep,
        reranker: RerankerDep,
        vectors: VectorStoreDep,
    ) -> BaseResponse[SearchResponse]:
        """Search your ``ready`` documents and return the best 5 chunks.

        Returns:
            BaseResponse[SearchResponse]: The hits, best first, and their score kind.
        """
        service = SearchService(session, dense, sparse, reranker, vectors)
        result = await service.search(user, request)
        return BaseResponse(
            message=SearchMessages.RESULTS_FETCHED,
            payload=result,
            status=status.HTTP_200_OK,
        )
