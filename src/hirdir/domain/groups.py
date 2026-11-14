"""Device groups: stacks, clusters, controller domains, and the items that are in them.

A group is a labelled set of items with roles. Groups nest: a controller domain may
hold a cluster. Membership keeps its own dates, so that the stack a switch belonged to
last year can still be answered: a membership is ended, and never removed.
"""

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from hirdir import clock
from hirdir.db import dialect
from hirdir.db.models import DeviceGroup, DeviceGroupMember, Item, Owner
from hirdir.domain import items, records, settings, tags
from hirdir.domain.audit import AuditContext
from hirdir.domain.errors import Conflict, Invalid, NotFound

RECORD_TYPE = "device_group"
MEMBER_TYPE = "device_group_member"
TYPES = ("stack", "cluster", "controller_domain", "custom")
# The roles a member may have in each type of group. The first is what a member is
# when none is named.
ROLES: Mapping[str, tuple[str, ...]] = {
    "stack": ("member", "master"),
    "cluster": ("member", "active", "standby"),
    "controller_domain": ("endpoint", "controller"),
    "custom": ("member",),
}
MASTER = "master"
MAX_NESTING = 8
MAX_AT_ONCE = 1000
TEXTS = ("hostname", "fqdn")
FIELDS = ("type", "name", *TEXTS, "parent_group_hid", "owner_hid", "record_status")
MEMBER_FIELDS = ("group_hid", "item_hid", "role", "position", "joined_on", "left_on")


def today(db: Session) -> date:
    """Return today's date where the application is."""
    return clock.today(str(settings.value(db, "time_zone")))


def get_group(db: Session, hid: str) -> DeviceGroup:
    """Return the device group with hid."""
    group = db.get(DeviceGroup, hid)
    if group is None:
        raise NotFound(f"there is no device group {hid}")
    return group


def find_group(db: Session, name: str) -> DeviceGroup | None:
    """Return the group with a name."""
    return db.scalar(select(DeviceGroup).where(DeviceGroup.name_key == records.key(name)))


def get_member(db: Session, group_hid: str, member_hid: str) -> DeviceGroupMember:
    """Return one membership of one group."""
    member = db.get(DeviceGroupMember, member_hid)
    if member is None or member.group_hid != group_hid:
        raise NotFound(f"there is no membership {member_hid} of this group")
    return member


# --- reading -------------------------------------------------------------------------


def _in_order() -> list[Any]:
    return [
        DeviceGroupMember.position.is_(None),
        DeviceGroupMember.position,
        DeviceGroupMember.joined_on,
        DeviceGroupMember.hid,
    ]


def current_members(db: Session, group_hid: str) -> list[DeviceGroupMember]:
    """Return the memberships of a group that have not ended, by position."""
    return list(
        db.scalars(
            select(DeviceGroupMember)
            .where(DeviceGroupMember.group_hid == group_hid, DeviceGroupMember.left_on.is_(None))
            .order_by(*_in_order())
        )
    )


def list_members(
    db: Session, group_hid: str, include_past: bool, limit: int, offset: int
) -> tuple[list[DeviceGroupMember], int]:
    """Return a page of the memberships of a group, the current ones first, and their number."""
    get_group(db, group_hid)
    query = select(DeviceGroupMember).where(DeviceGroupMember.group_hid == group_hid)
    if not include_past:
        query = query.where(DeviceGroupMember.left_on.is_(None))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    order = [DeviceGroupMember.left_on.is_not(None), *_in_order()]
    return list(db.scalars(query.order_by(*order).limit(limit).offset(offset))), total


def member_counts(db: Session, group_hids: Sequence[str]) -> dict[str, int]:
    """Return how many current members each of the groups has."""
    counts = dict.fromkeys(group_hids, 0)
    if group_hids:
        counted = db.execute(
            select(DeviceGroupMember.group_hid, func.count())
            .where(DeviceGroupMember.group_hid.in_(group_hids), DeviceGroupMember.left_on.is_(None))
            .group_by(DeviceGroupMember.group_hid)
        )
        for group_hid, count in counted:
            counts[group_hid] = count
    return counts


