"""Business logic for users."""

from app.helpers import AuthenticatedUser
from app.schemas.response import UserResponse


class UserService:
    """Everything the API does with users."""

    async def get_profile(self, user: AuthenticatedUser) -> UserResponse:
        """Return the logged-in user's profile."""
        return UserResponse(id=user.id, username=user.username, email=user.email)
