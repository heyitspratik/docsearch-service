"""IngestionService against a real Postgres (see ``db_session``)."""

import logging
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import DocumentStatus
from app.db.models import DocumentMaster
from app.services.ingestion_service import IngestionService

pytestmark = pytest.mark.integration


async def add_document(session: AsyncSession, status: DocumentStatus) -> DocumentMaster:
    document = DocumentMaster(
        uuid=uuid4(),
        user_uuid="user-1",
        filename="report.pdf",
        mime_type="application/pdf",
        size_bytes=10,
        storage_key=f"documents/user-1/{uuid4()}/original.pdf",
        status=status,
    )
    session.add(document)
    await session.flush()
    return document


async def test_reads_a_queued_document(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    document = await add_document(db_session, DocumentStatus.QUEUED)

    with caplog.at_level(logging.INFO):
        await IngestionService(db_session).ingest(document.uuid)

    assert "report.pdf, status QUEUED" in caplog.text


async def test_missing_document_is_skipped(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    missing = uuid4()

    with caplog.at_level(logging.INFO):
        await IngestionService(db_session).ingest(missing)

    assert f"Document {missing} not found" in caplog.text


async def test_deleted_document_is_skipped(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    document = await add_document(db_session, DocumentStatus.DELETED)

    with caplog.at_level(logging.INFO):
        await IngestionService(db_session).ingest(document.uuid)

    assert "was deleted; skipping ingest" in caplog.text
