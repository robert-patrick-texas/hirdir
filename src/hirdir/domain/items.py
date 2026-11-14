"""Items: the tracked things, their identity, and their standing in the lifecycle."""

import re
from collections.abc import Sequence
from datetime import date
from typing import Any

from sqlalchemy import func, literal, or_, select
from sqlalchemy.orm import Session

from hirdir import clock, ids
from hirdir.auth.roles import Role
from hirdir.db import dialect
from hirdir.db.models import (
    AuditEvent,
    CatalogEntry,
    DeviceGroup,
    DeviceGroupMember,
    Item,
    Location,
    Operator,
    Owner,
)
from hirdir.domain import catalog, choices, geography, health, lifecycle, records, settings, tags
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
    "condition",
    "observed_status",
    "observed_at",
    "owner_hid",
    "location_hid",
    "planned_location_hid",
    "operator_hid",
    "parent_item_hid",
    "position",
    *DAYS,
    *catalog.AMOUNTS,
    *catalog.DATES,
    "record_status",
)
MAC_SEPARATORS = re.compile(r"[\s:.\-]")
HEX = re.compile(r"[0-9a-f]*")
# How many levels of minor items there may be beneath a major item.
MAX_DEPTH = 3
# The types of group whose members are major items.
MAJOR_ONLY = ("stack", "cluster")
# The states in which an item has left the team's hands, and is in no group any more.
OUT_OF_HANDS = ("Released", "Archived")


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


def ancestors(db: Session, item: Item) -> list[Item]:
    """Return the items above a minor item, the nearest first. A major item has none."""
    above: list[Item] = []
    seen = {item.hid}
    parent_hid = item.parent_item_hid
    while parent_hid and parent_hid not in seen:
        parent = db.get(Item, parent_hid)
        if parent is None:
            break
        above.append(parent)
        seen.add(parent.hid)
        parent_hid = parent.parent_item_hid
    return above


def lines_above(db: Session, found: Sequence[Item]) -> dict[str, list[Item]]:
    """Return the items above each of the items, the nearest first, read a level at a time."""
    above: dict[str, Item] = {}
    wanted = {item.parent_item_hid for item in found}
    for _ in range(MAX_DEPTH):
        missing = {hid for hid in wanted if hid and hid not in above}
        if not missing:
            break
        level = list(db.scalars(select(Item).where(Item.hid.in_(missing))))
        above.update((item.hid, item) for item in level)
        wanted = {item.parent_item_hid for item in level}
    lines: dict[str, list[Item]] = {}
    for item in found:
        line: list[Item] = []
        parent_hid = item.parent_item_hid
        while parent_hid and parent_hid in above and len(line) < MAX_DEPTH:
            line.append(above[parent_hid])
            parent_hid = above[parent_hid].parent_item_hid
        lines[item.hid] = line
    return lines


def children(
    db: Session, hid: str, limit: int, offset: int, arrange: records.Arrange | None = None
) -> tuple[list[Item], int]:
    """Return the minor items directly in one item, by position and name, and their number.

    `arrange` sorts them as was asked for, and that order settles what it leaves tied.
    """
    get_item(db, hid)
    query = select(Item).where(Item.parent_item_hid == hid)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    if arrange is not None:
        query = arrange(query)
    order = [
        *dialect.blanks_last(dialect.folded(Item.position), False),
        *dialect.blanks_last(dialect.folded(func.coalesce(Item.name, Item.hostname)), False),
        Item.hid,
    ]
    return list(db.scalars(query.order_by(*order).limit(limit).offset(offset))), total


def _height(db: Session, hid: str) -> int:
    """Return how many levels of minor items there are beneath an item."""
    height, level = 0, [hid]
    while level and height <= MAX_DEPTH:
        level = list(db.scalars(select(Item.hid).where(Item.parent_item_hid.in_(level))))
        if level:
            height += 1
    return height


def known_as(db: Session, text: str, limit: int = 2) -> list[Item]:
    """Return the items known by text: an HID, a serial number, an asset tag or a name.

    A name is the item's own, or its hostname when it has no name. Retired items and
    drafts answer too, because a record is always reachable by what it is known as.
    """
    text = text.strip()
    if ids.is_hid(text):
        item = db.get(Item, text)
        if item is not None:
            return [item]
    wanted = records.key(text)
    return list(
        db.scalars(
            select(Item)
            .where(
                or_(
                    Item.serial_key == wanted,
                    Item.asset_tag_key == wanted,
                    dialect.equals_text(func.coalesce(Item.name, Item.hostname), text),
                )
            )
            .order_by(Item.hid)
            .limit(limit)
        )
    )


def the_one(db: Session, text: str, field: str) -> Item:
    """Return the one item known by text, or refuse: none, or more than one, is no answer."""
    found = known_as(db, text)
    if not found:
        raise Invalid("there is no such item", {field: f"there is no item {text}"})
    if len(found) > 1:
        raise Invalid(
            f"more than one item answers to {text}",
            {field: f"more than one item answers to {text}; give the HID of the one meant"},
        )
    return found[0]


