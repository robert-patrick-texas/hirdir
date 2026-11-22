"""The fields each list can be filtered and sorted by, and how the list is read.

A field named here is one a filter may use on that list. Dotted names reach a related
record (`catalog.pid`, `owner.label`), and `effective.<field>` is the value in force of
a field that inherits.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import (
    BigInteger,
    ColumnElement,
    Date,
    Integer,
    Select,
    and_,
    case,
    false,
    func,
    literal,
    or_,
    select,
    type_coerce,
    union_all,
)
from sqlalchemy.orm import Session, aliased

from hirdir.db import dialect
from hirdir.db.models import (
    ADDRESS_FIELDS,
    Address,
    Agreement,
    CapacityLine,
    CapacityLineTarget,
    CatalogEntry,
    Circuit,
    CircuitCarrier,
    CircuitContact,
    CircuitCost,
    CircuitDevice,
    CircuitGroup,
    CircuitGroupMember,
    Contact,
    ContactAssignment,
    Contract,
    ContractContact,
    ContractCoverage,
    Country,
    DeviceGroup,
    DeviceGroupMember,
    ExternalSystem,
    Item,
    ItemReplacement,
    Location,
    Network,
    Operator,
    Owner,
    OwnerMember,
    PurchaseLine,
    PurchaseRequest,
    Region,
    Registration,
    Scaled,
    Site,
    State,
    Tag,
    TagLink,
    User,
    Vendor,
    VendorContact,
)
from hirdir.domain import (
    circuit_records,
    circuits,
    contacts,
    contracts,
    descent,
    geography,
    groups,
    health,
    hosting,
    inheritance,
    lifecycle,
    not_renewed,
    operators,
    owners,
    purchases,
    records,
    systems,
    weights,
)
from hirdir.domain.addresses import comparable
from hirdir.domain.items import MAX_DEPTH, mac_digits
from hirdir.io import hosted
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
    if name == "support_weight":
        # A major item's weight in force takes the default and the minimum (P-155).
        return Field("number", weights.item_weight_column())
    if name == not_renewed.FIELD:
        # Its own, or its model's; blank for an item with no model and no word of its own.
        return Field("boolean", not_renewed.value_of(Item, CatalogEntry))
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


# The first value each item has from its own groups, one table for each field, shared by
# every level of every walk in a statement, so that it is worked out once (P-175).
_FIRST: dict[tuple[str, bool], Any] = {}


def _first_from_groups(field: str, live: Any = None) -> Any:
    """Return, as a table, each item that is a current member of a group with a value in
    force in a field, with the value of the first such group, as `hirdir.domain.descent`
    ranks them: a stack before a cluster before a controller domain before any other,
    then by name and by HID; and `holder_hid`, the group that holds that value."""
    cached = (field, live is not None)
    if cached in _FIRST:
        return _FIRST[cached]
    reach = descent.group_reach(field, live)
    member: Any = aliased(DeviceGroupMember, name=f"first_{field}_member")
    group: Any = aliased(DeviceGroup, name=f"first_{field}_group")
    rank = case(
        *((group.type == kind, place) for place, kind in enumerate(descent.GROUP_ORDER)),
        else_=len(descent.GROUP_ORDER),
    )
    ranked = (
        select(
            member.item_hid.label("item_hid"),
            reach.c.value.label("value"),
            reach.c.holder_hid.label("holder_hid"),
            func.row_number()
            .over(partition_by=member.item_hid, order_by=(rank, group.name_key, group.hid))
            .label("place"),
        )
        .select_from(member)
        .join(group, group.hid == member.group_hid)
        .join(reach, reach.c.group_hid == group.hid)
        .where(member.left_on.is_(None), group.record_status != "retired")
        .subquery(f"ranked_{field}")
    )
    # Worked out once for the statement, and not again at each level that reads it.
    first = dialect.materialized(
        select(ranked.c.item_hid, ranked.c.value, ranked.c.holder_hid).where(ranked.c.place == 1),
        f"first_{field}",
    )
    _FIRST[cached] = first
    return first


def _from_groups(
    field: str, level: int, live: Any = None, column: str = "value"
) -> ColumnElement[Any]:
    """Return what the record at `level` of an item's line, 0 the item itself, has in a
    field from the groups it is a current member of: the value of the first of them that
    has one in force. With `column` of `holder_hid`, the group that holds that value."""
    first = _first_from_groups(field, live)
    return (
        select(getattr(first.c, column))
        .where(first.c.item_hid == _LINE[level].hid)
        .correlate(*_LINE)
        .scalar_subquery()
    )


# --- the walk through what an item runs on (P-246) -------------------------------------
#
# What runs on a host has, after its own line, what its host has: the host and its
# groups, the items the host is installed in and their groups, then what the top of
# that line runs on in its turn, or the stack or the cluster it runs on, which answers
# as a group does. A line of hosts is at most three long, so the walk is read by a fixed
# number of joins, as the line of minor items is; and it is worked out once for each
# statement, for the items that run on a host alone, so that an inventory in which
# nothing does pays one look at an empty table.

_HOSTED: Any = aliased(Item, name="hosted_item")
# Each hop of the line of hosts: the host, the items it is installed in, the top of
# those, and the group the top of the line before runs on.
_HOPS: tuple[tuple[Any, ...], ...] = tuple(
    (
        aliased(Item, name=f"host_{hop}"),
        *(aliased(Item, name=f"host_{hop}_above_{level}") for level in range(MAX_DEPTH)),
    )
    for hop in range(hosting.MAX_LINE - 1)
)
_HOST_GROUPS: tuple[Any, ...] = tuple(
    aliased(DeviceGroup, name=f"host_group_{hop}") for hop in range(hosting.MAX_LINE - 1)
)


def _top_host(line: Sequence[Any], column: str) -> ColumnElement[Any]:
    """Return what the top of a line of items runs on, by one of the two columns: only a
    major item names a host, so it is the one of the line that names one."""
    return func.coalesce(*(getattr(one, column) for one in reversed(line)))


def _hosts_joined(query: Select[Any]) -> Select[Any]:
    """Join to a statement of `_HOSTED` the records of its line of hosts."""
    below: tuple[Any, ...] = (_HOSTED,)
    for hop, line in enumerate(_HOPS):
        host = line[0]
        top_item = _HOSTED.host_item_hid if hop == 0 else _top_host(below, "host_item_hid")
        top_group = _HOSTED.host_group_hid if hop == 0 else _top_host(below, "host_group_hid")
        group = _HOST_GROUPS[hop]
        query = query.outerjoin(
            group, and_(group.hid == top_group, group.record_status != "retired")
        ).outerjoin(host, host.hid == top_item)
        for upper, lower in zip(line[1:], line[:-1], strict=True):
            query = query.outerjoin(upper, upper.hid == lower.parent_item_hid)
        below = line
    return query


def _group_of_alias(field: str, one: Any, live: Any, column: str) -> ColumnElement[Any]:
    """Return what a record of the line of hosts has from its own groups."""
    first = _first_from_groups(field, live)
    return (
        select(getattr(first.c, column))
        .where(first.c.item_hid == one.hid)
        .correlate(one)
        .scalar_subquery()
    )


def _host_group_value(field: str, group: Any, live: Any, column: str) -> ColumnElement[Any]:
    """Return what a stack or a cluster that something runs on has in force: its own, or
    that of the group it is nested in; with `column` of `holder_hid`, the group that
    holds it."""
    reach = descent.group_reach(field, live)
    return (
        select(getattr(reach.c, column))
        .where(reach.c.group_hid == group.hid)
        .correlate(group)
        .scalar_subquery()
    )


_THROUGH: dict[tuple[str, bool], Any] = {}


def _through_hosts(field: str, live: Any = None) -> Any:
    """Return, as a table, each item that runs on a host with what it has from it in a
    field: `value`, and for the operator `holder_hid`, the record that holds it, and
    `source`, `host` where that is an item of the line of hosts, and `device_group`
    where it is a group: one of
    those items is a member of, the stack or the cluster it runs on, or one that is
    nested in, as `hirdir.domain.descent.of_items` says."""
    cached = (field, live is not None)
    if cached in _THROUGH:
        return _THROUGH[cached]
    steps: list[tuple[ColumnElement[Any], ColumnElement[Any], ColumnElement[Any]]] = []
    for hop, line in enumerate(_HOPS):
        group = _HOST_GROUPS[hop]
        steps.append(
            (
                _host_group_value(field, group, live, "value"),
                _host_group_value(field, group, live, "holder_hid"),
                literal(descent.SOURCE_GROUP),
            )
        )
        for one in line:
            own = getattr(one, field)
            steps.append((live(own) if live is not None else own, one.hid, literal("host")))
            steps.append(
                (
                    _group_of_alias(field, one, live, "value"),
                    _group_of_alias(field, one, live, "holder_hid"),
                    literal(descent.SOURCE_GROUP),
                )
            )
    value = func.coalesce(*(step[0] for step in steps))

    def chosen(at: int) -> ColumnElement[Any]:
        return case(*((step[0].is_not(None), step[at]) for step in steps), else_=None)

    columns = [_HOSTED.hid.label("item_hid"), value.label("value")]
    if live is not None:
        # Where it is had from is asked of the operator alone (P-177): the other fields
        # are spared working each step out twice more for every item that runs on a host.
        columns += [chosen(1).label("holder_hid"), chosen(2).label("source")]
    rows = _hosts_joined(select(*columns).select_from(_HOSTED)).where(
        or_(_HOSTED.host_item_hid.is_not(None), _HOSTED.host_group_hid.is_not(None))
    )
    through = dialect.materialized(rows, f"through_hosts_{field}")
    _THROUGH[cached] = through
    return through


# The top of an item's own line: the one whose host it has the rest of its walk from.
_TOP: ColumnElement[Any] = func.coalesce(*(one.hid for one in reversed(_LINE)))
_RUNS_ON_SOMETHING: ColumnElement[bool] = or_(
    _top_host(_LINE, "host_item_hid").is_not(None),
    _top_host(_LINE, "host_group_hid").is_not(None),
)


def _from_hosts(field: str, live: Any = None, column: str = "value") -> ColumnElement[Any]:
    """Return what an item has in a field through what the top of its line runs on."""
    through = _through_hosts(field, live)
    found = (
        select(getattr(through.c, column))
        .where(through.c.item_hid == _TOP)
        .correlate(*_LINE)
        .scalar_subquery()
    )
    # Looked up only for an item whose line runs on something: the others, nearly all
    # of an inventory, pay two columns they have read already. And written only where
    # something runs on a host at all: elsewhere the statement is as it was.
    return hosted.IfHosted(case((_RUNS_ON_SOMETHING, found), else_=None))


def _walk(field: str, live: Any = None) -> list[ColumnElement[Any]]:
    """Return the steps of an item's walk up its line for a field, in order (P-175): at
    each record, its own value and then its groups'; and last what it has through what
    the top of its line runs on (P-246). A record the line does not reach is an outer
    join that holds nothing."""
    steps: list[ColumnElement[Any]] = []
    for level, one in enumerate(_LINE):
        own = getattr(one, field)
        steps.append(live(own) if live is not None else own)
        steps.append(_from_groups(field, level, live))
    steps.append(_from_hosts(field, live))
    return steps


# Whose an item is, where it is and where it is going: the first value of its walk.
OWNER_IN_FORCE: ColumnElement[Any] = func.coalesce(*_walk("owner_hid"))
LOCATION_IN_FORCE: ColumnElement[Any] = func.coalesce(*_walk("location_hid"))
PLANNED_IN_FORCE: ColumnElement[Any] = func.coalesce(*_walk("planned_location_hid"))


# The operator each location has from its place, shared by every statement's walks.
_PLACES: Any = operators.location_reach()


def _operator_in_force() -> ColumnElement[Any]:
    """Return the operator in force for an item, as `hirdir.domain.operators` works it
    out: the first of its walk, its own and its groups', then each item above it and
    that item's groups, or else that of the place it is at. An operator that is retired
    is passed over at every level."""
    places = _PLACES
    from_place = (
        select(places.c.operator_hid)
        .where(places.c.location_hid == LOCATION_IN_FORCE)
        .correlate(*_LINE)
        .scalar_subquery()
    )
    return func.coalesce(*_walk("operator_hid", operators.live), from_place)


OPERATOR_IN_FORCE: ColumnElement[Any] = _operator_in_force()


def _operator_source(hid: bool) -> ColumnElement[Any]:
    """Return how an item has its operator in force, `own`, `parent_item`,
    `device_group`, `location`, `site`, `region` or `none`, or with `hid` the record it
    has it from: the step of its walk that decides (P-177)."""
    places = _PLACES

    def of_place(column: Any) -> ColumnElement[Any]:
        return (
            select(column)
            .where(places.c.location_hid == LOCATION_IN_FORCE)
            .correlate(*_LINE)
            .scalar_subquery()
        )

    whens: list[tuple[Any, Any]] = []
    for level, one in enumerate(_LINE):
        own = operators.live(one.operator_hid)
        whens.append(
            (own.is_not(None), one.hid if hid else literal("own" if level == 0 else "parent_item"))
        )
        grouped = _from_groups("operator_hid", level, operators.live)
        holder = _from_groups("operator_hid", level, operators.live, "holder_hid")
        whens.append((grouped.is_not(None), holder if hid else literal("device_group")))
    through = _from_hosts("operator_hid", operators.live)
    whens.append(
        (
            through.is_not(None),
            _from_hosts("operator_hid", operators.live, "holder_hid" if hid else "source"),
        )
    )
    whens.append(
        (
            of_place(places.c.operator_hid).is_not(None),
            of_place(places.c.holder_hid) if hid else of_place(places.c.holder_level),
        )
    )
    return case(*whens, else_=None if hid else literal("none"))


OPERATOR_SOURCE: ColumnElement[Any] = _operator_source(hid=False)
OPERATOR_SOURCE_HID: ColumnElement[Any] = _operator_source(hid=True)
ITEM_OPERATOR: Any = aliased(Operator, name="item_operator")
ITEM_OPERATOR_CONTACT: Any = aliased(Contact, name="item_operator_contact")


def is_user(contact_hid: Any) -> ColumnElement[bool]:
    """Say whether the contact a column names is a user's (P-172). A retired account is
    no user: its contact is nobody's, as `hirdir.domain.contacts.users_of` has it (P-296)."""
    return contact_hid.in_(
        select(User.contact_hid).where(
            User.contact_hid.is_not(None), User.record_status != "retired"
        )
    )


