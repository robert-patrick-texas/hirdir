"""Device groups: stacks, clusters, controller domains, and the items that are in them.

A group is a labelled set of items with roles. Groups nest: a controller domain may
hold a cluster. Membership keeps its own dates, so that the stack a switch belonged to
last year can still be answered: a membership is ended, and never removed.
"""

from collections.abc import Generator, Iterable, Mapping, Sequence
from contextlib import contextmanager
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hirdir import clock
from hirdir.db import dialect
from hirdir.db.models import (
    DeviceGroup,
    DeviceGroupMember,
    Item,
    Location,
    Operator,
    Owner,
)
from hirdir.domain import (
    addresses,
    audit,
    deleted,
    geography,
    health,
    items,
    lifecycle,
    records,
    settings,
    tags,
)
from hirdir.domain.audit import AuditContext
from hirdir.domain.errors import Conflict, Existing, Invalid, NotFound, StaleVersion

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
PLAIN = "member"
# How a cluster is managed: as one node, as its members, or as its members and a node
# of its own. See "Counting and weight" on the data model page.
MANAGED_AS = ("one", "members", "members_and_cluster")
MAX_NESTING = 8
TEXTS = ("hostname", "fqdn")
FIELDS = (
    "type",
    "name",
    *TEXTS,
    "parent_group_hid",
    "owner_hid",
    "location_hid",
    "planned_location_hid",
    "operator_hid",
    "managed_as",
    "expected_members",
    "observed_status",
    "observed_at",
    "observed_master_hid",
    "master_observed_at",
    "record_status",
)
MEMBER_FIELDS = ("group_hid", "item_hid", "role", "position", "joined_on", "left_on")
OBSERVED_MASTER = ("observed_master_hid", "master_observed_at")


def today(db: Session) -> date:
    """Return today's date where the application is."""
    return clock.today(str(settings.value(db, "time_zone")))


def get_group(db: Session, hid: str) -> DeviceGroup:
    """Return the device group with hid."""
    group = db.get(DeviceGroup, hid)
    if group is None:
        # One that an Admin deleted says so, when and by whom (P-236).
        raise deleted.missing(db, RECORD_TYPE, hid, "device group")
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
    db: Session,
    group_hid: str,
    include_past: bool,
    limit: int,
    offset: int,
    arrange: records.Arrange | None = None,
) -> tuple[list[DeviceGroupMember], int]:
    """Return a page of the memberships of a group, the current ones first, and their number.

    `arrange` sorts them as was asked for, and that order settles what it leaves tied.
    """
    get_group(db, group_hid)
    query = select(DeviceGroupMember).where(DeviceGroupMember.group_hid == group_hid)
    if not include_past:
        query = query.where(DeviceGroupMember.left_on.is_(None))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    if arrange is not None:
        query = arrange(query)
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


def lowest_free(held: Iterable[int | None]) -> int:
    """Return the lowest position from 1 that is not among those held."""
    taken = {position for position in held if position is not None}
    position = 1
    while position in taken:
        position += 1
    return position


def next_positions(db: Session, found: Sequence[DeviceGroup]) -> dict[str, int | None]:
    """Return, for each stack, the position a member added with none takes (P-219).

    It is the lowest from 1 that no current member holds. A group of another type has
    none: its members have a position only where one is given.
    """
    stacks = [group.hid for group in found if group.type == "stack"]
    held: dict[str, set[int]] = {hid: set() for hid in stacks}
    if stacks:
        rows = db.execute(
            select(DeviceGroupMember.group_hid, DeviceGroupMember.position).where(
                DeviceGroupMember.group_hid.in_(stacks),
                DeviceGroupMember.left_on.is_(None),
                DeviceGroupMember.position.is_not(None),
            )
        )
        for group_hid, position in rows:
            if position is not None:
                held[group_hid].add(position)
    return {
        group.hid: lowest_free(held[group.hid]) if group.type == "stack" else None
        for group in found
    }


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


