"""Logger accessor."""

from __future__ import annotations

import logging


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a logger for the given module name.

    Records are tagged with the current request id by the filter installed in
    :func:`app.log.config.configure_logging`.
    """
    return logging.getLogger(name or "app")
