"""Session tokens and service tokens.

A session token is a compact signed token (JWS, HMAC-SHA-256). It names the user and
the moment it was issued, and nothing else that could go stale: roles are read from the
database on every request.

A service token is 32 random bytes with a prefix that tells the two kinds apart. Only
its SHA-256 hash is stored.
"""

import hashlib
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import jwt

from hirdir.ids import new_hid

ALGORITHM = "HS256"
KEY_BYTES = 32
SERVICE_PREFIX = "hsv_"


class InvalidToken(Exception):
    """The token is malformed, has a bad signature, or has expired."""


@dataclass(frozen=True)
class SessionClaims:
    """What a valid session token says."""

    user_hid: str
    issued_ms: int
    expires_at: datetime


def load_or_create_key(path: Path) -> bytes:
    """Return the signing key at path, creating it readable only by its owner."""
    try:
        key = path.read_bytes()
    except FileNotFoundError:
        key = secrets.token_bytes(KEY_BYTES)
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(key)
    if len(key) < KEY_BYTES:
        raise ValueError(f"the signing key at {path} is shorter than {KEY_BYTES} bytes")
    return key


def issue_session(key: bytes, user_hid: str, issued_ms: int, hours: int) -> tuple[str, datetime]:
    """Sign a session token for user_hid. Return it with its expiry."""
    issued = issued_ms // 1000
    expires = issued + hours * 3600
    token = jwt.encode(
        {"sub": user_hid, "iat": issued, "exp": expires, "ims": issued_ms, "jti": new_hid()},
        key,
        algorithm=ALGORITHM,
    )
    return token, datetime.fromtimestamp(expires, UTC)


def read_session(key: bytes, token: str) -> SessionClaims:
    """Check the signature and expiry of token and return what it says."""
    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=[ALGORITHM],
            options={"require": ["sub", "exp", "ims"]},
        )
        return SessionClaims(
            user_hid=str(claims["sub"]),
            issued_ms=int(claims["ims"]),
            expires_at=datetime.fromtimestamp(int(claims["exp"]), UTC),
        )
    except (jwt.InvalidTokenError, ValueError, TypeError) as error:
        raise InvalidToken(str(error)) from error


def new_service_token() -> tuple[str, str]:
    """Return a new service token and the hash to store for it."""
    token = SERVICE_PREFIX + secrets.token_urlsafe(KEY_BYTES)
    return token, hash_service_token(token)


def hash_service_token(token: str) -> str:
    """Return the stored form of a service token."""
    return hashlib.sha256(token.encode()).hexdigest()


def is_service_token(token: str) -> bool:
    """Say whether token has the form of a service token."""
    return token.startswith(SERVICE_PREFIX)
