"""log_duration: one timing line per call, for async and normal functions."""

import logging

import pytest

from app.log import log_duration


@log_duration("Async step")
async def async_step(x: int) -> int:
    """Doubles x."""
    return x * 2


@log_duration("Sync step")
def sync_step(x: int) -> int:
    return x + 1


@log_duration("Failing step")
async def failing_step() -> None:
    raise ValueError("boom")


async def test_times_an_async_function(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger=__name__):
        assert await async_step(4) == 8

    (message,) = caplog.messages
    assert message.startswith("Async step took ")
    assert message.endswith(" ms")


def test_times_a_normal_function(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger=__name__):
        assert sync_step(1) == 2

    assert caplog.messages[0].startswith("Sync step took ")


async def test_still_logs_when_the_function_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO, logger=__name__), pytest.raises(ValueError):
        await failing_step()

    assert caplog.messages[0].startswith("Failing step took ")


def test_keeps_the_function_name_and_docstring() -> None:
    assert async_step.__name__ == "async_step"
    assert async_step.__doc__ == "Doubles x."


async def test_logs_under_the_decorated_functions_module(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO, logger=__name__):
        await async_step(1)

    assert caplog.records[0].name == __name__
