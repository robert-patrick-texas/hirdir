"""The fields each list can be filtered and sorted by, and how the list is read.

A field named here is one a filter may use on that list. Dotted names reach a related
record (`catalog.pid`, `owner.label`), and `effective.<field>` is the value in force of
a field that inherits.
"""

from collections.abc import Callable, Mapping
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
    CircuitCost,
    CircuitDevice,
    CircuitGroup,
    CircuitGroupMember,
    Contact,
    ContactAssignment,
    Contract,
    ContractContact,
    ContractCoverage,
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
    Tag,
    TagLink,
    Vendor,
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
    inheritance,
    lifecycle,
    not_renewed,
    operators,
    owners,
    purchases,
    records,
    systems,
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
        "catalog.vendor_hid": Field("reference", CatalogEntry.vendor_hid),
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
# The groups a circuit is in, retired ones too: retiring a group ends no membership.
_ITS_CIRCUIT_GROUPS = (CircuitGroupMember.circuit_hid == Circuit.hid,)
_CIRCUIT_GROUPS = _one_of(
    select(CircuitGroupMember.hid).join(
        CircuitGroup, CircuitGroup.hid == CircuitGroupMember.group_hid
    ),
    *_ITS_CIRCUIT_GROUPS,
)
_FIRST_CIRCUIT_GROUP = (
    select(func.min(CircuitGroup.name_key))
    .select_from(CircuitGroupMember)
    .join(CircuitGroup, CircuitGroup.hid == CircuitGroupMember.group_hid)
    .where(*_ITS_CIRCUIT_GROUPS)
    .correlate(Circuit)
    .scalar_subquery()
)
# What a circuit costs a month today: the sum of its lines in date (D-158, P-150).
_CIRCUIT_MONTHLY = (
    select(circuit_records.hundredths_of_lines())
    .where(CircuitCost.circuit_hid == Circuit.hid, circuit_records.line_in_date_column())
    .correlate(Circuit)
    .scalar_subquery()
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
        **_columns(Circuit, "date", "installed_on", "activated_on", "disconnected_on"),
        "production": Field("boolean", Circuit.production),
        **_columns(
            Circuit, "reference", "a_location_hid", "z_location_hid", "carrier_hid", "owner_hid"
        ),
        # A side at a location, or at or beneath a site or a region.
        "location": Field(
            "place",
            func.coalesce(Circuit.a_location_hid, Circuit.z_location_hid),
            within=_either_side,
        ),
        "a_location.name": Field("text", _A_LOCATION.name),
        "z_location.name": Field("text", _Z_LOCATION.name),
        # Where its cost and its weight count: the location of the side it counts at,
        # and that location's site.
        "cost_location": Field(
            "place",
            circuits.cost_location_column(),
            within=_within(_COST_LOCATION.hid, _COST_LOCATION.site_hid, _COST_SITE.region_hid),
        ),
        "cost_site_hid": Field("reference", _COST_LOCATION.site_hid),
        "carrier.name": Field("text", _PRIMARY_CARRIER.name),
        # Any of its carriers, the primary one among them, and the number any gives it.
        "carriers.vendor_hid": Field("reference", _EVERY_CARRIER.c.vendor_hid, among=_ANY_CARRIER),
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
        "effective.support_weight": Field("number", Circuit.support_weight),
        "effective.down_mbps": Field("number", _rate_in_force(Circuit.down_mbps)),
        "effective.up_mbps": Field("number", _rate_in_force(Circuit.up_mbps)),
        "monthly_cost": Field("number", circuit_records.as_money(_CIRCUIT_MONTHLY)),
        "annual_cost": Field(
            "number", circuit_records.as_money(_CIRCUIT_MONTHLY, circuit_records.MONTHS)
        ),
        "in_service": Field("boolean", circuit_records.in_service_column()),
        "tags": _tags(circuit_records.RECORD_TYPE, Circuit),
    },
    joined=lambda query: (
        query.outerjoin(_A_LOCATION, _A_LOCATION.hid == Circuit.a_location_hid)
        .outerjoin(_A_SITE, _A_SITE.hid == _A_LOCATION.site_hid)
        .outerjoin(_Z_LOCATION, _Z_LOCATION.hid == Circuit.z_location_hid)
        .outerjoin(_Z_SITE, _Z_SITE.hid == _Z_LOCATION.site_hid)
        .outerjoin(_COST_LOCATION, _COST_LOCATION.hid == circuits.cost_location_column())
        .outerjoin(_COST_SITE, _COST_SITE.hid == _COST_LOCATION.site_hid)
        .outerjoin(_PRIMARY_CARRIER, _PRIMARY_CARRIER.hid == Circuit.carrier_hid)
        .outerjoin(_CIRCUIT_OWNER, _CIRCUIT_OWNER.hid == Circuit.owner_hid)
    ),
    default_sort=("name",),
)

_MEMBER_CIRCUIT: Any = aliased(Circuit, name="member_circuit")
_GROUP_OWNER: Any = aliased(Owner, name="circuit_group_owner")
_OF_GROUP = (CircuitGroupMember.group_hid == CircuitGroup.hid,)
# How many circuits a group has, how many of them are in service today, and what those
# in service cost today, each circuit once.
_GROUP_CIRCUITS: ColumnElement[Any] = (
    select(func.count())
    .select_from(CircuitGroupMember)
    .where(*_OF_GROUP)
    .correlate(CircuitGroup)
    .scalar_subquery()
)
_GROUP_IN_SERVICE: ColumnElement[Any] = (
    select(func.count())
    .select_from(CircuitGroupMember)
    .join(_MEMBER_CIRCUIT, _MEMBER_CIRCUIT.hid == CircuitGroupMember.circuit_hid)
    .where(*_OF_GROUP, circuit_records.in_service_column(_MEMBER_CIRCUIT))
    .correlate(CircuitGroup)
    .scalar_subquery()
)
_GROUP_MONTHLY: ColumnElement[Any] = (
    select(circuit_records.hundredths_of_lines())
    .select_from(CircuitGroupMember)
    .join(_MEMBER_CIRCUIT, _MEMBER_CIRCUIT.hid == CircuitGroupMember.circuit_hid)
    .join(CircuitCost, CircuitCost.circuit_hid == _MEMBER_CIRCUIT.hid)
    .where(
        *_OF_GROUP,
        circuit_records.in_service_column(_MEMBER_CIRCUIT),
        circuit_records.line_in_date_column(),
    )
    .correlate(CircuitGroup)
    .scalar_subquery()
)

CIRCUIT_GROUPS = Listing(
    model=CircuitGroup,
    fields={
        **_bookkeeping(CircuitGroup),
        **_columns(CircuitGroup, "text", "name", "description", "notes"),
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
    joined=lambda query: query.outerjoin(_GROUP_OWNER, _GROUP_OWNER.hid == CircuitGroup.owner_hid),
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
