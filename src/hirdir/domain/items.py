"""Items: the tracked things, their identity, and their standing in the lifecycle."""

import re
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hirdir import clock
from hirdir.auth.roles import Role
from hirdir.db.models import AuditEvent, CatalogEntry, Item, Owner
from hirdir.domain import catalog, choices, lifecycle, records, tags
from hirdir.domain.audit import AuditContext, change
from hirdir.domain.errors import Conflict, Invalid, NotFound
from hirdir.domain.lifecycle import UNSET

RECORD_TYPE = "item"
TEXTS = ("serial_number", "asset_tag", "name", "hostname", "fqdn", "description", "comments")
DAYS = ("procured_on", "delivered_on", "in_service_on", "warranty_start", "warranty_end")
STANDING = ("lifecycle_state", "disposition", "expected_online", "state_reason")
FIELDS = (
    "catalog_entry_hid",
    *TEXTS[:2],
    "mac_address",
    *TEXTS[2:],
    "quantity",
    *STANDING,
    "owner_hid",
    *DAYS,
    *catalog.AMOUNTS,
    *catalog.DATES,
    "record_status",
)
MAC_SEPARATORS = re.compile(r"[\s:.\-]")
HEX = re.compile(r"[0-9a-f]*")


def mac_digits(value: str) -> str:
    """Return the hex digits of a MAC address, or of part of one, in any common notation."""
    digits = MAC_SEPARATORS.sub("", value).lower()
    if not digits or len(digits) > 12 or not HEX.fullmatch(digits):
        raise ValueError("a MAC address is twelve hex digits, in any common notation")
    return digits


def get_item(db: Session, hid: str) -> Item:
    """Return the item with hid."""
    item = db.get(Item, hid)
    if item is None:
        raise NotFound(f"there is no item {hid}")
    return item


def _reference(
    db: Session, model: Any, field: str, value: Any, item: Item | None, what: str
) -> str | None:
    """Return the HID of a record an item refers to, refusing a new link to a retired one."""
    hid = value or None
    if hid is None or (item is not None and getattr(item, field) == hid):
        return hid
    record = db.get(model, hid)
    if record is None:
        raise Invalid(f"there is no such {what}", {field: f"there is no {what} {hid}"})
    if record.record_status == "retired":
        raise Invalid(f"the {what} is retired", {field: f"this {what} is retired"})
    return hid


def _checked(db: Session, fields: dict[str, Any], item: Item | None) -> dict[str, Any]:
    """Return the values to store for fields, checked against the item as it will be."""
    values = catalog.checked_inherited(fields)
    for name in TEXTS:
        if name in fields:
            values[name] = records.clean(fields[name])
    if "serial_number" in values:
        serial = values["serial_number"]
        values["serial_key"] = records.key(serial) if serial else None
    if "asset_tag" in values:
        tag = values["asset_tag"]
        values["asset_tag_key"] = records.key(tag) if tag else None
    if "mac_address" in fields:
        given = records.clean(fields["mac_address"])
        try:
            mac = mac_digits(given) if given else None
            if mac is not None and len(mac) != 12:
                raise ValueError("a MAC address is twelve hex digits, in any common notation")
        except ValueError as error:
            raise Invalid(
                "the MAC address is not acceptable", {"mac_address": str(error)}
            ) from None
        values["mac_address"] = mac
    if "catalog_entry_hid" in fields:
        values["catalog_entry_hid"] = _reference(
            db,
            CatalogEntry,
            "catalog_entry_hid",
            fields["catalog_entry_hid"],
            item,
            "catalog entry",
        )
    if "owner_hid" in fields:
        values["owner_hid"] = _reference(db, Owner, "owner_hid", fields["owner_hid"], item, "owner")
    if "quantity" in fields:
        quantity = 1 if fields["quantity"] is None else fields["quantity"]
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
            raise Invalid(
                "the quantity is not acceptable", {"quantity": "a whole number, 1 or more"}
            )
        values["quantity"] = quantity
    for name in DAYS:
        if name in fields:
            if fields[name] is not None and not isinstance(fields[name], date):
                raise Invalid(f"{name} is not acceptable", {name: "a date, as YYYY-MM-DD"})
            values[name] = fields[name]
    if "record_status" in fields:
        values["record_status"] = records.checked_status(fields["record_status"])

    def final(name: str) -> Any:
        return values.get(name, getattr(item, name) if item is not None else None)

    start, end = final("warranty_start"), final("warranty_end")
    if start is not None and end is not None and end < start:
        raise Invalid(
            "the warranty dates are not acceptable",
            {"warranty_end": "must not be before the start of the warranty"},
        )
    identified = (final("serial_number") and final("catalog_entry_hid")) or any(
        final(name) for name in ("asset_tag", "name", "hostname")
    )
    if not identified:
        raise Invalid(
            "an item needs something to know it by",
            {"serial_number": "or a catalog entry with it, an asset tag, a name or a hostname"},
        )
    _check_unique(db, final("catalog_entry_hid"), final("serial_key"), final("asset_tag_key"), item)
    return values


