"""Turning the inventory's records into the shapes the API returns.

A page of a list is shaped together, so that the catalog entries, vendors, owners and
tags its rows refer to are each read once for the page and not once for each row.
"""

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hirdir.api import circuit_shapes
from hirdir.api import records as shapes
from hirdir.db.models import (
    Address,
    Agreement,
    CapacityLine,
    CapacityRecord,
    CatalogEntry,
    Choice,
    Circuit,
    CircuitContact,
    Contact,
    ContactAssignment,
    Contract,
    ContractCoverage,
    DeviceGroup,
    DeviceGroupMember,
    ExternalSystem,
    ImportJob,
    ImportRow,
    Item,
    ItemReplacement,
    LifecycleRule,
    Location,
    Network,
    Operator,
    Owner,
    OwnerMember,
    PurchaseLine,
    PurchaseRequest,
    Region,
    Registration,
    Site,
    Tag,
    User,
    Vendor,
    VendorContact,
)
from hirdir.domain import (
    addresses,
    capacity,
    carrier_contacts,
    choices,
    contacts,
    contract_contacts,
    contracts,
    descent,
    geography,
    groups,
    health,
    inheritance,
    operators,
    purchases,
    records,
    replacements,
    resolution,
    settings,
    systems,
    tags,
    weights,
)
from hirdir.domain import items as item_rules
from hirdir.domain import owners as owner_rules
from hirdir.domain.inheritance import Effective
from hirdir.domain.settings import SettingValue
from hirdir.io import alerts, balance, fields, imports, operated, planning, tried

FIRST_ROWS = 100


def _by_hid(db: Session, model: Any, hids: set[str | None]) -> dict[str, Any]:
    wanted = {hid for hid in hids if hid}
    if not wanted:
        return {}
    return {record.hid: record for record in db.scalars(select(model).where(model.hid.in_(wanted)))}


def _shown(name: str, value: Any) -> str | bool | None:
    """Return a value as a record answers it: a decimal and a date as text."""
    if isinstance(value, Decimal):
        return records.decimal_text(name, value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str | bool):
        return value
    return None


def _text(name: str, value: Any) -> str | None:
    """Return a value that is never a truth value as a record answers it."""
    shown = _shown(name, value)
    return shown if isinstance(shown, str) else None


def _effective(name: str, effective: Effective) -> shapes.EffectiveValue:
    return shapes.EffectiveValue(
        value=_shown(name, effective.value),
        source=effective.source,
        source_hid=effective.source_hid,
    )


def weight_out(found: weights.Weighed) -> shapes.EffectiveWeight:
    """Return a support weight in force, with what it was raised from (P-155)."""
    return shapes.EffectiveWeight.model_validate(weights.effective_entry(found))


def _health(found: health.Health) -> shapes.HealthOut:
    return shapes.HealthOut.model_validate(found)


def _count_by(db: Session, column: Any, hids: list[str]) -> dict[str, int]:
    counts = dict.fromkeys(hids, 0)
    if hids:
        counted = db.execute(select(column, func.count()).where(column.in_(hids)).group_by(column))
        for hid, count in counted:
            counts[hid] = count
    return counts


def item_refs(db: Session, items: list[Item]) -> dict[str, shapes.ItemRef]:
    """Return each of the items as another record names it."""
    entries = _by_hid(db, CatalogEntry, {item.catalog_entry_hid for item in items})
    return {
        item.hid: shapes.ItemRef(
            hid=item.hid,
            name=item.name or item.hostname,
            serial_number=item.serial_number,
            asset_tag=item.asset_tag,
            pid=entries[item.catalog_entry_hid].pid if item.catalog_entry_hid else None,
        )
        for item in items
    }


def _group_ref(group: DeviceGroup) -> shapes.DeviceGroupRef:
    return shapes.DeviceGroupRef(hid=group.hid, name=group.name, type=group.type)


def _address_refs(db: Session, field: str, hids: list[str]) -> dict[str, list[shapes.AddressRef]]:
    found = addresses.of_holders(db, field, hids)
    networks = _by_hid(
        db, Network, {address.network_hid for listed in found.values() for address in listed}
    )
    return {
        hid: [
            shapes.AddressRef(
                hid=address.hid,
                address=address.address,
                family=addresses.family(address.address),
                network_hid=address.network_hid,
                network=networks[address.network_hid].label if address.network_hid else None,
                role=address.role,
                is_primary=address.is_primary,
            )
            for address in listed
        ]
        for hid, listed in found.items()
    }


def vendors_out(db: Session, found: list[Vendor]) -> list[shapes.VendorOut]:
    """Return vendors, each with the contacts it names (P-149), read for all at once."""
    named = carrier_contacts.named_by_vendors(db, [vendor.hid for vendor in found])
    return [
        shapes.VendorOut(
            **_own(vendor, shapes.VendorOut, ("contacts",)),
            contacts=[vendor_contact_out(one) for one in named[vendor.hid]],
        )
        for vendor in found
    ]


def vendor_out(db: Session, vendor: Vendor) -> shapes.VendorOut:
    """Return a vendor, with the contacts it names."""
    return vendors_out(db, [vendor])[0]


def _owner_ref(owner: Owner) -> shapes.OwnerRef:
    return shapes.OwnerRef(hid=owner.hid, label=owner.label, is_external=owner.is_external)


def _exception(owner: Owner | None) -> dict[str, Any]:
    """Return whether what an owner has is an exception, and that owner's reason for it.

    The reason is said once, on the owner. What it owns is marked by it and holds none.
    """
    outside = owner is not None and owner.is_external
    return {
        "owner_exception": outside,
        "owner_exception_reason": owner.exception_reason if owner is not None and outside else None,
    }


def _keyed(prefix: str, found: dict[str, Effective]) -> dict[str, Effective]:
    """Return what was found under keys of its own, to be gathered with others."""
    return {f"{prefix}:{hid}": one for hid, one in found.items()}


def _place_in_force(
    found: Effective, places: dict[str, shapes.LocationRef], holders: dict[str, str]
) -> shapes.EffectiveLocation:
    """Return a location in force: its path, its site, and where it came from."""
    place = places.get(found.value or "")
    return shapes.EffectiveLocation(
        value=found.value,
        label=place.path if place is not None else None,
        source=found.source,
        source_hid=found.source_hid,
        source_label=holders.get(found.source_hid or "") if found.source != "own" else None,
        site_hid=place.site_hid if place is not None else None,
        site=place.site if place is not None else None,
        region_hid=place.region_hid if place is not None else None,
        region=place.region if place is not None else None,
    )


class _Labels:
    """The operators a page of records refers to, each read once with who is behind it."""

    def __init__(self, db: Session, hids: set[str | None]) -> None:
        self.found: dict[str, Operator] = _by_hid(db, Operator, hids)
        self.people: dict[str, Contact] = _by_hid(
            db, Contact, {operator.contact_hid for operator in self.found.values()}
        )
        self.users: dict[str, User] = contacts.users_of(db, list(self.people))

    def ref(self, hid: str | None) -> shapes.OperatorRef | None:
        """Return an operator as what it is given to shows it."""
        operator = self.found.get(hid or "")
        if operator is None:
            return None
        contact = self.people.get(operator.contact_hid or "")
        return shapes.OperatorRef.model_validate(
            {
                "hid": operator.hid,
                "label": operator.label,
                "colour": operator.colour,
                "contact_hid": operator.contact_hid,
                "contact": contact.name if contact is not None else None,
                "is_open": operators.is_open(operator, contact),
                "scope": operators.scope(contact, self.users),
                "record_status": operator.record_status,
            }
        )

    def in_force(self, found: Effective, holders: dict[str, str]) -> shapes.EffectiveOperator:
        """Return an operator in force: the label, who is behind it, where it came from.

        `holders` names the items, the groups and the places that it may come from.
        """
        ref = self.ref(found.value)
        return shapes.EffectiveOperator(
            value=found.value,
            label=ref.label if ref is not None else None,
            source=found.source,
            source_hid=found.source_hid,
            source_label=holders.get(found.source_hid or "") if found.source != "own" else None,
            colour=ref.colour if ref is not None else None,
            contact_hid=ref.contact_hid if ref is not None else None,
            contact=ref.contact if ref is not None else None,
            is_open=ref.is_open if ref is not None else False,
            scope=ref.scope if ref is not None else None,
        )


def _holders(db: Session, found: dict[str, Effective], above: dict[str, Item]) -> dict[str, str]:
    """Return what each record that an operator comes from is called: the item above
    or the group by its name, a place by its path."""
    named = {hid: item_rules.shown_name(item) for hid, item in above.items()}
    its_groups = _by_hid(
        db,
        DeviceGroup,
        {one.source_hid for one in found.values() if one.source == operators.SOURCE_GROUP},
    )
    named.update((hid, group.name) for hid, group in its_groups.items())
    atlas = geography.Atlas(db)
    for one in found.values():
        if one.source in geography.LEVELS and one.source_hid:
            place = geography.Place(
                one.source, db.get(geography.MODELS[one.source], one.source_hid)
            )
            if place.record is not None:
                named[one.source_hid] = atlas.path(place)
    return named


