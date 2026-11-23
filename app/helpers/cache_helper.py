"""Search cache keys: which query vectors and results count as the same."""

import hashlib
from collections.abc import Sequence
from uuid import UUID

from app.constants import CACHE_KEY_PREFIX


def normalize_query(query: str) -> str:
    """Lowercase, trim and collapse spaces: "Leave  days " matches "leave days"."""
    return " ".join(query.lower().split())


def digest(*parts: str) -> str:
    """A short, fixed-length hash of the parts; keys never contain the query text."""
    joined = "\x1f".join(parts)
    return hashlib.sha256(joined.encode()).hexdigest()[:32]


def vector_key(kind: str, model: str, normalized_query: str) -> str:
    """Key for one query's vector. Shared by all users: it depends only on the text."""
    return f"{CACHE_KEY_PREFIX}:vec:{kind}:{digest(model, normalized_query)}"


def result_key(
    *,
    pipeline: str,
    user_uuid: str,
    search_type: str,
    document_ids: Sequence[UUID] | None,
    fingerprint: str,
    normalized_query: str,
) -> str:
    """Key for one user's search results; a new fingerprint makes old keys miss."""
    ids = ",".join(sorted(str(d) for d in document_ids or []))
    return (
        f"{CACHE_KEY_PREFIX}:res:{user_uuid}:"
        f"{digest(pipeline, search_type, ids, fingerprint, normalized_query)}"
    )
