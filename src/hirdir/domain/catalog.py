"""The catalog: vendors, and what is true of every item of one model."""

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from hirdir.db.models import CatalogEntry, Vendor
from hirdir.domain import choices, records, settings, tags
from hirdir.domain.audit import AuditContext
from hirdir.domain.errors import Conflict, Invalid, NotFound

VENDOR_FIELDS = ("name", "aliases", "notes", "review_status")
KINDS = settings.CATALOG_KINDS
REVIEW_STATUSES = ("reviewed", "unreviewed")
DATES = ("end_of_sale", "end_of_sw_support", "end_of_hw_support", "ldos")
AMOUNTS = ("est_value", "support_weight", "annual_support_cost")
TEXTS = ("model_name", "description")
ENTRY_FIELDS = (
    "vendor_hid",
    "pid",
    "model_name",
    "kind",
    "type",
    "function",
    "description",
    *DATES,
    *AMOUNTS,
    "stack_discount_pct",
    "successor_hid",
    "review_status",
    "record_status",
)
RECORD_TYPE = "catalog_entry"


# --- vendors -----------------------------------------------------------------------


def get_vendor(db: Session, hid: str) -> Vendor:
    """Return the vendor with hid."""
    vendor = db.get(Vendor, hid)
    if vendor is None:
        raise NotFound(f"there is no vendor {hid}")
    return vendor


def find_vendor(db: Session, name: str) -> Vendor | None:
    """Return the vendor known by name, as its own name or as one of its aliases."""
    wanted = records.key(name)
    vendor = db.scalar(select(Vendor).where(Vendor.name_key == wanted))
    if vendor is not None:
        return vendor
    for candidate in db.scalars(select(Vendor)):
        if wanted in {records.key(alias) for alias in candidate.aliases}:
            return candidate
    return None


def _checked_vendor(db: Session, fields: dict[str, Any], vendor: Vendor | None) -> dict[str, Any]:
    values: dict[str, Any] = {}
    names: list[str] = []
    if "name" in fields:
        name = records.clean(fields["name"])
        if name is None:
            raise Invalid("the name is not acceptable", {"name": "must not be blank"})
        values["name"] = name
        values["name_key"] = records.key(name)
        names.append(name)
    if "aliases" in fields or ("name" in values and vendor is not None):
        # A new name is checked against the aliases too: a vendor renamed to one of its
        # own aliases no longer lists it as another spelling.
        own = values.get("name", vendor.name if vendor is not None else "")
        given = fields.get("aliases", vendor.aliases if vendor else [])
        aliases: dict[str, str] = {}
        for alias in given or []:
            alias = records.clean(alias)
            if alias is not None and records.key(alias) != records.key(own):
                aliases.setdefault(records.key(alias), alias)
        values["aliases"] = list(aliases.values())
        names += values["aliases"]
    for name in names:
        taken = find_vendor(db, name)
        if taken is not None and (vendor is None or taken.hid != vendor.hid):
            field = "name" if name == values.get("name") else "aliases"
            raise Conflict(
                f"{name} is already the vendor {taken.name}",
                {field: f"{name} is a name of the vendor {taken.name}"},
            )
    if "notes" in fields:
        values["notes"] = records.clean(fields["notes"])
    if "review_status" in fields:
        values["review_status"] = _review_status(fields["review_status"])
    return values


def _review_status(value: Any) -> str:
    status = records.key(str(value or ""))
    if status not in REVIEW_STATUSES:
        raise Invalid(
            "the review status is not acceptable",
            {"review_status": f"one of {', '.join(REVIEW_STATUSES)}"},
        )
    return status


def create_vendor(db: Session, context: AuditContext, fields: dict[str, Any]) -> Vendor:
    """Create a vendor."""
    vendor = Vendor(**_checked_vendor(db, {"name": None, **fields}, None))
    records.created(db, context, "vendor", vendor, VENDOR_FIELDS)
    return vendor


def update_vendor(
    db: Session, context: AuditContext, hid: str, row_version: int, fields: dict[str, Any]
) -> Vendor:
    """Change a vendor."""
    vendor = get_vendor(db, hid)
    records.apply(db, context, "vendor", vendor, row_version, _checked_vendor(db, fields, vendor))
    return vendor


# --- catalog entries ---------------------------------------------------------------


def get_entry(db: Session, hid: str) -> CatalogEntry:
    """Return the catalog entry with hid."""
    entry = db.get(CatalogEntry, hid)
    if entry is None:
        raise NotFound(f"there is no catalog entry {hid}")
    return entry


def _amount(name: str, value: Any, highest: Decimal | None = None) -> Decimal | None:
    if value is None:
        return None
    if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
        raise Invalid(f"{name} is not acceptable", {name: "a number that is not negative"})
    if highest is not None and value > highest:
        raise Invalid(f"{name} is not acceptable", {name: f"at most {highest}"})
    return value