def is_operator(contact: Any) -> ColumnElement[bool]:
    """Say whether a contact stands behind an operator that is not retired: a contact that
    is retired stands behind none, as nobody is behind its labels (P-280)."""
    return and_(
        ~operators.nobody_behind(contact),
        contact.hid.in_(
            select(Operator.contact_hid).where(
                Operator.contact_hid.is_not(None), Operator.record_status != "retired"
            )
        ),
    )


def operator_scope(contact: Any) -> ColumnElement[Any]:
    """Return `internal` where the contact behind a label is a user's, `external` where
    it is not, and nothing where nobody is behind it: no contact, or one that is retired,
    as an open label has (P-172)."""
    return case(
        (operators.nobody_behind(contact), None),
        (is_user(contact.hid), operators.INTERNAL),
        else_=operators.EXTERNAL,
    )


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


def nested_groups() -> Any:
    """Return, as a table, each device group that is not retired paired with itself and
    with every group nested in it at any depth. A retired group counts for nothing, so
    what is nested in it is not reached through it, as nothing is passed down through it
    (`hirdir.domain.descent`), and as the controllers of a domain are
    not (`hirdir.domain.groups.controllers`)."""
    inner: Any = aliased(DeviceGroup, name="nested_group")
    start = (
        select(DeviceGroup.hid.label("top_hid"), DeviceGroup.hid.label("group_hid"))
        .where(DeviceGroup.record_status != "retired")
        .cte("report_nested_groups", recursive=True)
    )
    # Each pair once: what is nested is never within itself, and were it so, the walk
    # would still end.
    return start.union(
        select(start.c.top_hid, inner.hid)
        .select_from(start)
        .join(inner, inner.parent_group_hid == start.c.group_hid)
        .where(inner.record_status != "retired")
    )


def under_groups(nested: Any = None) -> Any:
    """Return, as a table, each device group that is not retired paired with every item
    under it, each pair once (P-178): its current members, the current members of every
    group nested in it at any depth, and the minor items of all of them. An item is so
    in the row of each group it is under, as an item with several tags is in the row of
    each."""
    nested = nested_groups() if nested is None else nested
    member: Any = aliased(DeviceGroupMember, name="under_member")
    minor: Any = aliased(Item, name="under_minor")
    start = (
        select(nested.c.top_hid.label("group_hid"), member.item_hid.label("item_hid"))
        .select_from(nested)
        .join(member, member.group_hid == nested.c.group_hid)
        .where(member.left_on.is_(None))
        .cte("report_under_groups", recursive=True)
    )
    return start.union(
        select(start.c.group_hid, minor.hid)
        .select_from(start)
        .join(minor, minor.parent_item_hid == start.c.item_hid)
    )


def _under_group() -> tuple[ColumnElement[Any], Callable[[Session, str], ColumnElement[bool]]]:
    """Return the field of the groups an item is under, as a row of a report by group
    holds it (P-178): an expression that is blank where it is under none, and the test that
    it is under the group a filter names, by its HID or its name."""
    under = UNDER_GROUPS
    some = select(func.min(under.c.group_hid)).where(under.c.item_hid == Item.hid).correlate(Item)

    def test(db: Session, text: str) -> ColumnElement[bool]:
        found = db.get(DeviceGroup, text.strip()) or groups.find_group(db, text)
        if found is None:
            raise refuse(f"there is no device group {text}")
        return Item.hid.in_(select(under.c.item_hid).where(under.c.group_hid == found.hid))

    return some.scalar_subquery(), test


# One of each, shared: a statement that names one twice names the same table (P-178).
NESTED_GROUPS: Any = nested_groups()
UNDER_GROUPS: Any = under_groups(NESTED_GROUPS)
_UNDER_GROUP = _under_group()
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


# The coverages of an item, each with its contract: what covers it today, and the last
# day its cover runs to, as `hirdir.domain.contracts` works them out.
_COVER: Any = aliased(ContractCoverage, name="item_coverage")
_COVERING: Any = aliased(Contract, name="item_contract")
_ITS_COVER = select(_COVER.hid).join(_COVERING, _COVERING.hid == _COVER.contract_hid)
_COVERS_TODAY = (_COVER.item_hid == Item.hid, contracts.coverage_in_force(_COVER, _COVERING))
_ITEM_CONTRACTS = _one_of(_ITS_COVER, *_COVERS_TODAY)
COVERED: ColumnElement[Any] = _ITS_COVER.where(*_COVERS_TODAY).correlate(Item).exists()
# How many contracts cover it today: more than one is worth a look before a renewal.
CONTRACT_COUNT: ColumnElement[Any] = (
    select(func.count(func.distinct(_COVERING.hid)))
    .select_from(_COVER)
    .join(_COVERING, _COVERING.hid == _COVER.contract_hid)
    .where(*_COVERS_TODAY)
    .correlate(Item)
    .scalar_subquery()
)
# The last day a coverage runs to: its own, or the end of the last term of its contract
# that is known. Under a contract whose renewal is pending no day is known to end it.
_LAST_STATUS = contracts.last_status_value(_COVERING)
_COVER_END = contracts.last_day_value(_COVER, _COVERING)
COVERED_UNTIL: ColumnElement[Any] = type_coerce(
    select(
        case((func.count(case((_COVER_END.is_(None), 1))) > 0, None), else_=func.max(_COVER_END))
    )
    .select_from(_COVER)
    .join(_COVERING, _COVERING.hid == _COVER.contract_hid)
    .where(
        _COVER.item_hid == Item.hid,
        _COVERING.record_status == "active",
        _LAST_STATUS.in_(contracts.COVERING),
        or_(_COVER_END.is_(None), dialect.today() <= _COVER_END),
    )
    .correlate(Item)
    .scalar_subquery(),
    Date,
)
# Out of service, and a contract still counts it: its cover goes on, or its coverage was
# ended because it left while the term of its contract still runs. A coverage that ends
# today asks for nothing more: the cover that goes on is what counts. An item that was
# brought back is in service again, whatever a coverage of it says.
# `hirdir.domain.contracts.still_counts` is the same test for a page of records.
# An item with no state is not out of service: the test is false, and never unknown,
# so that its negation finds the item too.
_ITEM_OUT = or_(
    Item.record_status == "retired",
    and_(STATE_IN_FORCE.is_not(None), STATE_IN_FORCE.in_(contracts.OUT_OF_SERVICE)),
)
_COUNTING = (
    _COVER.item_hid == Item.hid,
    or_(
        and_(
            contracts.coverage_in_force(_COVER, _COVERING),
            or_(_COVER_END.is_(None), dialect.today() < _COVER_END),
        ),
        contracts.left_while_running(_COVER, _COVERING),
    ),
)
OUT_OF_SERVICE_COVER: ColumnElement[Any] = and_(
    _ITEM_OUT, _ITS_COVER.where(*_COUNTING).correlate(Item).exists()
)


