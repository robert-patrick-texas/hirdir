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
    Owner,
    OwnerMember,
    Region,
    Site,
    Tag,
    TagLink,
    Vendor,
)
from hirdir.domain import geography, health, inheritance, lifecycle, records
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

OWNER_IN_FORCE: ColumnElement[Any] = func.coalesce(*(one.owner_hid for one in _LINE))
# Where an item is: a minor item is where the nearest item above it is that has a location.
LOCATION_IN_FORCE: ColumnElement[Any] = func.coalesce(*(one.location_hid for one in _LINE))
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

# The health of an item: the cascade of `hirdir.domain.health.of_item`, for the database
# to filter and sort by. A test holds the two together.
HEALTH: ColumnElement[Any] = case(
    (
        or_(
            Item.condition.in_(health.FAILED_CONDITIONS),
            and_(
                standing("expected_online").is_(True),
                Item.observed_status == health.UNREACHABLE,
            ),
        ),
        health.FAILED,
    ),
    (
        or_(
            Item.condition.in_(health.POOR_CONDITIONS),
            Item.observed_status.in_((health.OBSERVED_DEGRADED, health.UNREACHABLE)),
        ),
        health.DEGRADED,
    ),
    (
        or_(Item.condition == health.GOOD_CONDITION, Item.observed_status.in_(health.SEEN_WELL)),
        health.GOOD,
    ),
    else_=health.UNKNOWN,
)
HEALTH_RANK: ColumnElement[Any] = case(
    (HEALTH == health.FAILED, 0),
    (HEALTH == health.DEGRADED, 1),
    (HEALTH == health.UNKNOWN, 2),
    else_=3,
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


_ITEM_GROUPS = _one_of(
    select(DeviceGroupMember.hid).join(DeviceGroup, DeviceGroup.hid == DeviceGroupMember.group_hid),
    DeviceGroupMember.item_hid == Item.hid,
    DeviceGroupMember.left_on.is_(None),
    DeviceGroup.record_status != "retired",
)
_ITEM_ADDRESSES = _one_of(
    select(Address.hid).outerjoin(Network, Network.hid == Address.network_hid),
    Address.item_hid == Item.hid,
)
_GROUP_ADDRESSES = _one_of(
    select(Address.hid).outerjoin(Network, Network.hid == Address.network_hid),
    Address.group_hid == DeviceGroup.hid,
)


def _address_fields(among: Any) -> dict[str, Field]:
    return {
        "address": Field("address", Address.address, convert=comparable, among=among),
        "network.label": Field("text", Network.label, among=among),
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
        **{f"effective.{name}": _effective(name) for name in inheritance.ITEM_FIELDS},
        "effective.owner_hid": Field("reference", OWNER_IN_FORCE),
        "effective.location_hid": Field("reference", LOCATION_IN_FORCE),
        # Where the item is, by the location in force.
        "location": Field(
            "place",
            LOCATION_IN_FORCE,
            within=_within(LOCATION_IN_FORCE, ITEM_LOCATION.site_hid, ITEM_SITE.region_hid),
        ),
        "location.name": Field("text", ITEM_LOCATION.name),
        "location.kind": Field("choice", ITEM_LOCATION.kind),
        "site": Field("text", ITEM_SITE.name),
        "site.code": Field("text", ITEM_SITE.code),
        "site_hid": Field("reference", ITEM_SITE.hid),
        "region": Field("text", ITEM_REGION.name),
        "region_hid": Field("reference", ITEM_REGION.hid),
        "owner_exception_reason": Field("text", Item.owner_exception_reason),
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
        "tags": Field("tags", test=_tagged("item", Item.hid)),
        "group.hid": Field("reference", DeviceGroup.hid, among=_ITEM_GROUPS),
        "group.name": Field("text", DeviceGroup.name, among=_ITEM_GROUPS),
        "group.type": Field("choice", DeviceGroup.type, among=_ITEM_GROUPS),
        **_address_fields(_ITEM_ADDRESSES),
    },
    joined=lambda query: (
        _with_items_above(query)
        .outerjoin(CatalogEntry, CatalogEntry.hid == Item.catalog_entry_hid)
        .outerjoin(Vendor, Vendor.hid == CatalogEntry.vendor_hid)
        .outerjoin(Owner, Owner.hid == OWNER_IN_FORCE)
        .outerjoin(ITEM_LOCATION, ITEM_LOCATION.hid == LOCATION_IN_FORCE)
        .outerjoin(ITEM_SITE, ITEM_SITE.hid == ITEM_LOCATION.site_hid)
        .outerjoin(ITEM_REGION, ITEM_REGION.hid == ITEM_SITE.region_hid)
    ),
    default_sort=("name",),
)

