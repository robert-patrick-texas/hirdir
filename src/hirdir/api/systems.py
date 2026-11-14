"""The routes of external systems, of registrations with them, and of capacity lines."""

from typing import Any

from fastapi import APIRouter

from hirdir.api import lists, shapes
from hirdir.api import records as r
from hirdir.api.deps import Audit, Db, Inventory, Viewer
from hirdir.api.idempotent import IdempotentRoute
from hirdir.api.lists import Listed
from hirdir.api.schemas import Page
from hirdir.domain import capacity, systems
from hirdir.io import fields

system_routes = APIRouter(
    prefix="/external-systems", tags=["External systems"], route_class=IdempotentRoute
)
registrations = APIRouter(
    prefix="/registrations", tags=["External systems"], route_class=IdempotentRoute
)
capacity_lines = APIRouter(prefix="/capacity-lines", tags=["Capacity"], route_class=IdempotentRoute)


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
    registration is then on the stack, and not on its members.
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
    """Change a registration. One that ends is given the status `removed`, and is
    never deleted."""
    changed = systems.update_registration(db, context, hid, body.row_version, _changes(body))
    return shapes.registrations_out(db, [changed])[0]


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


ROUTERS = (system_routes, registrations, capacity_lines)