def _item_counting(condition: ColumnElement[bool]) -> ColumnElement[bool]:
    """Return the test that a contract that still counts an item out of service meets a
    condition."""
    return and_(_ITEM_OUT, _ITS_COVER.where(*_COUNTING, condition).exists())


# The first number among the contracts that still count it, for a column to be sorted by.
_FIRST_COUNTING = case(
    (
        _ITEM_OUT,
        select(func.min(dialect.folded(contracts.term_value(_COVERING, "number"))))
        .select_from(_COVER)
        .join(_COVERING, _COVERING.hid == _COVER.contract_hid)
        .where(*_COUNTING)
        .correlate(Item)
        .scalar_subquery(),
    ),
    else_=None,
)
# The line an item arrived on is of another model than the item's.
_ITS_LINE: Any = aliased(PurchaseLine, name="item_line")
PURCHASE_LINE_MISMATCH: ColumnElement[Any] = (
    select(_ITS_LINE.hid)
    .where(_ITS_LINE.hid == Item.purchase_line_hid, purchases.another_model(Item, _ITS_LINE))
    .correlate(Item)
    .exists()
)
# What a list leaves out unless asked, of items: drafts, retired ones and the archived.
_ITEM_IN_VIEW = (
    Item.record_status == "active",
    or_(STATE_IN_FORCE.is_(None), STATE_IN_FORCE != lifecycle.ARCHIVED),
)
# The stacks and the clusters an item is a current member of: each is one device, and
# what knows the group knows its members.
_ONE_DEVICE = (
    select(DeviceGroupMember.group_hid)
    .join(DeviceGroup, DeviceGroup.hid == DeviceGroupMember.group_hid)
    .where(
        DeviceGroupMember.item_hid == Item.hid,
        DeviceGroupMember.left_on.is_(None),
        DeviceGroup.record_status != "retired",
        DeviceGroup.type.in_(systems.ONE_DEVICE),
    )
    # It stands two statements deep, and is still of the item of the outermost.
    .correlate(Item)
)


def _registered(held: ColumnElement[bool], model: Any) -> dict[str, Field]:
    """Return the field that finds a record by an external system that knows it, a
    registration that is removed not counting, sorted by the first name."""
    its = (held, Registration.status != systems.REMOVED)
    first = (
        select(func.min(ExternalSystem.name_key))
        .select_from(Registration)
        .join(ExternalSystem, ExternalSystem.hid == Registration.system_hid)
        .where(*its)
        .correlate(model)
        .scalar_subquery()
    )
    return {
        "registration.system": Field(
            "text",
            ExternalSystem.name,
            among=_one_of(
                select(Registration.hid).join(
                    ExternalSystem, ExternalSystem.hid == Registration.system_hid
                ),
                *its,
            ),
            ordered_by=first,
        )
    }


# --- what an item runs on, and what is to be looked at (P-246, P-249) -------------------

_RUNS_ON: Any = aliased(Item, name="runs_on_item")
_RUNS_ON_GROUP: Any = aliased(DeviceGroup, name="runs_on_group")
_SEEN_ON: Any = aliased(Item, name="seen_on_item")
_GONE_HOST: Any = aliased(Item, name="gone_host")
_GONE_ABOVE: tuple[Any, ...] = tuple(
    aliased(Item, name=f"gone_host_above_{level}") for level in range(MAX_DEPTH)
)
_GONE_GROUP: Any = aliased(DeviceGroup, name="gone_group")
_HOSTED_BY: Any = aliased(Item, name="hosted_by")
_SEEN_MEMBER: Any = aliased(DeviceGroupMember, name="seen_member")


def _named_item(item: Any, column: Any) -> ColumnElement[Any]:
    """Return the name an item named by a column is shown by: its name, or else its
    hostname, its serial number or its asset tag."""
    return (
        select(func.coalesce(item.name, item.hostname, item.serial_number, item.asset_tag))
        .where(item.hid == column)
        .correlate(Item)
        .scalar_subquery()
    )


# The name of what an item runs on: the item, or the stack or the cluster.
HOST_NAME: ColumnElement[Any] = func.coalesce(
    _named_item(_RUNS_ON, Item.host_item_hid),
    select(_RUNS_ON_GROUP.name)
    .where(_RUNS_ON_GROUP.hid == Item.host_group_hid)
    .correlate(Item)
    .scalar_subquery(),
)
# The item it was seen on is neither the host named nor a current member of the stack or
# the cluster named: no fault, and unknown where either is not known.
HOST_DIFFERS: ColumnElement[Any] = case(
    (Item.observed_host_hid.is_(None), None),
    (Item.host_item_hid.is_not(None), Item.observed_host_hid != Item.host_item_hid),
    (
        Item.host_group_hid.is_not(None),
        ~select(_SEEN_MEMBER.hid)
        .where(
            _SEEN_MEMBER.group_hid == Item.host_group_hid,
            _SEEN_MEMBER.item_hid == Item.observed_host_hid,
            _SEEN_MEMBER.left_on.is_(None),
        )
        .correlate(Item)
        .exists(),
    ),
    else_=None,
)
# How many items that are not retired name it as their host.
HOSTED_COUNT: ColumnElement[Any] = (
    select(func.count())
    .select_from(_HOSTED_BY)
    .where(_HOSTED_BY.host_item_hid == Item.hid, _HOSTED_BY.record_status != "retired")
    .correlate(Item)
    .scalar_subquery()
)


def _review_reasons() -> dict[str, ColumnElement[bool]]:
    """Return, for each reason an item is to be looked at, the test that it has it, as
    `hirdir.domain.hosting.reviews` works them out. A retired item has none."""
    live = Item.record_status != "retired"
    gone_line: Any = select(_GONE_HOST.hid).select_from(_GONE_HOST)
    below = _GONE_HOST
    for upper in _GONE_ABOVE:
        gone_line = gone_line.outerjoin(upper, upper.hid == below.parent_item_hid)
        below = upper
    # The state in force of the host: its own, or that of the nearest item above it.
    state = func.coalesce(*(one.lifecycle_state for one in (_GONE_HOST, *_GONE_ABOVE)))
    host_gone = or_(
        gone_line.where(
            _GONE_HOST.hid == Item.host_item_hid,
            or_(_GONE_HOST.record_status == "retired", state.in_(hosting.OUT_OF_HANDS)),
        )
        .correlate(Item)
        .exists(),
        select(_GONE_GROUP.hid)
        .where(_GONE_GROUP.hid == Item.host_group_hid, _GONE_GROUP.record_status == "retired")
        .correlate(Item)
        .exists(),
    )
    no_host = and_(
        CatalogEntry.kind.in_(hosting.HOSTED_KINDS),
        Item.host_item_hid.is_(None),
        Item.host_group_hid.is_(None),
    )
    not_reported = (
        select(Registration.hid)
        .where(
            Registration.item_hid == Item.hid,
            Registration.status == hosting.NOT_REPORTED_STATUS,
        )
        .correlate(Item)
        .exists()
    )
    return {
        hosting.NO_HOST: and_(live, no_host),
        hosting.HOST_GONE: and_(live, host_gone),
        hosting.NOT_REPORTED: and_(live, not_reported),
    }


REVIEW_REASONS: Mapping[str, ColumnElement[bool]] = _review_reasons()
# The reasons, as a table of three rows, which a filter of `review` tests one by one.
_REASONS: Any = union_all(
    *(select(literal(reason).label("reason")) for reason in hosting.REASONS)
).subquery("review_reason")


def _among_reasons(condition: ColumnElement[bool]) -> ColumnElement[bool]:
    """Return the test that one of the reasons an item has meets a condition."""
    has = or_(*(and_(_REASONS.c.reason == reason, test) for reason, test in REVIEW_REASONS.items()))
    return select(_REASONS.c.reason).where(condition, has).exists()


# Sorted by its first reason, in the order the record lists them.
_FIRST_REASON: ColumnElement[Any] = case(
    *((test, literal(reason)) for reason, test in REVIEW_REASONS.items()), else_=None
)


