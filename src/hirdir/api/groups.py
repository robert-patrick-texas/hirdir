"""The routes of device groups and their members."""

from typing import Annotated

from fastapi import APIRouter, Query

from hirdir.api import lists, shapes
from hirdir.api import records as r
from hirdir.api.deps import Audit, Db, Inventory, Viewer
from hirdir.api.idempotent import IdempotentRoute
from hirdir.api.lists import Limit, Listed, Offset
from hirdir.api.schemas import Page
from hirdir.domain import groups
from hirdir.io import fields

router = APIRouter(prefix="/device-groups", tags=["Groups"], route_class=IdempotentRoute)


def _page(db: Db, listed: lists.ListRequest) -> Page[r.DeviceGroupOut]:
    page, total = lists.read(db, fields.DEVICE_GROUPS, listed)
    return lists.narrowed(
        Page(
            items=shapes.groups_out(db, page),
            total=total,
            limit=listed.limit,
            offset=listed.offset,
        ),
        listed,
        r.DeviceGroupOut,
    )


@router.get("")
def list_groups(_: Viewer, db: Db, listed: Listed) -> Page[r.DeviceGroupOut]:
    """List device groups, by name unless a sort says otherwise.

    Drafts and retired groups are left out unless asked for.
    """
    return _page(db, listed)


@router.post("/query")
def query_groups(body: r.ListQuery, _: Viewer, db: Db) -> Page[r.DeviceGroupOut]:
    """List device groups, with the filter and sort in the body."""
    return _page(db, lists.from_body(body))


@router.post("", status_code=201)
def create_group(
    body: r.DeviceGroupCreate, _: Inventory, context: Audit, db: Db
) -> r.DeviceGroupOut:
    """Create a device group, with its members if they are given.

    A stack needs no master and may be one switch alone. Of the members given, at
    most one is marked `master`, the master that is intended.
    """
    return shapes.group_out(db, groups.create_group(db, context, body.model_dump()))


@router.get("/{hid}")
def get_group(hid: str, _: Viewer, db: Db) -> r.DeviceGroupOut:
    """Return one device group, whatever its status."""
    return shapes.group_out(db, groups.get_group(db, hid))


@router.patch("/{hid}")
def update_group(
    hid: str, body: r.DeviceGroupPatch, _: Inventory, context: Audit, db: Db
) -> r.DeviceGroupOut:
    """Change a device group."""
    changes = body.model_dump(exclude={"row_version"}, exclude_unset=True)
    return shapes.group_out(db, groups.update_group(db, context, hid, body.row_version, changes))


@router.post("/{hid}/retire")
def retire_group(
    hid: str, body: r.RowVersion, _: Inventory, context: Audit, db: Db
) -> r.DeviceGroupOut:
    """Retire a device group. Its record is kept, and its current memberships end today."""
    return shapes.group_out(db, groups.retire_group(db, context, hid, body.row_version))


@router.get("/{hid}/members")
def list_members(
    hid: str,
    _: Viewer,
    db: Db,
    include_past: Annotated[
        bool, Query(description="Show the memberships that have ended as well.")
    ] = False,
    limit: Limit = 100,
    offset: Offset = 0,
) -> Page[r.MemberOut]:
    """List the members of a group by position, the current ones first."""
    page, total = groups.list_members(db, hid, include_past, limit, offset)
    return Page(items=shapes.members_out(db, page), total=total, limit=limit, offset=offset)


@router.post("/{hid}/members", status_code=201)
def add_members(
    hid: str, body: r.MembersAdd, _: Inventory, context: Audit, db: Db
) -> list[r.MemberOut]:
    """Make items members of a group, all together.

    One that is added to a stack as `master`, the master that is intended, takes the
    mark from the member that had it.
    """
    made = groups.add_members(db, context, hid, [member.model_dump() for member in body.members])
    return shapes.members_out(db, made)


@router.patch("/{hid}/members/{member_hid}")
def update_member(
    hid: str, member_hid: str, body: r.MemberPatch, _: Inventory, context: Audit, db: Db
) -> r.MemberOut:
    """Change a membership. `left_on` ends it; it is never removed.

    Marking a member as the intended master of a stack takes the mark from the member
    that had it. The master that is seen is recorded on the stack itself.
    """
    changes = body.model_dump(exclude={"row_version"}, exclude_unset=True)
    member = groups.update_member(db, context, hid, member_hid, body.row_version, changes)
    return shapes.members_out(db, [member])[0]


ROUTERS = (router,)
