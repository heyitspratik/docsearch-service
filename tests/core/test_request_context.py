"""Correlation id middleware."""

from httpx import AsyncClient


async def test_response_carries_a_request_id(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.headers.get("x-request-id")


async def test_incoming_request_id_is_preserved(client: AsyncClient) -> None:
    """An id from the gateway must survive, or a trace breaks at this hop."""
    response = await client.get("/health", headers={"X-Request-ID": "trace-abc-123"})
    assert response.headers["x-request-id"] == "trace-abc-123"


async def test_each_request_gets_a_distinct_id(client: AsyncClient) -> None:
    first = await client.get("/health")
    second = await client.get("/health")
    assert first.headers["x-request-id"] != second.headers["x-request-id"]


async def test_process_time_header_is_present(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert float(response.headers["x-process-time"]) >= 0
