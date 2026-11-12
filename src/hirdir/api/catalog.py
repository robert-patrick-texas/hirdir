"""The routes of the catalog: vendors, catalog entries and owners."""

from fastapi import APIRouter

from hirdir.api import lists, shapes
from hirdir.api import records as r
from hirdir.api.deps import Audit, Db, Inventory, Viewer
from hirdir.api.lists import Listed
from hirdir.api.schemas import Page
from hirdir.domain import catalog, owners
from hirdir.io import fields

vendors = APIRouter(prefix="/vendors", tags=["Catalog"])
entries = APIRouter(prefix="/catalog-entries", tags=["Catalog"])
owner_routes = APIRouter(prefix="/owners", tags=["People"])


def _changes(body: r.Model) -> dict:
    return body.model_dump(exclude={"row_version"}, exclude_unset=True)


# --- vendors -------------------------------------------------------------------------


@vendors.get("")
def list_vendors(_: Viewer, db: Db, listed: Listed) -> Page[r.VendorOut]:
    """List vendors, by name unless a sort says otherwise."""
    page, total = lists.read(db, fields.VENDORS, listed)
    return Page(
        items=[shapes.vendor_out(vendor) for vendor in page],
        total=total,
        limit=listed.limit,
        offset=listed.offset,
    )


@vendors.post("", status_code=201)
def create_vendor(body: r.VendorCreate, _: Inventory, context: Audit, db: Db) -> r.VendorOut:
    """Create a vendor."""
    return shapes.vendor_out(catalog.create_vendor(db, context, body.model_dump()))


@vendors.get("/{hid}")
def get_vendor(hid: str, _: Viewer, db: Db) -> r.VendorOut:
    """Return one vendor."""
    return shapes.vendor_out(catalog.get_vendor(db, hid))


@vendors.patch("/{hid}")
def update_vendor(
    hid: str, body: r.VendorPatch, _: Inventory, context: Audit, db: Db
) -> r.VendorOut:
    """Change a vendor."""
    vendor = catalog.update_vendor(db, context, hid, body.row_version, _changes(body))
    return shapes.vendor_out(vendor)


# --- catalog entries -----------------------------------------------------------------


def _entries_page(db: Db, listed: lists.ListRequest) -> Page[r.CatalogEntryOut]:
    page, total = lists.read(db, fields.CATALOG_ENTRIES, listed)
    return Page(
        items=shapes.entries_out(db, page), total=total, limit=listed.limit, offset=listed.offset
    )


@entries.get("")
def list_entries(_: Viewer, db: Db, listed: Listed) -> Page[r.CatalogEntryOut]:
    """List catalog entries, by vendor and PID unless a sort says otherwise."""
    return _entries_page(db, listed)


@entries.post("/query")
def query_entries(body: r.ListQuery, _: Viewer, db: Db) -> Page[r.CatalogEntryOut]:
    """List catalog entries, with the filter and sort in the body."""
    return _entries_page(db, lists.from_body(body))


@entries.post("", status_code=201)
def create_entry(
    body: r.CatalogEntryCreate, _: Inventory, context: Audit, db: Db
) -> r.CatalogEntryOut:
    """Create a catalog entry."""
    return shapes.entry_out(db, catalog.create_entry(db, context, body.model_dump()))


@entries.get("/{hid}")
def get_entry(hid: str, _: Viewer, db: Db) -> r.CatalogEntryOut:
    """Return one catalog entry."""
    return shapes.entry_out(db, catalog.get_entry(db, hid))


@entries.patch("/{hid}")
def update_entry(
    hid: str, body: r.CatalogEntryPatch, _: Inventory, context: Audit, db: Db
) -> r.CatalogEntryOut:
    """Change a catalog entry. Every item of the model shows a changed date or amount
    at once, and no item is written to."""
    entry = catalog.update_entry(db, context, hid, body.row_version, _changes(body))
    return shapes.entry_out(db, entry)


@entries.post("/{hid}/retire")
def retire_entry(
    hid: str, body: r.RowVersion, _: Inventory, context: Audit, db: Db
) -> r.CatalogEntryOut:
    """Retire a catalog entry. Items of the model keep it."""
    return shapes.entry_out(db, catalog.retire_entry(db, context, hid, body.row_version))


# --- owners --------------------------------------------------------------------------


@owner_routes.get("")
def list_owners(_: Viewer, db: Db, listed: Listed) -> Page[r.OwnerOut]:
    """List owners, by label unless a sort says otherwise."""
    page, total = lists.read(db, fields.OWNERS, listed)
    return Page(
        items=[shapes.owner_out(owner) for owner in page],
        total=total,
        limit=listed.limit,
        offset=listed.offset,
    )


@owner_routes.post("", status_code=201)
def create_owner(body: r.OwnerCreate, _: Inventory, context: Audit, db: Db) -> r.OwnerOut:
    """Create an owner."""
    return shapes.owner_out(owners.create_owner(db, context, body.model_dump()))


@owner_routes.get("/{hid}")
def get_owner(hid: str, _: Viewer, db: Db) -> r.OwnerOut:
    """Return one owner."""
    return shapes.owner_out(owners.get_owner(db, hid))


@owner_routes.patch("/{hid}")
def update_owner(hid: str, body: r.OwnerPatch, _: Inventory, context: Audit, db: Db) -> r.OwnerOut:
    """Change an owner."""
    owner = owners.update_owner(db, context, hid, body.row_version, _changes(body))
    return shapes.owner_out(owner)


@owner_routes.post("/{hid}/retire")
def retire_owner(hid: str, body: r.RowVersion, _: Inventory, context: Audit, db: Db) -> r.OwnerOut:
    """Retire an owner. Items keep it."""
    return shapes.owner_out(owners.retire_owner(db, context, hid, body.row_version))


ROUTERS = (vendors, entries, owner_routes)
