"""What runs on a host: a virtual machine, a virtual context, a container (P-246, P-249).

Each is an item of its own that names what it runs on, an item or a stack or a cluster,
as a person names it, and the item it was seen on, as a tool or a person saw it. The
rules are said under "What runs on a host" on the data model page. What it has from its
host is worked out when it is read, by the walk of `hirdir.domain.descent`; nothing is
copied down. What is to be looked at, `review`, is worked out here when it is read.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from hirdir import clock
from hirdir.db import dialect
from hirdir.db.models import (
    CatalogEntry,
    DeviceGroup,
    DeviceGroupMember,
    ExternalSystem,
    Item,
    Registration,
)
from hirdir.domain import geography, health
from hirdir.domain.errors import Invalid

# The kinds of model that run on a host, and the kinds that may host one: an item of no
# model may host as well (P-246).
HOSTED_KINDS = ("virtual_machine", "virtual_context", "container")
HOST_KINDS = ("hardware", "virtual_machine")
# The groups that may be a host: the two that are one device.
HOST_GROUPS = ("stack", "cluster")
# How many records a line of hosts holds at most: a container in a virtual machine on a
# server.
MAX_LINE = 3
# The four fields of an item that say what it runs on.
FIELDS = ("host_item_hid", "host_group_hid", "observed_host_hid", "host_observed_at")
# The reasons an item is to be looked at (P-249).
NO_HOST, HOST_GONE, NOT_REPORTED = "no_host", "host_gone", "not_reported"
REASONS = (NO_HOST, HOST_GONE, NOT_REPORTED)
# A registration whose system reports the item no more (P-248).
NOT_REPORTED_STATUS = "not_reported"
# The states in which an item has left the team's hands.
OUT_OF_HANDS = geography.OUT_OF_HANDS

Reason = Literal["no_host", "host_gone", "not_reported"]
AboutType = Literal["item", "device_group", "external_system"]


@dataclass(frozen=True)
class Mark:
    """One reason to look at an item, and the record it is about."""

    reason: Reason
    about_type: AboutType | None = None
    about_hid: str | None = None
    about_label: str | None = None


def shown_name(item: Item) -> str:
    """Return what an item is called where one line must name it."""
    return item.name or item.hostname or item.serial_number or item.asset_tag or item.hid


def kinds_of(db: Session, entry_hids: set[str | None]) -> dict[str, str]:
    """Return the kind of each of the models."""
    wanted = {hid for hid in entry_hids if hid}
    if not wanted:
        return {}
    rows = db.execute(
        select(CatalogEntry.hid, CatalogEntry.kind).where(CatalogEntry.hid.in_(wanted))
    )
    return dict(rows.all())


def runs_on_a_host(kind: str | None) -> bool:
    """Say whether an item of a model of this kind runs on a host. One of no model does not."""
    return kind in HOSTED_KINDS


def may_host(kind: str | None) -> bool:
    """Say whether an item of a model of this kind may be a host: so may one of no model."""
    return kind is None or kind in HOST_KINDS


def hosted_counts(db: Session, column: Any, hids: Sequence[str]) -> dict[str, int]:
    """Return how many items that are not retired name each record as their host, by the
    column that names it: `Item.host_item_hid` or `Item.host_group_hid`."""
    counts = dict.fromkeys(hids, 0)
    if hids:
        counted = db.execute(
            select(column, func.count())
            .where(column.in_(list(hids)), Item.record_status != "retired")
            .group_by(column)
        )
        for hid, count in counted:
            counts[hid] = count
    return counts


def hosted(
    db: Session, column: Any, hid: str, include_retired: bool = False
) -> list[tuple[int, str, Item]]:
    """Return what runs on a record, and beneath each what runs on that: each with its
    depth, 1 for what names the record itself, and the HID of its host. Each comes after
    its host, and those of one host by name."""
    order = (dialect.folded(func.coalesce(Item.name, Item.hostname, Item.serial_number)), Item.hid)

    def named_by(field: Any, hosts: list[str]) -> list[Item]:
        query = select(Item).where(field.in_(hosts))
        if not include_retired:
            query = query.where(Item.record_status != "retired")
        return list(db.scalars(query.order_by(*order)))

    beneath: dict[str, list[Item]] = {}
    level = named_by(column, [hid])
    beneath[hid] = level
    seen = {hid, *(item.hid for item in level)}
    for _ in range(MAX_LINE - 1):
        if not level:
            break
        hosts = [one.hid for one in level]
        level = [one for one in named_by(Item.host_item_hid, hosts) if one.hid not in seen]
        for one in level:
            seen.add(one.hid)
            beneath.setdefault(one.host_item_hid or "", []).append(one)
    found: list[tuple[int, str, Item]] = []

    def walk(host_hid: str, depth: int) -> None:
        for one in beneath.get(host_hid, []):
            found.append((depth, host_hid, one))
            if depth < MAX_LINE:
                walk(one.hid, depth + 1)

    walk(hid, 1)
    return found


def states_in_force(db: Session, found: Sequence[Item]) -> dict[str, str | None]:
    """Return the lifecycle state in force of each of the items: its own, or for a minor
    item with none that of the nearest item above it that has one."""
    from hirdir.domain import items

    lines = items.lines_above(db, found)
    return {
        item.hid: next(
            (one.lifecycle_state for one in (item, *lines[item.hid]) if one.lifecycle_state),
            None,
        )
        for item in found
    }


@dataclass(frozen=True)
class Hosts:
    """What a page of items runs on and was seen on, read once for the page."""

    items: dict[str, Item]
    groups: dict[str, DeviceGroup]
    states: dict[str, str | None]
    members: dict[str, set[str]]


def hosts_of(db: Session, found: Sequence[Item]) -> Hosts:
    """Return the hosts named and seen of a page of items, with what is needed to judge
    them: the state in force of each host item, and the current members of each group."""
    item_hids = {item.host_item_hid for item in found} | {item.observed_host_hid for item in found}
    wanted = {hid for hid in item_hids if hid}
    its_items = (
        {item.hid: item for item in db.scalars(select(Item).where(Item.hid.in_(wanted)))}
        if wanted
        else {}
    )
    group_hids = {item.host_group_hid for item in found if item.host_group_hid}
    its_groups = (
        {
            group.hid: group
            for group in db.scalars(select(DeviceGroup).where(DeviceGroup.hid.in_(group_hids)))
        }
        if group_hids
        else {}
    )
    members: dict[str, set[str]] = {hid: set() for hid in its_groups}
    if its_groups:
        rows = db.execute(
            select(DeviceGroupMember.group_hid, DeviceGroupMember.item_hid).where(
                DeviceGroupMember.group_hid.in_(list(its_groups)),
                DeviceGroupMember.left_on.is_(None),
            )
        )
        for group_hid, item_hid in rows:
            members[group_hid].add(item_hid)
    named = [its_items[item.host_item_hid] for item in found if item.host_item_hid in its_items]
    return Hosts(its_items, its_groups, states_in_force(db, named), members)


def differs(item: Item, hosts: Hosts) -> bool | None:
    """Say whether the item an item was seen on is neither the host named nor a current
    member of the stack or the cluster named: no fault. None where either is not known."""
    seen = item.observed_host_hid
    if seen is None:
        return None
    if item.host_item_hid is not None:
        return seen != item.host_item_hid
    if item.host_group_hid is not None:
        return seen not in hosts.members.get(item.host_group_hid, set())
    return None


def gone(item: Item, hosts: Hosts) -> bool:
    """Say whether the host an item names is retired, or is an item that has left the
    team's hands."""
    if item.host_item_hid is not None:
        host = hosts.items.get(item.host_item_hid)
        return host is not None and (
            host.record_status == "retired" or hosts.states.get(host.hid) in OUT_OF_HANDS
        )
    if item.host_group_hid is not None:
        group = hosts.groups.get(item.host_group_hid)
        return group is not None and group.record_status == "retired"
    return False


