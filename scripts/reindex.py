"""Re-index every ready document with another dense model, then switch the alias.

Run it in the worker container, which has Docling's tokenizers and the models:

    docker compose exec worker python -m scripts.reindex --model BAAI/bge-small-en-v1.5

Searches keep working while it runs. After the switch, set the new model in
``.env`` and restart the API and worker, as the script prints.
"""

import argparse
import asyncio

from app.clients.database.client import db_client
from app.clients.qdrant.client import qdrant_client
from app.clients.qdrant.service import QdrantVectorStore
from app.clients.s3.client import s3_client
from app.clients.s3.service import S3Storage
from app.constants import DatabaseMessages
from app.helpers.embedding_helper import FastEmbedDense, get_sparse_embedder
from app.helpers.model_spec_helper import MODEL_SPECS, get_model_spec
from app.log import configure_logging, get_logger
from app.schemas.response import ReindexResult
from app.services.reindex_service import ReindexService
from app.settings import get_settings
from app.workers.worker_clients import worker_clients

logger = get_logger(__name__)


def parse_args() -> argparse.Namespace:
    """``--model`` (required) and ``--keep-old``."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--model", required=True, choices=list(MODEL_SPECS), help="New dense model"
    )
    parser.add_argument(
        "--keep-old",
        action="store_true",
        help="Keep the old collection, so the alias can be pointed back",
    )
    return parser.parse_args()


async def reindex(model: str, keep_old: bool) -> ReindexResult:
    """Open the clients, run the service, close them."""
    settings = get_settings()
    spec = get_model_spec(model)
    async with worker_clients():
        storage = S3Storage(s3_client.client, settings.S3_BUCKET)
        live = QdrantVectorStore(qdrant_client.client, settings.QDRANT_COLLECTION_ALIAS)
        dense = FastEmbedDense(
            spec, settings.EMBEDDING_CACHE_DIR, settings.EMBEDDING_BATCH_SIZE
        )
        async for session in db_client.get_session():
            return await ReindexService(
                session, storage, dense, get_sparse_embedder(), live
            ).run(spec, keep_old=keep_old)
    # get_session always yields once; this only satisfies the type checker.
    raise RuntimeError(DatabaseMessages.SESSION_FACTORY_NOT_INITIALIZED)


def main() -> None:
    """Run the re-index and say what to do next."""
    args = parse_args()
    configure_logging(get_settings())
    result = asyncio.run(reindex(args.model, args.keep_old))
    kept = "kept" if result.old_collection_kept else "deleted"
    logger.info(
        f"Alias now points to {result.new_collection}: {result.documents} "
        f"documents, {result.chunks} chunks ({result.caught_up} caught up, "
        f"{result.removed} removed). Old collection {result.old_collection}: {kept}"
    )
    logger.info(
        f"Next, so searches use the new model: set "
        f"EMBEDDING_DENSE_MODEL={result.model} in .env, then run "
        f"'docker compose up -d api worker'"
    )


if __name__ == "__main__":
    main()