def controllers(
    db: Session, domain_hids: Sequence[str]
) -> dict[str, list[tuple[Item, DeviceGroup | None]]]:
    """Return the controllers of each controller domain, each with the cluster it is in.

    They are the current members with the role `controller`, which are in no cluster,
    and the current members of every cluster nested in the domain, at any depth, that
    is not retired. A domain may hold several clusters: an east pair and a west pair.
    """
    found: dict[str, list[tuple[Item, DeviceGroup | None]]] = {hid: [] for hid in domain_hids}
    if not domain_hids:
        return found
    direct = db.execute(
        select(DeviceGroupMember.group_hid, Item)
        .join(Item, Item.hid == DeviceGroupMember.item_hid)
        .where(
            DeviceGroupMember.group_hid.in_(domain_hids),
            DeviceGroupMember.left_on.is_(None),
            DeviceGroupMember.role == "controller",
        )
    )
    for domain_hid, item in direct:
        found[domain_hid].append((item, None))
    # Every group beneath the domains, a level at a time, by the group it is in.
    inside: dict[str, list[DeviceGroup]] = {}
    seen: set[str] = set(domain_hids)
    level = list(domain_hids)
    for _ in range(MAX_NESTING):
        below = [
            group
            for group in db.scalars(
                select(DeviceGroup).where(
                    DeviceGroup.parent_group_hid.in_(level),
                    DeviceGroup.record_status != "retired",
                )
            )
            if group.parent_group_hid is not None
        ]
        for group in below:
            inside.setdefault(group.parent_group_hid or "", []).append(group)
        level = [group.hid for group in below if group.hid not in seen]
        seen.update(level)
        if not level:
            break
    # The clusters each domain holds, at any depth, a domain within it included: each
    # domain is walked for itself, so what one holds does not depend on which others
    # were asked for with it.
    clusters: dict[str, list[DeviceGroup]] = {}
    for domain_hid in domain_hids:
        walked, queue = {domain_hid}, [domain_hid]
        while queue:
            for group in inside.get(queue.pop(), []):
                if group.hid in walked:
                    continue
                walked.add(group.hid)
                queue.append(group.hid)
                if group.type == "cluster":
                    clusters.setdefault(domain_hid, []).append(group)
    wanted = {cluster.hid for held in clusters.values() for cluster in held}
    members: dict[str, list[Item]] = {}
    if wanted:
        nested = db.execute(
            select(DeviceGroupMember.group_hid, Item)
            .join(Item, Item.hid == DeviceGroupMember.item_hid)
            .where(DeviceGroupMember.group_hid.in_(wanted), DeviceGroupMember.left_on.is_(None))
        )
        for cluster_hid, item in nested:
            members.setdefault(cluster_hid, []).append(item)
    for domain_hid, held in clusters.items():
        listed = found[domain_hid]
        for cluster in held:
            for item in members.get(cluster.hid, []):
                if all(item.hid != other.hid for other, _ in listed):
                    listed.append((item, cluster))
    for listed in found.values():
        listed.sort(
            key=lambda one: (
                records.key(one[1].name) if one[1] is not None else "",
                records.key(items.shown_name(one[0])),
                one[0].hid,
            )
        )
    return found


# --- the rules of a group ------------------------------------------------------------


def observed_masters(db: Session, found: Sequence[DeviceGroup]) -> dict[str, Item]:
    """Return the item that each of the groups is seen to have as its master."""
    wanted = {group.observed_master_hid for group in found if group.observed_master_hid}
    if not wanted:
        return {}
    its = {item.hid: item for item in db.scalars(select(Item).where(Item.hid.in_(wanted)))}
    return {
        group.hid: its[group.observed_master_hid]
        for group in found
        if group.observed_master_hid in its
    }


def health_of(db: Session, found: Sequence[DeviceGroup]) -> dict[str, health.Health | None]:
    """Return the health of each group: of a stack and a cluster, from its members."""
    with_health = [group.hid for group in found if group.type in health.HAS_HEALTH]
    members: dict[str, list[tuple[health.Health, str | None]]] = {hid: [] for hid in with_health}
    if with_health:
        rows = db.execute(
            select(DeviceGroupMember.group_hid, Item)
            .join(Item, Item.hid == DeviceGroupMember.item_hid)
            .where(
                DeviceGroupMember.group_hid.in_(with_health),
                DeviceGroupMember.left_on.is_(None),
            )
        )
        for group_hid, item in rows:
            its = health.of_item(item.condition, item.observed_status, item.expected_online)
            members[group_hid].append((its, item.lifecycle_state))
    return {
        group.hid: health.of_group(
            group.type, members.get(group.hid, []), group.observed_status, group.expected_members
        )
        for group in found
    }


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


