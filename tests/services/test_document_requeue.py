"""DocumentService.requeue_stuck_documents against real Postgres."""

from collections.abc import Iterable
from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import DocumentStatus
from app.db.models import DocumentMaster
from app.services import DocumentService, document_service
from tests.api.test_document_read import add_document

pytestmark = pytest.mark.integration


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list[UUID]:
    """Documents sent to ingestion, instead of real Celery jobs."""
    sent: list[UUID] = []

    def record(document_uuids: Iterable[UUID]) -> None:
        sent.extend(document_uuids)

    monkeypatch.setattr(document_service, "enqueue_ingestion", record)
    return sent


async def add_aged(
    session: AsyncSession, status: DocumentStatus, minutes_ago: int
) -> DocumentMaster:
    """A document last updated ``minutes_ago`` by the database clock."""
    document = await add_document(session, f"{status.name.lower()}.pdf", status)
    await session.execute(
        update(DocumentMaster)
        .where(DocumentMaster.id == document.id)
        .values(updated_at=func.now() - timedelta(minutes=minutes_ago))
    )
    return document


async def test_requeues_only_documents_queued_too_long_oldest_first(
    db_session: AsyncSession, enqueued: list[UUID]
) -> None:
    newer_stuck = await add_aged(db_session, DocumentStatus.QUEUED, minutes_ago=10)
    older_stuck = await add_aged(db_session, DocumentStatus.QUEUED, minutes_ago=90)
    await add_aged(db_session, DocumentStatus.QUEUED, minutes_ago=2)  # just uploaded
    for status in (
        DocumentStatus.EXTRACTING,
        DocumentStatus.READY,
        DocumentStatus.FAILED,
        DocumentStatus.DELETED,
    ):
        await add_aged(db_session, status, minutes_ago=90)

    requeued = await DocumentService(db_session).requeue_stuck_documents(minutes=5)

    assert requeued == [older_stuck.uuid, newer_stuck.uuid]
    assert enqueued == [older_stuck.uuid, newer_stuck.uuid]


async def test_nothing_stuck_sends_nothing(
    db_session: AsyncSession, enqueued: list[UUID]
) -> None:
    await add_aged(db_session, DocumentStatus.QUEUED, minutes_ago=2)

    requeued = await DocumentService(db_session).requeue_stuck_documents(minutes=5)

    assert requeued == []
    assert enqueued == []
