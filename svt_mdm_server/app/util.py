"""Small shared helpers: UTC time and token hashing."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone


def utcnow() -> datetime:
    """Timezone-aware current UTC time (avoids the deprecated naive utcnow)."""
    return datetime.now(timezone.utc)


def iso_z(dt: datetime | None) -> str | None:
    """ISO-8601 UTC string ending in ``Z``. Naive datetimes (SQLite drops the
    tzinfo on load) are assumed to already be UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def new_token(nbytes: int = 32) -> str:
    """Generate an opaque, URL-safe secret token."""
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    """Hash a token for at-rest storage. Tokens are high-entropy, so a plain
    SHA-256 is sufficient here — this is not a low-entropy user password."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def token_matches(token: str, stored_hash: str) -> bool:
    return secrets.compare_digest(hash_token(token), stored_hash)