def _checked(
    db: Session, fields: dict[str, Any], group: DeviceGroup | None, looked_again: bool = True
) -> dict[str, Any]:
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
                Existing(RECORD_TYPE, taken.hid, taken.name),
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
    if "location_hid" in fields:
        hid = fields["location_hid"] or None
        if hid is not None and (group is None or group.location_hid != hid):
            location = db.get(Location, hid)
            if location is None:
                raise Invalid(
                    "there is no such location", {"location_hid": f"there is no location {hid}"}
                )
            if location.record_status == "retired":
                raise Invalid(
                    "the location is retired", {"location_hid": "this location is retired"}
                )
        values["location_hid"] = hid
    if "planned_location_hid" in fields:
        hid = fields["planned_location_hid"] or None
        if hid is not None and (group is None or group.planned_location_hid != hid):
            geography.checked_plan(db, hid)
        values["planned_location_hid"] = hid
    going = values.get(
        "planned_location_hid", group.planned_location_hid if group is not None else None
    )
    if going and going == values.get(
        "location_hid", group.location_hid if group is not None else None
    ):
        # It is where it was going: there is nothing planned any more.
        values["planned_location_hid"] = None
    if "operator_hid" in fields:
        hid = fields["operator_hid"] or None
        if hid is not None and (group is None or group.operator_hid != hid):
            operator = db.get(Operator, hid)
            if operator is None:
                raise Invalid(
                    "there is no such operator", {"operator_hid": f"there is no operator {hid}"}
                )
            if operator.record_status == "retired":
                raise Invalid(
                    "the operator is retired", {"operator_hid": "this operator is retired"}
                )
        values["operator_hid"] = hid
    if "record_status" in fields:
        values["record_status"] = records.checked_status(fields["record_status"])
        hid = values.get("location_hid", group.location_hid if group is not None else None)
        if group is not None and group.record_status == "retired" and hid:
            # Brought back: not into a location that was retired after the group.
            dialect.hold_other_writers(db)
            location = db.get(Location, hid)
            if location is not None and location.record_status == "retired":
                raise Invalid(
                    f"{location.name}, where the group was, is retired",
                    {"record_status": "give the group another location, or none, with the change"},
                )
    kind = values.get("type", group.type if group is not None else None)
    if "managed_as" in fields or "type" in values:
        given = fields.get("managed_as", group.managed_as if group is not None else None)
        managed = records.key(str(given)) if given else None
        if kind != "cluster":
            if "managed_as" in fields and managed is not None:
                raise Invalid(
                    "only a cluster says how it is managed",
                    {"managed_as": "a stack is always one managed node; leave this blank"},
                )
            managed = None
        elif managed is None:
            managed = MANAGED_AS[0]
        elif managed not in MANAGED_AS:
            raise Invalid(
                "how the cluster is managed is not acceptable",
                {"managed_as": f"one of {', '.join(MANAGED_AS)}"},
            )
        values["managed_as"] = managed
    if "expected_members" in fields:
        expected = fields["expected_members"]
        if expected is not None and (
            isinstance(expected, bool)
            or not isinstance(expected, int)
            or not 1 <= expected <= 10_000
        ):
            raise Invalid(
                "the number of members is not acceptable",
                {"expected_members": "a whole number from 1 to 10000, or blank"},
            )
        values["expected_members"] = expected
    values.update(health.observation(fields, group, settings.time_zone(db), looked_again))
    values.update(_observed_master(db, fields, group, kind, looked_again))
    return values


