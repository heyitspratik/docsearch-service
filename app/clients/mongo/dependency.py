"""MongoDB dependency for getting the application database."""

from typing import Annotated

from fastapi import Depends
from pymongo.asynchronous.database import AsyncDatabase

from app.clients.mongo.client import MongoDocument, mongo_client


def get_mongo() -> AsyncDatabase[MongoDocument]:
    """Dependency for getting the shared application database."""
    return mongo_client.database


#: Annotate handler parameters with this instead of repeating ``Depends``.
MongoDep = Annotated[AsyncDatabase[MongoDocument], Depends(get_mongo)]