def reviews(
    db: Session, found: Sequence[Item], kinds: dict[str, str], hosts: Hosts
) -> dict[str, list[Mark]]:
    """Return the reasons each of the items is to be looked at (P-249): worked out when it
    is read, in the order of `REASONS`. A retired item has none."""
    marks: dict[str, list[Mark]] = {item.hid: [] for item in found}
    live = [item for item in found if item.record_status != "retired"]
    for item in live:
        kind = kinds.get(item.catalog_entry_hid or "")
        if item.host_item_hid is None and item.host_group_hid is None:
            if runs_on_a_host(kind):
                marks[item.hid].append(Mark(NO_HOST))
        elif gone(item, hosts):
            if item.host_item_hid is not None:
                host = hosts.items[item.host_item_hid]
                marks[item.hid].append(Mark(HOST_GONE, "item", host.hid, shown_name(host)))
            else:
                group = hosts.groups[item.host_group_hid or ""]
                marks[item.hid].append(Mark(HOST_GONE, "device_group", group.hid, group.name))
    if live:
        rows = db.execute(
            select(Registration.item_hid, ExternalSystem.hid, ExternalSystem.name)
            .join(ExternalSystem, ExternalSystem.hid == Registration.system_hid)
            .where(
                Registration.item_hid.in_([item.hid for item in live]),
                Registration.status == NOT_REPORTED_STATUS,
            )
            .order_by(ExternalSystem.name_key, ExternalSystem.hid)
        )
        for item_hid, system_hid, name in rows:
            marks[item_hid or ""].append(Mark(NOT_REPORTED, "external_system", system_hid, name))
    return marks


