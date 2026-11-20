"""Request payload schemas.

One module per feature, named ``<feature>_request.py``.

Example:
    from app.schemas.request.document_request import DocumentCreateRequest
"""

from app.schemas.request.search_request import SearchRequest

__all__ = ["SearchRequest"]
