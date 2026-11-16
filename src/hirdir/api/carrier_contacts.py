"""The routes of the contacts of carriers and of circuits (P-149): contact records named
for a vendor, its account team and its support desk, and for a circuit, its own of the
carrier's and the site contacts of each side."""

from fastapi import APIRouter

from hirdir.api import lists, shapes
from hirdir.api import records as r
from hirdir.api.deps import Audit, Db, Inventory, Viewer
from hirdir.api.idempotent import IdempotentRoute
from hirdir.api.schemas import Page
from hirdir.db.models import CircuitContact, Contact, VendorContact
from hirdir.domain import carrier_contacts as named

vendors = APIRouter(prefix="/vendors", tags=["Catalog"], route_class=IdempotentRoute)
circuits = APIRouter(prefix="/circuits", tags=["Circuits"], route_class=IdempotentRoute)


def _changes(body: r.Model) -> dict:
    return body.model_dump(exclude={"row_version"}, exclude_unset=True)


def _page[T](found: list[T], limit: int, offset: int) -> Page[T]:
    return Page(items=found[offset : offset + limit], total=len(found), limit=limit, offset=offset)


# --- the contacts of a vendor --------------------------------------------------------


def _vendor_out(db: Db, link: VendorContact) -> r.VendorContactOut:
    return shapes.vendor_contact_out((link, db.get_one(Contact, link.contact_hid)))


@vendors.get("/{hid}/contacts")
def list_vendor_contacts(
    hid: str, _: Viewer, db: Db, limit: lists.Limit = 100, offset: lists.Offset = 0
) -> Page[r.VendorContactOut]:
    """List the contact records a vendor names, its account team and its support desk:
    by role, then by priority. Each circuit of the carrier that names nobody of its own
    in a role has these."""
    named.get_vendor(db, hid)
    return _page(shapes.vendor_contacts_out(db, hid), limit, offset)


@vendors.post("/{hid}/contacts", status_code=201)
def add_vendor_contact(
    hid: str, body: r.VendorContactAdd, _: Inventory, context: Audit, db: Db
) -> r.VendorContactOut:
    """Name a contact record for a vendor, as an account manager or a support contact.
    A contact is named once for one vendor and one role."""
    return _vendor_out(db, named.add_vendor_contact(db, context, hid, body.model_dump()))


@vendors.patch("/{hid}/contacts/{link_hid}")
def update_vendor_contact(
    hid: str, link_hid: str, body: r.VendorContactPatch, _: Inventory, context: Audit, db: Db
) -> r.VendorContactOut:
    """Change the role, the priority or the contact of a naming of a vendor."""
    changed = named.update_vendor_contact(
        db, context, hid, link_hid, body.row_version, _changes(body)
    )
    return _vendor_out(db, changed)


@vendors.delete("/{hid}/contacts/{link_hid}", status_code=204)
def remove_vendor_contact(hid: str, link_hid: str, _: Inventory, context: Audit, db: Db) -> None:
    """Remove a naming of a vendor that was a mistake. The audit event of the removal
    holds what it was."""
    named.remove_vendor_contact(db, context, hid, link_hid)


# --- the contacts of a circuit -------------------------------------------------------


def _circuit_out(db: Db, link: CircuitContact) -> r.CircuitContactOut:
    return shapes.circuit_contact_out((link, db.get_one(Contact, link.contact_hid)))


@circuits.get("/{hid}/contacts")
def list_circuit_contacts(
    hid: str, _: Viewer, db: Db, limit: lists.Limit = 100, offset: lists.Offset = 0
) -> Page[r.CircuitContactOut]:
    """List the contact records a circuit names of its own: the carrier's first, then
    the site contacts of the A side and of the Z side, each by role, then by priority.
    Those in force, its own, its carrier's and its locations', are in `effective` on
    the circuit."""
    named.get_circuit(db, hid)
    return _page(shapes.circuit_contacts_out(db, hid), limit, offset)


@circuits.post("/{hid}/contacts", status_code=201)
def add_circuit_contact(
    hid: str, body: r.CircuitContactAdd, _: Inventory, context: Audit, db: Db
) -> r.CircuitContactOut:
    """Name a contact record for a circuit: with no side, one of the carrier's, which
    with the others of its role stands in place of the carrier's; with a side, a site
    contact of that side, which stands in place of what the location gives in its
    role. A contact is named once for one circuit, side and role."""
    return _circuit_out(db, named.add_circuit_contact(db, context, hid, body.model_dump()))


@circuits.patch("/{hid}/contacts/{link_hid}")
def update_circuit_contact(
    hid: str, link_hid: str, body: r.CircuitContactPatch, _: Inventory, context: Audit, db: Db
) -> r.CircuitContactOut:
    """Change the side, the role, the priority or the contact of a naming of a circuit."""
    changed = named.update_circuit_contact(
        db, context, hid, link_hid, body.row_version, _changes(body)
    )
    return _circuit_out(db, changed)


@circuits.delete("/{hid}/contacts/{link_hid}", status_code=204)
def remove_circuit_contact(hid: str, link_hid: str, _: Inventory, context: Audit, db: Db) -> None:
    """Remove a naming of a circuit that was a mistake. The audit event of the removal
    holds what it was. A circuit that names nobody left in a role has its carrier's, or
    its location's, again."""
    named.remove_circuit_contact(db, context, hid, link_hid)


ROUTERS = (vendors, circuits)
