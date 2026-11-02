"""User controller: who the bearer token belongs to."""

from fastapi import APIRouter, status
from fastapi_utils.cbv import cbv

from app.constants import UserMessages
from app.helpers import CurrentUser
from app.schemas.response import BaseResponse, ErrorResponse, UserResponse
from app.services import UserService

user_router = APIRouter()


@cbv(user_router)
class UserController:
    """HTTP layer for the user endpoints; the logic lives in ``UserService``."""

    @user_router.get(
        "/me",
        response_model=BaseResponse[UserResponse],
        responses={status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse}},
    )
    async def get_me(self, user: CurrentUser) -> BaseResponse[UserResponse]:
        """Return the logged-in user.

        Returns:
            BaseResponse[UserResponse]: The user's ID (the token's ``sub``),
            username and email.
        """
        user_service = UserService()
        profile = await user_service.get_profile(user)
        return BaseResponse(
            message=UserMessages.CURRENT_USER_FETCHED,
            payload=profile,
            status=status.HTTP_200_OK,
        )