def _check_unique(
    db: Session,
    catalog_entry_hid: str | None,
    serial_key: str | None,
    asset_tag_key: str | None,
    item: Item | None,
) -> None:
    """Refuse a second item with the same model and serial number, or the same asset tag."""
    own = item.hid if item is not None else None
    if catalog_entry_hid and serial_key:
        twin = db.scalar(
            select(Item).where(
                Item.catalog_entry_hid == catalog_entry_hid,
                Item.serial_key == serial_key,
                Item.hid != own,
            )
        )
        if twin is not None:
            raise Conflict(
                f"there is already an item of this vendor and PID with the serial number "
                f"{twin.serial_number}: {twin.hid}",
                {"serial_number": "another item of this vendor and PID has this serial number"},
            )
    if asset_tag_key:
        twin = db.scalar(select(Item).where(Item.asset_tag_key == asset_tag_key, Item.hid != own))
        if twin is not None:
            raise Conflict(
                f"there is already an item with the asset tag {twin.asset_tag}: {twin.hid}",
                {"asset_tag": "another item has this asset tag"},
            )


def _checked_reason(db: Session, reason: Any, field: str) -> str | None:
    reason = records.clean(reason)
    return choices.checked(db, "state_reason", reason, field) if reason else None


def _standing_on_create(db: Session, fields: dict[str, Any]) -> dict[str, Any]:
    """Return the lifecycle fields of a new item. All of them may be blank."""
    state = records.clean(fields.get("lifecycle_state"))
    disposition = records.clean(fields.get("disposition"))
    online = fields.get("expected_online")
    reason = _checked_reason(db, fields.get("state_reason"), "state_reason")
    if state is None:
        given = {
            name: "give the item a lifecycle state first"
            for name, value in (
                ("disposition", disposition),
                ("expected_online", online),
                ("state_reason", reason),
            )
            if value is not None
        }
        if given:
            raise Invalid("an item with no lifecycle state has no standing", given)
        return {}
    state = lifecycle.state_name(state)
    rule = lifecycle.rule_of(db, state)
    disposition, online = lifecycle.entry_standing(
        rule,
        None,
        UNSET if disposition is None else lifecycle.disposition_name(disposition),
        online,
    )
    errors = lifecycle.standing_errors(rule, disposition, online, None)
    if errors:
        raise Invalid("the lifecycle rules do not allow this", errors)
    return {
        "lifecycle_state": state,
        "disposition": disposition,
        "expected_online": online,
        "state_reason": reason,
        "state_changed_at": clock.now(),
    }


def _standing_on_update(db: Session, fields: dict[str, Any], item: Item) -> dict[str, Any]:
    """Return a changed disposition and intent, checked against the item's state."""
    if "disposition" not in fields and "expected_online" not in fields:
        return {}
    disposition = records.clean(fields.get("disposition", item.disposition))
    online = fields.get("expected_online", item.expected_online)
    if item.lifecycle_state is None:
        if disposition is None and online is None:
            return {}
        raise Invalid(
            "an item with no lifecycle state has no standing",
            {
                name: "give the item a lifecycle state first"
                for name in ("disposition", "expected_online")
                if name in fields
            },
        )
    if disposition is not None:
        disposition = lifecycle.disposition_name(disposition)
    rule = lifecycle.rule_of(db, item.lifecycle_state)
    if online is None:
        raise Invalid(
            "an item with a lifecycle state is expected online or it is not",
            {"expected_online": "true or false"},
        )
    errors = lifecycle.standing_errors(rule, disposition, online, item.disposition)
    if errors:
        raise Invalid("the lifecycle rules do not allow this", errors)
    return {"disposition": disposition, "expected_online": online}