def summary_out(db: Session, found: Any) -> shapes.SummaryOut:
    """Return a summary, each operator of a row with its label and who is behind it."""
    marks = _Labels(db, {one.hid for row in found.rows for one in row.operators or ()})
    rows = []
    for row in found.rows:
        involved = None
        if row.operators is not None:
            involved = []
            for one in row.operators:
                ref = marks.ref(one.hid)
                involved.append(
                    shapes.RowOperator(
                        hid=one.hid,
                        label=ref.label if ref is not None else None,
                        colour=ref.colour if ref is not None else None,
                        contact=ref.contact if ref is not None else None,
                        is_open=ref.is_open if ref is not None else False,
                        items=one.items,
                        component_count=one.component_count,
                        support_weight=one.support_weight,
                    )
                )
        measures = shapes.Measures.model_validate(row).model_dump()
        # By group or by model, what the group or the model says of itself.
        record = shapes.RowRecord.model_validate(row).model_dump()
        rows.append(
            shapes.SummaryRow(
                **measures, **record, key=row.key, label=row.label, operators=involved
            )
        )
    return shapes.SummaryOut(
        by=found.by, totals=shapes.SummaryTotals.model_validate(found.totals), rows=rows
    )


def operators_out(db: Session, found: list[Operator]) -> list[shapes.OperatorOut]:
    """Return operators, each with who is behind it, the user that person is where it is
    one, and how much it is given to (P-172)."""
    people = _by_hid(db, Contact, {operator.contact_hid for operator in found})
    users = contacts.users_of(db, list(people))
    uses = operators.uses(db, [operator.hid for operator in found])
    out = []
    for operator in found:
        contact = people.get(operator.contact_hid or "")
        user = users.get(contact.hid) if contact is not None else None
        out.append(
            shapes.OperatorOut(
                **_own(
                    operator, shapes.OperatorOut, ("contact", "user", "scope", "is_open", "uses")
                ),
                contact=_contact_ref(contact) if contact is not None else None,
                user=_user_brief(user),
                scope=operators.scope(contact, users),
                is_open=operators.is_open(operator, contact),
                uses=uses[operator.hid],
            )
        )
    return out


def _user_brief(user: User | None) -> shapes.UserBrief | None:
    return shapes.UserBrief(hid=user.hid, username=user.username) if user is not None else None


def _contact_ref(contact: Contact) -> shapes.ContactRef:
    return shapes.ContactRef.model_validate(contact)


def _owner_member(member: OwnerMember, contact: Contact) -> shapes.OwnerMemberOut:
    return shapes.OwnerMemberOut(
        **{
            name: getattr(member, name)
            for name in shapes.OwnerMemberOut.model_fields
            if name != "contact"
        },
        contact=_contact_ref(contact),
    )


def owner_member_out(db: Session, member: OwnerMember) -> shapes.OwnerMemberOut:
    """Return one member of an owner, with its contact."""
    return _owner_member(member, db.get_one(Contact, member.contact_hid))


def owner_members_out(db: Session, owner_hid: str) -> list[shapes.OwnerMemberOut]:
    """Return the members of an owner, the primary first."""
    found = owner_rules.members_of(db, [owner_hid])[owner_hid]
    return [_owner_member(member, contact) for member, contact in found]


def owners_out(db: Session, found: list[Owner]) -> list[shapes.OwnerOut]:
    """Return owners, each with its tags and its people."""
    hids = [owner.hid for owner in found]
    labels = tags.labels_of(db, owner_rules.RECORD_TYPE, hids)
    members = owner_rules.members_of(db, hids)
    return [
        shapes.OwnerOut(
            **{
                name: getattr(owner, name)
                for name in shapes.OwnerOut.model_fields
                if name not in ("tags", "members")
            },
            tags=labels[owner.hid],
            members=[_owner_member(member, contact) for member, contact in members[owner.hid]],
        )
        for owner in found
    ]


def owner_out(db: Session, owner: Owner) -> shapes.OwnerOut:
    """Return one owner."""
    return owners_out(db, [owner])[0]


def location_refs(db: Session, hids: set[str | None]) -> dict[str, shapes.LocationRef]:
    """Return each of the locations as an item or a group that is there names it."""
    atlas = geography.Atlas(db)
    wanted = sorted(hid for hid in hids if hid)
    atlas.read_locations(wanted)
    refs = {}
    for hid in wanted:
        location = atlas.location(hid)
        site = atlas.site(location.site_hid) if location is not None else None
        if location is None or site is None:
            continue
        refs[hid] = shapes.LocationRef(
            hid=hid,
            name=location.name,
            path=atlas.location_path(hid),
            kind=location.kind,
            site_hid=site.hid,
            site=site.name,
            region_hid=site.region_hid,
            region=atlas.regions[site.region_hid].name,
        )
    return refs


def _own(record: Any, model: Any, shaped: tuple[str, ...]) -> dict[str, Any]:
    return {name: getattr(record, name) for name in model.model_fields if name not in shaped}


def _live_counts(db: Session, model: Any, column: Any, hids: list[str]) -> dict[str, int]:
    """Return how many records that are not retired name each of hids in a column."""
    counts = dict.fromkeys(hids, 0)
    if hids:
        counted = db.execute(
            select(column, func.count())
            .select_from(model)
            .where(column.in_(hids), model.record_status != "retired")
            .group_by(column)
        )
        for hid, count in counted:
            counts[hid] = count
    return counts


def regions_out(db: Session, found: list[Region]) -> list[shapes.RegionOut]:
    """Return regions, each with its path and what is directly in it."""
    atlas = geography.Atlas(db)
    hids = [region.hid for region in found]
    labels = tags.labels_of(db, geography.REGION, hids)
    within = _live_counts(db, Region, Region.parent_region_hid, hids)
    sites = _live_counts(db, Site, Site.region_hid, hids)
    marks = _Labels(db, {region.operator_hid for region in found})
    out = []
    for region in found:
        parent = atlas.regions.get(region.parent_region_hid or "")
        out.append(
            shapes.RegionOut(
                **_own(
                    region,
                    shapes.RegionOut,
                    ("parent", "path", "tags", "regions", "sites", "operator"),
                ),
                operator=marks.ref(region.operator_hid),
                parent=None
                if parent is None
                else shapes.PlaceRef(
                    hid=parent.hid, name=parent.name, path=atlas.region_path(parent.hid)
                ),
                path=atlas.region_path(region.hid),
                tags=labels[region.hid],
                regions=within[region.hid],
                sites=sites[region.hid],
            )
        )
    return out


def sites_out(db: Session, found: list[Site]) -> list[shapes.SiteOut]:
    """Return sites, each with its region, its path and its number of locations."""
    atlas = geography.Atlas(db)
    atlas.take(found)
    hids = [site.hid for site in found]
    labels = tags.labels_of(db, geography.SITE, hids)
    locations = _live_counts(db, Location, Location.site_hid, hids)
    marks = _Labels(db, {site.operator_hid for site in found})
    figures = weights.in_force(db)
    return [
        shapes.SiteOut(
            **_own(
                site,
                shapes.SiteOut,
                ("region", "path", "tags", "locations", "operator", "effective"),
            ),
            effective=shapes.SiteEffective(
                support_weight=weight_out(weights.of_site(site, figures))
            ),
            operator=marks.ref(site.operator_hid),
            region=shapes.PlaceRef(
                hid=site.region_hid,
                name=atlas.regions[site.region_hid].name,
                path=atlas.region_path(site.region_hid),
            ),
            path=atlas.site_path(site.hid),
            tags=labels[site.hid],
            locations=locations[site.hid],
        )
        for site in found
    ]


def locations_out(db: Session, found: list[Location]) -> list[shapes.LocationOut]:
    """Return locations, each with its site, what it is in, its path and what is in it."""
    atlas = geography.Atlas(db)
    atlas.take(found)
    atlas.read_locations(location.parent_location_hid for location in found)
    atlas.read_sites(location.site_hid for location in found)
    hids = [location.hid for location in found]
    labels = tags.labels_of(db, geography.LOCATION, hids)
    within = _live_counts(db, Location, Location.parent_location_hid, hids)
    placed = _live_counts(db, Item, Item.location_hid, hids)
    planned = _live_counts(db, Item, Item.planned_location_hid, hids)
    planned_groups = _live_counts(db, DeviceGroup, DeviceGroup.planned_location_hid, hids)
    marks = _Labels(db, {location.operator_hid for location in found})
    out = []
    for location in found:
        site = atlas.site(location.site_hid)
        parent = (
            atlas.location(location.parent_location_hid) if location.parent_location_hid else None
        )
        out.append(
            shapes.LocationOut(
                **_own(
                    location,
                    shapes.LocationOut,
                    (
                        "site",
                        "parent",
                        "path",
                        "depth",
                        "tags",
                        "locations",
                        "items",
                        "planned_items",
                        "planned_groups",
                        "operator",
                    ),
                ),
                planned_items=planned[location.hid],
                planned_groups=planned_groups[location.hid],
                operator=marks.ref(location.operator_hid),
                site=shapes.PlaceRef(
                    hid=location.site_hid,
                    name=site.name if site is not None else "",
                    path=atlas.site_path(location.site_hid),
                ),
                parent=None
                if parent is None
                else shapes.PlaceRef(
                    hid=parent.hid, name=parent.name, path=atlas.location_path(parent.hid)
                ),
                path=atlas.location_path(location.hid),
                depth=len(atlas.location_line(location.hid)) - 1,
                tags=labels[location.hid],
                locations=within[location.hid],
                items=placed[location.hid],
            )
        )
    return out


