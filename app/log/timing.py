"""A decorator that logs how long a function took."""

import functools
import inspect
import time
from collections.abc import Awaitable, Callable
from typing import Any, cast

from app.log.logger import get_logger


def log_duration[**P, R](label: str) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Log ``<label> took <n> ms`` after each call, sync or async, even on error.

    The line uses the decorated function's module logger, so it reads like the
    module's other log lines.
    """

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        logger = get_logger(func.__module__)

        def log(started: float) -> None:
            logger.info(f"{label} took {(time.perf_counter() - started) * 1000:.0f} ms")

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
                started = time.perf_counter()
                try:
                    # Awaiting is what takes the time; calling only makes a coroutine.
                    return await cast(Awaitable[Any], func(*args, **kwargs))
                finally:
                    log(started)

            return cast(Callable[P, R], async_wrapper)

        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            started = time.perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                log(started)

        return wrapper

    return decorator