def _observed_master(
    db: Session,
    fields: dict[str, Any],
    group: DeviceGroup | None,
    kind: str | None,
    looked_again: bool = True,
) -> dict[str, Any]:
    """Return the master that is seen and the moment it was seen, as a change sets them.

    Which member is master is decided by the stack as it boots, so this is an
    observation: of a stack only, and of an item that is a current member of it.
    """
    if "observed_master_hid" not in fields and "master_observed_at" not in fields:
        return {}
    current = group.observed_master_hid if group is not None else None
    hid = (fields["observed_master_hid"] or None) if "observed_master_hid" in fields else current
    at = fields.get("master_observed_at")
    if at is not None:
        at = health.moment(at, "master_observed_at", settings.time_zone(db))
    if hid is None:
        if at is not None:
            raise Invalid(
                "no master is observed at that moment",
                {"master_observed_at": "give observed_master_hid with it"},
            )
        return {"observed_master_hid": None, "master_observed_at": None}
    if kind != "stack":
        raise Invalid(
            "only a stack has a master",
            {"observed_master_hid": "the master that is seen is recorded on a stack"},
        )
    if hid != current:
        member = (
            db.scalar(
                select(DeviceGroupMember.hid).where(
                    DeviceGroupMember.group_hid == group.hid,
                    DeviceGroupMember.item_hid == hid,
                    DeviceGroupMember.left_on.is_(None),
                )
            )
            if group is not None
            else None
        )
        if member is None:
            raise Invalid(
                "the master that is seen is a member of the stack",
                {"observed_master_hid": "this item is not a current member of the stack"},
            )
    if at is None and "observed_master_hid" not in fields:
        raise Invalid(
            "a moment is not cleared by itself",
            {"master_observed_at": "clear observed_master_hid, and the moment goes with it"},
        )
    if at is None:
        restated = hid == current and group is not None and group.master_observed_at is not None
        at = group.master_observed_at if restated and not looked_again else clock.now()
    return {"observed_master_hid": hid, "master_observed_at": at}


# --- changing a group ----------------------------------------------------------------


def create_group(db: Session, context: AuditContext, fields: dict[str, Any]) -> DeviceGroup:
    """Create a device group, with the members it is given."""
    dialect.hold_other_writers(db)
    labels = fields.pop("tags", None) or []
    members = fields.pop("members", None) or []
    # The master that is seen is one of the members, so it is set once they are in.
    seen = {name: fields.pop(name) for name in OBSERVED_MASTER if name in fields}
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
    if any(value is not None for value in seen.values()):
        records.apply(
            db, context, RECORD_TYPE, group, None, _observed_master(db, seen, group, group.type)
        )
    return group


# What a stack made of a switch that stands alone takes from it, and the switch gives up
# in the same change (P-243): the four it has from the stack from then on, beside its
# name, which a stack holds for its members, and its addresses.
STACK_HOLDS = (
    "hostname",
    "fqdn",
    "location_hid",
    "planned_location_hid",
    "owner_hid",
    "operator_hid",
)


def make_stack(
    db: Session,
    context: AuditContext,
    item_hid: str,
    row_version: int,
    name: Any = None,
    members: Sequence[dict[str, Any]] = (),
) -> DeviceGroup:
    """Make a stack of an item that is in none, with the item as its first member.

    The stack takes from the item what a stack holds for its members: its host name and
    FQDN, its addresses, each moved as it is, and the location, planned location, owner
    and operator it has of its own. The item gives each up in the same change, and has
    them from the stack from then on, so that nothing is held twice. The rest of it stays
    its own. `members` are added after it, each as a member that joins a stack is. Every
    change of the item and each address moved says the stack it was made for, in
    `joining_group` (P-243).
    """
    dialect.hold_other_writers(db)
    item = items.get_item(db, item_hid)
    if item.row_version != row_version:
        raise StaleVersion(
            f"this record is at version {item.row_version}, "
            f"and the change was made against version {row_version}"
        )
    shown = items.shown_name(item)
    if item.parent_item_hid is not None:
        raise Invalid(
            f"{shown} is a minor item",
            {"item_hid": "a stack is made of a major item, and this one has a parent"},
        )
    if item.record_status == "retired":
        raise Invalid(f"{shown} is retired", {"item_hid": "this item is retired"})
    if item.lifecycle_state in items.OUT_OF_HANDS:
        raise Invalid(
            f"{shown} has left the team's hands",
            {"item_hid": f"an item in {item.lifecycle_state} is in no group"},
        )
    for other in items.major_only_groups(db, item.hid):
        if other.type == "stack":
            raise Conflict(
                f"the item {shown} is a member of the stack {other.name}",
                {"item_hid": f"an item is a member of one stack at a time: {other.name}"},
                Existing(RECORD_TYPE, other.hid, other.name),
            )
    called = records.clean(name) or item.name or item.hostname
    if called is None:
        raise Invalid(
            "the stack has no name", {"name": "give the stack a name: the item has none of its own"}
        )
    # The stack is as far along as the item: a draft of a draft, active of an active one.
    group = create_group(
        db,
        context,
        {
            "type": "stack",
            "name": called,
            "record_status": item.record_status,
            **{field: getattr(item, field) for field in STACK_HOLDS},
        },
    )
    joining = audit.because(context, "joining_group", None, group.hid)
    add_members(db, joining, group.hid, [{"item_hid": item.hid, "position": 1}])
    for address in addresses.of_holders(db, "item_hid", [item.hid])[item.hid]:
        addresses.move_to_group(db, joining, address.hid, group.hid)
    items.update_item(db, joining, item.hid, item.row_version, dict.fromkeys(STACK_HOLDS))
    if members:
        with _within_members():
            add_members(db, context, group.hid, list(members))
    return group


