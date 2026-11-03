"""File storage: where uploads and Docling JSON live, and the interface services use."""

from typing import Protocol


def original_key(user_uuid: str, document_uuid: str, extension: str) -> str:
    """Key of an uploaded file, e.g. ``documents/<user>/<doc>/original.pdf``.

    The filename is not part of the key: it can hold any character, and two
    uploads may share a name. It stays in ``document_master.filename``.
    """
    return f"documents/{user_uuid}/{document_uuid}/original{extension}"


def docling_json_key(user_uuid: str, document_uuid: str) -> str:
    """Key of a document's Docling JSON, next to its original."""
    return f"documents/{user_uuid}/{document_uuid}/docling.json"


class ObjectStorage(Protocol):
    """What services need from file storage. S3 in the app, a dict in tests."""

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        """Save ``data`` under ``key``, replacing anything already there."""
        ...

    async def get(self, key: str) -> bytes:
        """Return the bytes under ``key``, or raise ``NotFoundError``."""
        ...

    async def delete(self, key: str) -> None:
        """Remove ``key``. Deleting a missing key is not an error."""
        ...
