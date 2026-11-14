"""The routes of geography and of contacts: regions, sites, locations, the tree of
them, what a place has in force, contacts and their assignments."""

from typing import Annotated, Any

from fastapi import APIRouter, Query

from hirdir.api import lists, shapes
from hirdir.api import records as r
from hirdir.api.deps import Audit, Db, Inventory, Viewer
from hirdir.api.idempotent import IdempotentRoute
from hirdir.api.lists import Listed
from hirdir.api.schemas import Page
from hirdir.domain import contacts, geography, operators
from hirdir.io import fields, places

regions = APIRouter(prefix="/regions", tags=["Geography"], route_class=IdempotentRoute)
sites = APIRouter(prefix="/sites", tags=["Geography"], route_class=IdempotentRoute)
locations = APIRouter(prefix="/locations", tags=["Geography"], route_class=IdempotentRoute)
tree = APIRouter(prefix="/geography", tags=["Geography"])
contact_routes = APIRouter(prefix="/contacts", tags=["People"], route_class=IdempotentRoute)
operator_routes = APIRouter(prefix="/operators", tags=["People"], route_class=IdempotentRoute)
assignments = APIRouter(prefix="/contact-assignments", tags=["People"], route_class=IdempotentRoute)


def _changes(body: r.Model) -> dict:
    return body.model_dump(exclude={"row_version"}, exclude_unset=True)


def _page(items: list[Any], total: int, listed: lists.ListRequest, model: Any) -> Any:
    return lists.narrowed(
        Page(items=items, total=total, limit=listed.limit, offset=listed.offset), listed, model
    )


def _effective(db: Db, level: str, hid: str) -> r.PlaceEffective:
    return shapes.effective_out(db, geography.effective(db, geography.get_place(db, level, hid)))


# --- regions -------------------------------------------------------------------------


@regions.get("")
def list_regions(_: Viewer, db: Db, listed: Listed) -> Page[r.RegionOut]:
    """List regions, by name unless a sort says otherwise."""
    page, total = lists.read(db, fields.REGIONS, listed)
    return _page(shapes.regions_out(db, page), total, listed, r.RegionOut)


@regions.post("", status_code=201)
def create_region(body: r.RegionCreate, _: Inventory, context: Audit, db: Db) -> r.RegionOut:
    """Create a region: at the top, or within another."""
    made = geography.create_place(db, context, geography.REGION, body.model_dump())
    return shapes.place_out(db, geography.REGION, made)


@regions.get("/{hid}")
def get_region(hid: str, _: Viewer, db: Db) -> r.RegionOut:
    """Return one region."""
    return shapes.place_out(db, geography.REGION, geography.get_region(db, hid))


@regions.patch("/{hid}")
def update_region(
    hid: str, body: r.RegionPatch, _: Inventory, context: Audit, db: Db
) -> r.RegionOut:
    """Change a region. Given another parent, it moves with everything in it: the paths
    and what is inherited follow at once, and no other record is written to."""
    changed = geography.update_place(
        db, context, geography.REGION, hid, body.row_version, _changes(body)
    )
    return shapes.place_out(db, geography.REGION, changed)


@regions.post("/{hid}/retire")
def retire_region(
    hid: str, body: r.RowVersion, _: Inventory, context: Audit, db: Db
) -> r.RegionOut:
    """Retire a region that no region or site that is not retired is in."""
    retired = geography.retire_place(db, context, geography.REGION, hid, body.row_version)
    return shapes.place_out(db, geography.REGION, retired)


@regions.get("/{hid}/effective")
def region_effective(hid: str, _: Viewer, db: Db) -> r.PlaceEffective:
    """Return what a region has in force: its contacts for each role and its shipping
    address and instructions, each with the level it came from."""
    return _effective(db, geography.REGION, hid)


# --- sites ---------------------------------------------------------------------------


@sites.get("")
def list_sites(_: Viewer, db: Db, listed: Listed) -> Page[r.SiteOut]:
    """List sites, by name unless a sort says otherwise."""
    page, total = lists.read(db, fields.SITES, listed)
    return _page(shapes.sites_out(db, page), total, listed, r.SiteOut)


@sites.post("", status_code=201)
def create_site(body: r.SiteCreate, _: Inventory, context: Audit, db: Db) -> r.SiteOut:
    """Create a site in a region."""
    made = geography.create_place(db, context, geography.SITE, body.model_dump())
    return shapes.place_out(db, geography.SITE, made)


@sites.get("/{hid}")
def get_site(hid: str, _: Viewer, db: Db) -> r.SiteOut:
    """Return one site."""
    return shapes.place_out(db, geography.SITE, geography.get_site(db, hid))


@sites.patch("/{hid}")
def update_site(hid: str, body: r.SitePatch, _: Inventory, context: Audit, db: Db) -> r.SiteOut:
    """Change a site. Given another region, it moves: the paths of its locations, what
    they inherit and the totals of both regions follow at once. It is one change of one
    record, and no item is written to."""
    changed = geography.update_place(
        db, context, geography.SITE, hid, body.row_version, _changes(body)
    )
    return shapes.place_out(db, geography.SITE, changed)


