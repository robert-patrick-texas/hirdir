"""Several items or device groups retired at once, and an Admin's deletion of those that
were a mistake (P-227, P-228, P-236).

Retiring stays the way a record ends. Several are retired by one request each as its own
page retires one, with an audit event each. Deleting removes a record that should never
have been, and only one that nothing else depends on.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from hirdir.db import dialect
from hirdir.db.models import DeviceGroup, Item
from hirdir.domain import groups, items
from hirdir.domain.audit import AuditContext
from hirdir.domain.errors import DomainError, Invalid

# How many records one request retires or deletes, at most.
MOST_AT_ONCE = 1000
ITEM = items.RECORD_TYPE
DEVICE_GROUP = groups.RECORD_TYPE
KINDS = (ITEM, DEVICE_GROUP)
# Records are read this many to a statement.
PIECE = 500


@dataclass(frozen=True)
class Kind:
    """What retiring and deleting need to know of one kind of record."""

    record_type: str
    model: Any
    label: Callable[[Any], str]
    retire: Callable[[Session, AuditContext, str, int], Any]


def _group_label(group: DeviceGroup) -> str:
    return group.name


def kind_of(record_type: str) -> Kind:
    """Return the kind of record that is retired or deleted several at a time."""
    if record_type == ITEM:
        return Kind(ITEM, Item, items.shown_name, items.retire_item)
    if record_type == DEVICE_GROUP:
        return Kind(DEVICE_GROUP, DeviceGroup, _group_label, groups.retire_group)
    raise Invalid("this kind of record is not retired or deleted so", {"kind": "item or group"})


def unique(hids: Sequence[str], field_: str = "hids") -> list[str]:
    """Return the HIDs named, each once, in the order first named, refusing too many."""
    named = list(dict.fromkeys(hids))
    if not named:
        raise Invalid("nothing is named", {field_: "name one record at least"})
    if len(named) > MOST_AT_ONCE:
        raise Invalid("too many at once", {field_: f"at most {MOST_AT_ONCE:,} to a request"})
    return named


def read(db: Session, model: Any, hids: Sequence[str]) -> dict[str, Any]:
    """Return the records of a kind that the HIDs name, by HID."""
    found: dict[str, Any] = {}
    for start in range(0, len(hids), PIECE):
        piece = list(hids[start : start + PIECE])
        found.update(
            (one.hid, one) for one in db.scalars(select(model).where(model.hid.in_(piece)))
        )
    return found


def said(error: DomainError) -> str:
    """Return what a refusal says, with what it says of each field."""
    fields = getattr(error, "fields", None) or {}
    parts = [f"{name}: {text}" if name else text for name, text in fields.items()]
    return "; ".join([str(error), *parts]) if parts else str(error)


# --- several retired at once (P-228) --------------------------------------------------


@dataclass
class Retired:
    """What a request that retires several did with each record it named."""

    retired: list[tuple[str, str]] = field(default_factory=list)
    already: list[tuple[str, str]] = field(default_factory=list)
    refused: list[tuple[str, str, str]] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


def retire_many(
    db: Session, context: AuditContext, record_type: str, hids: Sequence[str]
) -> Retired:
    """Retire each record named, as its own page retires it, with an audit event each.

    One that is retired already is counted so and not refused. One that the rules refuse
    is named with why, and leaves the others as they went. No version is asked for: what
    a person ticked is what is retired, as it is when the request is worked.
    """
    kind = kind_of(record_type)
    named = unique(hids)
    # The memberships and the coverage that retiring ends are read with no other change
    # under way, as one retire reads them.
    dialect.hold_other_writers(db)
    found = read(db, kind.model, named)
    done = Retired()
    for hid in named:
        record = found.get(hid)
        if record is None:
            done.missing.append(hid)
            continue
        label = kind.label(record)
        if record.record_status == "retired":
            done.already.append((hid, label))
            continue
        savepoint = db.begin_nested()
        try:
            kind.retire(db, context, hid, record.row_version)
        except DomainError as error:
            savepoint.rollback()
            done.refused.append((hid, label, said(error)))
        else:
            savepoint.commit()
            done.retired.append((hid, label))
    return done