@contextmanager
def _within_members() -> Generator[None]:
    """Name each field of a refusal of the more members of a request under `members`,
    where the rule has not named it by its place in the list already."""
    try:
        yield
    except (Invalid, Conflict) as error:
        error.fields = {
            (name if name.startswith("members") else f"members.{name}"): message
            for name, message in error.fields.items()
        }
        raise


def update_group(
    db: Session, context: AuditContext, hid: str, row_version: int, fields: dict[str, Any]
) -> DeviceGroup:
    """Change a device group."""
    dialect.hold_other_writers(db)
    group = get_group(db, hid)
    has_tags = "tags" in fields
    labels = fields.pop("tags", None) or []
    values = _checked(db, fields, group, context.via != "import")
    tag_change = tags.set_labels(db, RECORD_TYPE, hid, labels) if has_tags else []
    records.apply(db, context, RECORD_TYPE, group, row_version, values, tag_change)
    return group


def retire_group(db: Session, context: AuditContext, hid: str, row_version: int) -> DeviceGroup:
    """Retire a group: its record stays, and its current memberships end today."""
    dialect.hold_other_writers(db)
    group = get_group(db, hid)
    values = {"record_status": "retired", "observed_master_hid": None, "master_observed_at": None}
    records.apply(db, context, RECORD_TYPE, group, row_version, values, action="retire")
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
    # The sentence does not begin with the item's name, which a page would capitalise.
    if already is not None:
        raise Conflict(
            f"the item {name} is a member of {group.name} already",
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
                f"the item {name} is a member of the {what} {other.name}",
                {"item_hid": f"an item is a member of one {what} at a time: {other.name}"},
            )


# What a member that joins a stack gives up of its own, so that the stack's is in force
# (P-217): its addresses go with them.
IDENTITY = ("hostname", "fqdn", "location_hid")
STANDING = ("disposition", "expected_online")


def _joining(
    group: DeviceGroup, given: Mapping[str, Any], ended: bool, where: str
) -> tuple[bool, dict[str, Any]]:
    """Return whether a member gives up its name and place, and what its item is to have.

    Only what the request names is changed. A membership that has ended already, entered
    for the record, changes nothing of its item.
    """
    drop = given.get("drop_identity")
    if drop is not None and not isinstance(drop, bool):
        raise Invalid("drop_identity is not acceptable", {f"{where}drop_identity": "true or false"})
    named = {name: given[name] for name in STANDING if given.get(name) is not None}
    if ended and (drop or named):
        first = "drop_identity" if drop else next(iter(named))
        raise Invalid(
            "a membership that has ended changes nothing of its item",
            {f"{where}{first}": "given with a member that joins, and not with left_on"},
        )
    if drop and group.type != "stack":
        raise Invalid(
            "only a member of a stack takes the stack's name and place",
            {
                f"{where}drop_identity": f"the members of a {group.type.replace('_', ' ')} "
                "keep their own names"
            },
        )
    return bool(drop), {**(dict.fromkeys(IDENTITY) if drop else {}), **named}


