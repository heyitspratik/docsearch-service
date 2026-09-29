"""Error envelope consistency."""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.exceptions import ConflictError, NotFoundError


async def test_unknown_route_uses_the_standard_envelope(client: AsyncClient) -> None:
    response = await client.get("/nope")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "not_found"
    assert body["request_id"]


@pytest.fixture
def failing_app(app: FastAPI) -> FastAPI:
    """App with routes that raise, to exercise each handler."""

    @app.get("/boom/app-error")
    async def app_error() -> None:
        raise NotFoundError("No document with id 42")

    @app.get("/boom/conflict")
    async def conflict() -> None:
        raise ConflictError("That slug is taken", details={"slug": "intro"})

    @app.get("/boom/unexpected")
    async def unexpected() -> None:
        raise RuntimeError("password=hunter2 leaked in this message")

    return app


@pytest.fixture
async def failing_client(failing_app: FastAPI):
    # raise_app_exceptions=False mirrors a real server: Starlette sends the
    # handler's 500 and then re-raises so the process can log it.
    async with (
        failing_app.router.lifespan_context(failing_app),
        AsyncClient(
            transport=ASGITransport(app=failing_app, raise_app_exceptions=False),
            base_url="http://test",
        ) as http_client,
    ):
        yield http_client


async def test_app_error_maps_to_its_status_and_code(failing_client) -> None:
    response = await failing_client.get("/boom/app-error")
    assert response.status_code == 404
    assert response.json()["error"] == {
        "code": "not_found",
        "message": "No document with id 42",
    }


async def test_details_are_included_when_provided(failing_client) -> None:
    response = await failing_client.get("/boom/conflict")
    assert response.status_code == 409
    body = response.json()["error"]
    assert body["code"] == "conflict"
    assert body["details"] == {"slug": "intro"}


async def test_unexpected_errors_never_leak_their_message(failing_client) -> None:
    """The whole point of the catch-all handler."""
    response = await failing_client.get("/boom/unexpected")
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert body["error"]["message"] == "An unexpected error occurred"
    assert "hunter2" not in response.text
    # The correlation id maps a user's report to the logged traceback.
    assert body["request_id"]
