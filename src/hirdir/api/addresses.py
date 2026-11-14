"""The routes of networks and addresses."""

from fastapi import APIRouter

from hirdir.api import lists, shapes
from hirdir.api import records as r
from hirdir.api.deps import Audit, Db, Inventory, Viewer
from hirdir.api.idempotent import IdempotentRoute
from hirdir.api.lists import Listed
from hirdir.api.schemas import Page
from hirdir.domain import addresses
from hirdir.io import fields

networks = APIRouter(prefix="/networks", tags=["Addresses"], route_class=IdempotentRoute)
router = APIRouter(prefix="/addresses", tags=["Addresses"], route_class=IdempotentRoute)


def _changes(body: r.Model) -> dict:
    return body.model_dump(exclude={"row_version"}, exclude_unset=True)


# --- networks ------------------------------------------------------------------------


@networks.get("")
def list_networks(_: Viewer, db: Db, listed: Listed) -> Page[r.NetworkOut]:
    """List networks, by label unless a sort says otherwise."""
    page, total = lists.read(db, fields.NETWORKS, listed)
    return lists.narrowed(
        Page(
            items=shapes.networks_out(db, page),
            total=total,
            limit=listed.limit,
            offset=listed.offset,
        ),
        listed,
        r.NetworkOut,
    )


@networks.post("", status_code=201)
def create_network(body: r.NetworkCreate, _: Inventory, context: Audit, db: Db) -> r.NetworkOut:
    """Create a network label."""
    made = addresses.create_network(db, context, body.model_dump())
    return shapes.networks_out(db, [made])[0]


@networks.get("/{hid}")
def get_network(hid: str, _: Viewer, db: Db) -> r.NetworkOut:
    """Return one network."""
    return shapes.networks_out(db, [addresses.get_network(db, hid)])[0]


@networks.patch("/{hid}")
def update_network(
    hid: str, body: r.NetworkPatch, _: Inventory, context: Audit, db: Db
) -> r.NetworkOut:
    """Change a network. Its addresses are under the new label at once."""
    network = addresses.update_network(db, context, hid, body.row_version, _changes(body))
    return shapes.networks_out(db, [network])[0]


@networks.delete("/{hid}", status_code=204)
def delete_network(hid: str, _: Inventory, context: Audit, db: Db) -> None:
    """Remove a network that no address is under."""
    addresses.delete_network(db, context, hid)


# --- addresses -----------------------------------------------------------------------


def _page(db: Db, listed: lists.ListRequest) -> Page[r.AddressOut]:
    page, total = lists.read(db, fields.ADDRESSES, listed)
    return lists.narrowed(
        Page(
            items=shapes.addresses_out(db, page),
            total=total,
            limit=listed.limit,
            offset=listed.offset,
        ),
        listed,
        r.AddressOut,
    )


@router.get("")
def list_addresses(_: Viewer, db: Db, listed: Listed) -> Page[r.AddressOut]:
    """List addresses, by address unless a sort says otherwise."""
    return _page(db, listed)


@router.post("/query")
def query_addresses(body: r.ListQuery, _: Viewer, db: Db) -> Page[r.AddressOut]:
    """List addresses, with the filter and sort in the body."""
    return _page(db, lists.from_body(body))


@router.post("", status_code=201)
def create_address(body: r.AddressCreate, _: Inventory, context: Audit, db: Db) -> r.AddressOut:
    """Give an item or a device group an address.

    The same address twice under one network is accepted, and is listed in the
    duplicates report.
    """
    made = addresses.create_address(db, context, body.model_dump())
    return shapes.addresses_out(db, [made])[0]


@router.get("/{hid}")
def get_address(hid: str, _: Viewer, db: Db) -> r.AddressOut:
    """Return one address."""
    return shapes.addresses_out(db, [addresses.get_address(db, hid)])[0]


@router.patch("/{hid}")
def update_address(
    hid: str, body: r.AddressPatch, _: Inventory, context: Audit, db: Db
) -> r.AddressOut:
    """Change an address. Marked as primary, it takes the mark from the one that had it."""
    address = addresses.update_address(db, context, hid, body.row_version, _changes(body))
    return shapes.addresses_out(db, [address])[0]


@router.delete("/{hid}", status_code=204)
def delete_address(hid: str, _: Inventory, context: Audit, db: Db) -> None:
    """Remove an address. The audit event of the removal holds what it was."""
    addresses.delete_address(db, context, hid)


ROUTERS = (networks, router)