def place_out(db: Session, level: str, record: Any) -> Any:
    """Return one region, site or location."""
    if level == geography.REGION:
        return regions_out(db, [record])[0]
    if level == geography.SITE:
        return sites_out(db, [record])[0]
    return locations_out(db, [record])[0]


def contacts_out(db: Session, found: list[Contact]) -> list[shapes.ContactOut]:
    """Return contacts, each with its tags, the number of its assignments, and the user it
    is, where it is one (P-172)."""
    hids = [contact.hid for contact in found]
    labels = tags.labels_of(db, contacts.RECORD_TYPE, hids)
    uses = contacts.uses(db, hids)
    users = contacts.users_of(db, hids)
    return [
        shapes.ContactOut(
            **_own(contact, shapes.ContactOut, ("tags", "uses", "user", "is_user")),
            tags=labels[contact.hid],
            uses=uses[contact.hid],
            is_user=contact.hid in users,
            user=_user_brief(users.get(contact.hid)),
        )
        for contact in found
    ]


def assignments_out(db: Session, found: list[ContactAssignment]) -> list[shapes.AssignmentOut]:
    """Return contact assignments, each with its contact and its place."""
    atlas = geography.Atlas(db)
    atlas.read_sites(assignment.site_hid for assignment in found)
    atlas.read_locations(assignment.location_hid for assignment in found)
    people = _by_hid(db, Contact, {assignment.contact_hid for assignment in found})
    out = []
    for assignment in found:
        name, hid = contacts.place_of(assignment)
        level = contacts.PLACES[name]
        if level == geography.REGION:
            called, path = atlas.regions[hid].name, atlas.region_path(hid)
        elif level == geography.SITE:
            site = atlas.site(hid)
            called, path = (site.name if site is not None else ""), atlas.site_path(hid)
        else:
            location = atlas.location(hid)
            called = location.name if location is not None else ""
            path = atlas.location_path(hid)
        contact = people.get(assignment.contact_hid) if assignment.contact_hid else None
        out.append(
            shapes.AssignmentOut(
                **_own(assignment, shapes.AssignmentOut, ("contact", "place")),
                contact=None if contact is None else _contact_ref(contact),
                place=shapes.AssignedPlace.model_validate(
                    {"hid": hid, "name": called, "path": path, "level": level}
                ),
            )
        )
    return out


def effective_out(db: Session, found: geography.InForce) -> shapes.PlaceEffective:
    """Return what a place has in force."""
    looked_after = found.operator
    mark = _Labels(db, {looked_after.value}).ref(looked_after.value)
    return shapes.PlaceEffective.model_validate(
        {
            "level": found.level,
            "hid": found.hid,
            "path": found.path,
            "contacts": [
                {
                    "role": one.role,
                    "label": one.label,
                    "source": one.source,
                    "source_hid": one.source_hid,
                    "source_path": one.source_path,
                    "stopped": one.stopped,
                    "overrides_hid": one.overrides_hid,
                    "overrides_path": one.overrides_path,
                    "contacts": [
                        {
                            **_contact_ref(contact).model_dump(),
                            "assignment_hid": assignment.hid,
                            "contact_hid": contact.hid,
                            "priority": assignment.priority,
                        }
                        for assignment, contact in one.contacts
                    ],
                }
                for one in found.contacts
            ],
            "ship_address": found.ship_address,
            "ship_instructions": found.ship_instructions,
            "operator": {
                "value": mark,
                "source": looked_after.source,
                "source_hid": looked_after.source_hid,
                "source_path": looked_after.source_path,
                "overrides_hid": looked_after.overrides_hid,
                "overrides_path": looked_after.overrides_path,
            },
        }
    )


