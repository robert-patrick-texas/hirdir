"""Turning the inventory's records into the shapes the API returns.

A page of a list is shaped together, so that the catalog entries, vendors, owners and
tags its rows refer to are each read once for the page and not once for each row.
"""

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from hirdir.api import records as shapes
from hirdir.db.models import (
    CatalogEntry,
    Choice,
    ImportJob,
    ImportRow,
    Item,
    LifecycleRule,
    Owner,
    Tag,
    User,
    Vendor,
)
from hirdir.domain import inheritance, records, settings, tags
from hirdir.domain.inheritance import Effective
from hirdir.domain.settings import SettingValue
from hirdir.io import imports

FIRST_ROWS = 100


def _by_hid(db: Session, model: Any, hids: set[str | None]) -> dict[str, Any]:
    wanted = {hid for hid in hids if hid}
    if not wanted:
        return {}
    return {record.hid: record for record in db.scalars(select(model).where(model.hid.in_(wanted)))}


def _effective(name: str, effective: Effective) -> shapes.EffectiveValue:
    value = effective.value
    if isinstance(value, Decimal):
        text = records.decimal_text(name, value)
    elif isinstance(value, date):
        text = value.isoformat()
    else:
        text = None
    return shapes.EffectiveValue(
        value=text, source=effective.source, source_hid=effective.source_hid
    )


def vendor_out(vendor: Vendor) -> shapes.VendorOut:
    """Return a vendor."""
    return shapes.VendorOut.model_validate(vendor)


def owner_out(owner: Owner) -> shapes.OwnerOut:
    """Return an owner."""
    return shapes.OwnerOut.model_validate(owner)


def entries_out(db: Session, entries: list[CatalogEntry]) -> list[shapes.CatalogEntryOut]:
    """Return catalog entries with their vendors, tags and the stack discount in force."""
    vendors = _by_hid(db, Vendor, {entry.vendor_hid for entry in entries})
    labels = tags.labels_of(db, "catalog_entry", [entry.hid for entry in entries])
    discount = Decimal(str(settings.value(db, "stack_discount_pct")))
    out = []
    for entry in entries:
        effective = inheritance.of_catalog_entry(entry, discount)
        out.append(
            shapes.CatalogEntryOut(
                **{
                    name: getattr(entry, name)
                    for name in shapes.CatalogEntryOut.model_fields
                    if name not in ("vendor", "tags", "effective")
                },
                vendor=shapes.VendorRef(hid=entry.vendor_hid, name=vendors[entry.vendor_hid].name),
                tags=labels[entry.hid],
                effective=shapes.CatalogEffective(
                    stack_discount_pct=_effective(
                        "stack_discount_pct", effective["stack_discount_pct"]
                    )
                ),
            )
        )
    return out


def entry_out(db: Session, entry: CatalogEntry) -> shapes.CatalogEntryOut:
    """Return one catalog entry."""
    return entries_out(db, [entry])[0]


def items_out(db: Session, items: list[Item]) -> list[shapes.ItemOut]:
    """Return items with what they refer to and the values in force of what they inherit."""
    entries = _by_hid(db, CatalogEntry, {item.catalog_entry_hid for item in items})
    vendors = _by_hid(db, Vendor, {entry.vendor_hid for entry in entries.values()})
    owners = _by_hid(db, Owner, {item.owner_hid for item in items})
    labels = tags.labels_of(db, "item", [item.hid for item in items])
    out = []
    for item in items:
        entry = entries.get(item.catalog_entry_hid) if item.catalog_entry_hid else None
        owner = owners.get(item.owner_hid) if item.owner_hid else None
        effective = inheritance.of_item(item, entry)
        out.append(
            shapes.ItemOut(
                **{
                    name: getattr(item, name)
                    for name in shapes.ItemOut.model_fields
                    if name not in ("catalog", "owner", "tags", "effective")
                },
                catalog=None
                if entry is None
                else shapes.CatalogRef(
                    hid=entry.hid,
                    vendor_hid=entry.vendor_hid,
                    vendor=vendors[entry.vendor_hid].name,
                    pid=entry.pid,
                    model_name=entry.model_name,
                    kind=entry.kind,
                    type=entry.type,
                    function=entry.function,
                ),
                owner=None if owner is None else shapes.OwnerRef(hid=owner.hid, label=owner.label),
                tags=labels[item.hid],
                effective=shapes.ItemEffective(
                    **{name: _effective(name, value) for name, value in effective.items()}
                ),
            )
        )
    return out


def item_out(db: Session, item: Item) -> shapes.ItemOut:
    """Return one item."""
    return items_out(db, [item])[0]


def tag_out(tag: Tag, uses: int) -> shapes.TagOut:
    """Return a tag with the number of records that carry it."""
    return shapes.TagOut(
        hid=tag.hid,
        label=tag.label,
        colour=tag.colour,
        description=tag.description,
        uses=uses,
        row_version=tag.row_version,
        created_at=tag.created_at,
        updated_at=tag.updated_at,
    )


def choice_out(choice: Choice) -> shapes.ChoiceOut:
    """Return a choice."""
    return shapes.ChoiceOut(
        hid=choice.hid,
        list=choice.list_name,
        value=choice.value,
        label=choice.label,
        sort=choice.sort,
        active=choice.active,
        row_version=choice.row_version,
        created_at=choice.created_at,
        updated_at=choice.updated_at,
    )


def setting_out(setting: SettingValue) -> shapes.SettingOut:
    """Return a setting."""
    return shapes.SettingOut.model_validate(setting)


def rule_out(rule: LifecycleRule) -> shapes.LifecycleRuleOut:
    """Return a lifecycle rule."""
    return shapes.LifecycleRuleOut.model_validate(rule)


def job_out(db: Session, job: ImportJob) -> shapes.ImportJobOut:
    """Return a stored preview with the username of whoever made it."""
    maker = db.get(User, job.created_by) if job.created_by else None
    applier = db.get(User, job.applied_by) if job.applied_by else None
    return shapes.ImportJobOut(
        **{
            name: getattr(job, name)
            for name in shapes.ImportJobOut.model_fields
            if not name.endswith("_by_name")
        },
        created_by_name=maker.username if maker else None,
        applied_by_name=applier.username if applier else None,
    )


def row_out(row: ImportRow) -> shapes.ImportRowOut:
    """Return one row of a preview."""
    return shapes.ImportRowOut.model_validate(row)


def preview_out(db: Session, job: ImportJob) -> shapes.ImportPreview:
    """Return a preview: the job, and the first of its rows."""
    rows, _ = imports.list_rows(db, job.hid, None, FIRST_ROWS, 0)
    return shapes.ImportPreview(job=job_out(db, job), rows=[row_out(row) for row in rows])
