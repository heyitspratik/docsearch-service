"""S3 file storage and the bucket key layout, without a running server."""

from typing import Any, Self

import pytest
from botocore.exceptions import ClientError

from app.clients.s3.service import S3Storage
from app.exceptions import NotFoundError
from app.helpers import extracted_key, original_key


class StubBody:
    """Stands in for aioboto3's streaming body, which is used with ``async with``."""

    def __init__(self, data: bytes) -> None:
        self.data = data

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def read(self) -> bytes:
        return self.data


class StubS3Client:
    """The three aioboto3 calls S3Storage makes, backed by a dict.

    Takes ``**kwargs`` because boto's argument names (``Bucket``, ``Key``) are
    capitalised.
    """

    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], tuple[bytes, str]] = {}

    async def put_object(self, **kwargs: Any) -> None:
        key = (kwargs["Bucket"], kwargs["Key"])
        self.objects[key] = (kwargs["Body"], kwargs["ContentType"])

    async def get_object(self, **kwargs: Any) -> dict[str, Any]:
        key = (kwargs["Bucket"], kwargs["Key"])
        if key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": StubBody(self.objects[key][0])}

    async def delete_object(self, **kwargs: Any) -> None:
        self.objects.pop((kwargs["Bucket"], kwargs["Key"]), None)


@pytest.fixture
def client() -> StubS3Client:
    return StubS3Client()


@pytest.fixture
def storage(client: StubS3Client) -> S3Storage:
    return S3Storage(client, "docsearch")


def test_keys_group_a_documents_files_under_one_folder() -> None:
    assert original_key("user-1", "doc-1", ".pdf") == (
        "documents/user-1/doc-1/original.pdf"
    )
    assert extracted_key("user-1", "doc-1") == "documents/user-1/doc-1/extracted.json"


async def test_put_then_get_returns_the_same_bytes(
    storage: S3Storage, client: StubS3Client
) -> None:
    await storage.put("a/b.pdf", b"%PDF-1.7", "application/pdf")

    assert await storage.get("a/b.pdf") == b"%PDF-1.7"
    assert client.objects[("docsearch", "a/b.pdf")][1] == "application/pdf"


async def test_get_missing_key_raises_not_found(storage: S3Storage) -> None:
    with pytest.raises(NotFoundError) as error:
        await storage.get("a/missing.pdf")

    assert "a/missing.pdf" in str(error.value)


async def test_other_s3_errors_are_not_hidden(
    storage: S3Storage, client: StubS3Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def access_denied(**_: Any) -> None:
        raise ClientError({"Error": {"Code": "AccessDenied"}}, "GetObject")

    monkeypatch.setattr(client, "get_object", access_denied)

    with pytest.raises(ClientError):
        await storage.get("a/b.pdf")


async def test_delete_removes_and_tolerates_missing_key(storage: S3Storage) -> None:
    await storage.put("a/b.pdf", b"x", "application/pdf")

    await storage.delete("a/b.pdf")
    await storage.delete("a/b.pdf")

    with pytest.raises(NotFoundError):
        await storage.get("a/b.pdf")