def _line_above(db: Session, host: Item) -> list[str]:
    """Return the records a host runs on in its turn, the nearest first: the line of
    hosts above it, by their HIDs, ending at a group."""
    line: list[str] = []
    at: Item | None = host
    seen: set[str] = set()
    while at is not None and at.hid not in seen and len(line) <= MAX_LINE:
        seen.add(at.hid)
        if at.host_group_hid is not None:
            line.append(at.host_group_hid)
            break
        if at.host_item_hid is None:
            break
        line.append(at.host_item_hid)
        at = db.get(Item, at.host_item_hid)
    return line


def _height(db: Session, hid: str) -> int:
    """Return how many levels of items run on an item, and on those, beneath it."""
    height, level = 0, [hid]
    while level and height <= MAX_LINE:
        level = list(db.scalars(select(Item.hid).where(Item.host_item_hid.in_(level))))
        if level:
            height += 1
    return height


def _check_host_item(db: Session, hid: str, item: Item | None) -> None:
    """Refuse an item as a host that may not be one (P-246)."""
    field = "host_item_hid"
    host = db.get(Item, hid)
    if host is None:
        raise Invalid("there is no such item", {field: f"there is no item {hid}"})
    if item is not None and host.hid == item.hid:
        raise Invalid("an item does not run on itself", {field: "this is the item itself"})
    if host.record_status == "retired":
        raise Invalid("the host is retired", {field: f"{shown_name(host)} is retired"})
    state = states_in_force(db, [host])[host.hid]
    if state in OUT_OF_HANDS:
        raise Invalid(
            "the host has left the team's hands",
            {field: f"{shown_name(host)} is {state}, and hosts nothing"},
        )
    kind = kinds_of(db, {host.catalog_entry_hid}).get(host.catalog_entry_hid or "")
    if not may_host(kind):
        raise Invalid(
            "the item hosts nothing",
            {
                field: f"{shown_name(host)} is of the kind {kind}, which hosts nothing; a host "
                "is hardware or a virtual machine"
            },
        )
    above = _line_above(db, host)
    if item is not None and item.hid in above:
        raise Invalid(
            "an item does not run on what runs on it",
            {field: f"{shown_name(host)} runs on this item"},
        )
    beneath = _height(db, item.hid) if item is not None else 0
    if 1 + 1 + len(above) + beneath > MAX_LINE:
        raise Invalid(
            "the line of hosts is too long",
            {
                field: f"a line of hosts is at most {MAX_LINE} long: a container in a virtual "
                "machine on a server"
            },
        )


