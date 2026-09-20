"""Main API router aggregator."""

from fastapi import APIRouter

api_router = APIRouter()

# Sub-routers would be included here, e.g.
# from app.controllers.user_controller import router as user_router
# api_router.include_router(user_router, prefix="/users", tags=["users"])