_PARENT_GROUP: Any = aliased(DeviceGroup, name="parent_group")
_GROUP_LOCATION: Any = aliased(Location, name="group_location")
_GROUP_SITE: Any = aliased(Site, name="group_site")

DEVICE_GROUPS = Listing(
    model=DeviceGroup,
    fields={
        **_bookkeeping(DeviceGroup),
        **_columns(DeviceGroup, "reference", "parent_group_hid", "owner_hid", "location_hid"),
        "location": Field(
            "place",
            DeviceGroup.location_hid,
            within=_within(
                DeviceGroup.location_hid, _GROUP_LOCATION.site_hid, _GROUP_SITE.region_hid
            ),
        ),
        "location.name": Field("text", _GROUP_LOCATION.name),
        "site": Field("text", _GROUP_SITE.name),
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
        "owner.label": Field("text", Owner.label),
        "parent.name": Field("text", _PARENT_GROUP.name),
        "tags": Field("tags", test=_tagged("device_group", DeviceGroup.hid)),
        "member.item_hid": Field(
            "reference",
            DeviceGroupMember.item_hid,
            among=_one_of(
                select(DeviceGroupMember.hid),
                DeviceGroupMember.group_hid == DeviceGroup.hid,
                DeviceGroupMember.left_on.is_(None),
            ),
        ),
        **_address_fields(_GROUP_ADDRESSES),
    },
    joined=lambda query: (
        query.outerjoin(Owner, Owner.hid == DeviceGroup.owner_hid)
        .outerjoin(_PARENT_GROUP, _PARENT_GROUP.hid == DeviceGroup.parent_group_hid)
        .outerjoin(_GROUP_LOCATION, _GROUP_LOCATION.hid == DeviceGroup.location_hid)
        .outerjoin(_GROUP_SITE, _GROUP_SITE.hid == _GROUP_LOCATION.site_hid)
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
        "tags": Field("tags", test=_tagged("catalog_entry", CatalogEntry.hid)),
    },
    joined=lambda query: query.join(Vendor, Vendor.hid == CatalogEntry.vendor_hid),
    default_sort=("vendor", "pid"),
)

VENDORS = Listing(
    model=Vendor,
    fields={
        **_bookkeeping(Vendor),
        **_columns(Vendor, "text", "name", "notes"),
        "review_status": Field("choice", Vendor.review_status),
    },
    joined=lambda query: query,
    default_sort=("name",),
    has_status=False,
)

OWNERS = Listing(
    model=Owner,
    fields={
        **_bookkeeping(Owner),
        **_columns(Owner, "text", "label", "organization", "exception_reason"),
        "is_external": Field("boolean", Owner.is_external),
        "record_status": Field("choice", Owner.record_status),
        "tags": Field("tags", test=_tagged("owner", Owner.hid)),
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
        **_columns(Region, "text", "name", "code", "notes", *_SHIPPING),
        "record_status": Field("choice", Region.record_status),
        "tags": Field("tags", test=_tagged("region", Region.hid)),
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
        **_columns(Site, "text", "name", "code", "notes", *ADDRESS_FIELDS, *_SHIPPING),
        **_columns(Site, "number", "latitude", "longitude"),
        "record_status": Field("choice", Site.record_status),
        "tags": Field("tags", test=_tagged("site", Site.hid)),
    },
    joined=lambda query: query.join(Region, Region.hid == Site.region_hid),
    default_sort=("name",),
)

_PARENT_LOCATION: Any = aliased(Location, name="parent_location")

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
        "parent.name": Field("text", _PARENT_LOCATION.name),
        "is_top": Field("boolean", Location.parent_location_hid.is_(None)),
        **_columns(Location, "text", "name", "code", "notes", *ADDRESS_FIELDS, *_SHIPPING),
        "kind": Field("choice", Location.kind),
        **_columns(Location, "number", "latitude", "longitude"),
        "record_status": Field("choice", Location.record_status),
        "tags": Field("tags", test=_tagged("location", Location.hid)),
    },
    joined=lambda query: query.join(Site, Site.hid == Location.site_hid).outerjoin(
        _PARENT_LOCATION, _PARENT_LOCATION.hid == Location.parent_location_hid
    ),
    default_sort=("site.name", "name"),
)

CONTACTS = Listing(
    model=Contact,
    fields={
        **_bookkeeping(Contact),
        **_columns(Contact, "text", "name", "organization", "email", "phone", "notes"),
        "record_status": Field("choice", Contact.record_status),
        "tags": Field("tags", test=_tagged("contact", Contact.hid)),
    },
    joined=lambda query: query,
    default_sort=("name",),
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