def why_no_host(db: Session, host: Item, running: Sequence[Item]) -> str | None:
    """Say why an item may not be the host of items that run on another now, or None
    where it may: the one question a replacement asks, of each item it would hand over,
    by the rules that naming a host is checked by (P-247)."""
    for one in running:
        try:
            _check_host_item(db, host.hid, one)
        except Invalid as refused:
            return next(iter(refused.fields.values()), str(refused))
    return None


def _check_host_group(db: Session, hid: str, item: Item | None) -> None:
    """Refuse a group as a host that may not be one: a stack or a cluster, not retired."""
    field = "host_group_hid"
    group = db.get(DeviceGroup, hid)
    if group is None:
        raise Invalid("there is no such device group", {field: f"there is no device group {hid}"})
    if group.type not in HOST_GROUPS:
        raise Invalid(
            "the group hosts nothing",
            {
                field: f"{group.name} is a {group.type.replace('_', ' ')}; a host is a stack or a "
                "cluster"
            },
        )
    if group.record_status == "retired":
        raise Invalid("the group is retired", {field: f"{group.name} is retired"})
    beneath = _height(db, item.hid) if item is not None else 0
    if 1 + 1 + beneath > MAX_LINE:
        raise Invalid(
            "the line of hosts is too long",
            {field: f"a line of hosts is at most {MAX_LINE} long, a group at its end"},
        )


def checked(
    db: Session,
    fields: dict[str, Any],
    values: dict[str, Any],
    item: Item | None,
    zone: str,
    looked_again: bool = True,
) -> dict[str, Any]:
    """Return the values of the four host fields to store, checked against the item as
    it will be: its model, its parent and the host named (P-246). `values` are the
    other fields as they will be stored."""

    def final(name: str) -> Any:
        if name in out:
            return out[name]
        if name in values:
            return values[name]
        return getattr(item, name) if item is not None else None

    out: dict[str, Any] = {}
    for name in ("host_item_hid", "host_group_hid", "observed_host_hid"):
        if name in fields:
            out[name] = fields[name] or None
    if out.get("host_item_hid") and out.get("host_group_hid"):
        raise Invalid(
            "an item runs on one host",
            {"host_group_hid": "an item runs on an item or on a group, not both"},
        )
    # Naming the one clears the other: what it runs on is one record.
    if out.get("host_item_hid") and "host_group_hid" not in fields:
        out["host_group_hid"] = None
    if out.get("host_group_hid") and "host_item_hid" not in fields:
        out["host_item_hid"] = None
    host_item, host_group = final("host_item_hid"), final("host_group_hid")
    if host_item and host_group:
        raise Invalid(
            "an item runs on one host",
            {"host_group_hid": "an item runs on an item or on a group, not both"},
        )
    named = host_item or host_group
    host_field = "host_item_hid" if host_item else "host_group_hid"
    if named:
        kind = kinds_of(db, {final("catalog_entry_hid")}).get(final("catalog_entry_hid") or "")
        if not runs_on_a_host(kind):
            said = f"an item of the kind {kind}" if kind else "an item of no model"
            field = host_field if host_field in fields else "catalog_entry_hid"
            raise Invalid(
                "the item runs on nothing",
                {
                    field: f"{said} runs on nothing; only a virtual machine, a virtual context "
                    "or a container has a host"
                },
            )
        if final("parent_item_hid"):
            if "parent_item_hid" in fields and host_field not in fields:
                raise Invalid(
                    "an item that runs on a host is installed in nothing",
                    {"parent_item_hid": "this item runs on a host; clear its host first"},
                )
            raise Invalid(
                "an item that is installed in another runs on nothing",
                {
                    host_field: "this item is installed in another; send parent_item_hid as "
                    f"null with {host_field}, which takes it out and names its host in one change"
                },
            )
    changed = {
        name: out[name]
        for name in ("host_item_hid", "host_group_hid")
        if name in out and out[name] and (item is None or getattr(item, name) != out[name])
    }
    if changed:
        # Checked against other records, so nobody else may be changing them meanwhile.
        dialect.hold_other_writers(db)
        if "host_item_hid" in changed:
            _check_host_item(db, changed["host_item_hid"], item)
        if "host_group_hid" in changed:
            _check_host_group(db, changed["host_group_hid"], item)
    seen = out.get("observed_host_hid")
    if seen and (item is None or seen != item.observed_host_hid):
        # What was seen is for the kinds that run on a host too. One that an item holds
        # from before stays until it is changed.
        kind = kinds_of(db, {final("catalog_entry_hid")}).get(final("catalog_entry_hid") or "")
        if not runs_on_a_host(kind):
            said = f"an item of the kind {kind}" if kind else "an item of no model"
            raise Invalid(
                "the item runs on nothing",
                {
                    "observed_host_hid": f"{said} is seen on nothing; only a virtual machine, "
                    "a virtual context or a container is seen on a host"
                },
            )
    out.update(_observation(db, fields, item, looked_again, zone))
    return out


