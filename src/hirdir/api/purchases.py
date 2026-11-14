"""The routes of purchase requests, their lines, and receiving."""

from typing import Any

from fastapi import APIRouter

from hirdir.api import lists, shapes
from hirdir.api import records as r
from hirdir.api.deps import Audit, Db, Inventory, Viewer
from hirdir.api.idempotent import IdempotentRoute
from hirdir.api.lists import Listed
from hirdir.api.schemas import Page
from hirdir.db.models import PurchaseLine
from hirdir.domain import purchases
from hirdir.io import fields

requests = APIRouter(prefix="/purchase-requests", tags=["Purchases"], route_class=IdempotentRoute)
lines = APIRouter(prefix="/purchase-lines", tags=["Purchases"], route_class=IdempotentRoute)


def _changes(body: r.Model) -> dict:
    return body.model_dump(exclude={"row_version"}, exclude_unset=True)


def _page(items: list[Any], total: int, listed: lists.ListRequest, model: Any) -> Any:
    return lists.narrowed(
        Page(items=items, total=total, limit=listed.limit, offset=listed.offset), listed, model
    )


@requests.get("")
def list_requests(_: Viewer, db: Db, listed: Listed) -> Page[r.PurchaseRequestOut]:
    """List purchase requests, by reference unless a sort says otherwise."""
    page, total = lists.read(db, fields.PURCHASE_REQUESTS, listed)
    return _page(shapes.requests_out(db, page), total, listed, r.PurchaseRequestOut)


@requests.post("", status_code=201)
def create_request(
    body: r.PurchaseRequestCreate, _: Inventory, context: Audit, db: Db
) -> r.PurchaseRequestOut:
    """Create a purchase request, with its lines if they are known. Nothing of it is
    inventory until a line is received."""
    given = body.model_dump(exclude={"lines"})
    made = purchases.create_request(db, context, given)
    for line in body.lines:
        purchases.add_line(db, context, made.hid, line.model_dump(exclude_unset=True))
    return shapes.requests_out(db, [made])[0]


@requests.get("/{hid}")
def get_request(hid: str, _: Viewer, db: Db) -> r.PurchaseRequestOut:
    """Return one purchase request, with its lines."""
    return shapes.requests_out(db, [purchases.get_request(db, hid)])[0]


@requests.patch("/{hid}")
def update_request(
    hid: str, body: r.PurchaseRequestPatch, _: Inventory, context: Audit, db: Db
) -> r.PurchaseRequestOut:
    """Change a purchase request. Its status is what a person says of it."""
    changed = purchases.update_request(db, context, hid, body.row_version, _changes(body))
    return shapes.requests_out(db, [changed])[0]


@requests.get("/{hid}/lines")
def list_request_lines(hid: str, _: Viewer, db: Db, listed: Listed) -> Page[r.PurchaseLineOut]:
    """List the lines of a purchase request, by their numbers unless a sort says
    otherwise."""
    purchases.get_request(db, hid)
    page, total = lists.read(
        db, fields.PURCHASE_LINES, listed, also=[PurchaseLine.request_hid == hid]
    )
    return _page(shapes.lines_out(db, page), total, listed, r.PurchaseLineOut)


@requests.post("/{hid}/lines", status_code=201)
def add_line(
    hid: str, body: r.PurchaseLineAdd, _: Inventory, context: Audit, db: Db
) -> r.PurchaseLineOut:
    """Add a line to a purchase request: a model and how many."""
    made = purchases.add_line(db, context, hid, body.model_dump(exclude_unset=True))
    return shapes.lines_out(db, [made])[0]


@lines.get("")
def list_lines(_: Viewer, db: Db, listed: Listed) -> Page[r.PurchaseLineOut]:
    """List the lines of every purchase request. `pending_quantity:gt:0` keeps to what
    is still to come: the planning list."""
    page, total = lists.read(db, fields.PURCHASE_LINES, listed)
    return _page(shapes.lines_out(db, page), total, listed, r.PurchaseLineOut)


@lines.get("/{hid}")
def get_line(hid: str, _: Viewer, db: Db) -> r.PurchaseLineOut:
    """Return one purchase line."""
    return shapes.lines_out(db, [purchases.get_line(db, hid)])[0]


@lines.patch("/{hid}")
def update_line(
    hid: str, body: r.PurchaseLinePatch, _: Inventory, context: Audit, db: Db
) -> r.PurchaseLineOut:
    """Change a purchase line. Its quantity is never below what has arrived on it: a
    line is taken back by lowering it to that."""
    changed = purchases.update_line(db, context, hid, body.row_version, _changes(body))
    return shapes.lines_out(db, [changed])[0]


@lines.post("/{hid}/receive", status_code=201)
def receive_line(hid: str, body: r.Receive, _: Inventory, context: Audit, db: Db) -> r.ReceivedOut:
    """Receive items on a line: each is created in Delivered, of the line's model, and
    names the line. Either all of them are created or none is."""
    line, made = purchases.receive(
        db,
        context,
        hid,
        body.row_version,
        [one.model_dump(exclude_unset=True) for one in body.items],
        body.delivered_on,
        body.location_hid,
    )
    return shapes.received_out(db, line, made)


ROUTERS = (requests, lines)