def masters(db: Session, group_hids: Sequence[str]) -> dict[str, Item]:
    """Return the current master of each of the groups that has one."""
    if not group_hids:
        return {}
    found = db.execute(
        select(DeviceGroupMember.group_hid, Item)
        .join(Item, Item.hid == DeviceGroupMember.item_hid)
        .where(
            DeviceGroupMember.group_hid.in_(group_hids),
            DeviceGroupMember.left_on.is_(None),
            DeviceGroupMember.role == MASTER,
        )
    )
    its: dict[str, Item] = {}
    for group_hid, item in found:
        its[group_hid] = item
    return its


def memberships_of(
    db: Session, item_hids: Sequence[str]
) -> dict[str, list[tuple[DeviceGroupMember, DeviceGroup]]]:
    """Return the current memberships of each item, in groups that are not retired."""
    found: dict[str, list[tuple[DeviceGroupMember, DeviceGroup]]] = {hid: [] for hid in item_hids}
    if not item_hids:
        return found
    rows = db.execute(
        select(DeviceGroupMember, DeviceGroup)
        .join(DeviceGroup, DeviceGroup.hid == DeviceGroupMember.group_hid)
        .where(
            DeviceGroupMember.item_hid.in_(item_hids),
            DeviceGroupMember.left_on.is_(None),
            DeviceGroup.record_status != "retired",
        )
        .order_by(DeviceGroup.name_key, DeviceGroupMember.hid)
    )
    for member, group in rows:
        found[member.item_hid].append((member, group))
    return found


def controllers(db: Session, domain_hids: Sequence[str]) -> dict[str, list[Item]]:
    """Return the controllers of each controller domain.

    They are the current members with the role `controller`, and the current members
    of every cluster nested in the domain that is not retired.
    """
    found: dict[str, list[Item]] = {hid: [] for hid in domain_hids}
    if not domain_hids:
        return found
    direct = (
        select(DeviceGroupMember.group_hid, Item)
        .join(Item, Item.hid == DeviceGroupMember.item_hid)
        .where(
            DeviceGroupMember.group_hid.in_(domain_hids),
            DeviceGroupMember.left_on.is_(None),
            DeviceGroupMember.role == "controller",
        )
    )
    nested = (
        select(DeviceGroup.parent_group_hid, Item)
        .join(DeviceGroupMember, DeviceGroupMember.group_hid == DeviceGroup.hid)
        .join(Item, Item.hid == DeviceGroupMember.item_hid)
        .where(
            DeviceGroup.parent_group_hid.in_(domain_hids),
            DeviceGroup.type == "cluster",
            DeviceGroup.record_status != "retired",
            DeviceGroupMember.left_on.is_(None),
        )
    )
    for query in (direct, nested):
        for domain_hid, item in db.execute(query):
            if all(item.hid != other.hid for other in found[domain_hid]):
                found[domain_hid].append(item)
    for listed in found.values():
        listed.sort(key=lambda item: (records.key(items.shown_name(item)), item.hid))
    return found


def members_disagree(db: Session, found: Sequence[DeviceGroup]) -> dict[str, list[str]]:
    """Return, for each group, the fields of its own that a current member contradicts.

    For now that is its owner: a member that has another owner in force, its own or
    the one of the item it is in. One statement answers for all the groups.
    """
    said: dict[str, list[str]] = {group.hid: [] for group in found}
    owned = [group.hid for group in found if group.owner_hid is not None]
    if not owned:
        return said
    line: list[Any] = [Item]
    query = (
        select(DeviceGroup.hid)
        .join(DeviceGroupMember, DeviceGroupMember.group_hid == DeviceGroup.hid)
        .join(Item, Item.hid == DeviceGroupMember.item_hid)
    )
    for level in range(items.MAX_DEPTH):
        above: Any = aliased(Item, name=f"member_above_{level}")
        query = query.outerjoin(above, above.hid == line[-1].parent_item_hid)
        line.append(above)
    owner = func.coalesce(*(one.owner_hid for one in line))
    query = query.where(
        DeviceGroup.hid.in_(owned),
        DeviceGroupMember.left_on.is_(None),
        owner.is_not(None),
        owner != DeviceGroup.owner_hid,
    )
    for group_hid in db.scalars(query.distinct()):
        said[group_hid] = ["owner_hid"]
    return said


# --- the rules of a group ------------------------------------------------------------