# How a file and a bulk edit name the fields that the rules above name as the API does.
FILE_WORDS = (
    ("parent_item_hid as null", "parent as !clear"),
    ("host_item_hid", "host"),
    ("host_group_hid", "host_group"),
    ("observed_host_hid", "observed_host"),
    ("parent_item_hid", "parent"),
)


def in_file_words(text: str) -> str:
    """Return what a refusal of the rules of a host says, in the words of a file."""
    for api, file in FILE_WORDS:
        text = text.replace(api, file)
    return text


def _observation(
    db: Session, fields: dict[str, Any], item: Item | None, looked_again: bool, zone: str
) -> dict[str, Any]:
    """Return the item seen and the moment, set together: clearing the one clears the
    other, and a moment left out is now where a person names the item seen again."""
    out: dict[str, Any] = {}
    current = item.observed_host_hid if item is not None else None
    if "observed_host_hid" in fields:
        seen = fields["observed_host_hid"] or None
        out["observed_host_hid"] = seen
        if seen is None:
            if fields.get("host_observed_at") is not None:
                raise Invalid(
                    "a moment is seen with a host",
                    {"host_observed_at": "give observed_host_hid with it"},
                )
            out["host_observed_at"] = None
            return out
        if item is not None and seen == item.hid:
            raise Invalid(
                "an item is not seen on itself", {"observed_host_hid": "this is the item itself"}
            )
        if seen != current and db.get(Item, seen) is None:
            raise Invalid(
                "there is no such item", {"observed_host_hid": f"there is no item {seen}"}
            )
        at = fields.get("host_observed_at")
        if at is None and (seen != current or looked_again):
            at = clock.now()
        if at is not None:
            out["host_observed_at"] = health.moment(at, "host_observed_at", zone)
        return out
    if fields.get("host_observed_at") is not None:
        if current is None:
            raise Invalid(
                "a moment is seen with a host",
                {"host_observed_at": "give observed_host_hid with it"},
            )
        out["host_observed_at"] = health.moment(
            fields["host_observed_at"], "host_observed_at", zone
        )
    elif "host_observed_at" in fields and current is not None:
        raise Invalid(
            "a moment is cleared with the host seen",
            {"host_observed_at": "clear observed_host_hid, which clears its moment"},
        )
    return out


def hosting(db: Session, column: Any, hid: str) -> list[Item]:
    """Return the items not retired that name a record as their host."""
    return list(
        db.scalars(
            select(Item).where(column == hid, Item.record_status != "retired").order_by(Item.hid)
        )
    )


def model_hosts(db: Session, entry_hid: str) -> Item | None:
    """Return an item of a model that is not retired and names a host, if there is one."""
    return db.scalar(
        select(Item)
        .where(
            Item.catalog_entry_hid == entry_hid,
            Item.record_status != "retired",
            or_(Item.host_item_hid.is_not(None), Item.host_group_hid.is_not(None)),
        )
        .limit(1)
    )
