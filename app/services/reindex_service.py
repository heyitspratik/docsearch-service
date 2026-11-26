"""Re-index: rebuild every ready document's vectors with another dense model."""

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID

from docling_core.types.doc.document import DoclingDocument
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.qdrant.service import QdrantVectorStore
from app.constants import REINDEX_CATCH_UP_MARGIN_SECONDS, ReindexMessages
from app.db.services import DocumentDBService
from app.exceptions import NotFoundError
from app.helpers import ModelSpec, ObjectStorage, extracted_key
from app.helpers.chunking_helper import Chunk, chunk_document
from app.helpers.embedding_helper import DenseEmbedder, SparseEmbedder
from app.helpers.vector_store_helper import collection_name
from app.log import get_logger, log_duration
from app.schemas.response import ReadyDocument, ReindexResult
from app.services.ingestion_service import IngestionService

logger = get_logger(__name__)


class ReindexService:
    """Builds a new model's collection next to the live one, then switches the alias.

    Searches keep using the old collection until the switch, which is a single
    Qdrant call. Docling does not run again: each document is re-chunked from
    its saved Docling JSON with the new model's tokenizer and token limit.
    """

    def __init__(
        self,
        session: AsyncSession,
        storage: ObjectStorage,
        dense: DenseEmbedder,
        sparse: SparseEmbedder,
        live: QdrantVectorStore,
    ) -> None:
        self.session = session
        self.document_db = DocumentDBService(session)
        self.storage = storage
        self.dense = dense
        self.sparse = sparse
        self.live = live

    @log_duration("Re-index")
    async def run(self, spec: ModelSpec, *, keep_old: bool = False) -> ReindexResult:
        """Index every ready document for ``spec``, switch the alias, drop the old.

        ``dense`` must be the embedder for ``spec``.

        Raises:
            ValueError: The alias already points to this model's collection.
            RuntimeError: A ready document has no saved Docling JSON; nothing
                was switched, so searches are unaffected.
        """
        old = await self.live.alias_target()
        new = collection_name(self.live.alias, spec.name)
        if old == new:
            raise ValueError(
                ReindexMessages.ALREADY_ON_MODEL.format(
                    alias=self.live.alias, collection=new
                )
            )
        # A stopped earlier run may have left this collection; start it fresh.
        await self.live.delete_collection(new)
        await self.live.create_collection(new, spec)
        target = QdrantVectorStore(self.live.client, new)

        # Documents that become ready from here on are picked up by the catch-up.
        started = datetime.now(UTC)
        indexed: dict[UUID, tuple[datetime, list[Chunk]]] = {}
        # Documents with no saved extraction, with the updated_at they had.
        missing: dict[UUID, datetime] = {}
        ready = await self.document_db.list_all_ready()
        await self._index(ready, spec, target, indexed, missing)
        caught_up = await self._catch_up(started, spec, target, indexed, missing)

        # Indexed, then deleted or failed during the run: not searchable any more.
        ready_now = {row.uuid for row in await self.document_db.list_all_ready()}
        removed = indexed.keys() - ready_now
        for document_uuid in removed:
            await target.delete_document(document_uuid)
            del indexed[document_uuid]
        still_missing = missing.keys() & ready_now
        if still_missing:
            raise RuntimeError(
                ReindexMessages.EXTRACTION_MISSING.format(
                    count=len(still_missing),
                    documents=", ".join(sorted(map(str, still_missing))),
                )
            )

        await self._save_chunks(spec, indexed)
        await self.live.switch_alias(new)
        await self.session.commit()
        if old is not None and not keep_old:
            await self.live.delete_collection(old)

        return ReindexResult(
            model=spec.name,
            old_collection=old,
            new_collection=new,
            documents=len(indexed),
            chunks=sum(len(chunks) for _, chunks in indexed.values()),
            caught_up=caught_up,
            removed=len(removed),
            old_collection_kept=old is not None and keep_old,
        )

    async def _catch_up(
        self,
        started: datetime,
        spec: ModelSpec,
        target: QdrantVectorStore,
        indexed: dict[UUID, tuple[datetime, list[Chunk]]],
        missing: dict[UUID, datetime],
    ) -> int:
        """Index documents that became ready, or were updated, during the run.

        Repeats until a pass finds nothing new. A document already tried, indexed
        or missing, is tried again only if its row changed since.
        """
        since = started - timedelta(seconds=REINDEX_CATCH_UP_MARGIN_SECONDS)
        caught_up = 0
        while True:
            changed = [
                row
                for row in await self.document_db.list_all_ready(changed_since=since)
                if self._changed_since_tried(row, indexed, missing)
            ]
            if not changed:
                return caught_up
            await self._index(changed, spec, target, indexed, missing)
            caught_up += len(changed)

    @staticmethod
    def _changed_since_tried(
        row: ReadyDocument,
        indexed: dict[UUID, tuple[datetime, list[Chunk]]],
        missing: dict[UUID, datetime],
    ) -> bool:
        """True if never tried, or updated after the last try."""
        if row.uuid in indexed:
            return row.updated_at > indexed[row.uuid][0]
        if row.uuid in missing:
            return row.updated_at > missing[row.uuid]
        return True

    async def _index(
        self,
        rows: Sequence[ReadyDocument],
        spec: ModelSpec,
        target: QdrantVectorStore,
        indexed: dict[UUID, tuple[datetime, list[Chunk]]],
        missing: dict[UUID, datetime],
    ) -> None:
        """Re-chunk, embed and write each document into the new collection."""
        for row in rows:
            chunks = await self._index_document(row, spec, target)
            if chunks is None:
                missing[row.uuid] = row.updated_at
            else:
                missing.pop(row.uuid, None)
                indexed[row.uuid] = (row.updated_at, chunks)

    async def _index_document(
        self, row: ReadyDocument, spec: ModelSpec, target: QdrantVectorStore
    ) -> list[Chunk] | None:
        """One document into the new collection; None if its JSON is missing."""
        try:
            data = await self.storage.get(extracted_key(row.user_uuid, str(row.uuid)))
        except NotFoundError:
            logger.warning(f"Document {row.uuid} has no saved extraction; skipped")
            return None
        document = DoclingDocument.model_validate_json(data)
        # Chunking and embedding are CPU work; threads keep the event loop free.
        chunks = await asyncio.to_thread(chunk_document, document, spec.name)
        texts = [chunk.embed_text for chunk in chunks]
        dense = await asyncio.to_thread(self.dense.embed_passages, texts)
        sparse = await asyncio.to_thread(self.sparse.embed_passages, texts)
        # A run stopped halfway may have left this document's points; start clean.
        await target.delete_document(row.uuid)
        await target.upsert(
            IngestionService.chunk_points(
                row.uuid, row.user_uuid, row.filename, spec.name, chunks, dense, sparse
            )
        )
        logger.info(f"Re-indexed document {row.uuid}: {len(chunks)} chunks")
        return chunks

    async def _save_chunks(
        self, spec: ModelSpec, indexed: dict[UUID, tuple[datetime, list[Chunk]]]
    ) -> None:
        """Replace each document's chunk rows and model; committed with the switch."""
        ids = {row.uuid: row.id for row in await self.document_db.list_all_ready()}
        for document_uuid, (_, chunks) in indexed.items():
            document_id = ids.get(document_uuid)
            if document_id is None:
                # Deleted in the last moments; the purge removes its rows anyway.
                continue
            await self.document_db.replace_chunks(
                document_id,
                [IngestionService.chunk_row(document_id, chunk) for chunk in chunks],
            )
            await self.document_db.update_document(
                document_uuid, chunk_count=len(chunks), embedding_model=spec.name
            )