def checked_inherited(fields: dict[str, Any]) -> dict[str, Any]:
    """Return the dates and amounts in fields, checked. Items override the same ones."""
    values: dict[str, Any] = {}
    for name in DATES:
        if name in fields:
            if fields[name] is not None and not isinstance(fields[name], date):
                raise Invalid(f"{name} is not acceptable", {name: "a date, as YYYY-MM-DD"})
            values[name] = fields[name]
    for name in AMOUNTS:
        if name in fields:
            values[name] = _amount(name, fields[name])
    return values


def _checked_entry(
    db: Session, fields: dict[str, Any], entry: CatalogEntry | None
) -> dict[str, Any]:
    values = checked_inherited(fields)
    if "vendor_hid" in fields:
        if not fields["vendor_hid"]:
            raise Invalid("a catalog entry needs a vendor", {"vendor_hid": "must not be blank"})
        try:
            values["vendor_hid"] = get_vendor(db, fields["vendor_hid"]).hid
        except NotFound as error:
            raise Invalid(str(error), {"vendor_hid": "there is no such vendor"}) from None
    if "pid" in fields:
        pid = records.clean(fields["pid"])
        if pid is None:
            raise Invalid("a catalog entry needs a PID", {"pid": "must not be blank"})
        values["pid"] = pid
        values["pid_key"] = records.key(pid)
    if "vendor_hid" in values or "pid_key" in values:
        vendor_hid = values.get("vendor_hid", entry.vendor_hid if entry is not None else None)
        pid_key = values.get("pid_key", entry.pid_key if entry is not None else None)
        taken = db.scalar(
            select(CatalogEntry).where(
                CatalogEntry.vendor_hid == vendor_hid, CatalogEntry.pid_key == pid_key
            )
        )
        if taken is not None and (entry is None or taken.hid != entry.hid):
            raise Conflict(
                f"this vendor already has the PID {taken.pid}: {taken.hid}",
                {"pid": "this vendor already has an entry with this PID"},
            )
    for name in TEXTS:
        if name in fields:
            values[name] = records.clean(fields[name])
    if "kind" in fields:
        kind = records.key(str(fields["kind"] or ""))
        if kind not in KINDS:
            raise Invalid("the kind is not acceptable", {"kind": f"one of {', '.join(KINDS)}"})
        values["kind"] = kind
    for name, list_name in (("type", "catalog_type"), ("function", "catalog_function")):
        if name in fields:
            given = records.clean(fields[name])
            unchanged = entry is not None and given == getattr(entry, name)
            if given is not None and not unchanged:
                given = choices.checked(db, list_name, given, name)
            values[name] = given
    if "stack_discount_pct" in fields:
        values["stack_discount_pct"] = _amount(
            "stack_discount_pct", fields["stack_discount_pct"], Decimal(100)
        )
    if "successor_hid" in fields:
        successor = fields["successor_hid"] or None
        if successor is not None:
            if entry is not None and successor == entry.hid:
                raise Invalid(
                    "the successor is not acceptable",
                    {"successor_hid": "a model does not replace itself"},
                )
            if db.get(CatalogEntry, successor) is None:
                raise Invalid(
                    "the successor is not acceptable",
                    {"successor_hid": "there is no such catalog entry"},
                )
        values["successor_hid"] = successor
    if "review_status" in fields:
        values["review_status"] = _review_status(fields["review_status"])
    if "record_status" in fields:
        values["record_status"] = records.checked_status(fields["record_status"])
    return values


def create_entry(db: Session, context: AuditContext, fields: dict[str, Any]) -> CatalogEntry:
    """Create a catalog entry."""
    labels = fields.pop("tags", None) or []
    entry = CatalogEntry(**_checked_entry(db, {"vendor_hid": None, "pid": None, **fields}, None))
    records.created(
        db,
        context,
        RECORD_TYPE,
        entry,
        ENTRY_FIELDS,
        then=lambda: tags.set_labels(db, RECORD_TYPE, entry.hid, labels),
    )
    return entry


def update_entry(
    db: Session, context: AuditContext, hid: str, row_version: int, fields: dict[str, Any]
) -> CatalogEntry:
    """Change a catalog entry.

    Every item of the model sees a changed date or amount the next time it is read. No
    item is written to, so no item's version changes.
    """
    entry = get_entry(db, hid)
    has_tags = "tags" in fields
    labels = fields.pop("tags", None) or []
    values = _checked_entry(db, fields, entry)
    tag_change = tags.set_labels(db, RECORD_TYPE, hid, labels) if has_tags else []
    records.apply(db, context, RECORD_TYPE, entry, row_version, values, tag_change)
    return entry


def retire_entry(db: Session, context: AuditContext, hid: str, row_version: int) -> CatalogEntry:
    """Retire a catalog entry. Items of the model keep it and what they inherit from it."""
    entry = get_entry(db, hid)
    records.apply(
        db,
        context,
        RECORD_TYPE,
        entry,
        row_version,
        {"record_status": "retired"},
        action="retire",
    )
    return entry
