"""The fields each list can be filtered and sorted by, and how the list is read.

A field named here is one a filter may use on that list. Dotted names reach a related
record (`catalog.pid`, `owner.label`), and `effective.<field>` is the value in force of
a field that inherits.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import ColumnElement, Integer, Select, and_, case, false, func, or_, select
from sqlalchemy.orm import Session, aliased

from hirdir.db import dialect
from hirdir.db.models import (
    ADDRESS_FIELDS,
    Address,
    CatalogEntry,
    Contact,
    ContactAssignment,
    DeviceGroup,
    DeviceGroupMember,
    Item,
    Location,
    Network,
    Operator,
    Owner,
    OwnerMember,
    Region,
    Site,
    Tag,
    TagLink,
    Vendor,
)
from hirdir.domain import (
    contacts,
    descent,
    geography,
    groups,
    health,
    inheritance,
    lifecycle,
    operators,
    owners,
    records,
)
from hirdir.domain.addresses import comparable
from hirdir.domain.items import MAX_DEPTH, mac_digits
from hirdir.io.filters import Field, refuse


@dataclass(frozen=True)
class Listing:
    """How one list is read: its record, its fields, and what it leaves out by default."""

    model: Any
    fields: Mapping[str, Field]
    joined: Callable[[Select[Any]], Select[Any]]
    default_sort: tuple[str, ...]
    has_status: bool = True


def _tagged(record_type: str, hid: Any) -> Callable[[str], ColumnElement[bool]]:
    """Return the test that a record carries a tag: the one with a label, or any at all."""

    def test(label: str) -> ColumnElement[bool]:
        linked = (
            select(TagLink.tag_hid)
            .join(Tag, Tag.hid == TagLink.tag_hid)
            .where(TagLink.record_type == record_type, TagLink.record_hid == hid)
        )
        if label:
            linked = linked.where(Tag.label_key == records.key(label))
        return linked.exists()

    return test


def _tags(record_type: str, model: Any) -> Field:
    """Return the field of a record's tags: found by any one of them, and sorted by the
    first as they are listed, which is the least label without regard to case."""
    first = (
        select(func.min(Tag.label_key))
        .join(TagLink, TagLink.tag_hid == Tag.hid)
        .where(TagLink.record_type == record_type, TagLink.record_hid == model.hid)
        .correlate(model)
        .scalar_subquery()
    )
    return Field("tags", test=_tagged(record_type, model.hid), ordered_by=first)


def _counted(model: Any, *named: Any) -> ColumnElement[Any]:
    """Return how many records name a record of model in one of the columns."""
    counts = [
        select(func.count()).where(column == model.hid).correlate(model).scalar_subquery()
        for column in named
    ]
    total = counts[0]
    for count in counts[1:]:
        total = total + count
    return total


def _columns(model: Any, kind: str, *names: str) -> dict[str, Field]:
    return {name: Field(kind, getattr(model, name)) for name in names}


def _bookkeeping(model: Any) -> dict[str, Field]:
    return {
        "hid": Field("reference", model.hid),
        "row_version": Field("integer", model.row_version),
        **_columns(model, "timestamp", "created_at", "updated_at"),
    }


def _effective(name: str) -> Field:
    own = getattr(Item, name)
    kind = (
        "date"
        if name in ("end_of_sale", "end_of_sw_support", "end_of_hw_support", "ldos")
        else "number"
    )
    return Field(kind, func.coalesce(own, getattr(CatalogEntry, name), type_=own.type))


_INHERITED_DATES = ("end_of_sale", "end_of_sw_support", "end_of_hw_support", "ldos")
_INHERITED_AMOUNTS = ("est_value", "support_weight", "annual_support_cost")

# The items above a minor item, the nearest first. Minor items nest only so deep, so
# what an item inherits from above is read by this many joins and no recursive query.
ABOVE: tuple[Any, ...] = tuple(aliased(Item, name=f"above_{level}") for level in range(MAX_DEPTH))
_LINE: tuple[Any, ...] = (Item, *ABOVE)


def _from_groups(field: str, live: Any = None) -> ColumnElement[Any]:
    """Return what an item has in a field from the groups that the item at the top of
    its line is a current member of, as `hirdir.domain.descent` works it out: that of
    the first group, a stack before a cluster before a controller domain before any
    other and then by name, that has one in force, its own or from the group it is
    nested in."""
    top = case(
        *((one.parent_item_hid.is_(None), one.hid) for one in _LINE[:-1]),
        else_=_LINE[-1].hid,
    )
    reach = descent.group_reach(field, live)
    member: Any = aliased(DeviceGroupMember, name=f"{field}_member")
    group: Any = aliased(DeviceGroup, name=f"{field}_group")
    return (
        select(reach.c.value)
        .select_from(member)
        .join(group, group.hid == member.group_hid)
        .join(reach, reach.c.group_hid == group.hid)
        .where(
            member.item_hid == top,
            member.left_on.is_(None),
            group.record_status != "retired",
        )
        .order_by(
            case(
                *((group.type == kind, place) for place, kind in enumerate(descent.GROUP_ORDER)),
                else_=len(descent.GROUP_ORDER),
            ),
            group.name_key,
            group.hid,
        )
        .limit(1)
        .correlate(*_LINE)
        .scalar_subquery()
    )


# Whose an item is: its own owner, that of the nearest item above it that has one, or
# that of a group the item at the top of the line is a member of.
OWNER_IN_FORCE: ColumnElement[Any] = func.coalesce(
    *(one.owner_hid for one in _LINE), _from_groups("owner_hid")
)
# Where an item is, by the same descent.
LOCATION_IN_FORCE: ColumnElement[Any] = func.coalesce(
    *(one.location_hid for one in _LINE), _from_groups("location_hid")
)
# Where it is going, by the same descent.
PLANNED_IN_FORCE: ColumnElement[Any] = func.coalesce(
    *(one.planned_location_hid for one in _LINE), _from_groups("planned_location_hid")
)


def _operator_in_force() -> ColumnElement[Any]:
    """Return the operator in force for an item, as `hirdir.domain.operators` works it
    out: its own, that of the nearest item above it, that of a group the item at the
    top of the line is a current member of, or that of the place it is at. An operator
    that is retired is passed over at every level."""
    places = operators.location_reach()
    from_place = (
        select(places.c.operator_hid)
        .where(places.c.location_hid == LOCATION_IN_FORCE)
        .correlate(*_LINE)
        .scalar_subquery()
    )
    return func.coalesce(
        *(operators.live(one.operator_hid) for one in _LINE),
        _from_groups("operator_hid", operators.live),
        from_place,
    )


OPERATOR_IN_FORCE: ColumnElement[Any] = _operator_in_force()
ITEM_OPERATOR: Any = aliased(Operator, name="item_operator")
ITEM_OPERATOR_CONTACT: Any = aliased(Contact, name="item_operator_contact")
PLANNED_LOCATION: Any = aliased(Location, name="planned_location")
PLANNED_SITE: Any = aliased(Site, name="planned_site")
ITEM_LOCATION: Any = aliased(Location, name="item_location")
ITEM_SITE: Any = aliased(Site, name="item_site")
ITEM_REGION: Any = aliased(Region, name="item_region")


def _within(
    location: Any = None, site: Any = None, region: Any = None
) -> Callable[[Session, str], ColumnElement[bool]]:
    """Return the test that a record is at or beneath a place a filter names.

    The three are the columns that say which location, which site and which region the
    record is in. A place of a level the record cannot be within finds nothing.
    """

    def test(db: Session, text: str) -> ColumnElement[bool]:
        place = geography.find_place(db, text)
        if place is None:
            raise refuse(f"there is no region, site or location {text}")
        if place.level == geography.REGION:
            return false() if region is None else region.in_(geography.regions_beneath(place.hid))
        if place.level == geography.SITE:
            return false() if site is None else site == place.hid
        if location is None:
            return false()
        return location.in_(geography.locations_beneath(place.hid))

    return test


DEPTH: ColumnElement[Any] = case(
    *(
        (one.parent_item_hid.is_(None), level)
        for level, one in enumerate(_LINE)
        if level < MAX_DEPTH
    ),
    else_=MAX_DEPTH,
)


def standing(name: str) -> ColumnElement[Any]:
    """Return the lifecycle state, disposition or intent in force for an item.

    The three are taken together, from the item itself when it has a state, and
    otherwise from the nearest item above it that has one.
    """
    return case(
        *((one.lifecycle_state.is_not(None), getattr(one, name)) for one in _LINE[:-1]),
        else_=getattr(_LINE[-1], name),
    )


STATE_IN_FORCE = standing("lifecycle_state")


def _health_of(item: Any, expected_online: Any) -> ColumnElement[Any]:
    """Return the health of an item, held against an intent: the cascade of
    `hirdir.domain.health.of_item`."""
    return case(
        (
            or_(
                item.condition.in_(health.FAILED_CONDITIONS),
                and_(expected_online.is_(True), item.observed_status == health.UNREACHABLE),
            ),
            health.FAILED,
        ),
        (
            or_(
                item.condition.in_(health.POOR_CONDITIONS),
                item.observed_status.in_((health.OBSERVED_DEGRADED, health.UNREACHABLE)),
            ),
            health.DEGRADED,
        ),
        (
            or_(
                item.condition == health.GOOD_CONDITION,
                item.observed_status.in_(health.SEEN_WELL),
            ),
            health.GOOD,
        ),
        else_=health.UNKNOWN,
    )


# The health of an item, for the database to filter and sort by. A test holds it and
# `hirdir.domain.health.of_item` together.
HEALTH: ColumnElement[Any] = _health_of(Item, standing("expected_online"))
# How bad each health is: the worst first, and what is not known before the good.
HEALTH_RANKS: Mapping[str, int] = {
    health.FAILED: 0,
    health.DEGRADED: 1,
    health.UNKNOWN: 2,
    health.GOOD: 3,
}
HEALTH_RANK: ColumnElement[Any] = case(
    (HEALTH == health.FAILED, HEALTH_RANKS[health.FAILED]),
    (HEALTH == health.DEGRADED, HEALTH_RANKS[health.DEGRADED]),
    (HEALTH == health.UNKNOWN, HEALTH_RANKS[health.UNKNOWN]),
    else_=HEALTH_RANKS[health.GOOD],
)


def _with_items_above(query: Select[Any]) -> Select[Any]:
    below = Item
    for one in ABOVE:
        query = query.outerjoin(one, one.hid == below.parent_item_hid)
        below = one
    return query


def _one_of(
    start: Any, *where: ColumnElement[bool]
) -> Callable[[ColumnElement[bool]], ColumnElement[bool]]:
    """Return what makes a condition on one of several related records a condition on
    the record that has them: there is one that meets it."""

    def among(condition: ColumnElement[bool]) -> ColumnElement[bool]:
        return start.where(*where, condition).exists()

    return among


# The groups an item is in: the ones it is a current member of, that are not retired.
_ITS_GROUPS = (
    DeviceGroupMember.item_hid == Item.hid,
    DeviceGroupMember.left_on.is_(None),
    DeviceGroup.record_status != "retired",
)
_ITEM_GROUPS = _one_of(
    select(DeviceGroupMember.hid).join(DeviceGroup, DeviceGroup.hid == DeviceGroupMember.group_hid),
    *_ITS_GROUPS,
)


def _first_group(value: Any) -> ColumnElement[Any]:
    """Return the least of what the groups of an item have in a column: what a list of
    them, in order, begins with."""
    return (
        select(func.min(value))
        .select_from(DeviceGroupMember)
        .join(DeviceGroup, DeviceGroup.hid == DeviceGroupMember.group_hid)
        .where(*_ITS_GROUPS)
        .correlate(Item)
        .scalar_subquery()
    )


def _address_fields(model: Any, held: ColumnElement[bool]) -> dict[str, Field]:
    """Return the fields of the addresses of a record: of an item, or of a device group.

    `held` says that an address is the record's. The record is found by any one of its
    addresses and of their networks, and is sorted by the lowest address, as an address
    and not as text, and by the first label of its networks. `mgmt_address` is the
    primary management address, the IPv4 one before the IPv6 one, to sort by.
    """
    among = _one_of(
        select(Address.hid).outerjoin(Network, Network.hid == Address.network_hid), held
    )

    def lowest(*where: ColumnElement[bool]) -> ColumnElement[Any]:
        return (
            select(func.min(dialect.as_address(Address.address)))
            .where(held, *where)
            .correlate(model)
            .scalar_subquery()
        )

    first_network = (
        select(func.min(Network.label_key))
        .select_from(Address)
        .join(Network, Network.hid == Address.network_hid)
        .where(held)
        .correlate(model)
        .scalar_subquery()
    )
    return {
        "address": Field(
            "address", Address.address, convert=comparable, among=among, ordered_by=lowest()
        ),
        "network.label": Field("text", Network.label, among=among, ordered_by=first_network),
        "mgmt_address": Field("address", ordered_by=lowest(Address.is_primary.is_(True))),
    }


# How many minor items are directly in an item. An item with none has no number, as its
# cell has none, and so comes last.
_MINOR: Any = aliased(Item, name="minor_item")
MINOR_ITEMS: ColumnElement[Any] = func.nullif(
    select(func.count())
    .where(_MINOR.parent_item_hid == Item.hid)
    .correlate(Item)
    .scalar_subquery(),
    0,
)


ITEMS = Listing(
    model=Item,
    fields={
        **_bookkeeping(Item),
        **_columns(
            Item, "reference", "catalog_entry_hid", "owner_hid", "location_hid", "parent_item_hid"
        ),
        "parent.name": Field("text", func.coalesce(ABOVE[0].name, ABOVE[0].hostname)),
        "is_major": Field("boolean", Item.parent_item_hid.is_(None)),
        "depth": Field("integer", DEPTH.cast(Integer)),
        **_columns(
            Item,
            "text",
            "serial_number",
            "asset_tag",
            "hostname",
            "fqdn",
            "position",
            "description",
            "comments",
        ),
        # A blank name shows the hostname, so that is what a filter and a sort see.
        "name": Field("text", func.coalesce(Item.name, Item.hostname)),
        "mac_address": Field("mac", Item.mac_address, convert=mac_digits),
        "quantity": Field("integer", Item.quantity),
        **_columns(
            Item,
            "choice",
            "lifecycle_state",
            "disposition",
            "state_reason",
            "condition",
            "observed_status",
            "record_status",
        ),
        "observed_at": Field("timestamp", Item.observed_at),
        # Sorted by how bad it is, the worst first, and what is not known before the good.
        "health": Field("choice", HEALTH, ordered_by=HEALTH_RANK),
        "expected_online": Field("boolean", Item.expected_online),
        "state_changed_at": Field("timestamp", Item.state_changed_at),
        **_columns(
            Item,
            "date",
            "procured_on",
            "delivered_on",
            "in_service_on",
            "warranty_start",
            "warranty_end",
            *_INHERITED_DATES,
        ),
        **_columns(Item, "number", *_INHERITED_AMOUNTS),
        **{f"effective.{name}": _effective(name) for name in inheritance.ITEM_FIELDS},
        "effective.owner_hid": Field("reference", OWNER_IN_FORCE),
        "effective.location_hid": Field("reference", LOCATION_IN_FORCE),
        "operator_hid": Field("reference", Item.operator_hid),
        # The operator in force: who looks after the item, by its own word or from above.
        "effective.operator_hid": Field("reference", OPERATOR_IN_FORCE),
        "operator.label": Field("text", ITEM_OPERATOR.label),
        "operator.contact": Field("text", ITEM_OPERATOR_CONTACT.name),
        # Assigned to a label that nobody is behind: no contact, or one that is retired.
        "operator.is_open": Field(
            "boolean",
            and_(
                ITEM_OPERATOR.hid.is_not(None),
                or_(
                    ITEM_OPERATOR_CONTACT.hid.is_(None),
                    ITEM_OPERATOR_CONTACT.record_status == "retired",
                ),
            ),
        ),
        # Where the item is, by the location in force.
        "location": Field(
            "place",
            LOCATION_IN_FORCE,
            within=_within(LOCATION_IN_FORCE, ITEM_LOCATION.site_hid, ITEM_SITE.region_hid),
        ),
        "location.name": Field("text", ITEM_LOCATION.name),
        "location.kind": Field("choice", ITEM_LOCATION.kind),
        # Where the item is going, when that place is not in use yet.
        "planned_location_hid": Field("reference", Item.planned_location_hid),
        # The name of the place it is going to, for a column to be sorted and found by.
        "planned_location.name": Field("text", PLANNED_LOCATION.name),
        "effective.planned_location_hid": Field("reference", PLANNED_IN_FORCE),
        "planned_location": Field(
            "place",
            PLANNED_IN_FORCE,
            within=_within(PLANNED_IN_FORCE, PLANNED_LOCATION.site_hid, PLANNED_SITE.region_hid),
        ),
        "site": Field("text", ITEM_SITE.name),
        "site.code": Field("text", ITEM_SITE.code),
        "site_hid": Field("reference", ITEM_SITE.hid),
        "region": Field("text", ITEM_REGION.name),
        "region_hid": Field("reference", ITEM_REGION.hid),
        # The reason of the owner in force, where that owner is outside the team.
        "owner_exception_reason": Field(
            "text", case((Owner.is_external.is_(True), Owner.exception_reason))
        ),
        # With an owner outside the team: the owner in force, so a minor item is too.
        "owner_exception": Field("boolean", func.coalesce(Owner.is_external, false())),
        "effective.lifecycle_state": Field("choice", STATE_IN_FORCE),
        "effective.disposition": Field("choice", standing("disposition")),
        "effective.expected_online": Field("boolean", standing("expected_online")),
        "catalog.pid": Field("text", CatalogEntry.pid),
        "catalog.model_name": Field("text", CatalogEntry.model_name),
        "catalog.vendor": Field("text", Vendor.name),
        "catalog.kind": Field("choice", CatalogEntry.kind),
        "catalog.type": Field("choice", CatalogEntry.type),
        "catalog.function": Field("choice", CatalogEntry.function),
        # The owner in force: a minor item has the owner of the item it is in.
        "owner.label": Field("text", Owner.label),
        "tags": _tags("item", Item),
        "group.hid": Field("reference", DeviceGroup.hid, among=_ITEM_GROUPS),
        # Sorted by the first of them, as the record lists its groups: by name.
        "group.name": Field(
            "text",
            DeviceGroup.name,
            among=_ITEM_GROUPS,
            ordered_by=_first_group(DeviceGroup.name_key),
        ),
        "group.type": Field(
            "choice",
            DeviceGroup.type,
            among=_ITEM_GROUPS,
            ordered_by=_first_group(DeviceGroup.type),
        ),
        **_address_fields(Item, Address.item_hid == Item.hid),
        "minor_items": Field("integer", ordered_by=MINOR_ITEMS),
    },
    joined=lambda query: (
        _with_items_above(query)
        .outerjoin(CatalogEntry, CatalogEntry.hid == Item.catalog_entry_hid)
        .outerjoin(Vendor, Vendor.hid == CatalogEntry.vendor_hid)
        .outerjoin(Owner, Owner.hid == OWNER_IN_FORCE)
        .outerjoin(ITEM_OPERATOR, ITEM_OPERATOR.hid == OPERATOR_IN_FORCE)
        .outerjoin(ITEM_OPERATOR_CONTACT, ITEM_OPERATOR_CONTACT.hid == ITEM_OPERATOR.contact_hid)
        .outerjoin(PLANNED_LOCATION, PLANNED_LOCATION.hid == PLANNED_IN_FORCE)
        .outerjoin(PLANNED_SITE, PLANNED_SITE.hid == PLANNED_LOCATION.site_hid)
        .outerjoin(ITEM_LOCATION, ITEM_LOCATION.hid == LOCATION_IN_FORCE)
        .outerjoin(ITEM_SITE, ITEM_SITE.hid == ITEM_LOCATION.site_hid)
        .outerjoin(ITEM_REGION, ITEM_REGION.hid == ITEM_SITE.region_hid)
    ),
    default_sort=("name",),
)

_PARENT_GROUP: Any = aliased(DeviceGroup, name="parent_group")
_GROUP_LOCATION: Any = aliased(Location, name="group_location")
_GROUP_SITE: Any = aliased(Site, name="group_site")
_GROUP_REGION: Any = aliased(Region, name="group_region")
_GROUP_OPERATOR: Any = aliased(Operator, name="group_operator")
_GROUP_PLANNED: Any = aliased(Location, name="group_planned_location")
_GROUP_PLANNED_SITE: Any = aliased(Site, name="group_planned_site")


def _group_in_force(field: str, live: Any = None) -> ColumnElement[Any]:
    """Return what a group has in force in a field: its own, or that of the nearest
    group it is nested in that has one."""
    reach = descent.group_reach(field, live)
    return (
        select(reach.c.value)
        .where(reach.c.group_hid == DeviceGroup.hid)
        .correlate(DeviceGroup)
        .scalar_subquery()
    )


GROUP_OWNER_IN_FORCE: ColumnElement[Any] = func.coalesce(
    DeviceGroup.owner_hid, _group_in_force("owner_hid")
)
GROUP_OPERATOR_IN_FORCE: ColumnElement[Any] = _group_in_force("operator_hid", operators.live)
GROUP_LOCATION_IN_FORCE: ColumnElement[Any] = func.coalesce(
    DeviceGroup.location_hid, _group_in_force("location_hid")
)
GROUP_PLANNED_IN_FORCE: ColumnElement[Any] = func.coalesce(
    DeviceGroup.planned_location_hid, _group_in_force("planned_location_hid")
)

# How many current members a group has, as `hirdir.domain.groups.member_counts` counts.
MEMBER_COUNT: ColumnElement[Any] = (
    select(func.count())
    .select_from(DeviceGroupMember)
    .where(DeviceGroupMember.group_hid == DeviceGroup.hid, DeviceGroupMember.left_on.is_(None))
    .correlate(DeviceGroup)
    .scalar_subquery()
)

_MASTER: Any = aliased(Item, name="master")
_SEEN_MASTER: Any = aliased(Item, name="observed_master")


def shown_name(item: Any) -> ColumnElement[Any]:
    """Return the name an item is shown by where another record names it: its name,
    or else its hostname, its serial number or its asset tag."""
    return func.coalesce(item.name, item.hostname, item.serial_number, item.asset_tag)


def _of_master(value: Any) -> ColumnElement[Any]:
    """Return what the master that is intended has in a column: the current member of a
    stack with that role, as `hirdir.domain.groups.masters` finds it."""
    return (
        select(func.min(value))
        .select_from(DeviceGroupMember)
        .join(_MASTER, _MASTER.hid == DeviceGroupMember.item_hid)
        .where(
            DeviceGroupMember.group_hid == DeviceGroup.hid,
            DeviceGroupMember.left_on.is_(None),
            DeviceGroupMember.role == groups.MASTER,
            DeviceGroup.type == "stack",
        )
        .correlate(DeviceGroup)
        .scalar_subquery()
    )


def _of_seen_master(value: Any) -> ColumnElement[Any]:
    """Return what the master that is seen has in a column."""
    return (
        select(value)
        .where(_SEEN_MASTER.hid == DeviceGroup.observed_master_hid)
        .correlate(DeviceGroup)
        .scalar_subquery()
    )


# The serial number a group reports: that of the master that is seen, when there is
# one, and else that of the one intended.
GROUP_SERIAL: ColumnElement[Any] = case(
    (_of_seen_master(_SEEN_MASTER.hid).is_not(None), _of_seen_master(_SEEN_MASTER.serial_number)),
    else_=_of_master(_MASTER.serial_number),
)


def _group_health(said: Mapping[str, Any]) -> ColumnElement[Any]:
    """Return the health of a stack or a cluster, from its current members and what is
    seen of it: the cascade of `hirdir.domain.health.of_group`, with the members as
    `hirdir.domain.groups.health_of` reads them. `said` is what to answer for each
    health. A group of another type has none. A test holds the two together.
    """
    member: Any = aliased(Item, name="health_member")
    its = _health_of(member, member.expected_online)
    members = func.count()

    def those(condition: ColumnElement[bool]) -> ColumnElement[Any]:
        return func.coalesce(func.sum(case((condition, 1), else_=0)), 0)

    worked_out = case(
        (members == 0, said[health.UNKNOWN]),
        (
            or_(
                DeviceGroup.observed_status == health.UNREACHABLE,
                those(its == health.FAILED) == members,
            ),
            said[health.FAILED],
        ),
        (
            or_(
                DeviceGroup.observed_status == health.OBSERVED_DEGRADED,
                those(its.in_((health.FAILED, health.DEGRADED))) > 0,
                those(member.lifecycle_state.in_(health.OUT_OF_SERVICE)) > 0,
                and_(
                    DeviceGroup.expected_members.is_not(None),
                    members < DeviceGroup.expected_members,
                ),
                and_(
                    DeviceGroup.expected_members.is_(None),
                    DeviceGroup.type == "stack",
                    members == 1,
                ),
            ),
            said[health.DEGRADED],
        ),
        (
            or_(
                DeviceGroup.observed_status.in_(health.SEEN_WELL),
                those(its == health.GOOD) == members,
            ),
            said[health.GOOD],
        ),
        else_=said[health.UNKNOWN],
    )
    of_members = (
        select(worked_out)
        .select_from(DeviceGroupMember)
        .join(member, member.hid == DeviceGroupMember.item_hid)
        .where(DeviceGroupMember.group_hid == DeviceGroup.hid, DeviceGroupMember.left_on.is_(None))
        .correlate(DeviceGroup)
        .scalar_subquery()
    )
    return case((DeviceGroup.type.in_(health.HAS_HEALTH), of_members), else_=None)


GROUP_HEALTH: ColumnElement[Any] = _group_health({value: value for value in health.HEALTHS})
GROUP_HEALTH_RANK: ColumnElement[Any] = _group_health(HEALTH_RANKS)

DEVICE_GROUPS = Listing(
    model=DeviceGroup,
    fields={
        **_bookkeeping(DeviceGroup),
        **_columns(DeviceGroup, "reference", "parent_group_hid", "owner_hid", "location_hid"),
        "effective.owner_hid": Field("reference", GROUP_OWNER_IN_FORCE),
        "effective.location_hid": Field("reference", GROUP_LOCATION_IN_FORCE),
        "effective.planned_location_hid": Field("reference", GROUP_PLANNED_IN_FORCE),
        "location": Field(
            "place",
            GROUP_LOCATION_IN_FORCE,
            within=_within(
                GROUP_LOCATION_IN_FORCE, _GROUP_LOCATION.site_hid, _GROUP_SITE.region_hid
            ),
        ),
        "location.name": Field("text", _GROUP_LOCATION.name),
        "site": Field("text", _GROUP_SITE.name),
        "region": Field("text", _GROUP_REGION.name),
        "owner_exception": Field("boolean", func.coalesce(Owner.is_external, false())),
        "operator_hid": Field("reference", DeviceGroup.operator_hid),
        "effective.operator_hid": Field("reference", GROUP_OPERATOR_IN_FORCE),
        "operator.label": Field("text", _GROUP_OPERATOR.label),
        "planned_location_hid": Field("reference", DeviceGroup.planned_location_hid),
        "planned_location.name": Field("text", _GROUP_PLANNED.name),
        "planned_location": Field(
            "place",
            GROUP_PLANNED_IN_FORCE,
            within=_within(
                GROUP_PLANNED_IN_FORCE,
                _GROUP_PLANNED.site_hid,
                _GROUP_PLANNED_SITE.region_hid,
            ),
        ),
        **_columns(DeviceGroup, "text", "name", "hostname", "fqdn"),
        **_columns(DeviceGroup, "choice", "type", "record_status", "managed_as", "observed_status"),
        "expected_members": Field("integer", DeviceGroup.expected_members),
        "observed_at": Field("timestamp", DeviceGroup.observed_at),
        # A stack answers to the serial number of any of its current members.
        "member.serial_number": Field(
            "text",
            Item.serial_number,
            among=_one_of(
                select(DeviceGroupMember.hid).join(Item, Item.hid == DeviceGroupMember.item_hid),
                DeviceGroupMember.group_hid == DeviceGroup.hid,
                DeviceGroupMember.left_on.is_(None),
            ),
        ),
        # What the columns of the grid that are worked out are sorted by. The serial
        # number is the one the group reports, where the filter finds a stack by any.
        "serial_number": Field("text", ordered_by=dialect.folded(GROUP_SERIAL)),
        "master.name": Field("text", ordered_by=dialect.folded(_of_master(shown_name(_MASTER)))),
        "observed_master.name": Field(
            "text", ordered_by=dialect.folded(_of_seen_master(shown_name(_SEEN_MASTER)))
        ),
        "member_count": Field("integer", ordered_by=MEMBER_COUNT),
        # The worst first, as an item's is, and a group that has no health last.
        "health": Field("choice", ordered_by=GROUP_HEALTH_RANK),
        "owner.label": Field("text", Owner.label),
        "parent.name": Field("text", _PARENT_GROUP.name),
        "tags": _tags("device_group", DeviceGroup),
        "member.item_hid": Field(
            "reference",
            DeviceGroupMember.item_hid,
            among=_one_of(
                select(DeviceGroupMember.hid),
                DeviceGroupMember.group_hid == DeviceGroup.hid,
                DeviceGroupMember.left_on.is_(None),
            ),
        ),
        **_address_fields(DeviceGroup, Address.group_hid == DeviceGroup.hid),
    },
    joined=lambda query: (
        query.outerjoin(Owner, Owner.hid == GROUP_OWNER_IN_FORCE)
        .outerjoin(_PARENT_GROUP, _PARENT_GROUP.hid == DeviceGroup.parent_group_hid)
        .outerjoin(_GROUP_LOCATION, _GROUP_LOCATION.hid == GROUP_LOCATION_IN_FORCE)
        .outerjoin(_GROUP_SITE, _GROUP_SITE.hid == _GROUP_LOCATION.site_hid)
        .outerjoin(_GROUP_REGION, _GROUP_REGION.hid == _GROUP_SITE.region_hid)
        .outerjoin(_GROUP_OPERATOR, _GROUP_OPERATOR.hid == GROUP_OPERATOR_IN_FORCE)
        .outerjoin(_GROUP_PLANNED, _GROUP_PLANNED.hid == GROUP_PLANNED_IN_FORCE)
        .outerjoin(_GROUP_PLANNED_SITE, _GROUP_PLANNED_SITE.hid == _GROUP_PLANNED.site_hid)
    ),
    default_sort=("name",),
)

DEVICE_GROUP_MEMBERS = Listing(
    model=DeviceGroupMember,
    fields={
        **_bookkeeping(DeviceGroupMember),
        **_columns(DeviceGroupMember, "reference", "group_hid", "item_hid"),
        "role": Field("choice", DeviceGroupMember.role),
        "position": Field("integer", DeviceGroupMember.position),
        **_columns(DeviceGroupMember, "date", "joined_on", "left_on"),
        "group.name": Field("text", DeviceGroup.name),
        "group.type": Field("choice", DeviceGroup.type),
        "item.name": Field("text", func.coalesce(Item.name, Item.hostname)),
    },
    joined=lambda query: query.join(
        DeviceGroup, DeviceGroup.hid == DeviceGroupMember.group_hid
    ).join(Item, Item.hid == DeviceGroupMember.item_hid),
    default_sort=("group.name", "position", "joined_on"),
    has_status=False,
)

NETWORKS = Listing(
    model=Network,
    fields={
        **_bookkeeping(Network),
        "label": Field("text", Network.label),
        "kind": Field("choice", Network.kind),
    },
    joined=lambda query: query,
    default_sort=("label",),
    has_status=False,
)

ADDRESSES = Listing(
    model=Address,
    fields={
        **_bookkeeping(Address),
        **_columns(Address, "reference", "item_hid", "group_hid", "network_hid"),
        "address": Field("address", Address.address, convert=comparable),
        # 4 or 6: an address with a colon in it is IPv6.
        "family": Field("integer", case((Address.address.contains(":"), 6), else_=4)),
        "role": Field("choice", Address.role),
        "is_primary": Field("boolean", Address.is_primary),
        "network.label": Field("text", Network.label),
        "item.name": Field("text", func.coalesce(Item.name, Item.hostname)),
        "group.name": Field("text", DeviceGroup.name),
    },
    joined=lambda query: (
        query.outerjoin(Network, Network.hid == Address.network_hid)
        .outerjoin(Item, Item.hid == Address.item_hid)
        .outerjoin(DeviceGroup, DeviceGroup.hid == Address.group_hid)
    ),
    default_sort=("address", "network.label"),
    has_status=False,
)

CATALOG_ENTRIES = Listing(
    model=CatalogEntry,
    fields={
        **_bookkeeping(CatalogEntry),
        **_columns(CatalogEntry, "reference", "vendor_hid", "successor_hid"),
        "vendor": Field("text", Vendor.name),
        **_columns(CatalogEntry, "text", "pid", "model_name", "description"),
        **_columns(
            CatalogEntry, "choice", "kind", "type", "function", "review_status", "record_status"
        ),
        **_columns(CatalogEntry, "date", *_INHERITED_DATES),
        **_columns(CatalogEntry, "number", *_INHERITED_AMOUNTS, "stack_discount_pct"),
        "tags": _tags("catalog_entry", CatalogEntry),
    },
    joined=lambda query: query.join(Vendor, Vendor.hid == CatalogEntry.vendor_hid),
    default_sort=("vendor", "pid"),
)

VENDORS = Listing(
    model=Vendor,
    fields={
        **_bookkeeping(Vendor),
        **_columns(Vendor, "text", "name", "notes"),
        # The other spellings of the name: sorted by the least of them.
        "aliases": Field("text", ordered_by=dialect.least_of_list(Vendor.aliases)),
        "review_status": Field("choice", Vendor.review_status),
    },
    joined=lambda query: query,
    default_sort=("name",),
    has_status=False,
)

_PRIMARY: Any = aliased(Contact, name="primary_contact")

OWNERS = Listing(
    model=Owner,
    fields={
        **_bookkeeping(Owner),
        **_columns(Owner, "text", "label", "organization", "exception_reason"),
        # The primary of its people, by name.
        "primary.name": Field(
            "text",
            ordered_by=select(func.min(_PRIMARY.name_key))
            .select_from(OwnerMember)
            .join(_PRIMARY, _PRIMARY.hid == OwnerMember.contact_hid)
            .where(OwnerMember.owner_hid == Owner.hid, OwnerMember.role == owners.PRIMARY)
            .correlate(Owner)
            .scalar_subquery(),
        ),
        "is_external": Field("boolean", Owner.is_external),
        "record_status": Field("choice", Owner.record_status),
        "tags": _tags("owner", Owner),
        "member.contact_hid": Field(
            "reference",
            OwnerMember.contact_hid,
            among=_one_of(select(OwnerMember.hid), OwnerMember.owner_hid == Owner.hid),
        ),
    },
    joined=lambda query: query,
    default_sort=("label",),
)

_OWNER_CONTACT: Any = aliased(Contact, name="member_contact")

OWNER_MEMBERS = Listing(
    model=OwnerMember,
    fields={
        **_bookkeeping(OwnerMember),
        **_columns(OwnerMember, "reference", "owner_hid", "contact_hid"),
        # The primary first, so that a file of members loads into an owner that has none.
        "role": Field(
            "choice", OwnerMember.role, ordered_by=case((OwnerMember.role == "primary", 0), else_=1)
        ),
        "priority": Field("integer", OwnerMember.priority),
        "owner.label": Field("text", Owner.label),
        "contact.name": Field("text", _OWNER_CONTACT.name),
    },
    joined=lambda query: query.join(Owner, Owner.hid == OwnerMember.owner_hid).join(
        _OWNER_CONTACT, _OWNER_CONTACT.hid == OwnerMember.contact_hid
    ),
    default_sort=("owner.label", "role", "priority"),
    has_status=False,
)

_SHIPPING = (*(f"ship_{name}" for name in ADDRESS_FIELDS), "ship_instructions")
_PARENT_REGION: Any = aliased(Region, name="parent_region")

REGIONS = Listing(
    model=Region,
    fields={
        **_bookkeeping(Region),
        "parent_region_hid": Field("reference", Region.parent_region_hid),
        "parent.name": Field("text", _PARENT_REGION.name),
        # At or beneath a region: the region itself, and every region within it.
        "region": Field("place", Region.hid, within=_within(region=Region.hid)),
        "operator_hid": Field("reference", Region.operator_hid),
        **_columns(Region, "text", "name", "code", "notes", *_SHIPPING),
        "record_status": Field("choice", Region.record_status),
        "tags": _tags("region", Region),
    },
    joined=lambda query: query.outerjoin(
        _PARENT_REGION, _PARENT_REGION.hid == Region.parent_region_hid
    ),
    default_sort=("name",),
)

SITES = Listing(
    model=Site,
    fields={
        **_bookkeeping(Site),
        "region_hid": Field("reference", Site.region_hid),
        "region": Field(
            "place", Site.region_hid, within=_within(site=Site.hid, region=Site.region_hid)
        ),
        "region.name": Field("text", Region.name),
        "operator_hid": Field("reference", Site.operator_hid),
        **_columns(Site, "text", "name", "code", "notes", *ADDRESS_FIELDS, *_SHIPPING),
        **_columns(Site, "number", "latitude", "longitude"),
        "ship_same_as_address": Field("boolean", Site.ship_same_as_address),
        "record_status": Field("choice", Site.record_status),
        "tags": _tags("site", Site),
    },
    joined=lambda query: query.join(Region, Region.hid == Site.region_hid),
    default_sort=("name",),
)

_PARENT_LOCATION: Any = aliased(Location, name="parent_location")
_LOCATION_REGION: Any = aliased(Region, name="location_region")

LOCATIONS = Listing(
    model=Location,
    fields={
        **_bookkeeping(Location),
        **_columns(Location, "reference", "site_hid", "parent_location_hid"),
        "location": Field(
            "place", Location.hid, within=_within(Location.hid, Location.site_hid, Site.region_hid)
        ),
        "site.name": Field("text", Site.name),
        "site.code": Field("text", Site.code),
        "region.name": Field("text", _LOCATION_REGION.name),
        "parent.name": Field("text", _PARENT_LOCATION.name),
        "is_top": Field("boolean", Location.parent_location_hid.is_(None)),
        # In use: active, as is everything it is in. What is not is planned for.
        "in_use": Field("boolean", Location.hid.not_in(geography.locations_not_in_use())),
        "operator_hid": Field("reference", Location.operator_hid),
        **_columns(Location, "text", "name", "code", "notes", *ADDRESS_FIELDS, *_SHIPPING),
        "kind": Field("choice", Location.kind),
        **_columns(Location, "number", "latitude", "longitude"),
        "ship_same_as_address": Field("boolean", Location.ship_same_as_address),
        "record_status": Field("choice", Location.record_status),
        "tags": _tags("location", Location),
    },
    joined=lambda query: (
        query.join(Site, Site.hid == Location.site_hid)
        .join(_LOCATION_REGION, _LOCATION_REGION.hid == Site.region_hid)
        .outerjoin(_PARENT_LOCATION, _PARENT_LOCATION.hid == Location.parent_location_hid)
    ),
    default_sort=("site.name", "name"),
)

CONTACTS = Listing(
    model=Contact,
    fields={
        **_bookkeeping(Contact),
        **_columns(Contact, "text", "name", "organization", "email", "phone", "notes"),
        "record_status": Field("choice", Contact.record_status),
        "tags": _tags("contact", Contact),
        # How many places, owners and operators name it, as its record counts them.
        "uses": Field("integer", ordered_by=_counted(Contact, *contacts.USED_BY)),
    },
    joined=lambda query: query,
    default_sort=("name",),
)

_OPERATOR_CONTACT: Any = aliased(Contact, name="operator_contact")

OPERATORS = Listing(
    model=Operator,
    fields={
        **_bookkeeping(Operator),
        **_columns(Operator, "text", "label", "description", "colour"),
        "contact_hid": Field("reference", Operator.contact_hid),
        "contact.name": Field("text", _OPERATOR_CONTACT.name),
        "contact.email": Field("text", _OPERATOR_CONTACT.email),
        "is_open": Field(
            "boolean",
            or_(_OPERATOR_CONTACT.hid.is_(None), _OPERATOR_CONTACT.record_status == "retired"),
        ),
        "record_status": Field("choice", Operator.record_status),
        # How many items, groups and places are given it, as its record counts them.
        "uses": Field(
            "integer",
            ordered_by=_counted(Operator, *(holder.operator_hid for holder in operators.HOLDERS)),
        ),
    },
    joined=lambda query: query.outerjoin(
        _OPERATOR_CONTACT, _OPERATOR_CONTACT.hid == Operator.contact_hid
    ),
    default_sort=("label",),
)

CONTACT_ASSIGNMENTS = Listing(
    model=ContactAssignment,
    fields={
        **_bookkeeping(ContactAssignment),
        **_columns(
            ContactAssignment, "reference", "contact_hid", "region_hid", "site_hid", "location_hid"
        ),
        "role": Field("choice", ContactAssignment.role),
        "priority": Field("integer", ContactAssignment.priority),
        "stop_inheritance": Field("boolean", ContactAssignment.stop_inheritance),
        "contact.name": Field("text", Contact.name),
        "contact.email": Field("text", Contact.email),
    },
    joined=lambda query: query.outerjoin(Contact, Contact.hid == ContactAssignment.contact_hid),
    default_sort=("role", "priority", "contact.name"),
    has_status=False,
)

TAGS = Listing(
    model=Tag,
    fields={**_bookkeeping(Tag), **_columns(Tag, "text", "label", "colour", "description")},
    joined=lambda query: query,
    default_sort=("label",),
    has_status=False,
)


def default_view(
    listing: Listing, include_archived: bool, include_drafts: bool
) -> list[ColumnElement[bool]]:
    """Return what a list leaves out unless asked: drafts, and retired and archived records."""
    if not listing.has_status:
        return []
    model = listing.model
    left_out: list[ColumnElement[bool]] = []
    if not include_drafts:
        left_out.append(model.record_status != "draft")
    if not include_archived:
        left_out.append(model.record_status != "retired")
        if model is Item:
            # The state in force: a module of an archived chassis is archived with it.
            left_out.append(or_(STATE_IN_FORCE.is_(None), STATE_IN_FORCE != lifecycle.ARCHIVED))
    return left_out


LISTINGS: tuple[Listing, ...] = (
    ITEMS,
    DEVICE_GROUPS,
    DEVICE_GROUP_MEMBERS,
    NETWORKS,
    ADDRESSES,
    CATALOG_ENTRIES,
    VENDORS,
    OWNERS,
    OWNER_MEMBERS,
    REGIONS,
    SITES,
    LOCATIONS,
    CONTACTS,
    OPERATORS,
    CONTACT_ASSIGNMENTS,
    TAGS,
)


def warm() -> int:
    """Build the statement of every list once, with every field, before a request is
    answered. Return how many statements were built.

    The tables and their aliases work out their columns the first time they are used,
    and that first time is not safe to share between two requests answered at once: a
    server just started could answer its first lists with an error until it was
    started again. Built here, by the one thread that starts the application, they are
    ready before any request arrives.
    """
    built = 0
    for listing in LISTINGS:
        columns = [
            term
            for one in listing.fields.values()
            for term in (one.expression, one.ordered_by)
            if term is not None
        ]
        # Joined from the record alone, as a list is, and the fields added after.
        base = select(listing.model).select_from(listing.model)
        str(listing.joined(base).add_columns(*columns).compile())
        built += 1
    return built
