"""The routes of external systems, of registrations with them, of capacity lines, and of
the records of the capacity balance."""

from typing import Annotated, Any

from fastapi import APIRouter

from hirdir.api import lists, shapes
from hirdir.api import records as r
from hirdir.api.deps import Audit, Db, Inventory, Viewer
from hirdir.api.idempotent import IdempotentRoute
from hirdir.api.lists import Limit, Listed, Offset, sort_of
from hirdir.api.schemas import Page
from hirdir.domain import capacity, systems
from hirdir.io import balance, fields, tables

system_routes = APIRouter(
    prefix="/external-systems", tags=["External systems"], route_class=IdempotentRoute
)
registrations = APIRouter(
    prefix="/registrations", tags=["External systems"], route_class=IdempotentRoute
)
capacity_lines = APIRouter(prefix="/capacity-lines", tags=["Capacity"], route_class=IdempotentRoute)
capacity_records = APIRouter(
    prefix="/capacity-records", tags=["Capacity"], route_class=IdempotentRoute
)


def _changes(body: r.Model) -> dict:
    return body.model_dump(exclude={"row_version"}, exclude_unset=True)


def _page(items: list[Any], total: int, listed: lists.ListRequest, model: Any) -> Any:
    return lists.narrowed(
        Page(items=items, total=total, limit=listed.limit, offset=listed.offset), listed, model
    )


# --- external systems ----------------------------------------------------------------


@system_routes.get("")
def list_systems(_: Viewer, db: Db, listed: Listed) -> Page[r.ExternalSystemOut]:
    """List external systems, by name unless a sort says otherwise."""
    page, total = lists.read(db, fields.EXTERNAL_SYSTEMS, listed)
    return _page(shapes.systems_out(db, page), total, listed, r.ExternalSystemOut)


@system_routes.post("", status_code=201)
def create_system(
    body: r.ExternalSystemCreate, _: Inventory, context: Audit, db: Db
) -> r.ExternalSystemOut:
    """Create an external system: a monitoring tool, an SDN controller, a cloud service."""
    return shapes.systems_out(db, [systems.create_system(db, context, body.model_dump())])[0]


@system_routes.get("/{hid}")
def get_system(hid: str, _: Viewer, db: Db) -> r.ExternalSystemOut:
    """Return one external system."""
    return shapes.systems_out(db, [systems.get_system(db, hid)])[0]


@system_routes.patch("/{hid}")
def update_system(
    hid: str, body: r.ExternalSystemPatch, _: Inventory, context: Audit, db: Db
) -> r.ExternalSystemOut:
    """Change an external system."""
    changed = systems.update_system(db, context, hid, body.row_version, _changes(body))
    return shapes.systems_out(db, [changed])[0]


@system_routes.post("/{hid}/retire")
def retire_system(
    hid: str, body: r.RowVersion, _: Inventory, context: Audit, db: Db
) -> r.ExternalSystemOut:
    """Retire an external system. Its registrations stay on record."""
    retired = systems.retire_system(db, context, hid, body.row_version)
    return shapes.systems_out(db, [retired])[0]


# --- registrations -------------------------------------------------------------------


@registrations.get("")
def list_registrations(_: Viewer, db: Db, listed: Listed) -> Page[r.RegistrationOut]:
    """List registrations: those of one system with `system_hid` in the filter, those
    of one item or group with `item_hid` or `group_hid`."""
    page, total = lists.read(db, fields.REGISTRATIONS, listed)
    return _page(shapes.registrations_out(db, page), total, listed, r.RegistrationOut)


@registrations.post("", status_code=201)
def create_registration(
    body: r.RegistrationCreate, _: Inventory, context: Audit, db: Db
) -> r.RegistrationOut:
    """Register one item or one device group with an external system.

    A stack that the system knows as one device is registered as the stack: the
    registration is then on the stack, and each of its members says what its stack is
    registered with.
    """
    made = systems.create_registration(db, context, body.model_dump(exclude_unset=True))
    return shapes.registrations_out(db, [made])[0]


@registrations.get("/{hid}")
def get_registration(hid: str, _: Viewer, db: Db) -> r.RegistrationOut:
    """Return one registration."""
    return shapes.registrations_out(db, [systems.get_registration(db, hid)])[0]


@registrations.patch("/{hid}")
def update_registration(
    hid: str, body: r.RegistrationPatch, _: Inventory, context: Audit, db: Db
) -> r.RegistrationOut:
    """Change a registration. One that ends is given the status `removed`."""
    changed = systems.update_registration(db, context, hid, body.row_version, _changes(body))
    return shapes.registrations_out(db, [changed])[0]


