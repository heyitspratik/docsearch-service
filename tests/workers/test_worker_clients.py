"""worker_clients(): open the enabled clients for one task, always close them."""

import pytest

from app.settings import Settings
from app.workers import worker_clients as module
from app.workers.worker_clients import worker_clients


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace each client's open and close with a recorder."""
    recorded: list[str] = []
    clients = {
        "db": (module.db_client, "init_db"),
        "qdrant": (module.qdrant_client, "init_qdrant"),
        "mongo": (module.mongo_client, "init_mongo"),
        "s3": (module.s3_client, "init_s3"),
    }
    for name, (client, init_name) in clients.items():

        async def init(name: str = name) -> None:
            recorded.append(f"open {name}")

        async def close(name: str = name) -> None:
            recorded.append(f"close {name}")

        monkeypatch.setattr(client, init_name, init)
        monkeypatch.setattr(client, "close", close)
    return recorded


@pytest.fixture(autouse=True)
def enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Postgres, Qdrant and S3 on; MongoDB off."""
    settings = Settings(
        _env_file=None,
        DB_ENABLED=True,
        DB_USER="app",
        DB_PASSWORD="app",
        DB_NAME="app",
        QDRANT_ENABLED=True,
        MONGO_ENABLED=False,
        S3_ENABLED=True,
        S3_ACCESS_KEY_ID="key",
        S3_SECRET_ACCESS_KEY="secret",
    )
    monkeypatch.setattr(module, "get_settings", lambda: settings)


async def test_opens_enabled_clients_and_closes_them_in_reverse(
    calls: list[str],
) -> None:
    async with worker_clients():
        calls.append("task runs")

    assert calls == [
        "open db",
        "open qdrant",
        "open s3",
        "task runs",
        "close s3",
        "close qdrant",
        "close db",
    ]


async def test_clients_are_closed_even_when_the_task_fails(calls: list[str]) -> None:
    with pytest.raises(RuntimeError):
        async with worker_clients():
            raise RuntimeError("Docling crashed")

    assert calls[-3:] == ["close s3", "close qdrant", "close db"]
