"""The routes of circuits, of their carriers, cost lines and devices, and of circuit
groups and their members (P-145 to P-154). The contacts of a circuit are elsewhere."""

from typing import Any

from fastapi import APIRouter

from hirdir.api import circuit_schemas as c
from hirdir.api import circuit_shapes, lists
from hirdir.api import records as r
from hirdir.api.deps import Audit, Db, Inventory, Viewer
from hirdir.api.idempotent import IdempotentRoute
from hirdir.api.lists import DEFAULT_LIMIT, Limit, Listed, Offset
from hirdir.api.schemas import Page
from hirdir.domain import circuit_groups, circuit_records
from hirdir.io import fields

circuit_routes = APIRouter(prefix="/circuits", tags=["Circuits"], route_class=IdempotentRoute)
group_routes = APIRouter(prefix="/circuit-groups", tags=["Circuits"], route_class=IdempotentRoute)


def _changes(body: r.Model) -> dict[str, Any]:
    return body.model_dump(exclude={"row_version"}, exclude_unset=True)


def _page_of(items: list[Any], limit: int, offset: int) -> Page[Any]:
    return Page(items=items[offset : offset + limit], total=len(items), limit=limit, offset=offset)


# --- circuits ------------------------------------------------------------------------


def _circuits(db: Db, listed: lists.ListRequest) -> Page[c.CircuitOut]:
    page, total = lists.read(db, fields.CIRCUITS, listed)
    # A list leaves the parts of each circuit out, unless `fields` names one of them.
    parts = any(
        name.partition(".")[0] in circuit_shapes.PARTS
        or name.startswith(circuit_shapes.CONTACTS_IN_FORCE)
        for name in listed.fields
    )
    return lists.narrowed(
        Page(
            items=circuit_shapes.circuits_out(
                db, page, parts=parts, include_drafts=listed.include_drafts
            ),
            total=total,
            limit=listed.limit,
            offset=listed.offset,
        ),
        listed,
        c.CircuitOut,
    )


@circuit_routes.get("")
def list_circuits(_: Viewer, db: Db, listed: Listed) -> Page[c.CircuitOut]:
    """List circuits, by name unless a sort says otherwise.

    Drafts and retired circuits are left out unless asked for. The carriers, cost
    lines, devices and groups of each are null unless `fields` names them.
    """
    return _circuits(db, listed)


@circuit_routes.post("/query")
def query_circuits(body: r.ListQuery, _: Viewer, db: Db) -> Page[c.CircuitOut]:
    """List circuits, with the filter and the sort in the body."""
    return _circuits(db, lists.from_body(body))


@circuit_routes.post("", status_code=201)
def create_circuit(body: c.CircuitCreate, _: Inventory, context: Audit, db: Db) -> c.CircuitOut:
    """Create a circuit. At least one side is a location, and a side with none has a
    note of where it ends. One that names no `cost_side` is given the setting's."""
    made = circuit_records.create_circuit(db, context, body.model_dump())
    return circuit_shapes.circuit_out(db, made)


@circuit_routes.get("/{hid}")
def get_circuit(hid: str, _: Viewer, db: Db) -> c.CircuitOut:
    """Return one circuit, whatever its status, with its parts."""
    return circuit_shapes.circuit_out(db, circuit_records.get_circuit(db, hid))


@circuit_routes.patch("/{hid}")
def update_circuit(
    hid: str, body: c.CircuitPatch, _: Inventory, context: Audit, db: Db
) -> c.CircuitOut:
    """Change a circuit. `record_status` of `active` or `draft` brings a retired one back."""
    changed = circuit_records.update_circuit(db, context, hid, body.row_version, _changes(body))
    return circuit_shapes.circuit_out(db, changed)


@circuit_routes.post("/{hid}/retire")
def retire_circuit(
    hid: str, body: r.RowVersion, _: Inventory, context: Audit, db: Db
) -> c.CircuitOut:
    """Retire a circuit. Its parts and its groups stay on record."""
    retired = circuit_records.retire_circuit(db, context, hid, body.row_version)
    return circuit_shapes.circuit_out(db, retired)


# --- carriers ------------------------------------------------------------------------


@circuit_routes.get("/{hid}/carriers")
def list_carriers(
    hid: str, _: Viewer, db: Db, limit: Limit = DEFAULT_LIMIT, offset: Offset = 0
) -> Page[c.CircuitCarrierOut]:
    """List the carriers of a circuit beside its primary one, by priority."""
    circuit_records.get_circuit(db, hid)
    found = circuit_records.carriers_of(db, [hid])[hid]
    return _page_of(circuit_shapes.carriers_out(db, found), limit, offset)


