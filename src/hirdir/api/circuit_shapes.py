"""Turning circuits, their parts and circuit groups into the shapes the API returns.

A page of a list is shaped together, so that the places, vendors, owners and tags its
rows refer to are each read once for the page.
"""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from hirdir.api import circuit_schemas as c
from hirdir.api import records as r
from hirdir.api import shapes
from hirdir.db.models import (
    Circuit,
    CircuitCarrier,
    CircuitCost,
    CircuitDevice,
    CircuitGroup,
    DeviceGroup,
    Item,
    Owner,
    Vendor,
)
from hirdir.domain import (
    circuit_groups,
    circuit_records,
    circuits,
    geography,
    tags,
    weights,
)
from hirdir.domain.inheritance import Effective

# The parts of a circuit that a list leaves out unless `fields` names them.
PARTS = ("carriers", "costs", "devices", "groups", "contacts")
ZERO = Decimal("0.00")
# The contacts in force, which a list reads with the parts.
CONTACTS_IN_FORCE = (
    "effective.account_managers",
    "effective.support_contacts",
    "effective.site_contacts",
)


def _by_hid(db: Session, model: Any, hids: set[str | None]) -> dict[str, Any]:
    wanted = sorted(hid for hid in hids if hid)
    found: dict[str, Any] = {}
    for start in range(0, len(wanted), 500):
        piece = wanted[start : start + 500]
        found.update(
            (record.hid, record) for record in db.scalars(select(model).where(model.hid.in_(piece)))
        )
    return found


def _owner_ref(owner: Owner | None) -> r.OwnerRef | None:
    if owner is None:
        return None
    return r.OwnerRef(hid=owner.hid, label=owner.label, is_external=owner.is_external)


def _mbps(value: Any) -> str | None:
    return None if value is None else f"{value:.2f}"


def _effective(found: Effective, text: str | None) -> r.EffectiveValue:
    return r.EffectiveValue(value=text, source=found.source, source_hid=found.source_hid)


def _day(found: Effective) -> r.EffectiveValue:
    """Return a date in force, as text, with where it came from."""
    return _effective(found, found.value.isoformat() if found.value is not None else None)


def group_ref(group: CircuitGroup, z_side: bool) -> c.CircuitGroupRef:
    """Return a circuit group as a circuit lists it."""
    return c.CircuitGroupRef.model_validate(
        {
            "hid": group.hid,
            "name": group.name,
            "kind": group.kind,
            "z_side": z_side,
            "record_status": group.record_status,
        }
    )


def _side(atlas: geography.Atlas, hid: str | None) -> c.CircuitSide | None:
    location = atlas.location(hid) if hid else None
    site = atlas.site(location.site_hid) if location is not None else None
    if location is None or site is None:
        return None
    return c.CircuitSide.model_validate(
        {
            "location_hid": location.hid,
            "name": location.name,
            "path": atlas.location_path(location.hid),
            "site_hid": site.hid,
            "site_path": atlas.site_path(site.hid),
            "region_hid": site.region_hid,
            "record_status": location.record_status,
        }
    )


# --- the parts of a circuit ----------------------------------------------------------


def carriers_out(db: Session, found: Sequence[CircuitCarrier]) -> list[c.CircuitCarrierOut]:
    """Return carriers of circuits, each with the name of its vendor."""
    vendors = _by_hid(db, Vendor, {link.vendor_hid for link in found})
    return [
        c.CircuitCarrierOut(
            **{
                name: getattr(link, name)
                for name in c.CircuitCarrierOut.model_fields
                if name != "vendor"
            },
            vendor=vendors[link.vendor_hid].name,
        )
        for link in found
    ]


def costs_out(db: Session, found: Sequence[CircuitCost], day: date) -> list[c.CircuitCostOut]:
    """Return cost lines, each saying whether it is billed on the day."""
    vendors = _by_hid(db, Vendor, {line.vendor_hid for line in found})
    return [
        c.CircuitCostOut(
            **{
                name: getattr(line, name)
                for name in c.CircuitCostOut.model_fields
                if name not in ("vendor", "in_date")
            },
            vendor=vendors[line.vendor_hid].name if line.vendor_hid else None,
            in_date=circuit_records.in_date(line, day),
        )
        for line in found
    ]


def devices_out(db: Session, found: Sequence[CircuitDevice]) -> list[c.CircuitDeviceOut]:
    """Return devices of circuits, each with what it is called and its status."""
    its_items = _by_hid(db, Item, {link.item_hid for link in found})
    its_groups = _by_hid(db, DeviceGroup, {link.group_hid for link in found})
    out = []
    for link in found:
        holder = its_items.get(link.item_hid or "") or its_groups[link.group_hid or ""]
        out.append(
            c.CircuitDeviceOut(
                **{
                    name: getattr(link, name)
                    for name in c.CircuitDeviceOut.model_fields
                    if name not in ("name", "record_status")
                },
                name=circuit_records.shown_name(holder),
                record_status=holder.record_status,
            )
        )
    return out


