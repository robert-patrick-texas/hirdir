"""What runs on a host goes with its host to a planned place (P-246, "A planned location")."""

from typing import Any

from tests.api.inventory import Maker
from tests.api.test_hosting import Lab


def _patch(make: Maker, path: str, **fields: Any) -> dict[str, Any]:
    now = make.get(path)
    return make.patch(path, {"row_version": now["row_version"], **fields})


def test_what_runs_on_a_server_planned_for_a_room_opens_with_it(make: Maker) -> None:
    lab = Lab(make)
    places = make.layout()
    store = make.location("Store Room", places["site"])
    new_site = make.site("Site-3", places["central"], record_status="draft")
    room = make.location("Room 9", new_site)
    _patch(
        make,
        f"/items/{lab.esx['hid']}",
        location_hid=store["hid"],
        planned_location_hid=room["hid"],
    )
    # Twelve things on the server, or in what is on it: ten machines, a container in
    # one of them, and a machine of its own place, in the store room as well.
    machines = [
        lab.vm(f"site2-vm-app{number:02d}", host_item_hid=lab.esx["hid"]) for number in range(1, 10)
    ]
    lab.ctr(host_item_hid=machines[0]["hid"])
    placed = lab.vm("site2-vm-placed", host_item_hid=lab.esx["hid"], location_hid=store["hid"])
    # One on the cluster the server is in, which has no plan: it stays.
    lab.vm("site2-vm-cluster", host_group_hid=lab.cluster["hid"])

    listed = make.get("/items", filter=f"effective.planned_location_hid:eq:{room['hid']}")
    assert listed["total"] == 12
    asked = make.get(f"/locations/{room['hid']}/opening")
    assert (asked["items"], asked["records_changed"]) == (12, 2)
    assert make.get(f"/sites/{new_site['hid']}/opening")["items"] == 12

    _patch(make, f"/sites/{new_site['hid']}", record_status="active")
    server = make.get(f"/items/{lab.esx['hid']}")
    assert (server["location_hid"], server["planned_location_hid"]) == (room["hid"], None)
    moved = make.get(f"/items/{placed['hid']}")
    # It gave its own place up, and is where its server is, with an entry of its own.
    assert moved["location_hid"] is None
    assert moved["effective"]["location_hid"]["value"] == room["hid"]
    history = make.get(f"/items/{placed['hid']}/history")["items"][0]
    assert history["changes"] == [{"field": "location_hid", "old": store["hid"], "new": None}]
    assert make.get("/items", filter=f"effective.location_hid:eq:{room['hid']}")["total"] == 12