def check_group(db: Session, group: DeviceGroup) -> None:
    """Refuse a stack that is not one: too few members, no master, or more than one.

    A stack with no members at all is one whose members are still to come. From its
    first member on, an active stack has at least two and exactly one master. A draft
    is being built, and may have fewer and no master yet. A retired one has none.
    """
    if group.type != "stack" or group.record_status == "retired":
        return
    members = current_members(db, group.hid)
    if not members:
        return
    count = sum(1 for member in members if member.role == MASTER)
    if count > 1:
        raise Invalid(
            f"the stack {group.name} would have {count} masters",
            {"members": "a stack has exactly one master"},
        )
    if group.record_status != "active":
        return
    if len(members) < 2:
        raise Invalid(
            f"the stack {group.name} would have one member",
            {
                "members": "a stack has at least two members; one being built is a draft, "
                "or is given its members together"
            },
        )
    if count == 0:
        raise Invalid(
            f"the stack {group.name} would have no master",
            {"members": "a stack has exactly one master"},
        )


def _ever_had_members(db: Session, group_hid: str) -> bool:
    return (
        db.scalar(
            select(DeviceGroupMember.hid).where(DeviceGroupMember.group_hid == group_hid).limit(1)
        )
        is not None
    )


def _checked_parent(db: Session, value: Any, group: DeviceGroup | None) -> str | None:
    hid = value or None
    if hid is None or (group is not None and group.parent_group_hid == hid):
        return hid
    field = "parent_group_hid"
    parent = db.get(DeviceGroup, hid)
    if parent is None:
        raise Invalid("there is no such group", {field: f"there is no device group {hid}"})
    if parent.record_status == "retired":
        raise Invalid("the group is retired", {field: "this group is retired"})
    above, seen = [parent], {parent.hid}
    while above[-1].parent_group_hid and above[-1].parent_group_hid not in seen:
        higher = db.get(DeviceGroup, above[-1].parent_group_hid)
        if higher is None:
            break
        above.append(higher)
        seen.add(higher.hid)
    if group is not None and group.hid in seen:
        raise Invalid(
            "a group is never within itself",
            {field: "this group is the group itself, or one that is within it"},
        )
    beneath, level = 0, [group.hid] if group is not None else []
    while level and beneath <= MAX_NESTING:
        level = list(
            db.scalars(select(DeviceGroup.hid).where(DeviceGroup.parent_group_hid.in_(level)))
        )
        beneath += 1 if level else 0
    if len(above) + beneath >= MAX_NESTING:
        raise Invalid("groups nest too deep", {field: f"groups nest at most {MAX_NESTING} deep"})
    return hid


def _checked(db: Session, fields: dict[str, Any], group: DeviceGroup | None) -> dict[str, Any]:
    values: dict[str, Any] = {}
    if "type" in fields:
        kind = records.key(str(fields["type"] or ""))
        if kind not in TYPES:
            raise Invalid("the type is not acceptable", {"type": f"one of {', '.join(TYPES)}"})
        if group is not None and kind != group.type and _ever_had_members(db, group.hid):
            raise Invalid(
                "the type of a group that has had members is not changed",
                {"type": "the roles of its members belong to the type it has"},
            )
        values["type"] = kind
    if "name" in fields:
        name = records.clean(fields["name"])
        if name is None:
            raise Invalid("the name is not acceptable", {"name": "must not be blank"})
        taken = find_group(db, name)
        if taken is not None and (group is None or taken.hid != group.hid):
            raise Conflict(
                f"there is already a device group {taken.name}",
                {"name": "another device group has this name"},
            )
        values["name"] = name
        values["name_key"] = records.key(name)
    for name in TEXTS:
        if name in fields:
            values[name] = records.clean(fields[name])
    if "parent_group_hid" in fields:
        values["parent_group_hid"] = _checked_parent(db, fields["parent_group_hid"], group)
    if "owner_hid" in fields:
        hid = fields["owner_hid"] or None
        if hid is not None and (group is None or group.owner_hid != hid):
            owner = db.get(Owner, hid)
            if owner is None:
                raise Invalid("there is no such owner", {"owner_hid": f"there is no owner {hid}"})
            if owner.record_status == "retired":
                raise Invalid("the owner is retired", {"owner_hid": "this owner is retired"})
        values["owner_hid"] = hid
    if "record_status" in fields:
        values["record_status"] = records.checked_status(fields["record_status"])
    return values


# --- changing a group ----------------------------------------------------------------