def create_item(db: Session, context: AuditContext, fields: dict[str, Any]) -> Item:
    """Create an item. Whatever is not given stays blank."""
    labels = fields.pop("tags", None) or []
    standing = _standing_on_create(db, fields)
    plain = {name: value for name, value in fields.items() if name not in STANDING}
    item = Item(**_checked(db, plain, None), **standing)
    records.created(
        db,
        context,
        RECORD_TYPE,
        item,
        FIELDS,
        then=lambda: tags.set_labels(db, RECORD_TYPE, item.hid, labels),
    )
    return item


def update_item(
    db: Session, context: AuditContext, hid: str, row_version: int, fields: dict[str, Any]
) -> Item:
    """Change an item. A value overrides, and None returns a field to blank or inheriting.

    The lifecycle state is not changed here: see `transition`.
    """
    item = get_item(db, hid)
    has_tags = "tags" in fields
    labels = fields.pop("tags", None) or []
    for name in ("lifecycle_state", "state_reason"):
        if name in fields:
            raise Invalid(
                "the lifecycle state is changed by a transition",
                {name: "use the transition route, which records who, when and why"},
            )
    plain = {name: value for name, value in fields.items() if name not in STANDING}
    values = {**_checked(db, plain, item), **_standing_on_update(db, fields, item)}
    tag_change = tags.set_labels(db, RECORD_TYPE, hid, labels) if has_tags else []
    records.apply(db, context, RECORD_TYPE, item, row_version, values, tag_change)
    return item


def retire_item(db: Session, context: AuditContext, hid: str, row_version: int) -> Item:
    """Retire an item: keep the record and its history, and leave it out of what is counted."""
    item = get_item(db, hid)
    records.apply(
        db, context, RECORD_TYPE, item, row_version, {"record_status": "retired"}, action="retire"
    )
    return item


def transition(
    db: Session,
    context: AuditContext,
    hid: str,
    row_version: int,
    *,
    to: str,
    role: Role | None,
    reason: str | None = None,
    disposition: Any = UNSET,
    expected_online: Any = UNSET,
    force: bool = False,
) -> Item:
    """Move an item to another lifecycle state, recording who, when, from, to and why.

    The move must be one the rules allow from the item's state, unless an Admin forces
    it and gives a reason. The disposition and intent are set as the new state has
    them on entry, or as the caller names them, and must be a combination it allows.
    """
    item = get_item(db, hid)
    to = lifecycle.state_name(to, "to")
    reason = _checked_reason(db, reason, "reason")
    forced = lifecycle.check_move(
        db, item.lifecycle_state, to, force=force, role=role, reason=reason
    )
    rule = lifecycle.rule_of(db, to)
    if disposition is not UNSET and disposition is not None:
        disposition = lifecycle.disposition_name(disposition)
    new_disposition, new_online = lifecycle.entry_standing(
        rule, item.disposition, disposition, expected_online
    )
    errors = lifecycle.standing_errors(rule, new_disposition, new_online, item.disposition)
    if errors:
        raise Invalid("the lifecycle rules do not allow this", errors)
    values = {
        "lifecycle_state": to,
        "disposition": new_disposition,
        "expected_online": new_online,
    }
    # The reason is recorded with every move, also when it is the same as the last one.
    extra = [change("state_reason", item.state_reason, reason)]
    if forced:
        extra.append(change("forced", None, True))
    records.apply(db, context, RECORD_TYPE, item, row_version, values, extra, action="transition")
    item.state_reason = reason
    item.state_changed_at = clock.now()
    return item


def history(db: Session, hid: str, limit: int, offset: int) -> tuple[list[AuditEvent], int]:
    """Return the audit events of one item, newest first, and how many there are."""
    get_item(db, hid)
    query = select(AuditEvent).where(
        AuditEvent.record_type == RECORD_TYPE, AuditEvent.record_hid == hid
    )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    page = db.scalars(
        query.order_by(AuditEvent.at.desc(), AuditEvent.hid.desc()).limit(limit).offset(offset)
    )
    return list(page), total
