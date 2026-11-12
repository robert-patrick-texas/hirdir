"""Access codes: making them, hashing them, checking them."""

import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

# Letters and digits that are hard to mistake for one another when read aloud or typed.
_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
_HASHER = PasswordHasher()
# Checked when the username is unknown, so that a wrong name takes as long as a wrong code.
_DUMMY_HASH = _HASHER.hash("no such user")


def generate() -> str:
    """Return a new access code that is easy to read and to type: three groups of four."""
    groups = ("".join(secrets.choice(_ALPHABET) for _ in range(4)) for _ in range(3))
    return "-".join(groups)


def hash_code(code: str) -> str:
    """Return the Argon2id hash of code."""
    return _HASHER.hash(code)


def verify(code_hash: str | None, code: str) -> bool:
    """Say whether code matches code_hash. A missing hash never matches."""
    try:
        return _HASHER.verify(code_hash or _DUMMY_HASH, code) and code_hash is not None
    except VerificationError, InvalidHashError:
        return False
