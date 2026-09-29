"""API route definitions.

Versioned from day one: adding ``/v2`` later without a ``/v1`` already in
place means either breaking every existing caller or serving two unlabelled
shapes from the same paths.
"""

from fastapi import APIRouter

api_router = APIRouter()

v1_router = APIRouter(prefix="/v1")

# Register feature routers on the version they belong to, for example:
#   from app.controllers.document_controller import document_router
#   v1_router.include_router(document_router, prefix="/documents", tags=["Documents"])

api_router.include_router(v1_router)

__all__ = ["api_router", "v1_router"]
