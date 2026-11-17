"""One ingest run per document at a time, with a lock in Celery's Redis."""

from functools import cache
from math import ceil
from typing import cast
from uuid import UUID

from redis import Redis
from redis.exceptions import LockError
from redis.lock import Lock

from app.constants import INGEST_LOCK_SECONDS
from app.log import get_logger
from app.settings import get_settings

logger = get_logger(__name__)


@cache
def _redis() -> Redis:
    """One client per worker process, made on first use (after the fork)."""
    return Redis.from_url(get_settings().celery_broker_url)


class IngestLock:
    """The lock ``ingest:<document_uuid>``, owned by one task run.

    It expires after ``INGEST_LOCK_SECONDS``, so a run that dies cannot block
    the document forever. Its random token makes sure a run only ever releases
    its own lock.
    """

    def __init__(self, document_uuid: UUID) -> None:
        self.document_uuid = document_uuid
        self.key = f"ingest:{document_uuid}"
        self._lock = Lock(
            _redis(), self.key, timeout=INGEST_LOCK_SECONDS, blocking=False
        )

    def acquire(self) -> bool:
        """Take the lock if nobody holds it; never waits."""
        return bool(self._lock.acquire())

    def release(self) -> None:
        """Release it, unless it expired and another run holds it now."""
        try:
            self._lock.release()
        except LockError:
            logger.warning(
                f"Ingest lock of {self.document_uuid} expired before the run ended"
            )

    def seconds_left(self) -> int:
        """Seconds until the lock expires; 0 if it is already gone."""
        milliseconds = cast(int, _redis().pttl(self.key))
        # -2: no such key (released meanwhile).
        return max(0, ceil(milliseconds / 1000))