def create_group(db: Session, context: AuditContext, fields: dict[str, Any]) -> DeviceGroup:
    """Create a device group, with the members it is given, and check it as a whole."""
    dialect.hold_other_writers(db)
    labels = fields.pop("tags", None) or []
    members = fields.pop("members", None) or []
    group = DeviceGroup(**_checked(db, {"type": None, "name": None, **fields}, None))
    records.created(
        db,
        context,
        RECORD_TYPE,
        group,
        FIELDS,
        then=lambda: tags.set_labels(db, RECORD_TYPE, group.hid, labels),
    )
    if members:
        add_members(db, context, group.hid, members)
    return group


def update_group(
    db: Session, context: AuditContext, hid: str, row_version: int, fields: dict[str, Any]
) -> DeviceGroup:
    """Change a device group. One that is made active is checked as a whole."""
    dialect.hold_other_writers(db)
    group = get_group(db, hid)
    has_tags = "tags" in fields
    labels = fields.pop("tags", None) or []
    values = _checked(db, fields, group)
    tag_change = tags.set_labels(db, RECORD_TYPE, hid, labels) if has_tags else []
    records.apply(db, context, RECORD_TYPE, group, row_version, values, tag_change)
    check_group(db, group)
    return group


def retire_group(db: Session, context: AuditContext, hid: str, row_version: int) -> DeviceGroup:
    """Retire a group: its record stays, and its current memberships end today."""
    dialect.hold_other_writers(db)
    group = get_group(db, hid)
    records.apply(
        db, context, RECORD_TYPE, group, row_version, {"record_status": "retired"}, action="retire"
    )
    day = today(db)
    for member in current_members(db, hid):
        # A membership that began on a later day than this one ends on the day it began.
        left = max(day, member.joined_on)
        records.apply(db, context, MEMBER_TYPE, member, None, {"left_on": left})
    return group


# --- members -------------------------------------------------------------------------


def _checked_role(group: DeviceGroup, value: Any) -> str:
    allowed = ROLES[group.type]
    if value is None or (isinstance(value, str) and not value.strip()):
        return allowed[0]
    role = records.key(value) if isinstance(value, str) else ""
    if role not in allowed:
        raise Invalid(
            "the role is not acceptable",
            {"role": f"in a {group.type.replace('_', ' ')}, one of {', '.join(allowed)}"},
        )
    return role


