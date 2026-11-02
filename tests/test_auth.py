"""Token verification and the CurrentUser dependency.

Tokens are signed with an RSA key made for the test run, and the verifier
reads its public half from a fake JWKS, so no Keycloak is needed.
"""

import time
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from httpx import AsyncClient
from jwt import PyJWKClient
from jwt.algorithms import RSAAlgorithm

from app.exceptions import ServiceUnavailableError, UnauthorizedError
from app.helpers import AuthenticatedUser, JWTVerifier, get_current_user
from app.helpers.auth_helper import get_verifier

ISSUER = "http://keycloak.test/realms/docsearch"
AUDIENCE = "docsearch-api"
KID = "test-key"
ME_URL = "/api/v1/users/me"

PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class FakeJWKClient(PyJWKClient):
    """Serves a fixed key set instead of fetching one over HTTP."""

    def __init__(self, jwks: dict[str, Any]) -> None:
        super().__init__("http://keycloak.test/certs", cache_jwk_set=False)
        self._jwks = jwks

    def fetch_data(self) -> Any:
        return self._jwks


class UnreachableJWKClient(PyJWKClient):
    """Behaves like Keycloak being down."""

    def __init__(self) -> None:
        super().__init__("http://keycloak.test/certs", cache_jwk_set=False)

    def fetch_data(self) -> Any:
        raise jwt.PyJWKClientConnectionError("connection refused")


def make_jwks() -> dict[str, Any]:
    jwk = RSAAlgorithm.to_jwk(PRIVATE_KEY.public_key(), as_dict=True)
    return {"keys": [{**jwk, "kid": KID, "use": "sig", "alg": "RS256"}]}


def make_token(
    key: Any = PRIVATE_KEY, kid: str = KID, algorithm: str = "RS256", **claims: Any
) -> str:
    """Sign a token that passes every check unless a claim is overridden."""
    now = int(time.time())
    payload = {
        "sub": "user-123",
        "preferred_username": "demo",
        "email": "demo@example.com",
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + 300,
        **claims,
    }
    return jwt.encode(payload, key, algorithm=algorithm, headers={"kid": kid})


@pytest.fixture
def verifier() -> JWTVerifier:
    return JWTVerifier(FakeJWKClient(make_jwks()), issuer=ISSUER, audience=AUDIENCE)


# --- JWTVerifier ---


async def test_valid_token_returns_its_claims(verifier: JWTVerifier) -> None:
    claims = await verifier.verify(make_token())
    assert claims["sub"] == "user-123"


async def test_expired_token_is_rejected(verifier: JWTVerifier) -> None:
    past = int(time.time()) - 600
    with pytest.raises(UnauthorizedError, match="expired"):
        await verifier.verify(make_token(iat=past, exp=past + 60))


@pytest.mark.parametrize(
    "claims",
    [
        pytest.param({"aud": "some-other-api"}, id="wrong audience"),
        pytest.param({"iss": "http://evil.test/realms/docsearch"}, id="wrong issuer"),
    ],
)
async def test_token_for_another_service_is_rejected(
    verifier: JWTVerifier, claims: dict[str, Any]
) -> None:
    with pytest.raises(UnauthorizedError, match="Invalid access token"):
        await verifier.verify(make_token(**claims))


async def test_token_signed_by_another_key_is_rejected(verifier: JWTVerifier) -> None:
    """Right kid, wrong private key: the signature check must fail."""
    with pytest.raises(UnauthorizedError, match="Invalid access token"):
        await verifier.verify(make_token(key=OTHER_KEY))


async def test_unknown_key_id_is_rejected(verifier: JWTVerifier) -> None:
    with pytest.raises(UnauthorizedError, match="Invalid access token"):
        await verifier.verify(make_token(kid="not-in-the-realm"))


async def test_hs256_token_is_rejected(verifier: JWTVerifier) -> None:
    """Only RS256 is allowed, so a token cannot pick a shared-secret algorithm."""
    token = make_token(key="a-guessable-secret-of-32-bytes!!", algorithm="HS256")
    with pytest.raises(UnauthorizedError, match="Invalid access token"):
        await verifier.verify(token)


async def test_token_without_sub_is_rejected(verifier: JWTVerifier) -> None:
    token = make_token()
    payload = jwt.decode(token, options={"verify_signature": False})
    del payload["sub"]
    no_sub = jwt.encode(payload, PRIVATE_KEY, algorithm="RS256", headers={"kid": KID})
    with pytest.raises(UnauthorizedError, match="Invalid access token"):
        await verifier.verify(no_sub)


async def test_garbage_token_is_rejected(verifier: JWTVerifier) -> None:
    with pytest.raises(UnauthorizedError, match="Invalid access token"):
        await verifier.verify("not-a-jwt")


async def test_keycloak_down_is_503_not_401() -> None:
    """A Keycloak outage is our problem, not a bad token, so it must not be 401."""
    verifier = JWTVerifier(UnreachableJWKClient(), issuer=ISSUER, audience=AUDIENCE)
    with pytest.raises(ServiceUnavailableError):
        await verifier.verify(make_token())


# --- GET /users/me through the real dependency ---


@pytest.fixture
def auth_app(app: FastAPI, verifier: JWTVerifier) -> FastAPI:
    """App whose CurrentUser checks tokens against the fake JWKS."""

    async def test_verifier() -> JWTVerifier:
        return verifier

    app.dependency_overrides[get_verifier] = test_verifier
    return app


async def test_me_without_token_is_401(auth_app: FastAPI, client: AsyncClient) -> None:
    response = await client.get(ME_URL)
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Missing bearer token"


async def test_me_with_bad_token_is_401(auth_app: FastAPI, client: AsyncClient) -> None:
    response = await client.get(
        ME_URL, headers={"Authorization": f"Bearer {make_token(aud='other')}"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Invalid access token"


async def test_me_returns_the_tokens_user(
    auth_app: FastAPI, client: AsyncClient
) -> None:
    response = await client.get(
        ME_URL, headers={"Authorization": f"Bearer {make_token()}"}
    )
    assert response.status_code == 200
    assert response.json()["payload"] == {
        "id": "user-123",
        "username": "demo",
        "email": "demo@example.com",
    }


# --- Overriding the user, the pattern other endpoint tests use ---


async def test_current_user_can_be_overridden(
    app: FastAPI, client: AsyncClient
) -> None:
    """Endpoint tests skip tokens entirely by replacing get_current_user."""

    async def fixed_user() -> AuthenticatedUser:
        return AuthenticatedUser(id="fixed-id", username="tester")

    app.dependency_overrides[get_current_user] = fixed_user
    response = await client.get(ME_URL)
    assert response.status_code == 200
    assert response.json()["payload"]["id"] == "fixed-id"
