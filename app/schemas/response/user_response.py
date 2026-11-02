"""Response models for the user endpoints."""

from pydantic import BaseModel


class UserResponse(BaseModel):
    """The logged-in user."""

    id: str
    username: str | None
    email: str | None
