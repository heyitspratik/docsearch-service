"""Services: the business logic, one class per area."""

from app.services.document_service import DocumentService
from app.services.search_service import SearchService
from app.services.user_service import UserService

__all__ = ["DocumentService", "SearchService", "UserService"]