@circuit_routes.post("/{hid}/carriers", status_code=201)
def add_carrier(
    hid: str, body: c.CircuitCarrierAdd, _: Inventory, context: Audit, db: Db
) -> c.CircuitCarrierOut:
    """Name a carrier of a circuit beside its primary one: a local exchange carrier, the
    provider of a cross-connect. A vendor is named once on a circuit."""
    made = circuit_records.add_carrier(db, context, hid, body.model_dump())
    return circuit_shapes.carriers_out(db, [made])[0]


@circuit_routes.patch("/{hid}/carriers/{link_hid}")
def update_carrier(
    hid: str, link_hid: str, body: c.CircuitCarrierPatch, _: Inventory, context: Audit, db: Db
) -> c.CircuitCarrierOut:
    """Change a carrier of a circuit."""
    changed = circuit_records.update_carrier(
        db, context, hid, link_hid, body.row_version, _changes(body)
    )
    return circuit_shapes.carriers_out(db, [changed])[0]


@circuit_routes.delete("/{hid}/carriers/{link_hid}", status_code=204)
def remove_carrier(hid: str, link_hid: str, _: Inventory, context: Audit, db: Db) -> None:
    """Remove a carrier of a circuit that was a mistake. One that a cost line names is
    not removed. The audit event of the removal holds what it was."""
    circuit_records.remove_carrier(db, context, hid, link_hid)


# --- cost lines ----------------------------------------------------------------------


@circuit_routes.get("/{hid}/costs")
def list_costs(
    hid: str, _: Viewer, db: Db, limit: Limit = DEFAULT_LIMIT, offset: Offset = 0
) -> Page[c.CircuitCostOut]:
    """List the cost lines of a circuit, by description."""
    circuit_records.get_circuit(db, hid)
    found = circuit_records.lines_of(db, [hid])[hid]
    return _page_of(circuit_shapes.costs_out(db, found, circuit_records.today(db)), limit, offset)


@circuit_routes.post("/{hid}/costs", status_code=201)
def add_cost(
    hid: str, body: c.CircuitCostAdd, _: Inventory, context: Audit, db: Db
) -> c.CircuitCostOut:
    """Add a line of what a carrier bills for a circuit each month: the port, the local
    loop, a credit below zero. A new rate is a line that ends and one that begins."""
    made = circuit_records.add_cost(db, context, hid, body.model_dump())
    return circuit_shapes.costs_out(db, [made], circuit_records.today(db))[0]


@circuit_routes.patch("/{hid}/costs/{line_hid}")
def update_cost(
    hid: str, line_hid: str, body: c.CircuitCostPatch, _: Inventory, context: Audit, db: Db
) -> c.CircuitCostOut:
    """Change a cost line. One that was billed for a time is given an end."""
    changed = circuit_records.update_cost(
        db, context, hid, line_hid, body.row_version, _changes(body)
    )
    return circuit_shapes.costs_out(db, [changed], circuit_records.today(db))[0]


@circuit_routes.delete("/{hid}/costs/{line_hid}", status_code=204)
def remove_cost(hid: str, line_hid: str, _: Inventory, context: Audit, db: Db) -> None:
    """Remove a cost line that was a mistake. The audit event holds what it was."""
    circuit_records.remove_cost(db, context, hid, line_hid)


# --- devices -------------------------------------------------------------------------


@circuit_routes.get("/{hid}/devices")
def list_devices(
    hid: str, _: Viewer, db: Db, limit: Limit = DEFAULT_LIMIT, offset: Offset = 0
) -> Page[c.CircuitDeviceOut]:
    """List the devices a circuit connects, the A side first."""
    circuit_records.get_circuit(db, hid)
    found = circuit_records.devices_of(db, [hid])[hid]
    return _page_of(circuit_shapes.devices_out(db, found), limit, offset)


@circuit_routes.post("/{hid}/devices", status_code=201)
def add_devices(
    hid: str, body: c.CircuitDevicesAdd, _: Inventory, context: Audit, db: Db
) -> list[c.CircuitDeviceOut]:
    """Connect items and device groups to a circuit, each on a side, all together. A
    device is connected to a circuit once."""
    made = circuit_records.add_devices(
        db, context, hid, [device.model_dump() for device in body.devices]
    )
    return circuit_shapes.devices_out(db, made)


