"""The records an import made, each with what it is now (P-234).

Nothing new is stored for it: a row that made a record keeps the record's HID, and the
audit trail the request that made the vendors and catalog entries a row named.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hirdir.db.models import CatalogEntry, ImportRow, PurchaseRequest, Vendor
from hirdir.domain import deleted, geography, items, purchases, removal
from hirdir.io import imports
from hirdir.io.entities import entity

# What a record an import made is now.
State = Literal["active", "draft", "retired", "deleted"]
# The fields a record is known by, the first it has, for the kinds that have no rule of
# their own.
KNOWN_BY = ("name", "label", "number", "reference", "title", "address", "enterprise_circuit_id")


@dataclass(frozen=True)
class Made:
    """A record that an import made, and what it is now."""

    row: int
    record_type: str
    record_hid: str
    label: str
    state: State


@dataclass(frozen=True)
class MadeForARow:
    """A vendor or a catalog entry that an import made only because a row named it."""

    record_type: Literal["vendor", "catalog_entry"]
    record_hid: str
    label: str
    state: State


def _state(record: Any) -> State:
    """Return what a record is now: its status, or active for one that has none."""
    status = getattr(record, "record_status", None)
    if status == "draft":
        return "draft"
    if status == "retired":
        return "retired"
    return "active"


def _labels(db: Session, record_type: str, found: Sequence[Any]) -> dict[str, str]:
    """Return what each record is known by, as one line names it."""
    if record_type in removal.KINDS:
        kind = removal.kind_of(record_type)
        return {record.hid: kind.label(record) for record in found}
    if record_type in geography.LEVELS:
        atlas = geography.Atlas(db)
        atlas.take(found)
        path = {
            geography.REGION: atlas.region_path,
            geography.SITE: atlas.site_path,
            geography.LOCATION: atlas.location_path,
        }[record_type]
        return {record.hid: path(record.hid) for record in found}
    if record_type == "catalog_entry":
        vendors = removal.read(db, Vendor, sorted({one.vendor_hid for one in found}))
        return {one.hid: f"{vendors[one.vendor_hid].name} {one.pid}" for one in found}
    if record_type == purchases.LINE_TYPE:
        asked = removal.read(db, PurchaseRequest, sorted({one.request_hid for one in found}))
        return {one.hid: purchases.line_name(asked[one.request_hid], one) for one in found}
    labels = {}
    for record in found:
        known = next(
            (getattr(record, name) for name in KNOWN_BY if getattr(record, name, None)), None
        )
        if known is not None:
            labels[record.hid] = str(known)
    return labels


def _was_known_by(db: Session, record_type: str, hid: str) -> str | None:
    """Return what a record that was deleted was known by then, from its deletion."""
    event = deleted.deletion(db, record_type, hid)
    if event is None:
        return None
    was = {entry["field"]: entry["old"] for entry in event.changes or []}
    if record_type == items.RECORD_TYPE:
        return (
            was.get("name")
            or was.get("hostname")
            or was.get("serial_number")
            or was.get("asset_tag")
        )
    return was.get("name")


def created(
    db: Session, hid: str, limit: int, offset: int
) -> tuple[list[Made], int, list[MadeForARow]]:
    """Return a page of the records an import made, by row, how many there are, and the
    vendors and catalog entries it made only because a row named them."""
    job = imports.get_job(db, hid)
    which = entity(job.entity)
    made = select(ImportRow).where(
        ImportRow.job_hid == hid,
        ImportRow.applied_outcome == "create",
        ImportRow.record_hid.is_not(None),
    )
    total = db.scalar(select(func.count()).select_from(made.subquery())) or 0
    rows = list(db.scalars(made.order_by(ImportRow.row).limit(limit).offset(offset)))
    found = removal.read(db, which.model, [row.record_hid for row in rows if row.record_hid])
    labels = _labels(db, which.record_type, list(found.values()))
    page = []
    for row in rows:
        record_hid = row.record_hid or ""
        record = found.get(record_hid)
        if record is None:
            label = _was_known_by(db, which.record_type, record_hid) or row.key
            state: State = "deleted"
        else:
            label, state = labels.get(record_hid) or row.key or record_hid, _state(record)
        page.append(Made(row.row, which.record_type, record_hid, label, state))
    return page, total, _made_for_rows(db, hid)


def _made_for_rows(db: Session, hid: str) -> list[MadeForARow]:
    """Return the vendors, then the catalog entries, that an import made only because a
    row named them, each by name."""
    made = sorted(imports._stubs_made(db, hid))
    vendors = removal.read(db, Vendor, made)
    entries = removal.read(db, CatalogEntry, made)
    named = _labels(db, "catalog_entry", list(entries.values()))
    return [
        *(
            MadeForARow("vendor", one.hid, one.name, "active")
            for one in sorted(vendors.values(), key=lambda one: one.name_key)
        ),
        *(
            MadeForARow("catalog_entry", one.hid, named[one.hid], _state(one))
            for one in sorted(entries.values(), key=lambda one: named[one.hid].casefold())
        ),
    ]
