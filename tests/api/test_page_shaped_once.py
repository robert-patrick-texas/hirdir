"""A page of items is shaped with what its parts read again read once (P-326): the
groups of each item, its walk up, what it has in force in a field, the places and the
operators that are retired. What is held is the page's alone: it is let go when the
page is shaped, a change made after it is seen by the next page, and a run that holds
already, as an import does, keeps its own rules."""

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from hirdir.api import shapes
from hirdir.db.models import DeviceGroupMember, Item
from hirdir.domain import groups, held
from tests.api.inventory import Maker


def _stocked(make: Maker) -> list[dict[str, Any]]:
    """Switches in a stack and a cluster at a place with an operator, a module in one,
    and one in nothing: each value in force comes from somewhere else."""
    places = make.layout()
    contact = make.contact("Kim Lee")
    operator = make.post("/operators", {"label": "Campus team", "contact_hid": contact["hid"]})
    make.patch(
        f"/locations/{places['room']['hid']}",
        {
            "row_version": make.get(f"/locations/{places['room']['hid']}")["row_version"],
            "operator_hid": operator["hid"],
        },
    )
    entry = make.entry(make.vendor())
    owner = make.owner()
    stacked = make.switches(entry, "site2-sw", 3)
    make.stack("site2-sw-stack1", stacked[:2], location_hid=places["room"]["hid"])
    make.group("site2-cluster", "cluster", [(stacked[2], "member")], owner_hid=owner["hid"])
    make.item(name="PS-A", parent_item_hid=stacked[0]["hid"], position="PS-A")
    make.item(name="loose-01", catalog_entry_hid=entry["hid"])
    return stacked


# How the statement that reads the memberships of items ends (`groups.memberships_of`).
_MEMBERSHIPS = "ORDER BY device_groups.name_key, device_group_members.hid"


def _statements(db: Session) -> tuple[list[str], Any]:
    sent: list[str] = []

    def note(_connection: object, _cursor: object, statement: str, *_more: object) -> None:
        sent.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", note)
    return sent, note


def test_a_page_reads_the_groups_of_its_items_once(
    client: TestClient, make: Maker, db: Session
) -> None:
    _stocked(make)
    page = list(db.scalars(select(Item).order_by(Item.hid)))
    sent, note = _statements(db)
    try:
        shaped = shapes.items_out(db, page)
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", note)
    # Each value in force that an item has from its groups, its owner, its location,
    # its planned location and its operator, and the groups the page lists, read the
    # memberships of the page's items: once.
    memberships = [one for one in sent if _MEMBERSHIPS in one]
    assert len(memberships) == 1, len(memberships)
    by_name = {one.name or one.hostname: one for one in shaped}
    stacked = by_name["site2-sw-01"]
    assert stacked.effective.location_hid.source == "device_group"
    assert stacked.effective.operator_hid.label == "Campus team"
    clustered = by_name["site2-sw-03"]
    assert clustered.effective.owner_hid.source == "device_group"
    module = by_name["PS-A"]
    # The module has its place from the stack of the switch it is in.
    assert module.effective.location_hid.value == stacked.effective.location_hid.value
    assert module.effective.location_hid.source_hid == stacked.effective.location_hid.source_hid
    # Nothing is held once the page is shaped.
    assert held.of(db) is None


def test_what_a_page_held_is_not_the_next_pages(client: TestClient, make: Maker, db: Session):
    stacked = _stocked(make)
    loose = db.scalars(select(Item).where(Item.name == "loose-01")).one()
    first = shapes.items_out(db, [loose])[0]
    assert first.groups == []
    # A change between two pages, in the same session, is seen by the second.
    stack = db.scalars(
        select(DeviceGroupMember.group_hid).where(DeviceGroupMember.item_hid == stacked[0]["hid"])
    ).one()
    make.add({"hid": stack}, [{"item_hid": loose.hid, "role": "member", "position": 3}])
    db.expire_all()
    db.rollback()
    second = shapes.items_out(db, [db.get_one(Item, loose.hid)])[0]
    assert [one.name for one in second.groups] == ["site2-sw-stack1"]
    assert second.effective.location_hid.source == "device_group"


def test_a_run_that_holds_keeps_its_own_rules(client: TestClient, make: Maker, db: Session):
    """An import holds what a file cannot change, and a row of it may change the groups
    of an item: while it holds, the groups are read anew each time they are asked."""
    stacked = _stocked(make)
    sent, note = _statements(db)
    try:
        with held.holding(db), held.reading(db) as page:
            # Inside a run that holds already, the run's holder stands.
            assert page is held.of(db)
            assert not page.reading
            groups.memberships_of(db, [stacked[0]["hid"]])
            groups.memberships_of(db, [stacked[0]["hid"]])
        with held.reading(db) as page:
            assert page.reading
            groups.memberships_of(db, [stacked[0]["hid"]])
            again = groups.memberships_of(db, [stacked[0]["hid"], stacked[1]["hid"]])
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", note)
    memberships = [one for one in sent if _MEMBERSHIPS in one]
    # Twice while the run held, once for the page, and once more for the item it had
    # not read yet.
    assert len(memberships) == 4
    assert [group.name for _, group in again[stacked[1]["hid"]]] == ["site2-sw-stack1"]
    assert held.of(db) is None
