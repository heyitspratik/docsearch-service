"""Derived settings and boot-time validation."""

from typing import Any

import pytest
from pydantic import ValidationError

from app.settings import Settings


def make_settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_mongo_dsn_escapes_credentials() -> None:
    settings = make_settings(MONGO_USER="app", MONGO_PASSWORD="p@ss:word")

    assert settings.mongo_dsn == "mongodb://app:p%40ss%3Aword@localhost:27017"


def test_mongo_dsn_without_user_has_no_credentials() -> None:
    assert make_settings().mongo_dsn == "mongodb://localhost:27017"


def test_celery_broker_uses_redis_server_on_its_own_database() -> None:
    settings = make_settings(REDIS_HOST="redis", REDIS_PASSWORD="secret")

    assert settings.celery_broker_url == "redis://:secret@redis:6379/1"
    assert settings.redis_dsn == "redis://:secret@redis:6379/0"


def test_keycloak_issuer_uses_public_url_and_jwks_uses_internal_url() -> None:
    settings = make_settings(
        KEYCLOAK_URL="http://keycloak:8080",
        KEYCLOAK_PUBLIC_URL="http://localhost:8080/",
    )

    assert settings.keycloak_issuer == "http://localhost:8080/realms/docsearch"
    assert settings.keycloak_jwks_url == (
        "http://keycloak:8080/realms/docsearch/protocol/openid-connect/certs"
    )


def test_keycloak_issuer_falls_back_to_internal_url() -> None:
    settings = make_settings(KEYCLOAK_URL="http://localhost:8080")

    assert settings.keycloak_issuer == "http://localhost:8080/realms/docsearch"


def test_s3_enabled_without_keys_is_rejected() -> None:
    with pytest.raises(ValidationError, match="S3_ACCESS_KEY_ID"):
        make_settings(S3_ENABLED=True)


@pytest.mark.parametrize(
    ("public_key", "secret_key", "enabled"),
    [(None, None, False), ("pk", "", False), ("pk", "sk", True)],
)
def test_langfuse_enabled_only_with_both_keys(
    public_key: str | None, secret_key: str | None, enabled: bool
) -> None:
    settings = make_settings(
        LANGFUSE_PUBLIC_KEY=public_key, LANGFUSE_SECRET_KEY=secret_key
    )

    assert settings.langfuse_enabled is enabled