# --- circuits ------------------------------------------------------------------------

_SHAPED = (
    "speed",
    "a_side",
    "z_side",
    "z_group",
    "cost_site_hid",
    "cost_site_path",
    "carrier",
    "owner",
    "owner_exception",
    "owner_exception_reason",
    "monthly_cost",
    "annual_cost",
    "in_service",
    *PARTS,
    "effective",
    "tags",
)


def circuits_out(
    db: Session, found: Sequence[Circuit], parts: bool = True, include_drafts: bool = False
) -> list[c.CircuitOut]:
    """Return circuits with what they refer to and what is worked out when they are read.

    Without parts, the carriers, cost lines, devices and groups of each are left out.
    """
    hids = [circuit.hid for circuit in found]
    day = circuit_records.today(db)
    atlas = geography.Atlas(db)
    atlas.read_locations(
        {circuit.a_location_hid for circuit in found}
        | {circuit.z_location_hid for circuit in found}
    )
    vendors = _by_hid(db, Vendor, {circuit.carrier_hid for circuit in found})
    owners = _by_hid(db, Owner, {circuit.owner_hid for circuit in found})
    labels = tags.labels_of(db, circuit_records.RECORD_TYPE, hids)
    lines = circuit_records.lines_of(db, hids)
    # The parts, read for a page at once, or not at all for a list that leaves them out.
    wanted = hids if parts else []
    carriers = circuit_records.carriers_of(db, wanted)
    devices = circuit_records.devices_of(db, wanted)
    its_groups = circuit_groups.every_group_of(db, list(found) if parts else [])
    networks = _by_hid(db, CircuitGroup, {circuit.z_group_hid for circuit in found})
    figures = weights.in_force(db)
    # The contacts named and in force (P-149), read together for the page.
    named = shapes.circuits_contacts(db, list(found)) if parts else {}
    carried = {
        one.hid: one
        for one in carriers_out(db, [link for listed in carriers.values() for link in listed])
    }
    connected = {
        one.hid: one
        for one in devices_out(db, [link for listed in devices.values() for link in listed])
    }
    costed = {
        one.hid: one for one in costs_out(db, [line for hid in wanted for line in lines[hid]], day)
    }
    out = []
    for circuit in found:
        owner = owners.get(circuit.owner_hid or "")
        outside = owner is not None and owner.is_external
        counted_at = circuits.cost_location_hid(circuit)
        place = atlas.location(counted_at) if counted_at else None
        # What it costs today: nothing on a day it is not in service; a draft is in
        # service in a view of drafts (P-145).
        serving = circuits.in_service_on(circuit, day, include_drafts)
        monthly = circuit_records.monthly_cost(lines[circuit.hid], day) if serving else ZERO
        rates = circuit_records.rates_in_force(circuit)
        z_dates = circuits.z_dates_in_force(circuit)
        weight = weights.of_circuit(circuit, figures)
        carrier = vendors.get(circuit.carrier_hid or "")
        network = networks.get(circuit.z_group_hid or "")
        out.append(
            c.CircuitOut(
                **{
                    name: getattr(circuit, name)
                    for name in c.CircuitOut.model_fields
                    if name not in _SHAPED
                },
                speed=circuit_records.speed(circuit),
                a_side=_side(atlas, circuit.a_location_hid),
                z_side=_side(atlas, circuit.z_location_hid),
                z_group=group_ref(network, True) if network is not None else None,
                cost_site_hid=place.site_hid if place is not None else None,
                cost_site_path=(atlas.site_path(place.site_hid) or None) if place else None,
                carrier=r.VendorRef(hid=carrier.hid, name=carrier.name) if carrier else None,
                owner=_owner_ref(owner),
                owner_exception=outside,
                owner_exception_reason=owner.exception_reason if owner and outside else None,
                monthly_cost=monthly,
                annual_cost=monthly * circuit_records.MONTHS,
                in_service=serving,
                carriers=[carried[link.hid] for link in carriers[circuit.hid]] if parts else None,
                costs=[costed[line.hid] for line in lines[circuit.hid]] if parts else None,
                devices=[connected[link.hid] for link in devices[circuit.hid]] if parts else None,
                groups=[group_ref(one.group, one.z_side) for one in its_groups[circuit.hid]]
                if parts
                else None,
                effective=c.CircuitEffective(
                    support_weight=r.EffectiveWeight(**weights.effective_entry(weight)),
                    down_mbps=_effective(rates["down_mbps"], _mbps(rates["down_mbps"].value)),
                    up_mbps=_effective(rates["up_mbps"], _mbps(rates["up_mbps"].value)),
                    z_installed_on=_day(z_dates["z_installed_on"]),
                    z_activated_on=_day(z_dates["z_activated_on"]),
                    z_disconnected_on=_day(z_dates["z_disconnected_on"]),
                    account_managers=named[circuit.hid][1].account_managers if parts else None,
                    support_contacts=named[circuit.hid][1].support_contacts if parts else None,
                    site_contacts=named[circuit.hid][1].site_contacts if parts else None,
                ),
                contacts=named[circuit.hid][0] if parts else None,
                tags=labels[circuit.hid],
            )
        )
    return out