@contextmanager
def _named_at(where: str, renamed: Mapping[str, str] | None = None) -> Generator[None]:
    """Name each field of a refusal as the member it is about: `members.0.disposition`.

    `renamed` gives the name the request has for a field the rule names otherwise.
    """
    try:
        yield
    except (Invalid, Conflict) as error:
        if where:
            error.fields = {
                f"{where}{(renamed or {}).get(name, name)}": message
                for name, message in error.fields.items()
            }
        raise


def take_on(
    db: Session,
    caused: AuditContext,
    item: Item,
    drop: bool,
    fields: Mapping[str, Any],
    where: str,
) -> None:
    """Give an item that joins a group what the request names for it, by the item's rules.

    Each change is audited as the item's, or as the removal of its address, and says in
    the cause of `caused` what it was made by: joining the group (P-217), or the
    replacement whose item takes a member's place (P-242).
    """
    with _named_at(where):
        items.update_item(db, caused, item.hid, item.row_version, dict(fields))
        if drop:
            for address in addresses.of_holders(db, "item_hid", [item.hid])[item.hid]:
                addresses.delete_address(db, caused, address.hid)


class _Positions:
    """The positions of a stack as the members of one request are added to it (P-219).

    It is read once the one writer's place is taken (D-104), so that of two requests at
    one moment the second sees what the first stored. A position is held by a current
    member; one that has ended keeps its number and holds nothing.
    """

    def __init__(self, db: Session, group: DeviceGroup, members: Sequence[Mapping[str, Any]]):
        self.db = db
        self.group = group
        self.held: dict[int, DeviceGroupMember] = {}
        for member in current_members(db, group.hid):
            if member.position is not None:
                self.held.setdefault(member.position, member)
        # What the request gives, which a member given none does not take.
        self.asked = {
            given["position"]
            for given in members
            if given.get("left_on") is None and _is_position(given.get("position"))
        }
        self.given: set[int] = set()

    def place(self, position: int | None, where: str) -> int:
        """Return the position a member takes, or refuse one that is held."""
        if position is None:
            position = lowest_free([*self.held, *self.asked, *self.given])
        elif position in self.given:
            raise Invalid(
                "two members are given one position",
                {f"{where}position": f"another of these members is given position {position}"},
            )
        elif position in self.held:
            _refuse_held(self.db, self.group, self.held[position], position, f"{where}position")
        self.given.add(position)
        return position