def shown_name(item: Item) -> str:
    """Return what an item is called where one line must name it."""
    return item.name or item.hostname or item.serial_number or item.asset_tag or item.hid


def reference_text(item: Item) -> str:
    """Return how a file names an item: the asset tag, else the serial number, else the name."""
    return item.asset_tag or item.serial_number or item.name or item.hostname or item.hid


def reference_texts(db: Session, found: Sequence[Item]) -> dict[str, str]:
    """Return how a file names each of the items, so that the name finds that item alone.

    It is what `reference_text` gives, unless another item answers to the same text, or
    the text has the form of an HID: then it is the item's HID, which never misleads.
    """
    texts = {item.hid: reference_text(item) for item in found}
    # Who answers to each text, found as `known_as` finds them: a serial number and an
    # asset tag by their keys, a name as text is compared, without regard to case.
    by_key: dict[str, set[str]] = {records.key(text): set() for text in texts.values()}
    by_name: dict[str, set[str]] = {text.strip().lower(): set() for text in texts.values()}
    name = dialect.folded(func.coalesce(Item.name, Item.hostname))
    wanted = sorted(set(texts.values()))
    for start in range(0, len(wanted), 500):
        piece = wanted[start : start + 500]
        keys = [records.key(text) for text in piece]
        rows = db.execute(
            select(Item.hid, Item.serial_key, Item.asset_tag_key, name).where(
                or_(
                    Item.serial_key.in_(keys),
                    Item.asset_tag_key.in_(keys),
                    name.in_([dialect.folded(literal(text.strip())) for text in piece]),
                )
            )
        )
        for hid, serial, tag, called in rows:
            for known in (serial, tag):
                if known in by_key:
                    by_key[known].add(hid)
            if called in by_name:
                by_name[called].add(hid)

    def alone(hid: str, text: str) -> bool:
        answering = by_key[records.key(text)] | by_name[text.strip().lower()]
        return answering == {hid} and not ids.is_hid(text)

    return {hid: text if alone(hid, text) else hid for hid, text in texts.items()}


def name_or_hid(name: str, hid: str) -> str:
    """Return how a file names a record that has a name of its own: by the name, unless
    the name has the form of an HID and would be read as one."""
    return hid if ids.is_hid(name.strip()) else name


def major_only_groups(db: Session, item_hid: str) -> list[DeviceGroup]:
    """Return the stacks and clusters, not retired, that an item is a current member of."""
    return list(
        db.scalars(
            select(DeviceGroup)
            .join(DeviceGroupMember, DeviceGroupMember.group_hid == DeviceGroup.hid)
            .where(
                DeviceGroupMember.item_hid == item_hid,
                DeviceGroupMember.left_on.is_(None),
                DeviceGroup.type.in_(MAJOR_ONLY),
                DeviceGroup.record_status != "retired",
            )
        )
    )


def _checked_parent(db: Session, value: Any, item: Item | None) -> str | None:
    """Return the HID of the item a minor item is in, refusing a place it cannot have."""
    hid = value or None
    if hid is None or (item is not None and item.parent_item_hid == hid):
        return hid
    field = "parent_item_hid"
    # Checked against other records, so nobody else may be changing them meanwhile.
    dialect.hold_other_writers(db)
    parent = db.get(Item, hid)
    if parent is None:
        raise Invalid("there is no such item", {field: f"there is no item {hid}"})
    if parent.record_status == "retired":
        raise Invalid("the parent is retired", {field: "this item is retired"})
    above = [parent, *ancestors(db, parent)]
    if item is not None and item.hid in {one.hid for one in above}:
        raise Invalid(
            "an item is never above itself",
            {field: "this item is the item itself, or one of its own minor items"},
        )
    beneath = _height(db, item.hid) if item is not None else 0
    if len(above) + beneath > MAX_DEPTH:
        raise Invalid(
            "minor items nest too deep",
            {field: f"minor items nest at most {MAX_DEPTH} deep beneath a major item"},
        )
    if item is not None:
        groups = major_only_groups(db, item.hid)
        if groups:
            raise Invalid(
                "a member of a stack or a cluster is a major item",
                {field: f"this item is a member of {groups[0].name}; end that membership first"},
            )
    return hid


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


