"""Idempotency keys: a request that is sent twice is carried out once.

A caller sends `Idempotency-Key` with a request it may have to send again, because the
answer to the first try was lost on the way. The key is reserved before the request is
worked on, and the answer is kept with it once there is one. The same request with the
same key is then answered with the answer that was kept.
"""

import hashlib
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from hirdir import clock
from hirdir.db.models import IdempotencyKey
from hirdir.domain.errors import Conflict, Invalid

HEADER = "Idempotency-Key"
KEPT_FOR = timedelta(hours=24)
MAX_KEY = 200
MAX_BODY = 1024 * 1024


@dataclass(frozen=True)
class Kept:
    """The answer that was given to the first request with a key."""

    status: int
    body: str


def refuse(message: str) -> Invalid:
    """Return the error for a key that cannot be taken."""
    return Invalid("the idempotency key is not acceptable", {HEADER: message})


def fingerprint(method: str, target: str, body: bytes) -> str:
    """Return what tells one request from another: its method, its URL and its body."""
    digest = hashlib.sha256(f"{method} {target}\n".encode())
    digest.update(body)
    return digest.hexdigest()


def begin(db: Session, user_hid: str, key: str, request_sha256: str) -> Kept | None:
    """Reserve a key for a request, or return the answer already kept for it.

    None means the request is to be carried out, and `finish` or `abandon` is to follow.
    The same key with a different request is refused, and so is a second request while
    the first is still being worked on.
    """
    if not 1 <= len(key) <= MAX_KEY or not key.isascii() or not key.isprintable():
        raise refuse(f"1 to {MAX_KEY} printable ASCII characters")
    db.execute(delete(IdempotencyKey).where(IdempotencyKey.created_at < clock.now() - KEPT_FOR))
    kept = db.get(IdempotencyKey, (user_hid, key))
    if kept is None:
        db.add(IdempotencyKey(user_hid=user_hid, key=key, request_sha256=request_sha256))
        try:
            db.flush()
        except IntegrityError:
            # Another request reserved the same key between the look and the write.
            raise Conflict("a request with this idempotency key is being worked on") from None
        return None
    if kept.request_sha256 != request_sha256:
        raise refuse("this key was sent with a different request; use a new key")
    if kept.status is None or kept.body is None:
        raise Conflict(
            "a request with this idempotency key is being worked on, or its answer was lost; "
            "read what it was to change before sending it again with a new key"
        )
    return Kept(kept.status, kept.body)


def finish(db: Session, user_hid: str, key: str, status: int, body: bytes) -> None:
    """Keep the answer to a request that succeeded. An answer that is too large is not kept."""
    kept = db.get(IdempotencyKey, (user_hid, key))
    if kept is None:
        return
    if len(body) > MAX_BODY:
        db.delete(kept)
        return
    kept.status = status
    kept.body = body.decode("utf-8")


def abandon(db: Session, user_hid: str, key: str) -> None:
    """Give a key back: its request failed, and may be sent again."""
    kept = db.get(IdempotencyKey, (user_hid, key))
    if kept is not None:
        db.delete(kept)