def _hosting_fields() -> dict[str, Field]:
    """Return the fields of the item list of what an item runs on (P-246) and of what it
    is to be looked at for (P-249)."""
    return {
        **_columns(Item, "reference", "host_item_hid", "host_group_hid", "observed_host_hid"),
        "host_observed_at": Field("timestamp", Item.host_observed_at),
        "host.name": Field("text", HOST_NAME),
        "observed_host.name": Field("text", _named_item(_SEEN_ON, Item.observed_host_hid)),
        "host_differs": Field("boolean", HOST_DIFFERS),
        "hosted_count": Field("integer", HOSTED_COUNT),
        "review": Field(
            "choice", _REASONS.c.reason, among=_among_reasons, ordered_by=_FIRST_REASON
        ),
    }


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
        # Its own word on renewing its support: blank has its model's.
        not_renewed.FIELD: Field("boolean", Item.do_not_renew),
        **{f"effective.{name}": _effective(name) for name in inheritance.ITEM_FIELDS},
        "effective.owner_hid": Field("reference", OWNER_IN_FORCE),
        "effective.location_hid": Field("reference", LOCATION_IN_FORCE),
        "operator_hid": Field("reference", Item.operator_hid),
        # The operator in force: who looks after the item, by its own word or from above.
        "effective.operator_hid": Field("reference", OPERATOR_IN_FORCE),
        # How it has it, and from which record (P-177).
        "effective.operator_hid.source": Field("choice", OPERATOR_SOURCE),
        "effective.operator_hid.source_hid": Field("reference", OPERATOR_SOURCE_HID),
        "operator.label": Field("text", ITEM_OPERATOR.label),
        "operator.contact": Field("text", ITEM_OPERATOR_CONTACT.name),
        # Internal where the person behind the operator in force is a user, external not.
        "operator.scope": Field("choice", operator_scope(ITEM_OPERATOR_CONTACT)),
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
        "catalog.vendor_hid": Field("reference", CatalogEntry.vendor_hid),
        "catalog.kind": Field("choice", CatalogEntry.kind),
        "catalog.type": Field("choice", CatalogEntry.type),
        "catalog.function": Field("choice", CatalogEntry.function),
        # The owner in force: a minor item has the owner of the item it is in.
        "owner.label": Field("text", Owner.label),
        "tags": _tags("item", Item),
        # The groups it is under, at any depth of nesting and from the item it is in: what a
        # row of a report by group holds (P-178). `group:within:<group>` and `group:empty`.
        "group": Field(
            "place",
            _UNDER_GROUP[0],
            within=_UNDER_GROUP[1],
            within_takes="the HID or the name of a device group",
        ),
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
        # The line of a purchase request it arrived on.
        "purchase_line_hid": Field("reference", Item.purchase_line_hid),
        # Under a contract today, and the last day its cover runs to.
        "covered": Field("boolean", COVERED),
        "covered_until": Field("date", COVERED_UNTIL),
        "contract_count": Field("integer", CONTRACT_COUNT),
        "out_of_service_cover": Field("boolean", OUT_OF_SERVICE_COVER),
        "out_of_service_contract.hid": Field("reference", _COVERING.hid, among=_item_counting),
        "out_of_service_contract.number": Field(
            "text",
            contracts.term_value(_COVERING, "number"),
            among=_item_counting,
            ordered_by=_FIRST_COUNTING,
        ),
        # On a line of another model, which 0.6.0 let in: to be put right.
        "purchase_line_mismatch": Field("boolean", PURCHASE_LINE_MISMATCH),
        "contract.hid": Field("reference", _COVERING.hid, among=_ITEM_CONTRACTS),
        "contract.status": Field(
            "choice",
            contracts.status_value(_COVERING),
            among=_ITEM_CONTRACTS,
            ordered_by=select(func.min(contracts.status_value(_COVERING)))
            .select_from(_COVER)
            .join(_COVERING, _COVERING.hid == _COVER.contract_hid)
            .where(*_COVERS_TODAY)
            .correlate(Item)
            .scalar_subquery(),
        ),
        "contract.number": Field(
            "text",
            contracts.term_value(_COVERING, "number"),
            among=_ITEM_CONTRACTS,
            ordered_by=select(func.min(dialect.folded(contracts.term_value(_COVERING, "number"))))
            .select_from(_COVER)
            .join(_COVERING, _COVERING.hid == _COVER.contract_hid)
            .where(*_COVERS_TODAY)
            .correlate(Item)
            .scalar_subquery(),
        ),
        **_registered(
            or_(Registration.item_hid == Item.hid, Registration.group_hid.in_(_ONE_DEVICE)), Item
        ),
        **_hosting_fields(),
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
        **_registered(Registration.group_hid == DeviceGroup.hid, DeviceGroup),
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
        # Sorted as an address and not as text: 192.0.2.9 before 192.0.2.10.
        "address": Field(
            "address",
            Address.address,
            convert=comparable,
            ordered_by=dialect.as_address(Address.address),
        ),
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

# How many items are of a model, counted as the item list counts them (D-152, P-180):
# major and minor, and drafts, retired items and items in Archived left out, so the
# number leads to as many rows of the grid.
MODEL_ITEMS: ColumnElement[Any] = (
    _with_items_above(select(func.count(func.distinct(Item.hid))).select_from(Item))
    .where(Item.catalog_entry_hid == CatalogEntry.hid, *_ITEM_IN_VIEW)
    .correlate(CatalogEntry)
    .scalar_subquery()
)


def model_items(db: Session, entry_hids: list[str]) -> dict[str, int]:
    """Return how many items are of each catalog entry."""
    counts = dict.fromkeys(entry_hids, 0)
    if entry_hids:
        found = db.execute(
            select(CatalogEntry.hid, MODEL_ITEMS).where(CatalogEntry.hid.in_(entry_hids))
        )
        counts.update({hid: count or 0 for hid, count in found})
    return counts


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
        not_renewed.FIELD: Field("boolean", CatalogEntry.do_not_renew),
        "tags": _tags("catalog_entry", CatalogEntry),
        # How many items are of it: sorted by, and not filtered by.
        "items": Field("integer", ordered_by=MODEL_ITEMS),
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
        # Its own support weight, which is the one it counts at (P-155).
        "support_weight": Field("number", Region.support_weight),
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
        # Its own support weight, and the one in force: the default, raised (P-155).
        "support_weight": Field("number", Site.support_weight),
        "effective.support_weight": Field("number", weights.site_weight_column()),
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
        # Its own support weight, which is the one it counts at (P-155).
        "support_weight": Field("number", Location.support_weight),
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
        **_columns(Contact, "text", "name", "organization", "email", "phone", "phone2", "notes"),
        "record_status": Field("choice", Contact.record_status),
        # The contact is a user's (P-172).
        "is_user": Field("boolean", is_user(Contact.hid)),
        # The contact stands behind an operator that is not retired (P-280).
        "is_operator": Field("boolean", is_operator(Contact)),
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
        "contact.phone": Field("text", _OPERATOR_CONTACT.phone),
        "contact.phone2": Field("text", _OPERATOR_CONTACT.phone2),
        "scope": Field("choice", operator_scope(_OPERATOR_CONTACT)),
        "is_open": Field("boolean", operators.nobody_behind(_OPERATOR_CONTACT)),
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

# --- contracts and coverage ----------------------------------------------------------

_COVERED_ITEM: Any = aliased(Item, name="covered_item")
_COVERED_ENTRY: Any = aliased(CatalogEntry, name="covered_entry")
_OF_CONTRACT: Any = aliased(ContractCoverage, name="coverage_of_contract")
_RESELLER: Any = aliased(Vendor, name="reseller")

_CONTRACT_OF_AGREEMENT: Any = aliased(Contract, name="contract_of_agreement")
# How many items a contract covers today, of those a list shows unless asked otherwise:
# the number of rows of the item list for that contract.
COVERED_ITEMS: ColumnElement[Any] = (
    _with_items_above(
        select(func.count(func.distinct(Item.hid)))
        .select_from(_OF_CONTRACT)
        .join(Item, Item.hid == _OF_CONTRACT.item_hid)
    )
    .where(
        _OF_CONTRACT.contract_hid == Contract.hid,
        contracts.coverage_in_force(_OF_CONTRACT, Contract),
        *_ITEM_IN_VIEW,
    )
    .correlate(Contract)
    .scalar_subquery()
)


def covered_items(db: Session, contract_hids: list[str]) -> dict[str, int]:
    """Return how many items each contract covers today."""
    counts = dict.fromkeys(contract_hids, 0)
    if contract_hids:
        found = db.execute(
            select(Contract.hid, COVERED_ITEMS).where(Contract.hid.in_(contract_hids))
        )
        counts.update({hid: count or 0 for hid, count in found})
    return counts


def _term_fields(model: Any) -> dict[str, Field]:
    """Return the fields of the term of an agreement or a contract, as it is in force
    today: the next term, from the day it begins."""
    return {
        "number": Field("text", contracts.term_value(model, "number")),
        "purchase_reference": Field("text", contracts.term_value(model, "purchase_reference")),
        "starts_on": Field("date", type_coerce(contracts.term_value(model, "starts_on"), Date)),
        "ends_on": Field("date", type_coerce(contracts.term_value(model, "ends_on"), Date)),
        "annual_cost": Field(
            "number",
            type_coerce(contracts.term_value(model, "annual_cost"), model.annual_cost.type),
        ),
        "status": Field("choice", contracts.status_value(model)),
        "record_status": Field("choice", model.record_status),
        "row_version": Field("integer", contracts.version_value(model)),
        # The term that is still to begin: blank where no renewal waits.
        "next_starts_on": Field("date", contracts.next_on_value(model)),
        "next_number": Field("text", model.next_number),
    }


AGREEMENTS = Listing(
    model=Agreement,
    fields={
        **_bookkeeping(Agreement),
        "vendor_hid": Field("reference", Agreement.vendor_hid),
        "vendor": Field("text", Vendor.name),
        "reseller_hid": Field("reference", Agreement.reseller_hid),
        "reseller": Field("text", _RESELLER.name),
        **_columns(Agreement, "text", "name", "support_level", "account_manager"),
        **_columns(Agreement, "text", "support_contact", "notes", "support_url"),
        **_term_fields(Agreement),
        "lapsed": Field(
            "boolean", contracts.lapsed_test(Agreement, contracts.term_value(Agreement, "ends_on"))
        ),
        "tags": _tags("agreement", Agreement),
        # How many contracts that are not retired it groups, as its record counts them.
        "contracts": Field(
            "integer",
            ordered_by=select(func.count())
            .where(
                _CONTRACT_OF_AGREEMENT.agreement_hid == Agreement.hid,
                _CONTRACT_OF_AGREEMENT.record_status != "retired",
            )
            .correlate(Agreement)
            .scalar_subquery(),
        ),
    },
    joined=lambda query: query.join(Vendor, Vendor.hid == Agreement.vendor_hid).outerjoin(
        _RESELLER, _RESELLER.hid == Agreement.reseller_hid
    ),
    default_sort=("name",),
)

_ITS_AGREEMENT: Any = aliased(Agreement, name="its_agreement")

CONTRACTS = Listing(
    model=Contract,
    fields={
        **_bookkeeping(Contract),
        "vendor_hid": Field("reference", Contract.vendor_hid),
        "vendor": Field("text", Vendor.name),
        # The agreement it is grouped into: blank for a contract that stands by itself.
        "agreement_hid": Field("reference", Contract.agreement_hid),
        "agreement.name": Field("text", _ITS_AGREEMENT.name),
        "reseller_hid": Field("reference", Contract.reseller_hid),
        "reseller": Field("text", _RESELLER.name),
        **_columns(Contract, "text", "support_level", "account_manager"),
        **_columns(Contract, "text", "support_contact", "notes", "support_url"),
        **_term_fields(Contract),
        "lapsed": Field(
            "boolean", contracts.lapsed_test(Contract, contracts.in_force_of(Contract, "ends_on"))
        ),
        # What is in force: the contract's own, or its agreement's where that is blank.
        **{
            f"effective.{name}": Field(
                "date"
                if name.endswith("_on")
                else "reference"
                if name.endswith("_hid")
                else "text",
                contracts.in_force_of(Contract, name),
            )
            for name in contracts.INHERITED
        },
        # It covers today: active in both senses, and in date.
        "covers_today": Field("boolean", contracts.contract_covers()),
        # Not to be renewed: it ends with its present term (D-180).
        "ends_with_term": Field("boolean", Contract.ends_with_term),
        # A renewal that is pending: for how long, and whether for too long (D-178).
        "renewal_pending_days": Field("integer", contracts.renewal_pending_days_value()),
        "renewal_overdue": Field("boolean", contracts.renewal_overdue_value()),
        # A renewal is entered that is still to begin: its own, or its agreement's.
        "renewal_waiting": Field("boolean", contracts.renewal_waiting_value()),
        # A member of an agreement that was renewed that still says it is pending or has
        # expired: a person looks at it (D-180).
        "to_review": Field("boolean", contracts.to_review_value()),
        "tags": _tags("contract", Contract),
        # A contract is found by an item it covers, at any time.
        "coverage.item_hid": Field(
            "reference",
            _OF_CONTRACT.item_hid,
            among=_one_of(select(_OF_CONTRACT.hid), _OF_CONTRACT.contract_hid == Contract.hid),
        ),
        # How many items it covers today, as its record counts them.
        "covered_items": Field("integer", ordered_by=COVERED_ITEMS),
    },
    joined=lambda query: (
        query.join(Vendor, Vendor.hid == Contract.vendor_hid)
        .outerjoin(_RESELLER, _RESELLER.hid == Contract.reseller_hid)
        .outerjoin(_ITS_AGREEMENT, _ITS_AGREEMENT.hid == Contract.agreement_hid)
    ),
    default_sort=("number", "vendor"),
)