def _checked_position(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 10_000:
        raise Invalid(
            "the position is not acceptable", {"position": "a whole number from 0 to 10000"}
        )
    return value


def _checked_day(value: Any, field: str) -> date:
    if not isinstance(value, date):
        raise Invalid(f"{field} is not acceptable", {field: "a date, as YYYY-MM-DD"})
    return value


def _check_joining(db: Session, group: DeviceGroup, item: Item) -> None:
    """Refuse an item that may not be a current member of a group."""
    already = db.scalar(
        select(DeviceGroupMember.hid).where(
            DeviceGroupMember.group_hid == group.hid,
            DeviceGroupMember.item_hid == item.hid,
            DeviceGroupMember.left_on.is_(None),
        )
    )
    name = items.shown_name(item)
    if already is not None:
        raise Conflict(
            f"{name} is a member of {group.name} already",
            {"item_hid": "this item is a member of the group already"},
        )
    if group.type not in items.MAJOR_ONLY:
        return
    what = group.type
    if item.parent_item_hid is not None:
        raise Invalid(
            f"{name} is a minor item",
            {"item_hid": f"the members of a {what} are major items, and this one has a parent"},
        )
    for other in items.major_only_groups(db, item.hid):
        if other.type == what and other.hid != group.hid:
            raise Conflict(
                f"{name} is a member of the {what} {other.name}",
                {"item_hid": f"an item is a member of one {what} at a time: {other.name}"},
            )


def add_members(
    db: Session,
    context: AuditContext,
    group_hid: str,
    members: Sequence[dict[str, Any]],
    check: bool = True,
) -> list[DeviceGroupMember]:
    """Add items to a group, all together, and check the group once they are in.

    A membership that is given `left_on` is one that has ended already, entered for
    the record: a file may hold the history of a group.
    """
    dialect.hold_other_writers(db)
    group = get_group(db, group_hid)
    if group.record_status == "retired" and any(one.get("left_on") is None for one in members):
        raise Invalid(
            "the group is retired", {"members": "a retired group takes no members; bring it back"}
        )
    if not members:
        raise Invalid("there is nobody to add", {"members": "name at least one item"})
    if len(members) > MAX_AT_ONCE:
        raise Invalid(
            "too many members at once", {"members": f"at most {MAX_AT_ONCE:,} in one request"}
        )
    day = today(db)
    made = []
    for given in members:
        item_hid = given.get("item_hid") or ""
        item = db.get(Item, item_hid)
        if item is None:
            raise Invalid("there is no such item", {"item_hid": f"there is no item {item_hid}"})
        if item.record_status == "retired":
            raise Invalid(
                f"{items.shown_name(item)} is retired", {"item_hid": "this item is retired"}
            )
        joined = (
            day if given.get("joined_on") is None else _checked_day(given["joined_on"], "joined_on")
        )
        left = None if given.get("left_on") is None else _checked_day(given["left_on"], "left_on")
        if left is None:
            _check_joining(db, group, item)
        elif left < joined:
            raise Invalid(
                "the dates are not acceptable", {"left_on": "must not be before the day it joined"}
            )
        member = DeviceGroupMember(
            group_hid=group.hid,
            item_hid=item.hid,
            role=_checked_role(group, given.get("role")),
            position=_checked_position(given.get("position")),
            joined_on=joined,
            left_on=left,
        )
        records.created(db, context, MEMBER_TYPE, member, MEMBER_FIELDS)
        made.append(member)
    if check:
        check_group(db, group)
    return made


def update_member(
    db: Session,
    context: AuditContext,
    group_hid: str,
    member_hid: str,
    row_version: int | None,
    fields: dict[str, Any],
    check: bool = True,
) -> DeviceGroupMember:
    """Change a membership: its role, its position or its dates. Giving it `left_on` ends it.

    Making a member the master of a stack makes the former master a member, in the
    same change. The master does not leave a stack that has other members.
    """
    dialect.hold_other_writers(db)
    group = get_group(db, group_hid)
    member = get_member(db, group_hid, member_hid)
    ended = member.left_on is not None
    values: dict[str, Any] = {}
    if "role" in fields:
        values["role"] = _checked_role(group, fields["role"])
    if "position" in fields:
        values["position"] = _checked_position(fields["position"])
    if "joined_on" in fields:
        values["joined_on"] = _checked_day(fields["joined_on"], "joined_on")
    if "left_on" in fields:
        left = fields["left_on"]
        values["left_on"] = None if left is None else _checked_day(left, "left_on")
    joined, left = values.get("joined_on", member.joined_on), values.get("left_on", member.left_on)
    changing = {name for name, value in values.items() if getattr(member, name) != value}
    if ended and (left is None or changing - {"joined_on", "left_on"}):
        raise Invalid(
            "this membership has ended",
            {"left_on": "only its dates are corrected; an item that is back is added again"},
        )
    if left is not None and left < joined:
        raise Invalid(
            "the dates are not acceptable", {"left_on": "must not be before the day it joined"}
        )
    leaving = left is not None and not ended
    others = [one for one in current_members(db, group.hid) if one.hid != member.hid]
    if group.type == "stack" and group.record_status != "retired":
        if leaving and member.role == MASTER and others:
            raise Invalid(
                "the master does not leave a stack that has other members",
                {"left_on": "make another member the master first"},
            )
        if values.get("role") == MASTER and member.role != MASTER and not leaving:
            for other in others:
                if other.role == MASTER:
                    records.apply(
                        db, context, MEMBER_TYPE, other, None, {"role": ROLES["stack"][0]}
                    )
    records.apply(db, context, MEMBER_TYPE, member, row_version, values)
    if check:
        check_group(db, group)
    return member


def leave_all(db: Session, context: AuditContext, item_hid: str) -> None:
    """End every current membership of an item today, under the rules of leaving.

    An item that is retired is in no group any more. Where its leaving would break a
    group, as the master of a stack would, the leaving is refused, and so is whatever
    asked for it.
    """
    day = today(db)
    for member, group in memberships_of(db, [item_hid])[item_hid]:
        try:
            update_member(
                db,
                context,
                group.hid,
                member.hid,
                None,
                {"left_on": max(day, member.joined_on)},
            )
        except Invalid as error:
            said = " ".join(error.fields.values())
            raise Invalid(
                f"the item is a member of {group.name}: {error}",
                {"record_status": f"end its membership of {group.name} first: {said}"},
            ) from None