@sites.post("/{hid}/retire")
def retire_site(hid: str, body: r.RowVersion, _: Inventory, context: Audit, db: Db) -> r.SiteOut:
    """Retire a site that no location that is not retired is in."""
    retired = geography.retire_place(db, context, geography.SITE, hid, body.row_version)
    return shapes.place_out(db, geography.SITE, retired)


@sites.get("/{hid}/effective")
def site_effective(hid: str, _: Viewer, db: Db) -> r.PlaceEffective:
    """Return what a site has in force, each thing with the level it came from."""
    return _effective(db, geography.SITE, hid)


# --- locations -----------------------------------------------------------------------


def _locations_page(db: Db, listed: lists.ListRequest) -> Page[r.LocationOut]:
    page, total = lists.read(db, fields.LOCATIONS, listed)
    return _page(shapes.locations_out(db, page), total, listed, r.LocationOut)


@locations.get("")
def list_locations(_: Viewer, db: Db, listed: Listed) -> Page[r.LocationOut]:
    """List locations, by site and name unless a sort says otherwise."""
    return _locations_page(db, listed)


@locations.post("/query")
def query_locations(body: r.ListQuery, _: Viewer, db: Db) -> Page[r.LocationOut]:
    """List locations, with the filter and sort in the body."""
    return _locations_page(db, lists.from_body(body))


@locations.post("", status_code=201)
def create_location(body: r.LocationCreate, _: Inventory, context: Audit, db: Db) -> r.LocationOut:
    """Create a location: in a site, or within another location of one."""
    made = geography.create_place(
        db, context, geography.LOCATION, body.model_dump(exclude_unset=True)
    )
    return shapes.place_out(db, geography.LOCATION, made)


@locations.get("/{hid}")
def get_location(hid: str, _: Viewer, db: Db) -> r.LocationOut:
    """Return one location."""
    return shapes.place_out(db, geography.LOCATION, geography.get_location(db, hid))


@locations.patch("/{hid}")
def update_location(
    hid: str, body: r.LocationPatch, _: Inventory, context: Audit, db: Db
) -> r.LocationOut:
    """Change a location. It is moved within its site by giving it another parent."""
    changed = geography.update_place(
        db, context, geography.LOCATION, hid, body.row_version, _changes(body)
    )
    return shapes.place_out(db, geography.LOCATION, changed)


@locations.post("/{hid}/retire")
def retire_location(
    hid: str, body: r.RowVersion, _: Inventory, context: Audit, db: Db
) -> r.LocationOut:
    """Retire a location that nothing that is not retired is in: no location, no item
    and no device group."""
    retired = geography.retire_place(db, context, geography.LOCATION, hid, body.row_version)
    return shapes.place_out(db, geography.LOCATION, retired)


@locations.get("/{hid}/effective")
def location_effective(hid: str, _: Viewer, db: Db) -> r.PlaceEffective:
    """Return what a location has in force: its contacts for each role and its shipping
    address and instructions, each with the level it came from."""
    return _effective(db, geography.LOCATION, hid)


# --- the tree ------------------------------------------------------------------------


@tree.get("/tree")
def geography_tree(
    _: Viewer,
    db: Db,
    filter_: Annotated[
        str,
        Query(
            alias="filter",
            max_length=8000,
            description="A filter of the item list, in the short form or as JSON.",
        ),
    ] = "",
    root: Annotated[
        str | None,
        Query(
            max_length=2000,
            description="The HID or the path of a region, site or location to start from.",
        ),
    ] = None,
    locations_: Annotated[
        bool,
        Query(alias="locations", description="False stops at the sites."),
    ] = True,
    include_archived: Annotated[
        bool, Query(description="Retired places, and retired and archived items, as well.")
    ] = False,
    include_drafts: Annotated[bool, Query(description="Draft places and items as well.")] = False,
) -> r.GeographyTree:
    """Return the regions, their sites and the locations within them as one tree, each
    with the items and the components at or beneath it.

    The counts are of the view the item list shows for the same filter. The roots,
    `unplaced` and `hidden` add up to `totals`.
    """
    found = places.tree(
        db,
        filter_=filter_,
        root=root,
        locations=locations_,
        include_archived=include_archived,
        include_drafts=include_drafts,
    )
    return r.GeographyTree.model_validate(found)


# --- contacts ------------------------------------------------------------------------


@contact_routes.get("")
def list_contacts(_: Viewer, db: Db, listed: Listed) -> Page[r.ContactOut]:
    """List contacts, by name unless a sort says otherwise."""
    page, total = lists.read(db, fields.CONTACTS, listed)
    return _page(shapes.contacts_out(db, page), total, listed, r.ContactOut)


