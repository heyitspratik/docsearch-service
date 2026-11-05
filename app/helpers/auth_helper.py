"""Login checks: verifying Keycloak access tokens and the CurrentUser dependency."""

import asyncio
from functools import lru_cache
from typing import Annotated, Any

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWK, PyJWKClient
from pydantic import BaseModel, ConfigDict

from app.constants import (
    JWKS_TIMEOUT_SECONDS,
    JWT_ALGORITHMS,
    JWT_REQUIRED_CLAIMS,
    AuthMessages,
)
from app.exceptions import ServiceUnavailableError, UnauthorizedError
from app.log import get_logger
from app.settings import get_settings

logger = get_logger(__name__)


class AuthenticatedUser(BaseModel):
    """Who is making the request.

    ``id`` is the token's ``sub``: Keycloak's stable user ID, and the value
    every owner column and filter uses. The username and email can change.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    username: str | None = None
    email: str | None = None

    @classmethod
    def from_claims(cls, claims: dict[str, Any]) -> "AuthenticatedUser":
        """Build the user from verified token claims."""
        return cls(
            id=claims["sub"],
            username=claims.get("preferred_username"),
            email=claims.get("email"),
        )


class JWTVerifier:
    """Checks a token's signature, expiry, issuer and audience.

    The keys come from ``PyJWKClient``, which caches the key set and fetches
    it again when a token names a key it has not seen (Keycloak rotated its
    keys), at most once per cooldown.
    """

    def __init__(self, jwks_client: PyJWKClient, issuer: str, audience: str) -> None:
        """Initialize the verifier.

        Args:
            jwks_client: Source of the realm's public signing keys.
            issuer: The ``iss`` claim tokens must carry.
            audience: The ``aud`` value tokens must include.
        """
        self._jwks_client = jwks_client
        self._issuer = issuer
        self._audience = audience

    async def verify(self, token: str) -> dict[str, Any]:
        """Return the token's claims, or raise if it cannot be trusted.

        Raises:
            UnauthorizedError: The token is malformed, expired, signed by an
                unknown key, or meant for another issuer or audience.
            ServiceUnavailableError: Keycloak's keys could not be fetched.
        """
        signing_key = await self._signing_key(token)
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                key=signing_key.key,
                algorithms=JWT_ALGORITHMS,
                audience=self._audience,
                issuer=self._issuer,
                options={"require": JWT_REQUIRED_CLAIMS},
            )
        except jwt.ExpiredSignatureError as e:
            raise UnauthorizedError(AuthMessages.TOKEN_EXPIRED) from e
        except jwt.PyJWTError as e:
            logger.info(f"Rejected token: {e!s}")
            raise UnauthorizedError(AuthMessages.INVALID_TOKEN) from e
        return claims

    async def _signing_key(self, token: str) -> PyJWK:
        """Find the public key named by the token's ``kid`` header."""
        try:
            # A fetch uses blocking urllib, so it runs off the event loop.
            return await asyncio.to_thread(
                self._jwks_client.get_signing_key_from_jwt, token
            )
        except jwt.PyJWKClientConnectionError as e:
            logger.warning(f"Could not fetch Keycloak signing keys: {e!s}")
            raise ServiceUnavailableError(AuthMessages.KEYS_UNAVAILABLE) from e
        except jwt.PyJWTError as e:
            # Malformed header, or a key ID the realm does not have.
            logger.info(f"Rejected token: {e!s}")
            raise UnauthorizedError(AuthMessages.INVALID_TOKEN) from e


@lru_cache(maxsize=1)
def get_jwt_verifier() -> JWTVerifier:
    """Return the process-wide verifier, built from settings on first use."""
    settings = get_settings()
    cache_seconds = settings.KEYCLOAK_JWKS_CACHE_SECONDS
    jwks_client = PyJWKClient(
        settings.keycloak_jwks_url,
        # PyJWKClient rejects a lifespan of 0; 0 here means fetch every time.
        cache_jwk_set=cache_seconds > 0,
        lifespan=cache_seconds or 1,
        timeout=JWKS_TIMEOUT_SECONDS,
    )
    return JWTVerifier(
        jwks_client,
        issuer=settings.keycloak_issuer,
        audience=settings.KEYCLOAK_AUDIENCE,
    )


# auto_error=False: a missing header reaches get_current_user, which raises
# UnauthorizedError so the response uses the standard error shape. The scheme
# also adds the "Authorize" button to the API docs.
bearer_scheme = HTTPBearer(auto_error=False)


async def get_verifier() -> JWTVerifier:
    """Dependency for getting the shared token verifier."""
    return get_jwt_verifier()


async def get_current_user(
    verifier: Annotated[JWTVerifier, Depends(get_verifier)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> AuthenticatedUser:
    """Return the user named by the request's bearer token.

    Raises:
        UnauthorizedError: No bearer token, or one that fails verification.
    """
    if credentials is None:
        raise UnauthorizedError(AuthMessages.MISSING_TOKEN)
    claims = await verifier.verify(credentials.credentials)
    return AuthenticatedUser.from_claims(claims)


#: Annotate handler parameters with this to require login, for example
#: ``async def list_documents(self, user: CurrentUser)``.
CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]