COVERAGE = Listing(
    model=ContractCoverage,
    fields={
        **_bookkeeping(ContractCoverage),
        **_columns(ContractCoverage, "reference", "contract_hid", "item_hid"),
        **_columns(ContractCoverage, "date", "starts_on", "ends_on"),
        # The days in force: its own or the contract's, and within the contract's.
        "effective.starts_on": Field("date", type_coerce(contracts.starts(), Date)),
        "effective.ends_on": Field("date", type_coerce(contracts.ends(), Date)),
        "in_force": Field("boolean", contracts.coverage_in_force()),
        "contract.number": Field("text", contracts.term_value(Contract, "number")),
        "contract.status": Field("choice", contracts.status_value(Contract)),
        "left_service": Field("boolean", ContractCoverage.left_service),
        "vendor": Field("text", Vendor.name),
        "item.name": Field("text", func.coalesce(_COVERED_ITEM.name, _COVERED_ITEM.hostname)),
        "item.serial_number": Field("text", _COVERED_ITEM.serial_number),
        "item.asset_tag": Field("text", _COVERED_ITEM.asset_tag),
        "item.pid": Field("text", _COVERED_ENTRY.pid),
        "item.lifecycle_state": Field("choice", _COVERED_ITEM.lifecycle_state),
        "item.record_status": Field("choice", _COVERED_ITEM.record_status),
    },
    joined=lambda query: (
        query.join(Contract, Contract.hid == ContractCoverage.contract_hid)
        .join(Vendor, Vendor.hid == Contract.vendor_hid)
        .join(_COVERED_ITEM, _COVERED_ITEM.hid == ContractCoverage.item_hid)
        .outerjoin(_COVERED_ENTRY, _COVERED_ENTRY.hid == _COVERED_ITEM.catalog_entry_hid)
    ),
    default_sort=("contract.number", "item.name", "starts_on"),
    has_status=False,
)

# --- the contacts of agreements and contracts ----------------------------------------

_NAMED_CONTACT: Any = aliased(Contact, name="named_contact")
_NAMING_AGREEMENT: Any = aliased(Agreement, name="naming_agreement")
_NAMING_CONTRACT: Any = aliased(Contract, name="naming_contract")

CONTRACT_CONTACTS = Listing(
    model=ContractContact,
    fields={
        **_bookkeeping(ContractContact),
        **_columns(ContractContact, "reference", "agreement_hid", "contract_hid", "contact_hid"),
        "role": Field("choice", ContractContact.role),
        "priority": Field("integer", ContractContact.priority),
        "agreement.name": Field("text", _NAMING_AGREEMENT.name),
        "contract.number": Field("text", _NAMING_CONTRACT.number),
        "contact.name": Field("text", _NAMED_CONTACT.name),
        "contact.email": Field("text", _NAMED_CONTACT.email),
    },
    joined=lambda query: (
        query.join(_NAMED_CONTACT, _NAMED_CONTACT.hid == ContractContact.contact_hid)
        .outerjoin(_NAMING_AGREEMENT, _NAMING_AGREEMENT.hid == ContractContact.agreement_hid)
        .outerjoin(_NAMING_CONTRACT, _NAMING_CONTRACT.hid == ContractContact.contract_hid)
    ),
    default_sort=("agreement.name", "contract.number", "role", "priority", "contact.name"),
    has_status=False,
)

# --- the contacts of carriers and of circuits (P-149) --------------------------------

_CARRIER_CONTACT: Any = aliased(Contact, name="carrier_contact")
_NAMING_VENDOR: Any = aliased(Vendor, name="naming_vendor")

VENDOR_CONTACTS = Listing(
    model=VendorContact,
    fields={
        **_bookkeeping(VendorContact),
        **_columns(VendorContact, "reference", "vendor_hid", "contact_hid"),
        "role": Field("choice", VendorContact.role),
        "priority": Field("integer", VendorContact.priority),
        "vendor.name": Field("text", _NAMING_VENDOR.name),
        "contact.name": Field("text", _CARRIER_CONTACT.name),
        "contact.email": Field("text", _CARRIER_CONTACT.email),
    },
    joined=lambda query: query.join(
        _NAMING_VENDOR, _NAMING_VENDOR.hid == VendorContact.vendor_hid
    ).join(_CARRIER_CONTACT, _CARRIER_CONTACT.hid == VendorContact.contact_hid),
    default_sort=("vendor.name", "role", "priority", "contact.name"),
    has_status=False,
)

_SITE_CONTACT: Any = aliased(Contact, name="site_contact")
_NAMING_CIRCUIT: Any = aliased(Circuit, name="naming_circuit")

CIRCUIT_CONTACTS = Listing(
    model=CircuitContact,
    fields={
        **_bookkeeping(CircuitContact),
        **_columns(CircuitContact, "reference", "circuit_hid", "contact_hid"),
        # Blank for one of the carrier's, `a` or `z` for a site contact of that side.
        "side": Field("choice", CircuitContact.side),
        "role": Field("choice", CircuitContact.role),
        "priority": Field("integer", CircuitContact.priority),
        "circuit.name": Field("text", _NAMING_CIRCUIT.name),
        "circuit.enterprise_circuit_id": Field("text", _NAMING_CIRCUIT.enterprise_circuit_id),
        "contact.name": Field("text", _SITE_CONTACT.name),
        "contact.email": Field("text", _SITE_CONTACT.email),
    },
    joined=lambda query: query.join(
        _NAMING_CIRCUIT, _NAMING_CIRCUIT.hid == CircuitContact.circuit_hid
    ).join(_SITE_CONTACT, _SITE_CONTACT.hid == CircuitContact.contact_hid),
    default_sort=("circuit.name", "side", "role", "priority", "contact.name"),
    has_status=False,
)

# --- purchases -----------------------------------------------------------------------

_ARRIVED: Any = aliased(Item, name="arrived_item")
_LINE_OF_REQUEST: Any = aliased(PurchaseLine, name="line_of_request")
_LINE_ENTRY: Any = aliased(CatalogEntry, name="line_entry")
_LINE_VENDOR: Any = aliased(Vendor, name="line_vendor")
_LINE_SITE: Any = aliased(Site, name="line_site")
# What has arrived on a line: the items that name it.
RECEIVED: ColumnElement[Any] = (
    select(func.count())
    .where(_ARRIVED.purchase_line_hid == PurchaseLine.hid)
    .correlate(PurchaseLine)
    .scalar_subquery()
)
# What arrived on a line and is of another model than the line's, which 0.6.0 let in,
# counted as the item list counts (D-152): drafts, retired items and items in Archived
# are left out, so the number leads to as many rows of the grid.
MISMATCHED: ColumnElement[Any] = (
    _with_items_above(select(func.count(func.distinct(Item.hid))).select_from(Item))
    .where(
        Item.purchase_line_hid == PurchaseLine.hid,
        purchases.another_model(Item, PurchaseLine),
        *_ITEM_IN_VIEW,
    )
    .correlate(PurchaseLine)
    .scalar_subquery()
)


def mismatched_items(db: Session, line_hids: list[str]) -> dict[str, int]:
    """Return how many items of another model than its own each purchase line has, as
    the item list counts them."""
    counts = dict.fromkeys(line_hids, 0)
    if line_hids:
        found = db.execute(
            select(PurchaseLine.hid, MISMATCHED).where(PurchaseLine.hid.in_(line_hids))
        )
        counts.update({hid: count or 0 for hid, count in found})
    return counts


# What is ordered of a request: the quantities of the lines that are tracked. A line that
# is not tracked is not waited for (D-172).
_REQUEST_ORDERED = (
    select(func.coalesce(func.sum(_LINE_OF_REQUEST.quantity), 0))
    .where(
        _LINE_OF_REQUEST.request_hid == PurchaseRequest.hid,
        _LINE_OF_REQUEST.catalog_entry_hid.is_not(None),
    )
    .correlate(PurchaseRequest)
    .scalar_subquery()
)
_REQUEST_ARRIVED = (
    select(func.count())
    .select_from(_ARRIVED)
    .join(_LINE_OF_REQUEST, _LINE_OF_REQUEST.hid == _ARRIVED.purchase_line_hid)
    .where(_LINE_OF_REQUEST.request_hid == PurchaseRequest.hid)
    .correlate(PurchaseRequest)
    .scalar_subquery()
)

PURCHASE_REQUESTS = Listing(
    model=PurchaseRequest,
    fields={
        **_bookkeeping(PurchaseRequest),
        **_columns(PurchaseRequest, "text", "reference", "notes"),
        "requested_on": Field("date", PurchaseRequest.requested_on),
        "status": Field("choice", PurchaseRequest.status),
        "line_count": Field(
            "integer",
            ordered_by=select(func.count())
            .where(_LINE_OF_REQUEST.request_hid == PurchaseRequest.hid)
            .correlate(PurchaseRequest)
            .scalar_subquery(),
        ),
        # How many items are still to come, on all of its lines.
        "pending_quantity": Field("integer", (_REQUEST_ORDERED - _REQUEST_ARRIVED).cast(Integer)),
    },
    joined=lambda query: query,
    default_sort=("reference",),
    has_status=False,
)

