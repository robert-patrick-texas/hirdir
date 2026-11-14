"""Turning the inventory's records into the shapes the API returns.

A page of a list is shaped together, so that the catalog entries, vendors, owners and
tags its rows refer to are each read once for the page and not once for each row.
"""

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hirdir.api import records as shapes
from hirdir.db.models import (
    Address,
    CatalogEntry,
    Choice,
    DeviceGroup,
    DeviceGroupMember,
    ImportJob,
    ImportRow,
    Item,
    ItemReplacement,
    LifecycleRule,
    Network,
    Owner,
    Tag,
    User,
    Vendor,
)
from hirdir.domain import (
    addresses,
    groups,
    health,
    inheritance,
    records,
    replacements,
    settings,
    tags,
)
from hirdir.domain import items as item_rules
from hirdir.domain.inheritance import Effective
from hirdir.domain.settings import SettingValue
from hirdir.io import imports

FIRST_ROWS = 100


def _by_hid(db: Session, model: Any, hids: set[str | None]) -> dict[str, Any]:
    wanted = {hid for hid in hids if hid}
    if not wanted:
        return {}
    return {record.hid: record for record in db.scalars(select(model).where(model.hid.in_(wanted)))}


def _effective(name: str, effective: Effective) -> shapes.EffectiveValue:
    value = effective.value
    shown: str | bool | None
    if isinstance(value, Decimal):
        shown = records.decimal_text(name, value)
    elif isinstance(value, date):
        shown = value.isoformat()
    elif isinstance(value, str | bool):
        shown = value
    else:
        shown = None
    return shapes.EffectiveValue(
        value=shown, source=effective.source, source_hid=effective.source_hid
    )


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


def vendor_out(vendor: Vendor) -> shapes.VendorOut:
    """Return a vendor."""
    return shapes.VendorOut.model_validate(vendor)


def owner_out(owner: Owner) -> shapes.OwnerOut:
    """Return an owner."""
    return shapes.OwnerOut.model_validate(owner)


def entries_out(db: Session, entries: list[CatalogEntry]) -> list[shapes.CatalogEntryOut]:
    """Return catalog entries with their vendors, tags and the stack discount in force."""
    vendors = _by_hid(db, Vendor, {entry.vendor_hid for entry in entries})
    labels = tags.labels_of(db, "catalog_entry", [entry.hid for entry in entries])
    discount = Decimal(str(settings.value(db, "stack_discount_pct")))
    out = []
    for entry in entries:
        effective = inheritance.of_catalog_entry(entry, discount)
        out.append(
            shapes.CatalogEntryOut(
                **{
                    name: getattr(entry, name)
                    for name in shapes.CatalogEntryOut.model_fields
                    if name not in ("vendor", "tags", "effective")
                },
                vendor=shapes.VendorRef(hid=entry.vendor_hid, name=vendors[entry.vendor_hid].name),
                tags=labels[entry.hid],
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


def items_out(db: Session, items: list[Item]) -> list[shapes.ItemOut]:
    """Return items with what they refer to and the values in force of what they inherit."""
    hids = [item.hid for item in items]
    lines = item_rules.lines_above(db, items)
    above = {one.hid: one for line in lines.values() for one in line}
    entries = _by_hid(db, CatalogEntry, {item.catalog_entry_hid for item in items})
    vendors = _by_hid(db, Vendor, {entry.vendor_hid for entry in entries.values()})
    owners = _by_hid(
        db,
        Owner,
        {item.owner_hid for item in items} | {item.owner_hid for item in above.values()},
    )
    labels = tags.labels_of(db, "item", hids)
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
    out = []
    for item in items:
        entry = entries.get(item.catalog_entry_hid) if item.catalog_entry_hid else None
        owner = owners.get(item.owner_hid) if item.owner_hid else None
        line = lines[item.hid]
        effective = inheritance.of_item(item, entry, line)
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
                else shapes.CatalogRef(
                    hid=entry.hid,
                    vendor_hid=entry.vendor_hid,
                    vendor=vendors[entry.vendor_hid].name,
                    pid=entry.pid,
                    model_name=entry.model_name,
                    kind=entry.kind,
                    type=entry.type,
                    function=entry.function,
                ),
                owner=None if owner is None else shapes.OwnerRef(hid=owner.hid, label=owner.label),
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
                tags=labels[item.hid],
                effective=shapes.ItemEffective(
                    owner_hid=shapes.EffectiveReference(
                        value=effective["owner_hid"].value,
                        label=owner_in_force.label if owner_in_force is not None else None,
                        source=effective["owner_hid"].source,
                        source_hid=effective["owner_hid"].source_hid,
                    ),
                    **{
                        name: _effective(name, value)
                        for name, value in effective.items()
                        if name != "owner_hid"
                    },
                ),
            )
        )
    return out


_ITEM_SHAPED = (
    "health",
    "catalog",
    "owner",
    "parent",
    "is_major",
    "depth",
    "minor_items",
    "groups",
    "controllers",
    "addresses",
    "replaces",
    "replaced_by",
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
    owners = _by_hid(db, Owner, {group.owner_hid for group in found})
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
    masters = groups.masters(db, [group.hid for group in found if group.type == "stack"])
    seen = groups.observed_masters(db, found)
    master_refs = item_refs(
        db, list({item.hid: item for item in (*masters.values(), *seen.values())}.values())
    )
    healths = groups.health_of(db, found)
    labels = tags.labels_of(db, groups.RECORD_TYPE, hids)
    its_addresses = _address_refs(db, "group_hid", hids)
    disagree = groups.members_disagree(db, found)
    out = []
    for group in found:
        owner = owners.get(group.owner_hid) if group.owner_hid else None
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
                owner=None if owner is None else shapes.OwnerRef(hid=owner.hid, label=owner.label),
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
                tags=labels[group.hid],
            )
        )
    return out


_GROUP_SHAPED = (
    "health",
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
