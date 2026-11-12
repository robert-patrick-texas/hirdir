"""The hirdir ID (HID): the application-assigned identity of every record."""

import uuid


def new_hid() -> str:
    """Return a new HID: a UUID version 7 in lower-case canonical text."""
    return str(uuid.uuid7())


def is_hid(value: str) -> bool:
    """Say whether value has the form of an HID."""
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False
