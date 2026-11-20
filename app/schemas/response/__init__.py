"""Response schemas.

``common_response.py`` holds the shapes shared by every endpoint; per-feature
responses go in their own ``<feature>_response.py``.
"""

from app.schemas.response.common_response import (
    BaseResponse,
    ErrorDetail,
    ErrorInfo,
    ErrorResponse,
)
from app.schemas.response.document_response import (
    DocumentDeleteResponse,
    DocumentListResponse,
    DocumentMetadataResponse,
    DocumentStatusResponse,
    DocumentSummaryResponse,
    UploadedFileResponse,
)
from app.schemas.response.health_response import (
    ComponentHealth,
    DetailedHealthResponse,
    HealthResponse,
    VersionResponse,
)
from app.schemas.response.search_response import SearchHitResponse, SearchResponse
from app.schemas.response.user_response import UserResponse

__all__ = [
    "BaseResponse",
    "ComponentHealth",
    "DetailedHealthResponse",
    "DocumentDeleteResponse",
    "DocumentListResponse",
    "DocumentMetadataResponse",
    "DocumentStatusResponse",
    "DocumentSummaryResponse",
    "ErrorDetail",
    "ErrorInfo",
    "ErrorResponse",
    "HealthResponse",
    "SearchHitResponse",
    "SearchResponse",
    "UploadedFileResponse",
    "UserResponse",
    "VersionResponse",
]