def entries_out(db: Session, entries: list[CatalogEntry]) -> list[shapes.CatalogEntryOut]:
    """Return catalog entries with their vendors, tags, the stack discount in force and
    how many items are of each."""
    vendors = _by_hid(db, Vendor, {entry.vendor_hid for entry in entries})
    labels = tags.labels_of(db, "catalog_entry", [entry.hid for entry in entries])
    counted = fields.model_items(db, [entry.hid for entry in entries])
    discount = Decimal(str(settings.value(db, "stack_discount_pct")))
    out = []
    for entry in entries:
        effective = inheritance.of_catalog_entry(entry, discount)
        out.append(
            shapes.CatalogEntryOut(
                **{
                    name: getattr(entry, name)
                    for name in shapes.CatalogEntryOut.model_fields
                    if name not in ("vendor", "tags", "items", "effective")
                },
                vendor=shapes.VendorRef(hid=entry.vendor_hid, name=vendors[entry.vendor_hid].name),
                tags=labels[entry.hid],
                items=counted[entry.hid],
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


def _replacement_refs(
    db: Session, hids: list[str]
) -> tuple[dict[str, shapes.ReplacementRef], dict[str, shapes.ReplacementRef]]:
    """Return, for each item, the item that took its place and the one whose place it took."""
    replaced_by, replaces = replacements.of_items(db, hids)
    others = _by_hid(
        db,
        Item,
        {found.new_item_hid for found in replaced_by.values()}
        | {found.old_item_hid for found in replaces.values()},
    )

    def ref(found: ItemReplacement, other_hid: str) -> shapes.ReplacementRef:
        other = others[other_hid]
        return shapes.ReplacementRef(
            hid=found.hid,
            item_hid=other_hid,
            name=other.name or other.hostname,
            serial_number=other.serial_number,
            reason=found.reason,
            reference=found.reference,
            replaced_on=found.replaced_on,
        )

    return (
        {hid: ref(found, found.new_item_hid) for hid, found in replaced_by.items()},
        {hid: ref(found, found.old_item_hid) for hid, found in replaces.items()},
    )


def _contract_refs(
    db: Session, found: list[Contract], today: date
) -> dict[str, shapes.ContractRef]:
    vendors = _by_hid(db, Vendor, {contract.vendor_hid for contract in found})
    return {
        # The statuses are read as the record has them, and checked against the shape's.
        contract.hid: shapes.ContractRef.model_validate(
            {
                "hid": contract.hid,
                "number": contracts.term(contract, today)["number"],
                "vendor": vendors[contract.vendor_hid].name,
                "status": contracts.status_of(contract, today),
                "record_status": contract.record_status,
            }
        )
        for contract in found
    }


def _cover(
    db: Session, item_hids: list[str], today: date
) -> dict[str, tuple[list[shapes.CoverageRef], date | None, int, list[shapes.ContractRef]]]:
    """Return the coverages of each item, the last day its cover runs to, how many
    contracts cover it today, and the contracts that would still count it once it is
    out of service."""
    found = contracts.of_items(db, item_hids)
    under = {contract.hid: contract for its in found.values() for _, contract in its}
    # Read once and held while the page is shaped, so that each period below finds the
    # agreement of its contract in the session and does not read it again.
    _held = _by_hid(db, Agreement, {contract.agreement_hid for contract in under.values()})
    refs = _contract_refs(db, list(under.values()), today)
    out: dict[str, tuple[list[shapes.CoverageRef], date | None, int, list[shapes.ContractRef]]]
    out = {}
    for hid, its in found.items():
        listed = []
        counting: dict[str, shapes.ContractRef] = {}
        for coverage, contract in its:
            if contracts.still_counts(coverage, contract, today):
                counting.setdefault(contract.hid, refs[contract.hid])
            span = contracts.span(coverage, contract, today)
            listed.append(
                shapes.CoverageRef(
                    hid=coverage.hid,
                    contract_hid=contract.hid,
                    contract=refs[contract.hid],
                    starts_on=span.starts_on,
                    ends_on=span.ends_on,
                    in_force=contracts.in_force(coverage, contract, today),
                    left_service=coverage.left_service,
                )
            )
        covering = {one.contract_hid for one in listed if one.in_force}
        ordered = sorted(counting.values(), key=lambda ref: (records.key(ref.number), ref.hid))
        out[hid] = (listed, contracts.covered_until(its, today), len(covering), ordered)
    return out


def _system_ref(system: ExternalSystem) -> shapes.SystemRef:
    return shapes.SystemRef(hid=system.hid, name=system.name, kind=system.kind)


def _registration_refs(
    db: Session, field: str, hids: list[str]
) -> dict[str, list[shapes.RegistrationRef]]:
    """Return the registrations of each item, or of each group, as its record lists them."""
    return {
        hid: [
            shapes.RegistrationRef.model_validate(
                {
                    "hid": registration.hid,
                    "system_hid": system.hid,
                    "system": _system_ref(system),
                    "external_id": registration.external_id,
                    "status": registration.status,
                    "confirmed_at": registration.confirmed_at,
                }
            )
            for registration, system in found
        ]
        for hid, found in systems.of_holders(db, field, hids).items()
    }


def _group_registration_refs(
    db: Session, item_hids: list[str]
) -> dict[str, list[shapes.GroupRegistrationRef]]:
    """Return what the stacks and the clusters of each item are registered with."""
    return {
        hid: [
            shapes.GroupRegistrationRef.model_validate(
                {
                    "hid": registration.hid,
                    "system_hid": system.hid,
                    "system": _system_ref(system),
                    "external_id": registration.external_id,
                    "status": registration.status,
                    "confirmed_at": registration.confirmed_at,
                    "group": _group_ref(group),
                }
            )
            for registration, system, group in found
        ]
        for hid, found in systems.of_groups_of_items(db, item_hids).items()
    }


def _line_refs(db: Session, hids: set[str | None]) -> dict[str, shapes.PurchaseLineRef]:
    """Return each purchase line as the item that arrived on it names it."""
    lines = _by_hid(db, PurchaseLine, hids)
    requests = _by_hid(db, PurchaseRequest, {line.request_hid for line in lines.values()})
    return {
        line.hid: shapes.PurchaseLineRef(
            hid=line.hid,
            name=purchases.line_name(requests[line.request_hid], line),
            request_hid=line.request_hid,
            reference=requests[line.request_hid].reference,
            line=line.line,
            catalog_entry_hid=line.catalog_entry_hid,
        )
        for line in lines.values()
    }


def items_out(db: Session, items: list[Item]) -> list[shapes.ItemOut]:
    """Return items with what they refer to and the values in force of what they inherit."""
    hids = [item.hid for item in items]
    lines = item_rules.lines_above(db, items)
    above = {one.hid: one for line in lines.values() for one in line}
    entries = _by_hid(db, CatalogEntry, {item.catalog_entry_hid for item in items})
    vendors = _by_hid(db, Vendor, {entry.vendor_hid for entry in entries.values()})
    owned = descent.of_items(db, items, lines, "owner_hid")
    owners = _by_hid(
        db,
        Owner,
        {item.owner_hid for item in items} | {one.value for one in owned.values()},
    )
    labels = tags.labels_of(db, "item", hids)
    looked_after = operators.of_items(db, items, lines)
    marks = _Labels(
        db, {item.operator_hid for item in items} | {one.value for one in looked_after.values()}
    )
    where = descent.of_items(db, items, lines, "location_hid")
    going = descent.of_items(db, items, lines, "planned_location_hid")
    holders = _holders(db, {**looked_after, **_keyed("w", where), **_keyed("g", going)}, above)
    places = location_refs(
        db,
        {item.location_hid for item in items}
        | {item.planned_location_hid for item in items}
        | {one.value for one in where.values()}
        | {one.value for one in going.values()},
    )
    parents = item_refs(db, [lines[item.hid][0] for item in items if lines[item.hid]])
    minor = _count_by(db, Item.parent_item_hid, hids)
    memberships = groups.memberships_of(db, hids)
    domains = sorted(
        {
            group.hid
            for listed in memberships.values()
            for member, group in listed
            if group.type == "controller_domain" and member.role == "endpoint"
        }
    )
    controllers = groups.controllers(db, domains)
    controller_refs = item_refs(
        db,
        list({item.hid: item for listed in controllers.values() for item, _ in listed}.values()),
    )
    its_addresses = _address_refs(db, "item_hid", hids)
    replaced_by, replaces = _replacement_refs(db, hids)
    today = contracts.today(db)
    cover = _cover(db, hids, today)
    registered = _registration_refs(db, "item_hid", hids)
    through_groups = _group_registration_refs(db, hids)
    # The circuits each is connected to (P-147).
    connected = circuit_shapes.connections_out(db, "item_hid", hids)
    arrived_on = _line_refs(db, {item.purchase_line_hid for item in items})
    figures = weights.in_force(db)
    out = []
    for item in items:
        entry = entries.get(item.catalog_entry_hid) if item.catalog_entry_hid else None
        owner = owners.get(item.owner_hid) if item.owner_hid else None
        line = lines[item.hid]
        effective = inheritance.of_item(item, entry, line)
        # The weight of one unit in force: for a major item, the default and the minimum.
        weight = weights.of_item(item, entry, figures, effective.pop("support_weight"))
        # Where it is, and where it is going: its own, or from the item or group above.
        effective["location_hid"] = where[item.hid]
        effective["owner_hid"] = owned[item.hid]
        owner_in_force = owners.get(effective["owner_hid"].value)
        its_groups = memberships[item.hid]
        its_controllers: dict[str, shapes.ControllerRef] = {}
        for member, group in its_groups:
            if group.hid in controllers and member.role == "endpoint":
                for controller, cluster in controllers[group.hid]:
                    its_controllers[controller.hid] = shapes.ControllerRef(
                        **controller_refs[controller.hid].model_dump(),
                        cluster_hid=cluster.hid if cluster is not None else None,
                        cluster=cluster.name if cluster is not None else None,
                    )
        out.append(
            shapes.ItemOut(
                **{
                    name: getattr(item, name)
                    for name in shapes.ItemOut.model_fields
                    if name not in _ITEM_SHAPED
                },
                catalog=None
                if entry is None
                else shapes.ItemCatalog(
                    hid=entry.hid,
                    vendor_hid=entry.vendor_hid,
                    vendor=vendors[entry.vendor_hid].name,
                    pid=entry.pid,
                    model_name=entry.model_name,
                    kind=entry.kind,
                    type=entry.type,
                    function=entry.function,
                    # The links of its model: an item has none of its own.
                    links=entry.links,
                ),
                owner=None if owner is None else _owner_ref(owner),
                **_exception(owner_in_force),
                location=places.get(item.location_hid) if item.location_hid else None,
                planned_location=places.get(item.planned_location_hid or ""),
                operator=marks.ref(item.operator_hid),
                parent=parents.get(item.parent_item_hid) if item.parent_item_hid else None,
                is_major=item.parent_item_hid is None,
                health=_health(
                    health.of_item(
                        item.condition, item.observed_status, effective["expected_online"].value
                    )
                ),
                depth=len(line),
                minor_items=minor[item.hid],
                groups=[
                    shapes.MembershipRef(
                        hid=member.hid,
                        group_hid=group.hid,
                        name=group.name,
                        type=group.type,
                        role=member.role,
                        position=member.position,
                        joined_on=member.joined_on,
                    )
                    for member, group in its_groups
                ],
                controllers=list(its_controllers.values()),
                addresses=its_addresses[item.hid],
                replaces=replaces.get(item.hid),
                replaced_by=replaced_by.get(item.hid),
                purchase_line=arrived_on.get(item.purchase_line_hid or ""),
                covered=cover[item.hid][2] > 0,
                covered_until=cover[item.hid][1],
                contract_count=cover[item.hid][2],
                coverage=cover[item.hid][0],
                out_of_service_contracts=cover[item.hid][3]
                if contracts.out_of_service(item.record_status, effective["lifecycle_state"].value)
                else [],
                purchase_line_mismatch=item.purchase_line_hid in arrived_on
                and purchases.of_another_model(
                    item.catalog_entry_hid, arrived_on[item.purchase_line_hid].catalog_entry_hid
                ),
                registrations=registered[item.hid],
                group_registrations=through_groups[item.hid],
                circuits=connected[item.hid],
                tags=labels[item.hid],
                effective=shapes.ItemEffective(
                    operator_hid=marks.in_force(looked_after[item.hid], holders),
                    owner_hid=shapes.EffectiveReference(
                        value=effective["owner_hid"].value,
                        label=owner_in_force.label if owner_in_force is not None else None,
                        source=effective["owner_hid"].source,
                        source_hid=effective["owner_hid"].source_hid,
                    ),
                    location_hid=_place_in_force(where[item.hid], places, holders),
                    planned_location_hid=_place_in_force(going[item.hid], places, holders),
                    support_weight=weight_out(weight),
                    **{
                        name: _effective(name, value)
                        for name, value in effective.items()
                        if name not in ("owner_hid", "location_hid")
                    },
                ),
            )
        )
    return out


_ITEM_SHAPED = (
    "health",
    "catalog",
    "owner",
    "owner_exception",
    "owner_exception_reason",
    "location",
    "planned_location",
    "operator",
    "parent",
    "is_major",
    "depth",
    "minor_items",
    "groups",
    "controllers",
    "addresses",
    "replaces",
    "replaced_by",
    "purchase_line",
    "purchase_line_mismatch",
    "covered",
    "covered_until",
    "contract_count",
    "coverage",
    "out_of_service_contracts",
    "registrations",
    "group_registrations",
    "circuits",
    "tags",
    "effective",
)


def item_out(db: Session, item: Item) -> shapes.ItemOut:
    """Return one item."""
    return items_out(db, [item])[0]


def replacement_out(db: Session, replacement: ItemReplacement) -> shapes.ReplacementOut:
    """Return a replacement with both of its items."""
    old, new = items_out(
        db, [db.get_one(Item, replacement.old_item_hid), db.get_one(Item, replacement.new_item_hid)]
    )
    return shapes.ReplacementOut(
        **{
            name: getattr(replacement, name)
            for name in shapes.ReplacementOut.model_fields
            if name not in ("old_item", "new_item")
        },
        old_item=old,
        new_item=new,
    )


def groups_out(db: Session, found: list[DeviceGroup]) -> list[shapes.DeviceGroupOut]:
    """Return device groups with their masters, their numbers of members and what they refer to."""
    hids = [group.hid for group in found]
    owned = descent.of_groups(db, found, "owner_hid")
    owners = _by_hid(
        db, Owner, {group.owner_hid for group in found} | {one.value for one in owned.values()}
    )
    parents = _by_hid(db, DeviceGroup, {group.parent_group_hid for group in found})
    nested: dict[str, list[shapes.DeviceGroupRef]] = {hid: [] for hid in hids}
    if hids:
        inside = db.scalars(
            select(DeviceGroup)
            .where(DeviceGroup.parent_group_hid.in_(hids), DeviceGroup.record_status != "retired")
            .order_by(DeviceGroup.name_key)
        )
        for group in inside:
            if group.parent_group_hid is not None:
                nested[group.parent_group_hid].append(_group_ref(group))
    counts = groups.member_counts(db, hids)
    registered = _registration_refs(db, "group_hid", hids)
    # The circuits each is connected to (P-147).
    connected = circuit_shapes.connections_out(db, "group_hid", hids)
    masters = groups.masters(db, [group.hid for group in found if group.type == "stack"])
    seen = groups.observed_masters(db, found)
    master_refs = item_refs(
        db, list({item.hid: item for item in (*masters.values(), *seen.values())}.values())
    )
    healths = groups.health_of(db, found)
    labels = tags.labels_of(db, groups.RECORD_TYPE, hids)
    its_addresses = _address_refs(db, "group_hid", hids)
    disagree = groups.members_disagree(db, found)
    looked_after = operators.of_groups(db, found)
    marks = _Labels(
        db, {group.operator_hid for group in found} | {one.value for one in looked_after.values()}
    )
    where = descent.of_groups(db, found, "location_hid")
    going = descent.of_groups(db, found, "planned_location_hid")
    holders = _holders(db, {**looked_after, **_keyed("w", where), **_keyed("g", going)}, {})
    places = location_refs(
        db,
        {group.location_hid for group in found}
        | {group.planned_location_hid for group in found}
        | {one.value for one in where.values()}
        | {one.value for one in going.values()},
    )
    out = []
    for group in found:
        owner = owners.get(group.owner_hid) if group.owner_hid else None
        owner_in_force = owners.get(owned[group.hid].value or "")
        parent = parents.get(group.parent_group_hid) if group.parent_group_hid else None
        master, observed = masters.get(group.hid), seen.get(group.hid)
        # Read from the master that is seen, and else from the one intended, each time
        # it is asked for, and stored nowhere.
        reported = observed or master
        its_health = healths[group.hid]
        out.append(
            shapes.DeviceGroupOut(
                **{
                    name: getattr(group, name)
                    for name in shapes.DeviceGroupOut.model_fields
                    if name not in _GROUP_SHAPED
                },
                parent=None if parent is None else _group_ref(parent),
                groups=nested[group.hid],
                owner=None if owner is None else _owner_ref(owner),
                **_exception(owner_in_force),
                location=places.get(group.location_hid) if group.location_hid else None,
                planned_location=places.get(group.planned_location_hid or ""),
                operator=marks.ref(group.operator_hid),
                effective=shapes.GroupEffective(
                    owner_hid=shapes.EffectiveReference(
                        value=owned[group.hid].value,
                        label=owner_in_force.label if owner_in_force is not None else None,
                        source=owned[group.hid].source,
                        source_hid=owned[group.hid].source_hid,
                    ),
                    operator_hid=marks.in_force(looked_after[group.hid], holders),
                    location_hid=_place_in_force(where[group.hid], places, holders),
                    planned_location_hid=_place_in_force(going[group.hid], places, holders),
                ),
                members_disagree=disagree[group.hid],
                health=_health(its_health) if its_health is not None else None,
                serial_number=reported.serial_number if reported is not None else None,
                serial_source=None
                if reported is None
                else ("observed" if observed is not None else "intended"),
                master=master_refs[master.hid] if master is not None else None,
                observed_master=master_refs[observed.hid] if observed is not None else None,
                master_as_intended=None
                if observed is None or master is None
                else observed.hid == master.hid,
                member_count=counts[group.hid],
                addresses=its_addresses[group.hid],
                registrations=registered[group.hid],
                circuits=connected[group.hid],
                tags=labels[group.hid],
            )
        )
    return out


_GROUP_SHAPED = (
    "health",
    "owner_exception",
    "owner_exception_reason",
    "location",
    "planned_location",
    "operator",
    "effective",
    "serial_source",
    "observed_master",
    "master_as_intended",
    "parent",
    "groups",
    "owner",
    "members_disagree",
    "serial_number",
    "master",
    "member_count",
    "addresses",
    "registrations",
    "circuits",
    "tags",
)


def group_out(db: Session, group: DeviceGroup) -> shapes.DeviceGroupOut:
    """Return one device group."""
    return groups_out(db, [group])[0]


def members_out(db: Session, members: list[DeviceGroupMember]) -> list[shapes.MemberOut]:
    """Return memberships, each with its item."""
    refs = item_refs(db, list(_by_hid(db, Item, {member.item_hid for member in members}).values()))
    return [
        shapes.MemberOut(
            **{
                name: getattr(member, name)
                for name in shapes.MemberOut.model_fields
                if name != "item"
            },
            item=refs[member.item_hid],
        )
        for member in members
    ]


def networks_out(db: Session, found: list[Network]) -> list[shapes.NetworkOut]:
    """Return networks, each with the number of addresses under it."""
    uses = addresses.uses(db, [network.hid for network in found])
    return [
        shapes.NetworkOut(
            **{
                name: getattr(network, name)
                for name in shapes.NetworkOut.model_fields
                if name != "uses"
            },
            uses=uses[network.hid],
        )
        for network in found
    ]


def addresses_out(db: Session, found: list[Address]) -> list[shapes.AddressOut]:
    """Return addresses, each with the item or the group that has it and its network."""
    refs = item_refs(db, list(_by_hid(db, Item, {address.item_hid for address in found}).values()))
    its_groups = _by_hid(db, DeviceGroup, {address.group_hid for address in found})
    networks = _by_hid(db, Network, {address.network_hid for address in found})
    out = []
    for address in found:
        network = networks.get(address.network_hid) if address.network_hid else None
        group = its_groups.get(address.group_hid) if address.group_hid else None
        out.append(
            shapes.AddressOut(
                **{
                    name: getattr(address, name)
                    for name in shapes.AddressOut.model_fields
                    if name not in ("item", "group", "network", "family")
                },
                family=addresses.family(address.address),
                item=refs.get(address.item_hid) if address.item_hid else None,
                group=None if group is None else _group_ref(group),
                network=None
                if network is None
                else shapes.NetworkRef(hid=network.hid, label=network.label),
            )
        )
    return out


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


# --- contracts and coverage ----------------------------------------------------------


def _vendor_ref(vendor: Vendor) -> shapes.VendorRef:
    return shapes.VendorRef(hid=vendor.hid, name=vendor.name)


def _next_term(record: Any, today: date) -> shapes.NextTerm | None:
    waiting = contracts.pending_term(record, today)
    return None if waiting is None else shapes.NextTerm.model_validate(waiting)


# --- the contacts of agreements and contracts ----------------------------------------


def contract_contact_out(named: contract_contacts.Named) -> shapes.ContractContactOut:
    """Return one naming of a contact for an agreement or a contract, with the contact
    as its record is now."""
    link, contact = named
    return shapes.ContractContactOut(
        **_own(link, shapes.ContractContactOut, ("contact",)), contact=_contact_ref(contact)
    )


def contract_contacts_out(db: Session, field: str, hid: str) -> list[shapes.ContractContactOut]:
    """Return what one agreement or contract names, by role and then by priority."""
    return [contract_contact_out(one) for one in contract_contacts.named_by(db, field, [hid])[hid]]


def _contacts_in_force(
    found: dict[str, contract_contacts.InForce],
) -> dict[str, shapes.EffectiveContacts]:
    """Return the contacts in force of a record, each role under its name in `effective`."""
    return {
        contract_contacts.IN_FORCE[role]: shapes.EffectiveContacts(
            value=[contract_contact_out(one) for one in its.named],
            source=its.source,
            source_hid=its.source_hid,
        )
        for role, its in found.items()
    }


# --- the contacts of carriers and of circuits (P-149) --------------------------------


def vendor_contact_out(named: tuple[VendorContact, Contact]) -> shapes.VendorContactOut:
    """Return one naming of a contact for a vendor, with the contact as its record is now."""
    link, contact = named
    return shapes.VendorContactOut(
        **_own(link, shapes.VendorContactOut, ("contact",)), contact=_contact_ref(contact)
    )


def vendor_contacts_out(db: Session, hid: str) -> list[shapes.VendorContactOut]:
    """Return what one vendor names, by role and then by priority."""
    return [vendor_contact_out(one) for one in carrier_contacts.named_by_vendors(db, [hid])[hid]]


def circuit_contact_out(named: tuple[CircuitContact, Contact]) -> shapes.CircuitContactOut:
    """Return one naming of a contact for a circuit, with the contact as its record is now."""
    link, contact = named
    return shapes.CircuitContactOut(
        **_own(link, shapes.CircuitContactOut, ("contact",)), contact=_contact_ref(contact)
    )


def circuit_contacts_out(db: Session, hid: str) -> list[shapes.CircuitContactOut]:
    """Return what one circuit names of its own: the carrier's first, then each side's."""
    return [circuit_contact_out(one) for one in carrier_contacts.named_by_circuits(db, [hid])[hid]]


def _named_contacts(named: list[carrier_contacts.Naming]) -> list[shapes.NamedContact]:
    return [
        shapes.NamedContact(
            hid=one.hid,
            role=one.role,
            priority=one.priority,
            contact_hid=one.contact.hid,
            contact=_contact_ref(one.contact),
        )
        for one in named
    ]


def _contacts_of_circuit(found: carrier_contacts.OfCircuit) -> shapes.CircuitContactsEffective:
    carrier = {
        carrier_contacts.IN_FORCE[role]: shapes.CarrierContacts(
            value=_named_contacts(its.named), source=its.source, source_hid=its.source_hid
        )
        for role, its in found.carrier.items()
    }
    sites = {
        side: [
            shapes.SiteRoleContacts(
                role=one.role,
                value=_named_contacts(one.named),
                source=one.source,
                source_hid=one.source_hid,
            )
            for one in listed
        ]
        for side, listed in found.sites.items()
    }
    return shapes.CircuitContactsEffective(
        account_managers=carrier["account_managers"],
        support_contacts=carrier["support_contacts"],
        site_contacts=shapes.SiteContacts(a=sites["a"], z=sites["z"]),
    )


def circuits_contacts(
    db: Session, found: list[Circuit]
) -> dict[str, tuple[list[shapes.CircuitContactOut], shapes.CircuitContactsEffective]]:
    """Return, for each circuit by its HID, the contacts it names of its own, for its
    `contacts`, and those it has in force, for its `effective` block:
    `account_managers`, `support_contacts` and `site_contacts`.

    The circuits are read together, so that a page of them costs a handful of
    statements, as one circuit does. Nothing is copied: each contact is as its record
    is now.
    """
    held = carrier_contacts.of_circuits(db, found)
    return {
        hid: ([circuit_contact_out(one) for one in its.own], _contacts_of_circuit(its))
        for hid, its in held.items()
    }


def agreements_out(db: Session, found: list[Agreement]) -> list[shapes.AgreementOut]:
    """Return agreements, each with its term in force, its vendor, its tags and how
    many contracts it groups."""
    hids = [agreement.hid for agreement in found]
    vendors = _by_hid(
        db, Vendor, {one.vendor_hid for one in found} | {one.reseller_hid for one in found}
    )
    labels = tags.labels_of(db, contracts.AGREEMENT_TYPE, hids)
    grouped = contracts.contracts_in(db, hids)
    named, in_force = contract_contacts.of_agreements(db, hids)
    today = contracts.today(db)
    review = _members_to_review(db, hids, today)
    shaped = (
        *contracts.TERM,
        "status",
        "row_version",
        "vendor",
        "reseller",
        "tags",
        "lapsed",
        "next_term",
        "contracts",
        "contacts",
        "effective",
        "members_to_review",
    )
    out = []
    for agreement in found:
        its = contracts.term(agreement, today)
        out.append(
            # The status is read as the record has it, and checked against the shape's.
            shapes.AgreementOut.model_validate(
                {
                    **_own(agreement, shapes.AgreementOut, shaped),
                    **its,
                    "status": contracts.status_of(agreement, today),
                    "row_version": contracts.version(agreement, today),
                    "vendor": _vendor_ref(vendors[agreement.vendor_hid]),
                    "reseller": _vendor_ref(vendors[agreement.reseller_hid])
                    if agreement.reseller_hid
                    else None,
                    "tags": labels[agreement.hid],
                    "lapsed": contracts.lapsed(agreement, its["ends_on"], today),
                    "next_term": _next_term(agreement, today),
                    "contracts": grouped[agreement.hid],
                    "contacts": [contract_contact_out(one) for one in named[agreement.hid]],
                    "effective": shapes.AgreementEffective(
                        **_contacts_in_force(in_force[agreement.hid])
                    ),
                    "members_to_review": review.get(agreement.hid, []),
                }
            )
        )
    return out


def _members_to_review(
    db: Session, agreement_hids: list[str], today: date
) -> dict[str, list[shapes.ContractRef]]:
    """Return, for each agreement, its members that a person must look at (D-180)."""
    if not agreement_hids:
        return {}
    found = list(
        db.scalars(
            select(Contract)
            .where(Contract.agreement_hid.in_(agreement_hids), contracts.to_review_value())
            .order_by(Contract.number_key, Contract.hid)
        )
    )
    refs = _contract_refs(db, found, today)
    review: dict[str, list[shapes.ContractRef]] = {}
    for contract in found:
        review.setdefault(contract.agreement_hid or "", []).append(refs[contract.hid])
    return review


def contracts_out(db: Session, found: list[Contract]) -> list[shapes.ContractOut]:
    """Return contracts, each with its term in force, its vendor, its agreement, what
    it has in force from there, its tags and how many items it covers."""
    hids = [contract.hid for contract in found]
    today = contracts.today(db)
    in_force = {contract.hid: contracts.effective(contract, today) for contract in found}
    above = {contract.hid: contracts.agreement_gives(contract, today) for contract in found}
    vendors = _by_hid(
        db,
        Vendor,
        {contract.vendor_hid for contract in found}
        | {contract.reseller_hid for contract in found}
        | {its["reseller_hid"].value for its in in_force.values()}
        | {gives["reseller_hid"] for gives in above.values()},
    )
    labels = tags.labels_of(db, contracts.RECORD_TYPE, hids)
    covered = fields.covered_items(db, hids)
    scope = contracts.in_scope(db, hids)
    overdue_after = contracts.overdue_after(db)
    named, people_in_force = contract_contacts.of_contracts(db, found)
    shaped = (
        *contracts.TERM,
        "status",
        "row_version",
        "vendor",
        "agreement",
        "contacts",
        "effective",
        "reseller",
        "tags",
        "covers_today",
        "lapsed",
        "next_term",
        "covered_items",
        "items_in_scope",
        "renewal_pending_days",
        "renewal_overdue",
        "part_began_on",
        "part_began_by",
    )
    out = []
    for contract in found:
        its = in_force[contract.hid]
        gives = above[contract.hid]
        within = contracts.agreement_of(contract)
        through = vendors.get(its["reseller_hid"].value or "")
        theirs = vendors.get(gives["reseller_hid"] or "")
        out.append(
            shapes.ContractOut.model_validate(
                {
                    **_own(contract, shapes.ContractOut, shaped),
                    **contracts.term(contract, today),
                    "status": contracts.status_of(contract, today),
                    "row_version": contracts.version(contract, today),
                    "vendor": _vendor_ref(vendors[contract.vendor_hid]),
                    "agreement": None
                    if within is None
                    else shapes.AgreementRef(
                        hid=within.hid,
                        name=within.name,
                        number=contracts.term(within, today)["number"],
                    ),
                    "effective": shapes.ContractEffective(
                        reseller_hid=shapes.ContractEffectiveReference(
                            value=its["reseller_hid"].value,
                            label=through.name if through is not None else None,
                            source=its["reseller_hid"].source,
                            source_hid=its["reseller_hid"].source_hid,
                            from_agreement=gives["reseller_hid"],
                            from_agreement_label=theirs.name if theirs is not None else None,
                        ),
                        **{
                            name: shapes.ContractEffectiveValue(
                                value=_shown(name, value.value),
                                source=value.source,
                                source_hid=value.source_hid,
                                from_agreement=_text(name, gives[name]),
                            )
                            for name, value in its.items()
                            if name != "reseller_hid"
                        },
                        **_contacts_in_force(people_in_force[contract.hid]),
                    ),
                    "contacts": [contract_contact_out(one) for one in named[contract.hid]],
                    "reseller": _vendor_ref(vendors[contract.reseller_hid])
                    if contract.reseller_hid
                    else None,
                    "tags": labels[contract.hid],
                    "covers_today": contracts.covers(contract, today),
                    "lapsed": contracts.lapsed(
                        contract, contracts.period(contract, today).ends_on, today
                    ),
                    "next_term": _next_term(contract, today),
                    "covered_items": covered[contract.hid],
                    "items_in_scope": scope[contract.hid],
                    "renewal_pending_days": contracts.renewal_pending_days(contract, today),
                    "renewal_overdue": contracts.renewal_overdue(contract, today, overdue_after),
                }
            )
        )
    return out


def contract_out(db: Session, contract: Contract) -> shapes.ContractOut:
    """Return one contract, with when the present part of its history began."""
    out = contracts_out(db, [contract])[0]
    present = contracts.history(db, contract)
    out.part_began_on, out.part_began_by = present.began_on, present.began_by
    return out


def _term(term: contracts.Term, users: dict[str, Any]) -> dict[str, Any]:
    return {
        "number": term.number,
        "starts_on": term.starts_on,
        "ends_on": term.ends_on,
        "annual_cost": term.annual_cost,
        "purchase_reference": term.purchase_reference,
        "renewed_at": term.renewed_at,
        "renewed_by": term.renewed_by,
        "renewed_by_name": users[term.renewed_by].username if term.renewed_by in users else None,
        "began_on": term.began_on,
        "ended_on": term.ended_on,
        "began_by": term.began_by,
    }


def terms_out(db: Session, contract: Contract) -> list[shapes.ContractTerm]:
    """Return the terms a contract had before, each with who renewed it and the dates it
    had in force, with where each came from."""
    found = contracts.terms(db, contract)
    users = _by_hid(db, User, {term.renewed_by for term in found})
    return [
        shapes.ContractTerm(
            **_term(term, users),
            starts_on_source=term.starts_on_source,
            ends_on_source=term.ends_on_source,
            agreement_hid=term.agreement_hid,
        )
        for term in found
    ]


def agreement_terms_out(db: Session, agreement: Agreement) -> list[shapes.AgreementTerm]:
    """Return the terms an agreement had before, each with who renewed it."""
    found = contracts.terms(db, agreement, contracts.AGREEMENT_TYPE)
    users = _by_hid(db, User, {term.renewed_by for term in found})
    return [shapes.AgreementTerm(**_term(term, users)) for term in found]


def coverage_out(db: Session, found: list[ContractCoverage]) -> list[shapes.CoverageOut]:
    """Return coverages, each with its contract, its item and the days in force."""
    held = _by_hid(db, Contract, {coverage.contract_hid for coverage in found})
    today = contracts.today(db)
    refs = _contract_refs(db, list(held.values()), today)
    items = _by_hid(db, Item, {coverage.item_hid for coverage in found})
    named = item_refs(db, list(items.values()))
    out = []
    for coverage in found:
        contract, item = held[coverage.contract_hid], items[coverage.item_hid]
        span = contracts.span(coverage, contract, today)
        out.append(
            shapes.CoverageOut(
                **_own(
                    coverage,
                    shapes.CoverageOut,
                    (
                        "contract",
                        "item",
                        "item_lifecycle_state",
                        "item_record_status",
                        "effective_starts_on",
                        "effective_ends_on",
                        "in_force",
                    ),
                ),
                contract=refs[contract.hid],
                item=named[item.hid],
                item_lifecycle_state=item.lifecycle_state,
                item_record_status=item.record_status,
                effective_starts_on=span.starts_on,
                effective_ends_on=span.ends_on,
                in_force=contracts.in_force(coverage, contract, today),
            )
        )
    return out


# --- purchases -----------------------------------------------------------------------


def _catalog_refs(db: Session, hids: set[str | None]) -> dict[str, shapes.CatalogRef]:
    entries = _by_hid(db, CatalogEntry, hids)
    vendors = _by_hid(db, Vendor, {entry.vendor_hid for entry in entries.values()})
    return {
        entry.hid: shapes.CatalogRef(
            hid=entry.hid,
            vendor_hid=entry.vendor_hid,
            vendor=vendors[entry.vendor_hid].name,
            pid=entry.pid,
            model_name=entry.model_name,
            kind=entry.kind,
            type=entry.type,
            function=entry.function,
        )
        for entry in entries.values()
    }


def _site_refs(db: Session, hids: set[str | None]) -> dict[str, shapes.PlaceRef]:
    atlas = geography.Atlas(db)
    wanted = sorted(hid for hid in hids if hid)
    atlas.read_sites(wanted)
    refs = {}
    for hid in wanted:
        site = atlas.site(hid)
        if site is not None:
            refs[hid] = shapes.PlaceRef(hid=hid, name=site.name, path=atlas.site_path(hid))
    return refs


def _region_refs(db: Session, hids: set[str | None]) -> dict[str, shapes.PlaceRef]:
    atlas = geography.Atlas(db)
    return {
        hid: shapes.PlaceRef(hid=hid, name=atlas.regions[hid].name, path=atlas.region_path(hid))
        for hid in hids
        if hid and hid in atlas.regions
    }


def lines_out(db: Session, found: list[PurchaseLine]) -> list[shapes.PurchaseLineOut]:
    """Return purchase lines, each with its model and what has arrived on it."""
    requests = _by_hid(db, PurchaseRequest, {line.request_hid for line in found})
    models = _catalog_refs(db, {line.catalog_entry_hid for line in found})
    sites = _site_refs(db, {line.destination_site_hid for line in found})
    arrived = purchases.received(db, [line.hid for line in found])
    astray = fields.mismatched_items(db, [line.hid for line in found])
    shaped = (
        "reference",
        "request_status",
        "name",
        "catalog",
        "tracked",
        "received_quantity",
        "pending_quantity",
        "mismatched_items",
        "destination_site",
    )
    out = []
    for line in found:
        request = requests[line.request_hid]
        out.append(
            shapes.PurchaseLineOut(
                **_own(line, shapes.PurchaseLineOut, shaped),
                reference=request.reference,
                request_status=request.status,
                name=purchases.line_name(request, line),
                catalog=models.get(line.catalog_entry_hid or ""),
                tracked=purchases.tracked(line),
                received_quantity=arrived[line.hid],
                pending_quantity=purchases.pending(line, arrived[line.hid]),
                mismatched_items=astray[line.hid],
                destination_site=sites.get(line.destination_site_hid or ""),
            )
        )
    return out


def received_out(db: Session, line: PurchaseLine, made: list[Item]) -> shapes.ReceivedOut:
    """Return a line after a receipt, with the items the receipt created."""
    refs = item_refs(db, made)
    return shapes.ReceivedOut(
        **lines_out(db, [line])[0].model_dump(), items=[refs[item.hid] for item in made]
    )


def requests_out(db: Session, found: list[PurchaseRequest]) -> list[shapes.PurchaseRequestOut]:
    """Return purchase requests, each with its lines and what is still to come."""
    its_lines = purchases.lines_of(db, [request.hid for request in found])
    shaped = lines_out(db, [line for lines in its_lines.values() for line in lines])
    by_request: dict[str, list[shapes.PurchaseLineOut]] = {request.hid: [] for request in found}
    for line in shaped:
        by_request[line.request_hid].append(line)
    out = []
    for request in found:
        lines = by_request[request.hid]
        # What is not tracked is in no count (D-172).
        counted = [line for line in lines if line.tracked]
        out.append(
            shapes.PurchaseRequestOut(
                **_own(
                    request,
                    shapes.PurchaseRequestOut,
                    ("lines", "quantity", "received_quantity", "pending_quantity"),
                ),
                lines=lines,
                quantity=sum(line.quantity for line in counted),
                received_quantity=sum(line.received_quantity for line in counted),
                pending_quantity=sum(line.pending_quantity for line in counted),
            )
        )
    return out


# --- external systems ----------------------------------------------------------------


def systems_out(db: Session, found: list[ExternalSystem]) -> list[shapes.ExternalSystemOut]:
    """Return external systems, each with how many records are registered with it."""
    counts = fields.registered(db, [system.hid for system in found])
    return [
        shapes.ExternalSystemOut(
            **_own(system, shapes.ExternalSystemOut, ("registrations",)),
            registrations=counts[system.hid],
        )
        for system in found
    ]


def registrations_out(db: Session, found: list[Registration]) -> list[shapes.RegistrationOut]:
    """Return registrations, each with its system and the item or the group it is of."""
    held = _by_hid(db, ExternalSystem, {registration.system_hid for registration in found})
    items = item_refs(
        db, list(_by_hid(db, Item, {registration.item_hid for registration in found}).values())
    )
    its_groups = _by_hid(db, DeviceGroup, {registration.group_hid for registration in found})
    return [
        shapes.RegistrationOut(
            **_own(registration, shapes.RegistrationOut, ("system", "item", "group")),
            system=_system_ref(held[registration.system_hid]),
            item=items.get(registration.item_hid or ""),
            group=_group_ref(its_groups[registration.group_hid])
            if registration.group_hid
            else None,
        )
        for registration in found
    ]


# --- capacity ------------------------------------------------------------------------


def capacity_lines_out(db: Session, found: list[CapacityLine]) -> list[shapes.CapacityLineOut]:
    """Return capacity lines, each with its units and what it refers to."""
    vendors = _by_hid(db, Vendor, {line.vendor_hid for line in found})
    regions = _region_refs(db, {line.region_hid for line in found})
    sites = _site_refs(db, {line.site_hid for line in found})
    called = {one.value: one.label for one in choices.list_choices(db, capacity.CATEGORY_LIST)}
    today = contracts.today(db)
    targets = capacity.targets_of(db, [line.hid for line in found if capacity.multiplies(line)])
    named = _by_hid(db, CapacityLine, {hid for hids in targets.values() for hid in hids})
    shaped = ("category_label", "units", "applies_to", "vendor", "region", "site", "in_date")
    return [
        shapes.CapacityLineOut(
            **_own(line, shapes.CapacityLineOut, shaped),
            category_label=called.get(line.category, line.category),
            units=None if capacity.multiplies(line) else capacity.units(line),
            applies_to=sorted(
                (
                    shapes.CapacityLineRef(hid=hid, name=named[hid].name)
                    for hid in targets.get(line.hid, [])
                ),
                key=lambda ref: records.key(ref.name),
            ),
            vendor=_vendor_ref(vendors[line.vendor_hid]) if line.vendor_hid else None,
            region=regions.get(line.region_hid or ""),
            site=sites.get(line.site_hid or ""),
            in_date=capacity.in_date(line, today),
        )
        for line in found
    ]


def capacity_out(found: balance.Balance) -> shapes.CapacityOut:
    """Return the capacity balance."""
    return shapes.CapacityOut.model_validate(found)


def capacity_try_out(found: tried.Answer) -> shapes.CapacityTryOut:
    """Return the capacity balance in force beside the one tried, and what was tried."""
    return shapes.CapacityTryOut.model_validate(found)


def capacity_records_out(found: list[CapacityRecord]) -> list[shapes.CapacityRecordOut]:
    """Return records of the balance, with the balance and the coverage of each view
    worked out from its demand and its supply."""
    return [
        shapes.CapacityRecordOut(
            **_own(record, shapes.CapacityRecordOut, capacity.VIEWS),
            **{
                view: shapes.CapacityRecordView.model_validate(
                    capacity.figures(getattr(record, view))
                )
                for view in capacity.VIEWS
            },
        )
        for record in found
    ]


# --- the reports that look ahead -----------------------------------------------------


def _sections(found: dict[str, planning.Section]) -> dict[str, shapes.ReportSection]:
    return {name: shapes.ReportSection.model_validate(one) for name, one in found.items()}


def _page_of(db: Session, page: planning.Page) -> dict[str, Any]:
    return {
        "section": page.section,
        "items": items_out(db, page.items),
        "total": page.total,
        "limit": page.limit,
        "offset": page.offset,
    }


def coverage_report_out(db: Session, found: planning.Coverage) -> shapes.CoverageReport:
    """Return the coverage report, with the items of the section that was asked for."""
    return shapes.CoverageReport.model_validate(
        {
            "as_of": found.as_of,
            "within_days": found.within_days,
            "service_states": found.service_states,
            "totals": shapes.CoverageTotals.model_validate(found.totals),
            "sections": {
                name: shapes.CoverageReportSection.model_validate(
                    {
                        **shapes.ReportSection.model_validate(one).model_dump(),
                        # What is not renewed, counted by model.
                        "by_model": [
                            shapes.NotRenewedModel.model_validate(model) for model in found.by_model
                        ]
                        if name == "not_renewed"
                        else None,
                    }
                )
                for name, one in found.sections.items()
            },
            "lapsed_contracts": shapes.LapsedContracts.model_validate(found.lapsed_contracts),
            **_page_of(db, found.page),
        }
    )


def renewals_report_out(db: Session, found: planning.Renewals) -> shapes.RenewalsReport:
    """Return the renewal worklist, with the rows of the list that was asked for."""
    page = found.page
    of_items = page.section == "overlapping"
    return shapes.RenewalsReport.model_validate(
        {
            "as_of": found.as_of,
            "within_days": found.within_days,
            "overdue_after": found.overdue_after,
            "totals": shapes.RenewalTotals.model_validate(found.totals),
            "sections": _sections(found.sections),
            "agreements": _sections(found.agreements),
            "groups": [
                shapes.RenewalGroup.model_validate(
                    {**group.__dict__, "counts": shapes.RenewalTotals.model_validate(group.counts)}
                )
                for group in found.groups
            ],
            "section": page.section,
            "contracts": [] if of_items or page.section is None else contracts_out(db, page.items),
            "items": items_out(db, page.items) if of_items else [],
            "total": page.total,
            "limit": page.limit,
            "offset": page.offset,
        }
    )


def renewal_alert_out(found: alerts.Alert) -> shapes.RenewalAlert:
    """Return the renewal alert for one person."""
    summary = found.summary
    return shapes.RenewalAlert.model_validate(
        {
            "as_of": summary.as_of,
            "within_days": summary.within_days,
            "overdue_after": summary.overdue_after,
            "show": found.show,
            "version": summary.version,
            "overdue": summary.overdue,
            **{
                name: {"count": len(hids), "new": found.new[name], "section": name}
                for name, hids in summary.lists.items()
            },
            "agreements": {name: len(hids) for name, hids in summary.agreements.items()},
        }
    )


def end_of_life_out(db: Session, found: planning.EndOfLife) -> shapes.EndOfLifeReport:
    """Return the end-of-life report, with the items of the section that was asked for."""
    return shapes.EndOfLifeReport.model_validate(
        {
            "as_of": found.as_of,
            "within_days": found.within_days,
            "date": found.date,
            "dates": {
                name: shapes.PastAndApproaching.model_validate(one)
                for name, one in found.dates.items()
            },
            "by_fiscal_year": [
                shapes.FiscalYearCount.model_validate(year) for year in found.by_fiscal_year
            ],
            "sections": _sections(found.sections),
            **_page_of(db, found.page),
        }
    )


def replacement_rows_out(db: Session, found: list[ItemReplacement]) -> list[shapes.ReplacementRow]:
    """Return replacements as rows of the report, each item as another record names it."""
    held = _by_hid(
        db,
        Item,
        {one.old_item_hid for one in found} | {one.new_item_hid for one in found},
    )
    refs = item_refs(db, list(held.values()))
    called = {one.value: one.label for one in choices.list_choices(db, "replacement_reason")}
    return [
        shapes.ReplacementRow(
            **_own(one, shapes.ReplacementRow, ("old_item", "new_item", "reason_label")),
            old_item=refs[one.old_item_hid],
            new_item=refs[one.new_item_hid],
            reason_label=called.get(one.reason, one.reason),
        )
        for one in found
    ]


def portfolio_out(db: Session, found: planning.Portfolio) -> shapes.PortfolioOut:
    """Return the portfolio of a vendor."""
    measured = tuple(shapes.PortfolioMeasures.model_fields)

    def measures(one: Any) -> dict[str, Any]:
        return {name: getattr(one, name) for name in measured}

    return shapes.PortfolioOut(
        vendor=_vendor_ref(found.vendor),
        as_of=found.as_of,
        totals=shapes.PortfolioMeasures(**measures(found.totals)),
        kinds=[shapes.PortfolioKind(**measures(one), kind=one.kind) for one in found.kinds],
        models=[
            shapes.PortfolioModel(
                **measures(one),
                catalog_entry_hid=one.entry.hid,
                pid=one.entry.pid,
                model_name=one.entry.model_name,
                kind=one.entry.kind,
                type=one.entry.type,
                function=one.entry.function,
                end_of_sale=one.entry.end_of_sale,
                end_of_sw_support=one.entry.end_of_sw_support,
                end_of_hw_support=one.entry.end_of_hw_support,
                ldos=one.entry.ldos,
                covered_until=one.covered_until,
            )
            for one in found.models
        ],
        agreements=agreements_out(db, found.agreements),
        contracts=contracts_out(db, found.contracts),
        capacity_lines=capacity_lines_out(db, found.capacity_lines),
        filter=found.filter,
    )


def contract_refs(db: Session, hids: list[str]) -> list[shapes.ContractRef]:
    """Return contracts as other records name them, in the order given."""
    found = {one.hid: one for one in db.scalars(select(Contract).where(Contract.hid.in_(hids)))}
    refs = _contract_refs(db, list(found.values()), contracts.today(db))
    return [refs[hid] for hid in hids if hid in refs]


def _walk_value(name: str, value: Any) -> Any:
    return (
        records.jsonable(value, name)
        if value is not None and not isinstance(value, bool)
        else value
    )


def resolution_out(hid: str, walks: list[resolution.Walk]) -> shapes.Resolution:
    """Return the walk of each value of a record (P-176)."""
    return shapes.Resolution(
        hid=hid,
        fields=[
            shapes.ResolutionField(
                field=walk.field,
                value=_walk_value(walk.field, walk.value),
                label=walk.label,
                source=walk.source,
                source_hid=walk.source_hid,
                overrides=_walk_value(walk.field, walk.overrides),
                overrides_label=walk.overrides_label,
                steps=[
                    shapes.ResolutionStep(
                        level=step.level,
                        hid=step.hid,
                        name=step.name,
                        type=step.type,
                        rank=step.rank,
                        via_hid=step.via_hid,
                        via_name=step.via_name,
                        value=_walk_value(walk.field, step.value),
                        label=step.label,
                        outcome=step.outcome,
                    )
                    for step in walk.steps
                ],
            )
            for walk in walks
        ],
    )


def _count(found: operated.Count) -> shapes.ItemCount:
    return shapes.ItemCount(count=found.count, filter=found.filter)


def operated_out(found: operated.Operated) -> shapes.OperatorAssignments:
    """Return what an operator is on, and how (P-177)."""
    return shapes.OperatorAssignments(
        operator_hid=found.operator_hid,
        places=[
            shapes.OperatorPlace.model_validate(
                {
                    "hid": box.hid,
                    "level": box.level,
                    "path": box.path,
                    "items": _count(box.items),
                    "places_beneath": {
                        "count": box.beneath.count,
                        "more": box.beneath.more,
                        "shown": box.beneath.shown,
                    },
                    "exceptions": _count(box.exceptions),
                }
            )
            for box in found.places
        ],
        groups=[
            shapes.OperatorGroup.model_validate(
                {
                    "hid": box.hid,
                    "name": box.name,
                    "type": box.type,
                    "items": _count(box.items),
                    "groups_beneath": {
                        "count": box.beneath.count,
                        "more": box.beneath.more,
                        "shown": box.beneath.shown,
                    },
                    "exceptions": _count(box.exceptions),
                }
            )
            for box in found.groups
        ],
        own=_count(found.own),
        from_item=_count(found.from_item),
        totals=_count(found.totals),
    )
