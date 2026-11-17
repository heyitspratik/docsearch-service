"""IngestLock against a real Redis (Celery's database)."""

import logging
from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from app.constants import INGEST_LOCK_SECONDS
from app.workers import ingest_lock
from app.workers.ingest_lock import IngestLock

pytestmark = pytest.mark.integration


@pytest.fixture
def document_uuid() -> Iterator[UUID]:
    """A fresh document; its lock key is removed after the test."""
    redis = ingest_lock._redis()
    try:
        redis.ping()
    except RedisConnectionError as e:
        pytest.skip(f"Redis not reachable ({type(e).__name__}); set REDIS_*")
    uuid = uuid4()
    yield uuid
    redis.delete(f"ingest:{uuid}")


def test_only_one_run_holds_the_lock_until_it_releases(document_uuid: UUID) -> None:
    first, second = IngestLock(document_uuid), IngestLock(document_uuid)

    assert first.acquire() is True
    assert second.acquire() is False

    first.release()

    assert second.acquire() is True


def test_seconds_left_counts_down_from_the_lock_expiry(document_uuid: UUID) -> None:
    lock = IngestLock(document_uuid)
    assert lock.seconds_left() == 0  # not taken yet

    lock.acquire()

    assert INGEST_LOCK_SECONDS - 2 <= lock.seconds_left() <= INGEST_LOCK_SECONDS


def test_an_expired_lock_is_not_released_from_its_new_owner(
    document_uuid: UUID, caplog: pytest.LogCaptureFixture
) -> None:
    slow, newcomer = IngestLock(document_uuid), IngestLock(document_uuid)
    slow.acquire()
    ingest_lock._redis().delete(f"ingest:{document_uuid}")  # as if it expired
    newcomer.acquire()

    with caplog.at_level(logging.WARNING):
        slow.release()

    assert f"Ingest lock of {document_uuid} expired" in caplog.text
    assert IngestLock(document_uuid).acquire() is False  # the newcomer still holds it