@contact_routes.post("", status_code=201)
def create_contact(body: r.ContactCreate, _: Inventory, context: Audit, db: Db) -> r.ContactOut:
    """Create a contact: a person, or a shared mailbox."""
    made = contacts.create_contact(db, context, body.model_dump())
    return shapes.contacts_out(db, [made])[0]


@contact_routes.get("/{hid}")
def get_contact(hid: str, _: Viewer, db: Db) -> r.ContactOut:
    """Return one contact."""
    return shapes.contacts_out(db, [contacts.get_contact(db, hid)])[0]


@contact_routes.patch("/{hid}")
def update_contact(
    hid: str, body: r.ContactPatch, _: Inventory, context: Audit, db: Db
) -> r.ContactOut:
    """Change a contact. Every place and owner it is assigned to shows the change at once."""
    changed = contacts.update_contact(db, context, hid, body.row_version, _changes(body))
    return shapes.contacts_out(db, [changed])[0]


@contact_routes.post("/{hid}/retire")
def retire_contact(
    hid: str, body: r.RowVersion, _: Inventory, context: Audit, db: Db
) -> r.ContactOut:
    """Retire a contact. Its assignments stay, and show it as retired."""
    retired = contacts.retire_contact(db, context, hid, body.row_version)
    return shapes.contacts_out(db, [retired])[0]


# --- operators -----------------------------------------------------------------------


@operator_routes.get("")
def list_operators(_: Viewer, db: Db, listed: Listed) -> Page[r.OperatorOut]:
    """List operators, by label unless a sort says otherwise."""
    page, total = lists.read(db, fields.OPERATORS, listed)
    return _page(shapes.operators_out(db, page), total, listed, r.OperatorOut)


@operator_routes.post("", status_code=201)
def create_operator(body: r.OperatorCreate, _: Inventory, context: Audit, db: Db) -> r.OperatorOut:
    """Create an operator: a short label, with somebody behind it or open."""
    made = operators.create_operator(db, context, body.model_dump())
    return shapes.operators_out(db, [made])[0]


@operator_routes.get("/{hid}")
def get_operator(hid: str, _: Viewer, db: Db) -> r.OperatorOut:
    """Return one operator."""
    return shapes.operators_out(db, [operators.get_operator(db, hid)])[0]


@operator_routes.patch("/{hid}")
def update_operator(
    hid: str, body: r.OperatorPatch, _: Inventory, context: Audit, db: Db
) -> r.OperatorOut:
    """Change an operator. Given another contact, everything the label is on is handed
    over at once; given none, it is an open assignment. Nothing else is written to."""
    changed = operators.update_operator(db, context, hid, body.row_version, _changes(body))
    return shapes.operators_out(db, [changed])[0]


@operator_routes.post("/{hid}/retire")
def retire_operator(
    hid: str, body: r.RowVersion, _: Inventory, context: Audit, db: Db
) -> r.OperatorOut:
    """Release what an operator is on: retired, the label stands for nothing, and each
    thing it was on has the operator of the next level up, or none."""
    retired = operators.retire_operator(db, context, hid, body.row_version)
    return shapes.operators_out(db, [retired])[0]


# --- contact assignments -------------------------------------------------------------


@assignments.get("")
def list_assignments(_: Viewer, db: Db, listed: Listed) -> Page[r.AssignmentOut]:
    """List contact assignments: those of one place with `region_hid`, `site_hid` or
    `location_hid` in the filter, those of one contact with `contact_hid`."""
    page, total = lists.read(db, fields.CONTACT_ASSIGNMENTS, listed)
    return _page(shapes.assignments_out(db, page), total, listed, r.AssignmentOut)


@assignments.post("", status_code=201)
def create_assignment(
    body: r.AssignmentCreate, _: Inventory, context: Audit, db: Db
) -> r.AssignmentOut:
    """Assign a contact to a region, a site or a location in a role.

    With no contact and `stop_inheritance` set, the place says that it has nobody in
    that role, and nothing above it is looked at.
    """
    made = contacts.create_assignment(db, context, body.model_dump(exclude_unset=True))
    return shapes.assignments_out(db, [made])[0]


@assignments.get("/{hid}")
def get_assignment(hid: str, _: Viewer, db: Db) -> r.AssignmentOut:
    """Return one contact assignment."""
    return shapes.assignments_out(db, [contacts.get_assignment(db, hid)])[0]


@assignments.patch("/{hid}")
def update_assignment(
    hid: str, body: r.AssignmentPatch, _: Inventory, context: Audit, db: Db
) -> r.AssignmentOut:
    """Change the role, the priority or the contact of an assignment."""
    changed = contacts.update_assignment(db, context, hid, body.row_version, _changes(body))
    return shapes.assignments_out(db, [changed])[0]


@assignments.delete("/{hid}", status_code=204)
def delete_assignment(hid: str, _: Inventory, context: Audit, db: Db) -> None:
    """Remove an assignment. The audit event of the removal holds what it was."""
    contacts.delete_assignment(db, context, hid)


ROUTERS = (regions, sites, locations, tree, contact_routes, operator_routes, assignments)
