"""What every editable record shares: clean text, stale-edit refusal and audited changes."""

from collections.abc import Callable, Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from hirdir import clock
from hirdir.domain import audit
from hirdir.domain.audit import AuditContext, change
from hirdir.domain.errors import Invalid, StaleVersion

RECORD_STATUSES = ("draft", "active", "retired")


def key(text: str) -> str:
    """Return text as it is compared: without case or surrounding space."""
    return text.strip().casefold()


def clean(value: Any) -> Any:
    """Return a text value without surrounding space, and a blank one as None.

    Text with a NUL character in it is refused: no database keeps it faithfully.
    """
    if isinstance(value, str):
        if "\x00" in value:
            raise Invalid("text must not hold a NUL character")
        return value.strip() or None
    return value


def jsonable(value: Any) -> Any:
    """Return value in the form it takes in an audit event."""
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def touch(record: Any, context: AuditContext, expected_version: int | None) -> None:
    """Refuse a stale edit, then mark record as changed by the caller."""
    if expected_version is not None and record.row_version != expected_version:
        raise StaleVersion(
            f"this record is at version {record.row_version}, "
            f"and the change was made against version {expected_version}"
        )
    record.row_version += 1
    record.updated_at = clock.now()
    record.updated_by = context.actor_hid


def _stored_only(name: str) -> bool:
    """Say whether a column is bookkeeping for comparing, and not a field of the record."""
    return name.endswith("_key")


def differences(record: Any, values: dict[str, Any]) -> list[dict[str, Any]]:
    """Return a change for each of values that differs from what record holds."""
    return [
        change(name, jsonable(getattr(record, name)), jsonable(new))
        for name, new in values.items()
        if getattr(record, name) != new and not _stored_only(name)
    ]


def created(
    db: Session,
    context: AuditContext,
    record_type: str,
    record: Any,
    fields: tuple[str, ...],
    *,
    names: Mapping[str, str] | None = None,
    then: Callable[[], list[dict[str, Any]]] | None = None,
) -> None:
    """Add record, and audit its creation with every field that was given a value.

    `names` gives the documented name of a field whose attribute is called something
    else. `then` runs once the record has its HID, for what is stored beside the record
    and belongs in the same event, such as its tags; it returns the changes it made.
    """
    record.created_by = context.actor_hid
    record.updated_by = context.actor_hid
    db.add(record)
    db.flush()
    changes = [
        change((names or {}).get(name, name), None, jsonable(getattr(record, name)))
        for name in fields
        if getattr(record, name) not in (None, [], "")
    ]
    if then is not None:
        changes += then()
    audit.record(db, context, "create", record_type, record.hid, changes)


def apply(
    db: Session,
    context: AuditContext,
    record_type: str,
    record: Any,
    row_version: int | None,
    values: dict[str, Any],
    extra_changes: list[dict[str, Any]] | None = None,
    action: str = "update",
) -> bool:
    """Write values to record and audit what changed. Say whether anything did.

    A request that changes nothing leaves the record and its version alone, and is
    still refused when it was made against a stale copy.
    """
    changes = differences(record, values) + (extra_changes or [])
    if not changes:
        if row_version is not None and record.row_version != row_version:
            touch(record, context, row_version)
        return False
    touch(record, context, row_version)
    for name, new in values.items():
        setattr(record, name, new)
    db.flush()
    audit.record(db, context, action, record_type, record.hid, changes)
    return True


def checked_status(value: Any, allowed: tuple[str, ...] = ("draft", "active")) -> str:
    """Return a record status that a change may set, or refuse it."""
    status = key(str(value or ""))
    if status not in allowed:
        raise Invalid(
            "the record status is not acceptable",
            {"record_status": f"one of {', '.join(allowed)}; use the retire route to retire"},
        )
    return status