PURCHASE_LINES = Listing(
    model=PurchaseLine,
    fields={
        **_bookkeeping(PurchaseLine),
        **_columns(
            PurchaseLine, "reference", "request_hid", "catalog_entry_hid", "destination_site_hid"
        ),
        **_columns(PurchaseLine, "integer", "line", "quantity"),
        "expected_on": Field("date", PurchaseLine.expected_on),
        "notes": Field("text", PurchaseLine.notes),
        # As procurement gave them, and whether the line has a model (D-172).
        **_columns(PurchaseLine, "text", "part_number", "description"),
        "tracked": Field("boolean", PurchaseLine.catalog_entry_hid.is_not(None)),
        "request.reference": Field("text", PurchaseRequest.reference),
        "request.status": Field("choice", PurchaseRequest.status),
        "catalog.pid": Field("text", _LINE_ENTRY.pid),
        "catalog.model_name": Field("text", _LINE_ENTRY.model_name),
        "catalog.vendor": Field("text", _LINE_VENDOR.name),
        "site": Field("text", _LINE_SITE.name),
        "received_quantity": Field("integer", RECEIVED.cast(Integer)),
        # Nothing is still to come on a line that is not tracked: it is not waited for.
        "pending_quantity": Field(
            "integer",
            case(
                (PurchaseLine.catalog_entry_hid.is_(None), 0),
                else_=(PurchaseLine.quantity - RECEIVED),
            ).cast(Integer),
        ),
        "mismatched_items": Field("integer", MISMATCHED.cast(Integer)),
    },
    joined=lambda query: (
        query.join(PurchaseRequest, PurchaseRequest.hid == PurchaseLine.request_hid)
        .outerjoin(_LINE_ENTRY, _LINE_ENTRY.hid == PurchaseLine.catalog_entry_hid)
        .outerjoin(_LINE_VENDOR, _LINE_VENDOR.hid == _LINE_ENTRY.vendor_hid)
        .outerjoin(_LINE_SITE, _LINE_SITE.hid == PurchaseLine.destination_site_hid)
    ),
    default_sort=("request.reference", "line"),
    has_status=False,
)

# --- external systems ----------------------------------------------------------------

_REGISTERED_ITEM: Any = aliased(Item, name="registered_item")
_REGISTERED_GROUP: Any = aliased(DeviceGroup, name="registered_group")
_OF_SYSTEM: Any = aliased(Registration, name="registration_of_system")
# How many records are registered with a system: the items and the groups that a list
# shows unless asked otherwise, a registration that is removed not counting.
REGISTERED: ColumnElement[Any] = (
    _with_items_above(
        select(func.count()).select_from(_OF_SYSTEM).join(Item, Item.hid == _OF_SYSTEM.item_hid)
    )
    .where(
        _OF_SYSTEM.system_hid == ExternalSystem.hid,
        _OF_SYSTEM.status != systems.REMOVED,
        *_ITEM_IN_VIEW,
    )
    .correlate(ExternalSystem)
    .scalar_subquery()
) + (
    select(func.count())
    .select_from(_OF_SYSTEM)
    .join(_REGISTERED_GROUP, _REGISTERED_GROUP.hid == _OF_SYSTEM.group_hid)
    .where(
        _OF_SYSTEM.system_hid == ExternalSystem.hid,
        _OF_SYSTEM.status != systems.REMOVED,
        _REGISTERED_GROUP.record_status == "active",
    )
    .correlate(ExternalSystem)
    .scalar_subquery()
)


def registered(db: Session, system_hids: list[str]) -> dict[str, int]:
    """Return how many records are registered with each external system."""
    counts = dict.fromkeys(system_hids, 0)
    if system_hids:
        found = db.execute(
            select(ExternalSystem.hid, REGISTERED).where(ExternalSystem.hid.in_(system_hids))
        )
        counts.update({hid: count or 0 for hid, count in found})
    return counts


EXTERNAL_SYSTEMS = Listing(
    model=ExternalSystem,
    fields={
        **_bookkeeping(ExternalSystem),
        **_columns(ExternalSystem, "text", "name", "url", "notes"),
        **_columns(ExternalSystem, "choice", "kind", "record_status"),
        # How many records are registered with it, those removed not counted.
        "registrations": Field("integer", ordered_by=REGISTERED),
    },
    joined=lambda query: query,
    default_sort=("name",),
)

REGISTRATIONS = Listing(
    model=Registration,
    fields={
        **_bookkeeping(Registration),
        **_columns(Registration, "reference", "system_hid", "item_hid", "group_hid"),
        "external_id": Field("text", Registration.external_id),
        "status": Field("choice", Registration.status),
        "confirmed_at": Field("timestamp", Registration.confirmed_at),
        "system.name": Field("text", ExternalSystem.name),
        "system.kind": Field("choice", ExternalSystem.kind),
        "item.name": Field("text", func.coalesce(_REGISTERED_ITEM.name, _REGISTERED_ITEM.hostname)),
        "item.serial_number": Field("text", _REGISTERED_ITEM.serial_number),
        "group.name": Field("text", _REGISTERED_GROUP.name),
        # What is registered, an item or a group, by the name it is shown by.
        "holder": Field(
            "text",
            func.coalesce(
                _REGISTERED_GROUP.name,
                _REGISTERED_ITEM.name,
                _REGISTERED_ITEM.hostname,
                _REGISTERED_ITEM.serial_number,
                _REGISTERED_ITEM.asset_tag,
            ),
        ),
    },
    joined=lambda query: (
        query.join(ExternalSystem, ExternalSystem.hid == Registration.system_hid)
        .outerjoin(_REGISTERED_ITEM, _REGISTERED_ITEM.hid == Registration.item_hid)
        .outerjoin(_REGISTERED_GROUP, _REGISTERED_GROUP.hid == Registration.group_hid)
    ),
    default_sort=("system.name", "holder"),
    has_status=False,
)

# --- capacity ------------------------------------------------------------------------

_LINE_REGION: Any = aliased(Region, name="capacity_region")
_CAPACITY_SITE: Any = aliased(Site, name="capacity_site")
_CAPACITY_VENDOR: Any = aliased(Vendor, name="capacity_vendor")
# The units of a line: its quantity times the units of one. Each is kept in
# hundredths, so the product is in ten-thousandths. A line that multiplies has neither,
# and none: its units are those of the lines it applies to, in each view of the report.
UNITS: ColumnElement[Any] = type_coerce(
    type_coerce(CapacityLine.quantity, BigInteger)
    * type_coerce(CapacityLine.units_each, BigInteger),
    Scaled(4),
)

# The staff lines a line that multiplies works on (D-188), found by one of their names
# and sorted by the first of them.
_TARGET: Any = aliased(CapacityLine, name="target_line")
_ITS_TARGETS = (CapacityLineTarget.line_hid == CapacityLine.hid,)
_LINE_TARGETS = _one_of(
    select(CapacityLineTarget.line_hid).join(_TARGET, _TARGET.hid == CapacityLineTarget.target_hid),
    *_ITS_TARGETS,
)
_FIRST_TARGET = (
    select(func.min(_TARGET.name_key))
    .select_from(CapacityLineTarget)
    .join(_TARGET, _TARGET.hid == CapacityLineTarget.target_hid)
    .where(*_ITS_TARGETS)
    .correlate(CapacityLine)
    .scalar_subquery()
)

CAPACITY_LINES = Listing(
    model=CapacityLine,
    fields={
        **_bookkeeping(CapacityLine),
        **_columns(CapacityLine, "choice", "side", "category", "effect", "record_status"),
        **_columns(CapacityLine, "text", "name", "notes"),
        **_columns(
            CapacityLine, "number", "quantity", "units_each", "factor", "share", "annual_cost"
        ),
        "units": Field("number", UNITS),
        "applies_to": Field("text", _TARGET.name, among=_LINE_TARGETS, ordered_by=_FIRST_TARGET),
        **_columns(CapacityLine, "reference", "vendor_hid", "region_hid", "site_hid"),
        "vendor": Field("text", _CAPACITY_VENDOR.name),
        "region": Field("text", _LINE_REGION.name),
        "site": Field("text", _CAPACITY_SITE.name),
        **_columns(CapacityLine, "date", "starts_on", "ends_on"),
        # It counts today: not before it starts, and not after it ends.
        "in_date": Field(
            "boolean",
            and_(
                or_(CapacityLine.starts_on.is_(None), CapacityLine.starts_on <= dialect.today()),
                or_(CapacityLine.ends_on.is_(None), CapacityLine.ends_on >= dialect.today()),
            ),
        ),
    },
    joined=lambda query: (
        query.outerjoin(_CAPACITY_VENDOR, _CAPACITY_VENDOR.hid == CapacityLine.vendor_hid)
        .outerjoin(_LINE_REGION, _LINE_REGION.hid == CapacityLine.region_hid)
        .outerjoin(_CAPACITY_SITE, _CAPACITY_SITE.hid == CapacityLine.site_hid)
    ),
    default_sort=("side", "category", "name"),
)

# --- replacements --------------------------------------------------------------------

_OLD_ITEM: Any = aliased(Item, name="old_item")
_NEW_ITEM: Any = aliased(Item, name="new_item")

REPLACEMENTS = Listing(
    model=ItemReplacement,
    fields={
        **_bookkeeping(ItemReplacement),
        **_columns(ItemReplacement, "reference", "old_item_hid", "new_item_hid"),
        "reason": Field("choice", ItemReplacement.reason),
        "reference": Field("text", ItemReplacement.reference),
        "replaced_on": Field("date", ItemReplacement.replaced_on),
        "old.name": Field("text", func.coalesce(_OLD_ITEM.name, _OLD_ITEM.hostname)),
        "old.serial_number": Field("text", _OLD_ITEM.serial_number),
        "new.name": Field("text", func.coalesce(_NEW_ITEM.name, _NEW_ITEM.hostname)),
        "new.serial_number": Field("text", _NEW_ITEM.serial_number),
    },
    joined=lambda query: query.join(_OLD_ITEM, _OLD_ITEM.hid == ItemReplacement.old_item_hid).join(
        _NEW_ITEM, _NEW_ITEM.hid == ItemReplacement.new_item_hid
    ),
    default_sort=("-replaced_on", "old.name"),
    has_status=False,
)

# --- the lists of countries and states (P-321) ---