def _is_position(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _refuse_held(
    db: Session, group: DeviceGroup, holder: DeviceGroupMember, position: int, field: str
) -> None:
    """Refuse a position of a stack that another current member holds, naming its item."""
    item = db.get_one(Item, holder.item_hid)
    name = items.shown_name(item)
    raise Conflict(
        f"position {position} of {group.name} is held by {name}",
        {field: f"another current member holds position {position}: {name}"},
        items.existing_item(item),
    )


def doubled(db: Session, group_hid: str, member_hid: str) -> DeviceGroupMember | None:
    """Return another current member that holds the position of a member of a stack."""
    member = db.get(DeviceGroupMember, member_hid)
    if member is None or member.left_on is not None or member.position is None:
        return None
    for other in current_members(db, group_hid):
        if other.hid != member.hid and other.position == member.position:
            return other
    return None


def add_members(
    db: Session,
    context: AuditContext,
    group_hid: str,
    members: Sequence[dict[str, Any]],
    *,
    indexed: bool = True,
    handed_over: bool = False,
) -> list[DeviceGroupMember]:
    """Add items to a group, all together, or none of them.

    A membership that is given `left_on` is one that has ended already, entered for
    the record: a file may hold the history of a group. A stack has at most one member
    marked as the master that is intended: one that is added so takes the mark from
    the member that had it. A member that joins a stack with `drop_identity` gives up
    its own host name, FQDN, addresses and location in the same change, and one given
    a `disposition` or `expected_online` has them from it (P-217). A current member of
    a stack holds its position alone, and one given none takes the lowest free one
    (P-219).

    `indexed` names the fields of a refusal of what a member brings with it by the
    member's place in the list, `members.0.disposition`, as a request has them; a row
    of a file, which is one member, names them as they are. `handed_over` is a
    replacement's: the new item takes the old one's position as it is.
    """
    dialect.hold_other_writers(db)
    group = get_group(db, group_hid)
    if group.record_status == "retired" and any(one.get("left_on") is None for one in members):
        raise Invalid(
            "the group is retired", {"members": "a retired group takes no members; bring it back"}
        )
    if not members:
        raise Invalid("there is nobody to add", {"members": "name at least one item"})
    settings.check_items(db, len(members), "members", "members")
    day = today(db)
    made = []
    # The members of a stack are numbered (P-219). A replacement hands its position over
    # as it is, which another member may hold from before this rule.
    numbered = _Positions(db, group, members) if group.type == "stack" and not handed_over else None
    for place, given in enumerate(members):
        where = f"members.{place}." if indexed else ""
        item_hid = given.get("item_hid") or ""
        item = db.get(Item, item_hid)
        if item is None:
            raise Invalid("there is no such item", {"item_hid": f"there is no item {item_hid}"})
        if item.record_status == "retired":
            raise Invalid(
                f"{items.shown_name(item)} is retired", {"item_hid": "this item is retired"}
            )
        if item.lifecycle_state in items.OUT_OF_HANDS and given.get("left_on") is None:
            raise Invalid(
                f"{items.shown_name(item)} has left the team's hands",
                {
                    "item_hid": f"an item in {item.lifecycle_state} is in no group; "
                    "enter a membership that has ended with its left_on"
                },
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
        drop, taken_on = _joining(group, given, left is not None, where)
        role = _checked_role(group, given.get("role"))
        position = _checked_position(given.get("position"))
        if numbered is not None and left is None:
            position = numbered.place(position, where)
        if left is None and group.type == "stack" and role == MASTER:
            if any(one.role == MASTER and one.left_on is None for one in made):
                raise Invalid(
                    "a stack has one intended master",
                    {"role": "more than one of these members is named as the master"},
                )
            _unmark_master(db, context, group.hid, None)
        member = DeviceGroupMember(
            group_hid=group.hid,
            item_hid=item.hid,
            role=role,
            position=position,
            joined_on=joined,
            left_on=left,
        )
        records.created(db, context, MEMBER_TYPE, member, MEMBER_FIELDS)
        if taken_on:
            joining = audit.because(context, "joining_group", None, group.hid)
            take_on(db, joining, item, drop, taken_on, where)
        made.append(member)
    return made


def _unmark_master(db: Session, context: AuditContext, group_hid: str, but: str | None) -> None:
    """Make the member that is marked as the intended master of a stack a plain member."""
    for other in current_members(db, group_hid):
        if other.role == MASTER and other.hid != but:
            records.apply(db, context, MEMBER_TYPE, other, None, {"role": PLAIN})


def _forget_observed_master(
    db: Session, context: AuditContext, group: DeviceGroup, item_hid: str
) -> None:
    """Clear the master that was seen, when that item is no longer in the stack."""
    if group.observed_master_hid == item_hid:
        values = {"observed_master_hid": None, "master_observed_at": None}
        records.apply(db, context, RECORD_TYPE, group, None, values)


def update_member(
    db: Session,
    context: AuditContext,
    group_hid: str,
    member_hid: str,
    row_version: int | None,
    fields: dict[str, Any],
    *,
    held_later: bool = False,
) -> DeviceGroupMember:
    """Change a membership: its role, its position or its dates. Giving it `left_on` ends it.

    `held_later` is for a file, which may move several members of a stack at once, two
    of them into each other's places: whether a position is held by two is then judged
    when every row of the file is in (`doubled`), and not a row at a time.

    Marking a member as the intended master of a stack takes the mark from the member
    that had it, in the same change. No rule stops a member leaving, the master among
    them: a stack may be left with no intended master, and with none that is seen.

    `item`, given with the end of a current membership, is what the item is to have
    from the end: it is changed by its own rules once the membership has ended (P-218).
    """
    dialect.hold_other_writers(db)
    group = get_group(db, group_hid)
    member = get_member(db, group_hid, member_hid)
    ended = member.left_on is not None
    back = fields.get("item")
    if back is not None and ended:
        raise Invalid(
            "this membership has ended",
            {"item": "what becomes of the item is given as it leaves; change it on its own page"},
        )
    if back is not None and fields.get("left_on") is None:
        raise Invalid(
            "what becomes of the item is given with the end",
            {"item": "give left_on with it"},
        )
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
    if back and leaving and left > today(db):
        # What becomes of the item is done as the request is, and not on a day to come.
        raise Invalid(
            "the item is given what becomes of it on the day it leaves",
            {"left_on": "with item, a day that has come: today or before"},
        )
    moved = values.get("position") if "position" in changing else None
    if group.type == "stack" and left is None and moved is not None and not held_later:
        # A current member is moved only to a position nobody else holds (P-219). Two
        # that hold one from before stay so until one of them is moved.
        for other in current_members(db, group.hid):
            if other.position == moved and other.hid != member.hid:
                _refuse_held(db, group, other, moved, "position")
    marking = values.get("role") == MASTER and member.role != MASTER
    if group.type == "stack" and marking and not leaving and not ended:
        _unmark_master(db, context, group.hid, member.hid)
    records.apply(db, context, MEMBER_TYPE, member, row_version, values)
    if leaving:
        _forget_observed_master(db, context, group, member.item_hid)
    if back:
        # The membership has ended first, so that the item's rules see one that has left.
        leaving = audit.because(
            context, "leaving_group", group.hid, None, of=(items.RECORD_TYPE, member.item_hid)
        )
        give_back(db, leaving, member.item_hid, back, "item.")
    return member


# What an item that leaves a group may be given with the end, beside its standing: its
# condition among them, which follows from nothing by a rule (P-245).
LEAVING = ("hostname", "fqdn", "location_hid", "condition")


def give_back(
    db: Session, caused: AuditContext, item_hid: str, given: Mapping[str, Any], where: str
) -> None:
    """Give an item that has left a group what the request says it is to have (P-218).

    Each part is applied by the item's own rules, as a file of items applies them: a
    state that is not the item's moves it by a transition, with the reason as its why
    and the disposition and intent as named; otherwise these are an edit, and a reason
    is refused. Each change is audited as the item's, and says in the cause of `caused`
    what it was made by: leaving the group, or the replacement of the item (P-242). A
    refusal names each field after `where`: `item.condition`, `old_item.condition`.
    """
    item = items.get_item(db, item_hid)
    leaving = caused
    with _named_at(where, {"to": "lifecycle_state", "reason": "state_reason"}):
        state = given.get("lifecycle_state")
        if "lifecycle_state" in given and state is None:
            raise Invalid(
                "a lifecycle state is not cleared",
                {"lifecycle_state": "an item leaves a state by moving to another"},
            )
        moving = state is not None and lifecycle.state_name(state) != item.lifecycle_state
        reason = given.get("state_reason")
        fields = {name: given[name] for name in LEAVING if name in given}
        if not moving:
            if reason is not None and records.key(reason) != records.key(item.state_reason or ""):
                raise Invalid(
                    "a reason is given with a move",
                    {"state_reason": "a reason is taken with a move to another lifecycle state"},
                )
            fields.update({name: given[name] for name in STANDING if name in given})
        if fields:
            items.update_item(db, leaving, item.hid, item.row_version, fields)
        if moving:
            items.transition(
                db,
                leaving,
                item.hid,
                item.row_version,
                to=state,
                role=None,
                reason=reason,
                disposition=given.get("disposition", lifecycle.UNSET),
                expected_online=given.get("expected_online", lifecycle.UNSET),
            )


def leave_all(db: Session, context: AuditContext, item_hid: str) -> None:
    """End every current membership of an item today.

    An item that is retired, or has left the team's hands, is in no group any more.
    The memberships stay on record with the day they ended.
    """
    day = today(db)
    for member, group in memberships_of(db, [item_hid])[item_hid]:
        left = max(day, member.joined_on)
        update_member(db, context, group.hid, member.hid, None, {"left_on": left})