@circuit_routes.patch("/{hid}/devices/{link_hid}")
def update_device(
    hid: str, link_hid: str, body: c.CircuitDevicePatch, _: Inventory, context: Audit, db: Db
) -> c.CircuitDeviceOut:
    """Change the side of a device of a circuit, or its notes."""
    changed = circuit_records.update_device(
        db, context, hid, link_hid, body.row_version, _changes(body)
    )
    return circuit_shapes.devices_out(db, [changed])[0]


@circuit_routes.delete("/{hid}/devices/{link_hid}", status_code=204)
def remove_device(hid: str, link_hid: str, _: Inventory, context: Audit, db: Db) -> None:
    """Remove a device of a circuit that was a mistake, or that was taken out. The audit
    event of the removal holds what it was."""
    circuit_records.remove_device(db, context, hid, link_hid)


# --- circuit groups ------------------------------------------------------------------


def _groups(db: Db, listed: lists.ListRequest) -> Page[c.CircuitGroupOut]:
    page, total = lists.read(db, fields.CIRCUIT_GROUPS, listed)
    return lists.narrowed(
        Page(
            items=circuit_shapes.groups_out(db, page),
            total=total,
            limit=listed.limit,
            offset=listed.offset,
        ),
        listed,
        c.CircuitGroupOut,
    )


@group_routes.get("")
def list_groups(_: Viewer, db: Db, listed: Listed) -> Page[c.CircuitGroupOut]:
    """List circuit groups, by name unless a sort says otherwise."""
    return _groups(db, listed)


@group_routes.post("/query")
def query_groups(body: r.ListQuery, _: Viewer, db: Db) -> Page[c.CircuitGroupOut]:
    """List circuit groups, with the filter and the sort in the body."""
    return _groups(db, lists.from_body(body))


@group_routes.post("", status_code=201)
def create_group(
    body: c.CircuitGroupCreate, _: Inventory, context: Audit, db: Db
) -> c.CircuitGroupOut:
    """Create a circuit group: circuits to be looked at and costed together."""
    made = circuit_groups.create_group(db, context, body.model_dump())
    return circuit_shapes.group_out(db, made)


@group_routes.get("/{hid}")
def get_group(hid: str, _: Viewer, db: Db) -> c.CircuitGroupOut:
    """Return one circuit group, with how many circuits it has and what they cost."""
    return circuit_shapes.group_out(db, circuit_groups.get_group(db, hid))


@group_routes.patch("/{hid}")
def update_group(
    hid: str, body: c.CircuitGroupPatch, _: Inventory, context: Audit, db: Db
) -> c.CircuitGroupOut:
    """Change a circuit group."""
    changed = circuit_groups.update_group(db, context, hid, body.row_version, _changes(body))
    return circuit_shapes.group_out(db, changed)


@group_routes.post("/{hid}/retire")
def retire_group(
    hid: str, body: r.RowVersion, _: Inventory, context: Audit, db: Db
) -> c.CircuitGroupOut:
    """Retire a circuit group. Its circuits stay listed in it, and it takes no new one."""
    retired = circuit_groups.retire_group(db, context, hid, body.row_version)
    return circuit_shapes.group_out(db, retired)


@group_routes.get("/{hid}/members")
def list_members(
    hid: str, _: Viewer, db: Db, limit: Limit = DEFAULT_LIMIT, offset: Offset = 0
) -> Page[c.CircuitGroupMemberOut]:
    """List the circuits of a group, by name, retired ones too, which say so."""
    page, total = circuit_groups.list_members(db, hid, limit, offset)
    return Page(items=circuit_shapes.members_out(db, page), total=total, limit=limit, offset=offset)


@group_routes.post("/{hid}/members", status_code=201)
def add_members(
    hid: str, body: c.CircuitGroupMembersAdd, _: Inventory, context: Audit, db: Db
) -> list[c.CircuitGroupMemberOut]:
    """Put circuits into a group, all together, each once. A retired group takes none,
    and a retired circuit is added to none."""
    made = circuit_groups.add_members(db, context, hid, body.circuit_hids)
    circuits = {
        circuit.hid: circuit
        for circuit in (circuit_records.get_circuit(db, member.circuit_hid) for member in made)
    }
    return circuit_shapes.members_out(
        db, [(member, circuits[member.circuit_hid]) for member in made]
    )


@group_routes.delete("/{hid}/members/{member_hid}", status_code=204)
def remove_member(hid: str, member_hid: str, _: Inventory, context: Audit, db: Db) -> None:
    """Take a circuit out of a group. The audit event of the removal holds what it was."""
    circuit_groups.remove_member(db, context, hid, member_hid)


ROUTERS = (circuit_routes, group_routes)