def _checked(
    db: Session, fields: dict[str, Any], item: Item | None, looked_again: bool = True
) -> dict[str, Any]:
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
    if "operator_hid" in fields:
        values["operator_hid"] = _reference(
            db, Operator, "operator_hid", fields["operator_hid"], item, "operator"
        )
    if "location_hid" in fields:
        if fields["location_hid"] and (item is None or item.location_hid != fields["location_hid"]):
            # Checked against the location, which may be retired only while nothing is
            # in it: nobody may be retiring it between the look and the write.
            dialect.hold_other_writers(db)
        values["location_hid"] = _reference(
            db, Location, "location_hid", fields["location_hid"], item, "location"
        )
    if "planned_location_hid" in fields:
        values["planned_location_hid"] = _checked_plan(db, fields["planned_location_hid"], item)
    if "parent_item_hid" in fields:
        values["parent_item_hid"] = _checked_parent(db, fields["parent_item_hid"], item)
        if values["parent_item_hid"] is None and "position" not in fields:
            # Out of its parent, an item has no place in it any more.
            values["position"] = None
    if "position" in fields:
        position = records.clean(fields["position"])
        parent = values.get("parent_item_hid", item.parent_item_hid if item is not None else None)
        if position is not None and parent is None:
            raise Invalid(
                "only a minor item has a position",
                {"position": "name the item it is in, as parent_item_hid, or leave this blank"},
            )
        values["position"] = position
    if "condition" in fields:
        condition = records.clean(fields["condition"])
        values["condition"] = (
            choices.checked(db, health.CONDITION_LIST, condition, "condition")
            if condition
            else None
        )
    values.update(health.observation(fields, item, settings.time_zone(db), looked_again))
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

    if item is not None and item.record_status == "retired" and "record_status" in values:
        _check_still_there(db, final("location_hid"))
    if final("planned_location_hid") and final("planned_location_hid") == final("location_hid"):
        # It is where it was going: there is nothing planned any more.
        values["planned_location_hid"] = None

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


def _checked_plan(db: Session, value: Any, item: Item | None) -> str | None:
    """Return the location an item is planned to go to: one that is not in use yet."""
    hid = value or None
    if hid is None or (item is not None and item.planned_location_hid == hid):
        return hid
    return geography.checked_plan(db, hid)


def _check_still_there(db: Session, location_hid: str | None) -> None:
    """Refuse to bring an item back into a location that was retired after it."""
    dialect.hold_other_writers(db)
    location = db.get(Location, location_hid) if location_hid else None
    if location is not None and location.record_status == "retired":
        raise Invalid(
            f"{location.name}, where the item was, is retired",
            {"record_status": "give the item another location, or none, with the change"},
        )


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
    # A person who states what is observed again has looked again. A file has not.
    looked_again = context.via != "import"
    values = {
        **_checked(db, plain, item, looked_again),
        **_standing_on_update(db, fields, item),
    }
    tag_change = tags.set_labels(db, RECORD_TYPE, hid, labels) if has_tags else []
    records.apply(db, context, RECORD_TYPE, item, row_version, values, tag_change)
    return item


def retire_item(db: Session, context: AuditContext, hid: str, row_version: int) -> Item:
    """Retire an item: keep the record and its history, and leave it out of what is counted.

    Its memberships of groups end today: a retired item is in no stack, cluster or
    domain any more, and the memberships stay on record with the day they ended.
    """
    dialect.hold_other_writers(db)
    item = get_item(db, hid)
    if item.record_status != "retired":
        if item.row_version != row_version:
            records.touch(item, context, row_version)
        _leave_groups(db, context, hid)
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
    to: str | None,
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

    A move to no state returns a minor item to the standing of the item above it.
    """
    item = get_item(db, hid)
    if to is None:
        return _inherit_standing(db, context, item, row_version, reason)
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
    if to in OUT_OF_HANDS:
        # Checked against the groups it is in, so nobody else may be changing them.
        dialect.hold_other_writers(db)
    records.apply(db, context, RECORD_TYPE, item, row_version, values, extra, action="transition")
    item.state_reason = reason
    item.state_changed_at = clock.now()
    if to in OUT_OF_HANDS:
        _leave_groups(db, context, item.hid)
    return item


def _leave_groups(db: Session, context: AuditContext, hid: str) -> None:
    """End every current membership of an item that has left the team's hands."""
    # Groups are built on items, so the module that knows them is fetched here.
    from hirdir.domain import groups

    groups.leave_all(db, context, hid)


def _inherit_standing(
    db: Session, context: AuditContext, item: Item, row_version: int, reason: str | None
) -> Item:
    """Return a minor item to the lifecycle state, disposition and intent of the item above."""
    if item.parent_item_hid is None:
        raise Invalid(
            "a lifecycle state is not cleared",
            {"to": "an item leaves a state by moving to another; only a minor item has none"},
        )
    if item.lifecycle_state is None:
        raise Invalid(
            "the item is already there",
            {"to": "the item already has the standing of the item above it"},
        )
    reason = _checked_reason(db, reason, "reason")
    values = {"lifecycle_state": None, "disposition": None, "expected_online": None}
    extra = [change("state_reason", item.state_reason, reason)]
    records.apply(db, context, RECORD_TYPE, item, row_version, values, extra, action="transition")
    item.state_reason = reason
    item.state_changed_at = clock.now()
    return item


def history(
    db: Session, hid: str, limit: int, offset: int, arrange: records.Arrange | None = None
) -> tuple[list[AuditEvent], int]:
    """Return the audit events of one item, newest first, and how many there are.

    `arrange` sorts them as was asked for, and the newest first settles what that
    leaves tied.
    """
    get_item(db, hid)
    query = select(AuditEvent).where(
        AuditEvent.record_type == RECORD_TYPE, AuditEvent.record_hid == hid
    )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    if arrange is not None:
        query = arrange(query)
    page = db.scalars(
        query.order_by(AuditEvent.at.desc(), AuditEvent.hid.desc()).limit(limit).offset(offset)
    )
    return list(page), total
