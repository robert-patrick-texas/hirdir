"""The routes of items: the grid's list, the record, its history and its lifecycle."""

from fastapi import APIRouter

from hirdir.api import lists, shapes, views
from hirdir.api import records as r
from hirdir.api.deps import Audit, Db, Inventory, Viewer
from hirdir.api.lists import Limit, Listed, Offset
from hirdir.api.schemas import AuditEventOut, Page
from hirdir.domain import items
from hirdir.domain.lifecycle import UNSET
from hirdir.io import fields

router = APIRouter(prefix="/items", tags=["Items"])


def _page(db: Db, listed: lists.ListRequest) -> Page[r.ItemOut]:
    page, total = lists.read(db, fields.ITEMS, listed)
    return Page(
        items=shapes.items_out(db, page), total=total, limit=listed.limit, offset=listed.offset
    )


@router.get("")
def list_items(_: Viewer, db: Db, listed: Listed) -> Page[r.ItemOut]:
    """List items, by name unless a sort says otherwise.

    Drafts, retired items and items in Archived are left out unless asked for.
    """
    return _page(db, listed)


@router.post("/query")
def query_items(body: r.ListQuery, _: Viewer, db: Db) -> Page[r.ItemOut]:
    """List items, with the filter and sort in the body."""
    return _page(db, lists.from_body(body))


@router.post("", status_code=201)
def create_item(body: r.ItemCreate, _: Inventory, context: Audit, db: Db) -> r.ItemOut:
    """Create an item. What is not given stays blank."""
    return shapes.item_out(db, items.create_item(db, context, body.model_dump()))


@router.get("/{hid}")
def get_item(hid: str, _: Viewer, db: Db) -> r.ItemOut:
    """Return one item, whatever its status."""
    return shapes.item_out(db, items.get_item(db, hid))


@router.patch("/{hid}")
def update_item(hid: str, body: r.ItemPatch, _: Inventory, context: Audit, db: Db) -> r.ItemOut:
    """Change an item. Null clears a field, and a cleared field that inherits does so again."""
    changes = body.model_dump(exclude={"row_version"}, exclude_unset=True)
    return shapes.item_out(db, items.update_item(db, context, hid, body.row_version, changes))


@router.post("/{hid}/retire")
def retire_item(hid: str, body: r.RowVersion, _: Inventory, context: Audit, db: Db) -> r.ItemOut:
    """Retire an item. Its record and history are kept."""
    return shapes.item_out(db, items.retire_item(db, context, hid, body.row_version))


@router.post("/{hid}/transition")
def transition_item(
    hid: str, body: r.Transition, principal: Inventory, context: Audit, db: Db
) -> r.ItemOut:
    """Move an item to another lifecycle state, recording who, when, from, to and why."""
    given = body.model_fields_set
    item = items.transition(
        db,
        context,
        hid,
        body.row_version,
        to=body.to,
        role=principal.role,
        reason=body.reason,
        disposition=body.disposition if "disposition" in given else UNSET,
        expected_online=body.expected_online if "expected_online" in given else UNSET,
        force=body.force,
    )
    return shapes.item_out(db, item)


@router.get("/{hid}/history")
def item_history(
    hid: str, _: Viewer, db: Db, limit: Limit = 100, offset: Offset = 0
) -> Page[AuditEventOut]:
    """List every change made to one item, newest first."""
    page, total = items.history(db, hid, limit, offset)
    return Page(
        items=[views.audit_out(db, event) for event in page],
        total=total,
        limit=limit,
        offset=offset,
    )


ROUTERS = (router,)
