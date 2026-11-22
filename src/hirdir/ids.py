"""The hirdir ID (HID): the application-assigned identity of every record."""

import uuid
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar

# The HID that the next record of one kind made in this context is to have: a row of a
# file that names a record by an HID that no record has makes it with that HID (P-311).
_GIVEN: ContextVar[tuple[str, str] | None] = ContextVar("given_hid", default=None)


def new_hid() -> str:
    """Return a new HID: a UUID version 7 in lower-case canonical text."""
    return str(uuid.uuid7())


def is_hid(value: str) -> bool:
    """Say whether value has the form of an HID."""
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False


def is_made_hid(value: str) -> bool:
    """Say whether value is an HID as the server makes one: a UUID of version 7, of the
    variant of RFC 9562, in lower-case canonical text. A file gives a new record no
    other (P-311)."""
    try:
        made = uuid.UUID(value)
    except ValueError:
        return False
    return str(made) == value and made.version == 7 and made.variant == uuid.RFC_4122


@contextmanager
def given(record_type: str, hid: str) -> Generator[None]:
    """Within it, the first record of `record_type` that is made is made with `hid`."""
    token = _GIVEN.set((record_type, hid))
    try:
        yield
    finally:
        _GIVEN.reset(token)


def take_given(record_type: str) -> str | None:
    """Return the HID given for the next record of `record_type`, once, or None."""
    found = _GIVEN.get()
    if found is None or found[0] != record_type:
        return None
    _GIVEN.set(None)
    return found[1]


@contextmanager
def withheld() -> Generator[None]:
    """Within it, no record takes a given HID: a record made for a reference, as a
    vendor that a row names and no file describes, is made with an HID of its own."""
    token = _GIVEN.set(None)
    try:
        yield
    finally:
        _GIVEN.reset(token)