# The countries as the list shows them: the United States first, then by name.
_US_FIRST = case((Country.code == "US", 0), else_=1)
COUNTRIES = Listing(
    model=Country,
    fields={
        **_bookkeeping(Country),
        **_columns(Country, "text", "code"),
        "name": Field("text", Country.name, ordered_by=Country.name_key),
        "us_first": Field("integer", ordered_by=_US_FIRST),
    },
    joined=lambda query: query,
    default_sort=("us_first", "name", "code"),
    has_status=False,
)
# A state's country, by its place in the list of countries.
_STATE_COUNTRY = (
    select(Country.name_key).where(Country.code == State.country).correlate(State).scalar_subquery()
)
STATES = Listing(
    model=State,
    fields={
        **_bookkeeping(State),
        **_columns(State, "text", "country", "code"),
        "name": Field("text", State.name, ordered_by=State.name_key),
        "us_first": Field("integer", ordered_by=case((State.country == "US", 0), else_=1)),
        "country_name": Field("text", ordered_by=_STATE_COUNTRY),
    },
    joined=lambda query: query,
    default_sort=("us_first", "country_name", "country", "name"),
    has_status=False,
)

TAGS = Listing(
    model=Tag,
    fields={**_bookkeeping(Tag), **_columns(Tag, "text", "label", "colour", "description")},
    joined=lambda query: query,
    default_sort=("label",),
    has_status=False,
)

# --- circuits and circuit groups (P-145 to P-154) ------------------------------------

_A_LOCATION: Any = aliased(Location, name="a_location")
_A_SITE: Any = aliased(Site, name="a_site")
_Z_LOCATION: Any = aliased(Location, name="z_location")
_Z_SITE: Any = aliased(Site, name="z_site")
_Z_GROUP: Any = aliased(CircuitGroup, name="z_group")
_COST_LOCATION: Any = aliased(Location, name="cost_location")
_COST_SITE: Any = aliased(Site, name="cost_site")
_PRIMARY_CARRIER: Any = aliased(Vendor, name="primary_carrier")
_CIRCUIT_OWNER: Any = aliased(Owner, name="circuit_owner")
_SELF: Any = aliased(Circuit, name="carrier_of_circuit")


def _either_side(db: Session, text: str) -> ColumnElement[bool]:
    """Return the test that a side of a circuit is at or beneath a place a filter names."""
    a_side = _within(_A_LOCATION.hid, _A_LOCATION.site_hid, _A_SITE.region_hid)(db, text)
    z_side = _within(_Z_LOCATION.hid, _Z_LOCATION.site_hid, _Z_SITE.region_hid)(db, text)
    return or_(a_side, z_side)


# Every carrier of a circuit, its primary one among them, with the number each gives it.
_EVERY_CARRIER: Any = union_all(
    select(
        _SELF.hid.label("circuit_hid"),
        _SELF.carrier_hid.label("vendor_hid"),
        _SELF.carrier_circuit_number.label("circuit_number"),
    ).where(_SELF.carrier_hid.is_not(None)),
    select(CircuitCarrier.circuit_hid, CircuitCarrier.vendor_hid, CircuitCarrier.circuit_number),
).subquery("every_carrier")
_ANY_CARRIER = _one_of(
    select(_EVERY_CARRIER.c.vendor_hid), _EVERY_CARRIER.c.circuit_hid == Circuit.hid
)
_FIRST_NUMBER = (
    select(func.min(dialect.folded(_EVERY_CARRIER.c.circuit_number)))
    .where(_EVERY_CARRIER.c.circuit_hid == Circuit.hid)
    .correlate(Circuit)
    .scalar_subquery()
)
# The groups a circuit is in, retired ones too, since retiring a group ends no
# membership: those it was added to, and the network its Z side names (P-320).
_SELF_IN_GROUP: Any = aliased(Circuit, name="circuit_in_group")
_EVERY_CIRCUIT_GROUP: Any = union_all(
    select(
        CircuitGroupMember.circuit_hid.label("circuit_hid"),
        CircuitGroupMember.group_hid.label("group_hid"),
    ),
    select(_SELF_IN_GROUP.hid, _SELF_IN_GROUP.z_group_hid).where(
        _SELF_IN_GROUP.z_group_hid.is_not(None)
    ),
).subquery("every_circuit_group")
_ITS_CIRCUIT_GROUPS = (_EVERY_CIRCUIT_GROUP.c.circuit_hid == Circuit.hid,)
_CIRCUIT_GROUPS = _one_of(
    select(_EVERY_CIRCUIT_GROUP.c.group_hid).join(
        CircuitGroup, CircuitGroup.hid == _EVERY_CIRCUIT_GROUP.c.group_hid
    ),
    *_ITS_CIRCUIT_GROUPS,
)
_FIRST_CIRCUIT_GROUP = (
    select(func.min(CircuitGroup.name_key))
    .select_from(_EVERY_CIRCUIT_GROUP)
    .join(CircuitGroup, CircuitGroup.hid == _EVERY_CIRCUIT_GROUP.c.group_hid)
    .where(*_ITS_CIRCUIT_GROUPS)
    .correlate(Circuit)
    .scalar_subquery()
)
# Who bills a circuit: its primary carrier, and the carrier of each of its cost lines,
# the line's own or else the primary carrier (P-151). The dates of the lines are not
# looked at: the report of a year counts only the lines it bills, and the filter of a
# carrier's row lists the circuits of the year that carrier bills or provides.
_BILLING: Any = aliased(Circuit, name="billed_circuit")
_BILLED_BY: Any = union_all(
    select(
        CircuitCost.circuit_hid.label("circuit_hid"),
        func.coalesce(CircuitCost.vendor_hid, _BILLING.carrier_hid).label("vendor_hid"),
    ).join(_BILLING, _BILLING.hid == CircuitCost.circuit_hid),
    select(_SELF.hid, _SELF.carrier_hid).where(_SELF.carrier_hid.is_not(None)),
).subquery("billed_by")
_ANY_BILLER = _one_of(select(_BILLED_BY.c.vendor_hid), _BILLED_BY.c.circuit_hid == Circuit.hid)
# What a circuit costs a month today: the sum of its lines in date (D-158, P-150), and
# nothing on a day it is not in service. A draft is in service in a view of drafts, the
# only view that lists one.
_IN_SERVICE = circuit_records.in_service_column(include_drafts=True)
_CIRCUIT_MONTHLY = case(
    (
        _IN_SERVICE,
        select(circuit_records.hundredths_of_lines())
        .where(CircuitCost.circuit_hid == Circuit.hid, circuit_records.line_in_date_column())
        .correlate(Circuit)
        .scalar_subquery(),
    ),
    else_=0,
)


def _rate_in_force(rate: Any) -> ColumnElement[Any]:
    """Return the rate in force one way: its own, or the full rate of the port."""
    return func.coalesce(rate, Circuit.port_mbps, type_=rate.type)


CIRCUITS = Listing(
    model=Circuit,
    fields={
        **_bookkeeping(Circuit),
        **_columns(
            Circuit,
            "text",
            "name",
            "enterprise_circuit_id",
            "description",
            "notes",
            "a_note",
            "z_note",
            "carrier_circuit_number",
            "billing_account",
            "billing_contract",
        ),
        **_columns(Circuit, "choice", "circuit_type", "cost_side", "record_status"),
        **_columns(Circuit, "number", "port_mbps", "down_mbps", "up_mbps", "support_weight"),
        # The dates of each side, and the Z side's in force, its own or the A side's (P-320).
        **_columns(Circuit, "date", *circuits.A_DATES, *circuits.Z_DATES),
        **{
            f"effective.z_{day}": Field("date", circuits.z_in_force_column(day))
            for day in circuits.DAYS
        },
        "production": Field("boolean", Circuit.production),
        **_columns(
            Circuit,
            "reference",
            "a_location_hid",
            "z_location_hid",
            "z_group_hid",
            "carrier_hid",
            "owner_hid",
        ),
        # A side at a location, or at or beneath a site or a region.
        "location": Field(
            "place",
            func.coalesce(Circuit.a_location_hid, Circuit.z_location_hid),
            within=_either_side,
        ),
        "a_location.name": Field("text", _A_LOCATION.name),
        "z_location.name": Field("text", _Z_LOCATION.name),
        # The carrier network the Z side reaches, by its name (P-319).
        "z_group.name": Field("text", _Z_GROUP.name),
        # Where its cost and its weight count: the location of the side it counts at,
        # and that location's site.
        "cost_location": Field(
            "place",
            circuits.cost_location_column(),
            within=_within(_COST_LOCATION.hid, _COST_LOCATION.site_hid, _COST_SITE.region_hid),
        ),
        "cost_site_hid": Field("reference", _COST_LOCATION.site_hid),
        # The names of the sites of its sides and of the one it counts at, to sort and
        # find by, as a place's name is (D-132).
        "cost_site.name": Field("text", _COST_SITE.name),
        "a_site.name": Field("text", _A_SITE.name),
        "z_site.name": Field("text", _Z_SITE.name),
        "carrier.name": Field("text", _PRIMARY_CARRIER.name),
        # Any of its carriers, the primary one among them, and the number any gives it.
        "carriers.vendor_hid": Field("reference", _EVERY_CARRIER.c.vendor_hid, among=_ANY_CARRIER),
        "billed_by": Field("reference", _BILLED_BY.c.vendor_hid, among=_ANY_BILLER),
        "carriers.circuit_number": Field(
            "text",
            _EVERY_CARRIER.c.circuit_number,
            among=_ANY_CARRIER,
            ordered_by=_FIRST_NUMBER,
        ),
        "groups.hid": Field("reference", CircuitGroup.hid, among=_CIRCUIT_GROUPS),
        "groups.name": Field(
            "text", CircuitGroup.name, among=_CIRCUIT_GROUPS, ordered_by=_FIRST_CIRCUIT_GROUP
        ),
        "owner.label": Field("text", _CIRCUIT_OWNER.label),
        "owner_exception": Field("boolean", func.coalesce(_CIRCUIT_OWNER.is_external, false())),
        "owner_exception_reason": Field(
            "text", case((_CIRCUIT_OWNER.is_external.is_(True), _CIRCUIT_OWNER.exception_reason))
        ),
        # Its own weight. The default and the minimum of the settings are added to this
        # at the merge of 0.8.0 (P-155).
        "effective.support_weight": Field("number", weights.circuit_weight_column()),
        "effective.down_mbps": Field("number", _rate_in_force(Circuit.down_mbps)),
        "effective.up_mbps": Field("number", _rate_in_force(Circuit.up_mbps)),
        "monthly_cost": Field("number", circuit_records.as_money(_CIRCUIT_MONTHLY)),
        "annual_cost": Field(
            "number", circuit_records.as_money(_CIRCUIT_MONTHLY, circuit_records.MONTHS)
        ),
        "in_service": Field("boolean", _IN_SERVICE),
        "tags": _tags(circuit_records.RECORD_TYPE, Circuit),
    },
    joined=lambda query: (
        query.outerjoin(_A_LOCATION, _A_LOCATION.hid == Circuit.a_location_hid)
        .outerjoin(_A_SITE, _A_SITE.hid == _A_LOCATION.site_hid)
        .outerjoin(_Z_LOCATION, _Z_LOCATION.hid == Circuit.z_location_hid)
        .outerjoin(_Z_SITE, _Z_SITE.hid == _Z_LOCATION.site_hid)
        .outerjoin(_Z_GROUP, _Z_GROUP.hid == Circuit.z_group_hid)
        .outerjoin(_COST_LOCATION, _COST_LOCATION.hid == circuits.cost_location_column())
        .outerjoin(_COST_SITE, _COST_SITE.hid == _COST_LOCATION.site_hid)
        .outerjoin(_PRIMARY_CARRIER, _PRIMARY_CARRIER.hid == Circuit.carrier_hid)
        .outerjoin(_CIRCUIT_OWNER, _CIRCUIT_OWNER.hid == Circuit.owner_hid)
    ),
    default_sort=("name",),
)