@registrations.delete("/{hid}", status_code=204)
def remove_registration(hid: str, _: Inventory, context: Audit, db: Db) -> None:
    """Remove a registration that was a mistake. The audit event of the removal holds
    what it was. One that was true for a time is given the status `removed` instead."""
    systems.remove_registration(db, context, hid)


# --- capacity lines ------------------------------------------------------------------


@capacity_lines.get("")
def list_capacity_lines(_: Viewer, db: Db, listed: Listed) -> Page[r.CapacityLineOut]:
    """List capacity lines: the supply first, by category and name, unless a sort says
    otherwise."""
    page, total = lists.read(db, fields.CAPACITY_LINES, listed)
    return _page(shapes.capacity_lines_out(db, page), total, listed, r.CapacityLineOut)


@capacity_lines.post("", status_code=201)
def create_capacity_line(
    body: r.CapacityLineCreate, _: Inventory, context: Audit, db: Db
) -> r.CapacityLineOut:
    """Create a capacity line: a source of resource units, or other work that calls on
    them. A draft line is a what-if."""
    made = capacity.create_line(db, context, body.model_dump())
    return shapes.capacity_lines_out(db, [made])[0]


@capacity_lines.get("/{hid}")
def get_capacity_line(hid: str, _: Viewer, db: Db) -> r.CapacityLineOut:
    """Return one capacity line."""
    return shapes.capacity_lines_out(db, [capacity.get_line(db, hid)])[0]


@capacity_lines.patch("/{hid}")
def update_capacity_line(
    hid: str, body: r.CapacityLinePatch, _: Inventory, context: Audit, db: Db
) -> r.CapacityLineOut:
    """Change a capacity line."""
    changed = capacity.update_line(db, context, hid, body.row_version, _changes(body))
    return shapes.capacity_lines_out(db, [changed])[0]


@capacity_lines.post("/{hid}/retire")
def retire_capacity_line(
    hid: str, body: r.RowVersion, _: Inventory, context: Audit, db: Db
) -> r.CapacityLineOut:
    """Retire a capacity line. It counts for nothing any more."""
    retired = capacity.retire_line(db, context, hid, body.row_version)
    return shapes.capacity_lines_out(db, [retired])[0]


# --- the records of the capacity balance ---------------------------------------------


@capacity_records.get("")
def list_capacity_records(
    _: Viewer,
    db: Db,
    sort: Annotated[list[str] | None, sort_of(tables.CAPACITY_RECORDS)] = None,
    limit: Limit = 100,
    offset: Offset = 0,
) -> Page[r.CapacityRecordOut]:
    """List the records of the balance, one for each week, the oldest first unless a
    sort says otherwise."""
    arrange = tables.arrange(tables.CAPACITY_RECORDS, sort)
    page, total = balance.list_records(db, limit, offset, arrange)
    return Page(items=shapes.capacity_records_out(page), total=total, limit=limit, offset=offset)


@capacity_records.post("", status_code=201)
def record_capacity(
    body: r.CapacityRecordCreate, _: Inventory, context: Audit, db: Db
) -> r.CapacityRecordOut:
    """Record the balance of the whole installation as it is now. The record of this
    week, by the application's time zone, is replaced: what it held is in its audit
    event."""
    return shapes.capacity_records_out([balance.record(db, context, note=body.note)])[0]


@capacity_records.get("/{hid}")
def get_capacity_record(hid: str, _: Viewer, db: Db) -> r.CapacityRecordOut:
    """Return one record of the balance."""
    return shapes.capacity_records_out([capacity.get_record(db, hid)])[0]


@capacity_records.patch("/{hid}")
def correct_capacity_record(
    hid: str, body: r.CapacityRecordPatch, _: Inventory, context: Audit, db: Db
) -> r.CapacityRecordOut:
    """Correct the demand and the supply of a saved week, with a note that says why.
    The record is then marked `adjusted`."""
    corrected = capacity.correct_record(
        db,
        context,
        hid,
        body.row_version,
        body.model_dump(exclude={"row_version"}, exclude_none=True),
    )
    return shapes.capacity_records_out([corrected])[0]


@capacity_records.delete("/{hid}", status_code=204)
def remove_capacity_record(hid: str, _: Inventory, context: Audit, db: Db) -> None:
    """Remove a record of the balance that was a mistake. The audit event of the removal
    holds what it was."""
    capacity.remove_record(db, context, hid)


ROUTERS = (system_routes, registrations, capacity_lines, capacity_records)