def circuit_out(db: Session, circuit: Circuit) -> c.CircuitOut:
    """Return one circuit, with its parts. A draft read by itself is read as a view of
    drafts reads it: in service on the days it will be, at what it will cost."""
    return circuits_out(db, [circuit], include_drafts=True)[0]


# --- circuit groups ------------------------------------------------------------------


_GROUP_SHAPED = (
    "owner",
    "carrier",
    "circuits",
    "in_service",
    "monthly_cost",
    "annual_cost",
    "tags",
)


def _vendor_ref(vendor: Vendor | None) -> r.VendorRef | None:
    return r.VendorRef(hid=vendor.hid, name=vendor.name) if vendor is not None else None


def groups_out(db: Session, found: Sequence[CircuitGroup]) -> list[c.CircuitGroupOut]:
    """Return circuit groups, each with how many circuits it has and what they cost."""
    hids = [group.hid for group in found]
    owners = _by_hid(db, Owner, {group.owner_hid for group in found})
    carriers = _by_hid(db, Vendor, {group.carrier_hid for group in found})
    labels = tags.labels_of(db, circuit_groups.RECORD_TYPE, hids)
    summed = circuit_groups.summaries(db, hids, circuit_records.today(db))
    return [
        c.CircuitGroupOut(
            **{
                name: getattr(group, name)
                for name in c.CircuitGroupOut.model_fields
                if name not in _GROUP_SHAPED
            },
            owner=_owner_ref(owners.get(group.owner_hid or "")),
            carrier=_vendor_ref(carriers.get(group.carrier_hid or "")),
            circuits=summed[group.hid].circuits,
            in_service=summed[group.hid].in_service,
            monthly_cost=summed[group.hid].monthly_cost,
            annual_cost=summed[group.hid].annual_cost,
            tags=labels[group.hid],
        )
        for group in found
    ]


def group_out(db: Session, group: CircuitGroup) -> c.CircuitGroupOut:
    """Return one circuit group."""
    return groups_out(db, [group])[0]


def members_out(
    db: Session, group_hid: str, found: Sequence[circuit_groups.Listed]
) -> list[c.CircuitGroupMemberOut]:
    """Return the circuits of a circuit group, each with its membership, where it was
    added by hand, and whether its Z side names the group (P-320)."""
    day = circuit_records.today(db)
    lines = circuit_records.lines_of(db, [one.circuit.hid for one in found])
    return [
        c.CircuitGroupMemberOut(
            hid=member.hid if member is not None else None,
            group_hid=group_hid,
            circuit_hid=circuit.hid,
            z_side=z_side,
            created_at=member.created_at if member is not None else None,
            circuit=c.CircuitRef.model_validate(
                {
                    "hid": circuit.hid,
                    "name": circuit.name,
                    "enterprise_circuit_id": circuit.enterprise_circuit_id,
                    "circuit_type": circuit.circuit_type,
                    "speed": circuit_records.speed(circuit),
                    "in_service": circuits.in_service_on(circuit, day),
                    "monthly_cost": circuit_records.monthly_cost(lines[circuit.hid], day)
                    if circuits.in_service_on(circuit, day)
                    else ZERO,
                    "record_status": circuit.record_status,
                }
            ),
        )
        for member, circuit, z_side in ((one.member, one.circuit, one.z_side) for one in found)
    ]


def connections_out(
    db: Session, field: str, hids: list[str]
) -> dict[str, list[r.CircuitConnection]]:
    """Return the circuits each item, or each device group, is connected to."""
    return {
        hid: [
            r.CircuitConnection.model_validate(
                {
                    "hid": circuit.hid,
                    "name": circuit.name,
                    "enterprise_circuit_id": circuit.enterprise_circuit_id,
                    "side": link.side,
                    "link_hid": link.hid,
                    "record_status": circuit.record_status,
                }
            )
            for link, circuit in listed
        ]
        for hid, listed in circuit_records.connections_of(db, field, hids).items()
    }