_MEMBER_CIRCUIT: Any = aliased(Circuit, name="member_circuit")
_GROUP_OWNER: Any = aliased(Owner, name="circuit_group_owner")
_GROUP_CARRIER: Any = aliased(Vendor, name="circuit_group_carrier")


def _of_group(total: Any, *where: ColumnElement[bool], lines: bool = False) -> ColumnElement[Any]:
    """Return, as SQL, `total` of the circuits of a group, each once (P-320): those added
    to it, found by the index of the memberships, and beside them those whose Z side
    names it and that were not added to it, found by the index of `z_group_hid`, so that
    neither part reads every circuit. `lines` joins the cost lines of each."""

    def part(query: Any, *its: ColumnElement[bool]) -> ColumnElement[Any]:
        if lines:
            query = query.join(CircuitCost, CircuitCost.circuit_hid == _MEMBER_CIRCUIT.hid)
        return query.where(*its, *where).correlate(CircuitGroup).scalar_subquery()

    added = part(
        select(total)
        .select_from(CircuitGroupMember)
        .join(_MEMBER_CIRCUIT, _MEMBER_CIRCUIT.hid == CircuitGroupMember.circuit_hid),
        CircuitGroupMember.group_hid == CircuitGroup.hid,
    )
    reaching = part(
        select(total).select_from(_MEMBER_CIRCUIT),
        _MEMBER_CIRCUIT.z_group_hid == CircuitGroup.hid,
        ~select(CircuitGroupMember.hid)
        .where(
            CircuitGroupMember.group_hid == CircuitGroup.hid,
            CircuitGroupMember.circuit_hid == _MEMBER_CIRCUIT.hid,
        )
        .correlate(CircuitGroup, _MEMBER_CIRCUIT)
        .exists(),
    )
    return added + reaching


# How many circuits a group has, how many of them are in service today, and what those
# in service cost today, each circuit once.
_GROUP_CIRCUITS = _of_group(func.count())
_GROUP_IN_SERVICE = _of_group(func.count(), circuit_records.in_service_column(_MEMBER_CIRCUIT))
_GROUP_MONTHLY = _of_group(
    circuit_records.hundredths_of_lines(),
    circuit_records.in_service_column(_MEMBER_CIRCUIT),
    circuit_records.line_in_date_column(),
    lines=True,
)

CIRCUIT_GROUPS = Listing(
    model=CircuitGroup,
    fields={
        **_bookkeeping(CircuitGroup),
        **_columns(CircuitGroup, "text", "name", "description", "notes"),
        # A network, which a Z side may name, with its carrier, or a collection (P-319).
        "kind": Field("choice", CircuitGroup.kind),
        "carrier_hid": Field("reference", CircuitGroup.carrier_hid),
        "carrier.name": Field("text", _GROUP_CARRIER.name),
        "owner_hid": Field("reference", CircuitGroup.owner_hid),
        "owner.label": Field("text", _GROUP_OWNER.label),
        "record_status": Field("choice", CircuitGroup.record_status),
        "tags": _tags("circuit_group", CircuitGroup),
        "circuits": Field("integer", _GROUP_CIRCUITS),
        "in_service": Field("integer", _GROUP_IN_SERVICE),
        "monthly_cost": Field("number", circuit_records.as_money(_GROUP_MONTHLY)),
        "annual_cost": Field(
            "number", circuit_records.as_money(_GROUP_MONTHLY, circuit_records.MONTHS)
        ),
    },
    joined=lambda query: query.outerjoin(
        _GROUP_OWNER, _GROUP_OWNER.hid == CircuitGroup.owner_hid
    ).outerjoin(_GROUP_CARRIER, _GROUP_CARRIER.hid == CircuitGroup.carrier_hid),
    default_sort=("name",),
)

# The parts of circuits, as files carry them: each by the name of its circuit.
_PART_CIRCUIT: Any = aliased(Circuit, name="circuit_of_part")
_CARRIER_VENDOR: Any = aliased(Vendor, name="carrier_vendor")
_COST_VENDOR: Any = aliased(Vendor, name="cost_vendor")
_CONNECTED_ITEM: Any = aliased(Item, name="connected_item")
_CONNECTED_GROUP: Any = aliased(DeviceGroup, name="connected_group")

CIRCUIT_CARRIERS = Listing(
    model=CircuitCarrier,
    fields={
        **_bookkeeping(CircuitCarrier),
        **_columns(CircuitCarrier, "reference", "circuit_hid", "vendor_hid"),
        "role": Field("choice", CircuitCarrier.role),
        **_columns(CircuitCarrier, "text", "circuit_number", "notes"),
        "priority": Field("integer", CircuitCarrier.priority),
        "circuit.name": Field("text", _PART_CIRCUIT.name),
        "vendor.name": Field("text", _CARRIER_VENDOR.name),
    },
    joined=lambda query: query.join(
        _PART_CIRCUIT, _PART_CIRCUIT.hid == CircuitCarrier.circuit_hid
    ).join(_CARRIER_VENDOR, _CARRIER_VENDOR.hid == CircuitCarrier.vendor_hid),
    default_sort=("circuit.name", "priority", "vendor.name"),
    has_status=False,
)

CIRCUIT_COSTS = Listing(
    model=CircuitCost,
    fields={
        **_bookkeeping(CircuitCost),
        **_columns(CircuitCost, "reference", "circuit_hid", "vendor_hid"),
        **_columns(CircuitCost, "text", "description", "notes"),
        "monthly_cost": Field("number", CircuitCost.monthly_cost),
        **_columns(CircuitCost, "date", "starts_on", "ends_on"),
        "in_date": Field("boolean", circuit_records.line_in_date_column()),
        "circuit.name": Field("text", _PART_CIRCUIT.name),
        "vendor.name": Field("text", _COST_VENDOR.name),
    },
    joined=lambda query: query.join(
        _PART_CIRCUIT, _PART_CIRCUIT.hid == CircuitCost.circuit_hid
    ).outerjoin(_COST_VENDOR, _COST_VENDOR.hid == CircuitCost.vendor_hid),
    default_sort=("circuit.name", "description"),
    has_status=False,
)

CIRCUIT_DEVICES = Listing(
    model=CircuitDevice,
    fields={
        **_bookkeeping(CircuitDevice),
        **_columns(CircuitDevice, "reference", "circuit_hid", "item_hid", "group_hid"),
        "side": Field("choice", CircuitDevice.side),
        "notes": Field("text", CircuitDevice.notes),
        "circuit.name": Field("text", _PART_CIRCUIT.name),
        # The device, by the name it is shown by: a group's, or an item's.
        "device.name": Field(
            "text",
            func.coalesce(
                _CONNECTED_GROUP.name,
                _CONNECTED_ITEM.name,
                _CONNECTED_ITEM.hostname,
                _CONNECTED_ITEM.serial_number,
                _CONNECTED_ITEM.asset_tag,
            ),
        ),
    },
    joined=lambda query: (
        query.join(_PART_CIRCUIT, _PART_CIRCUIT.hid == CircuitDevice.circuit_hid)
        .outerjoin(_CONNECTED_ITEM, _CONNECTED_ITEM.hid == CircuitDevice.item_hid)
        .outerjoin(_CONNECTED_GROUP, _CONNECTED_GROUP.hid == CircuitDevice.group_hid)
    ),
    default_sort=("circuit.name", "side", "device.name"),
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
    AGREEMENTS,
    CONTRACTS,
    CONTRACT_CONTACTS,
    COVERAGE,
    PURCHASE_REQUESTS,
    PURCHASE_LINES,
    EXTERNAL_SYSTEMS,
    REGISTRATIONS,
    CAPACITY_LINES,
    REPLACEMENTS,
    TAGS,
    CIRCUITS,
    CIRCUIT_GROUPS,
    CIRCUIT_CARRIERS,
    CIRCUIT_COSTS,
    CIRCUIT_DEVICES,
    # The contacts of carriers and of circuits (P-149).
    VENDOR_CONTACTS,
    CIRCUIT_CONTACTS,
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


def members_disagree(db: Session, found: Sequence[DeviceGroup]) -> dict[str, list[str]]:
    """Return, for each group, the fields of its own that a current member contradicts.

    For now that is its owner: a member whose owner in force, by the walk of P-175, is
    another, its own, from the item it is in or from a group that ranks first. One
    statement answers for all the groups, worked out by the database as the item list's
    `effective.owner_hid` is.
    """
    said: dict[str, list[str]] = {group.hid: [] for group in found}
    owned = [group.hid for group in found if group.owner_hid is not None]
    if not owned:
        return said
    group: Any = aliased(DeviceGroup, name="disagreeing_group")
    member: Any = aliased(DeviceGroupMember, name="disagreeing_member")
    query = (
        ITEMS.joined(select(group.hid).select_from(Item))
        .join(member, member.item_hid == Item.hid)
        .join(group, group.hid == member.group_hid)
        .where(
            group.hid.in_(owned),
            member.left_on.is_(None),
            OWNER_IN_FORCE.is_not(None),
            group.owner_hid != OWNER_IN_FORCE,
        )
        .distinct()
    )
    for group_hid in db.scalars(query):
        said[group_hid] = ["owner_hid"]
    return said
