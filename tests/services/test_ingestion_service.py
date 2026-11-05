"""IngestionService against a real Postgres (see ``db_session``)."""

import json
import logging
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import DocumentStatus
from app.db.models import DocumentMaster
from app.exceptions import ExtractionError
from app.helpers import extracted_key
from app.services.ingestion_service import IngestionService
from tests.fakes import InMemoryStorage

pytestmark = pytest.mark.integration

NOTES = b"# Leave policy\n\nStaff get twenty days.\n"


async def add_document(
    session: AsyncSession,
    storage: InMemoryStorage,
    status: DocumentStatus,
    data: bytes = NOTES,
) -> DocumentMaster:
    document_uuid = uuid4()
    storage_key = f"documents/user-1/{document_uuid}/original.txt"
    await storage.put(storage_key, data, "text/plain")
    document = DocumentMaster(
        uuid=document_uuid,
        user_uuid="user-1",
        filename="notes.txt",
        mime_type="text/plain",
        size_bytes=len(data),
        storage_key=storage_key,
        status=status,
    )
    session.add(document)
    await session.flush()
    return document


async def test_extracts_and_saves_the_docling_json(db_session: AsyncSession) -> None:
    storage = InMemoryStorage()
    document = await add_document(db_session, storage, DocumentStatus.QUEUED)

    await IngestionService(db_session, storage).ingest(document.uuid)

    data, content_type = storage.objects[extracted_key("user-1", str(document.uuid))]
    assert content_type == "application/json"
    texts = [item["text"] for item in json.loads(data)["texts"]]
    assert texts == ["Leave policy", "Staff get twenty days."]


async def test_unreadable_file_raises(db_session: AsyncSession) -> None:
    storage = InMemoryStorage()
    document = await add_document(
        db_session, storage, DocumentStatus.QUEUED, data=b"\n  \n"
    )

    with pytest.raises(ExtractionError):
        await IngestionService(db_session, storage).ingest(document.uuid)


async def test_missing_document_is_skipped(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    missing = uuid4()

    with caplog.at_level(logging.INFO):
        await IngestionService(db_session, InMemoryStorage()).ingest(missing)

    assert f"Document {missing} not found" in caplog.text


async def test_deleted_document_is_skipped(db_session: AsyncSession) -> None:
    storage = InMemoryStorage()
    document = await add_document(db_session, storage, DocumentStatus.DELETED)

    await IngestionService(db_session, storage).ingest(document.uuid)

    assert extracted_key("user-1", str(document.uuid)) not in storage.objects
