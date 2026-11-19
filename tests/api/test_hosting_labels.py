"""What a value in force came from is named, and the walk says what each record is to the
item (P-246, P-176)."""

from typing import Any

from tests.api.inventory import Maker
from tests.api.test_hosting import Lab


def _patch(make: Maker, path: str, **fields: Any) -> dict[str, Any]:
    now = make.get(path)
    return make.patch(path, {"row_version": now["row_version"], **fields})


def _from(found: dict[str, Any], field: str) -> tuple[str, str | None]:
    one = found["effective"][field]
    return one["source"], one["source_label"]


def test_the_source_of_each_of_the_four_values_is_named(make: Maker) -> None:
    lab = Lab(make)
    places = make.layout()
    owner = make.owner("Server Team")
    op = make.post("/operators", {"label": "OP2"})
    _patch(
        make,
        f"/items/{lab.esx['hid']}",
        owner_hid=owner["hid"],
        operator_hid=op["hid"],
        location_hid=places["room"]["hid"],
    )
    vm = lab.vm(host_item_hid=lab.esx["hid"])
    ctr = lab.ctr(host_item_hid=vm["hid"])
    found = make.get(f"/items/{ctr['hid']}")
    # Each from the server, two hosts up, by its name.
    for field in ("owner_hid", "operator_hid", "location_hid"):
        assert _from(found, field) == ("host", "site2-esx-01"), field
    # And in a list's rows the same.
    row = make.get("/items", filter=f"hid:eq:{ctr['hid']}")["items"][0]
    assert _from(row, "owner_hid") == ("host", "site2-esx-01")

    # From the cluster a machine runs on, a group, by the group's name.
    network = make.owner("Network Engineering")
    _patch(make, f"/device-groups/{lab.cluster['hid']}", owner_hid=network["hid"])
    on_cluster = lab.vm("site2-vm-app02", host_group_hid=lab.cluster["hid"])
    found = make.get(f"/items/{on_cluster['hid']}")
    assert _from(found, "owner_hid") == ("device_group", "site2-esx-cluster")
    # Its own says nothing of where it is from.
    own = make.get(f"/items/{lab.esx['hid']}")
    assert _from(own, "owner_hid") == ("own", None)


def test_the_walk_says_what_each_record_is_to_the_item(make: Maker) -> None:
    lab = Lab(make)
    vm = lab.vm(host_item_hid=lab.esx["hid"])
    ctr = lab.ctr(host_item_hid=vm["hid"])
    disk = make.item(name="site2-vm-app01-disk1", parent_item_hid=vm["hid"])
    on_cluster = lab.vm("site2-vm-app02", host_group_hid=lab.cluster["hid"])

    def steps(item: dict[str, Any]) -> list[tuple[str, str | None, str | None]]:
        walk = make.get(f"/items/{item['hid']}/resolution")["fields"]
        owner = next(one for one in walk if one["field"] == "owner_hid")
        return [(one["level"], one["name"], one["reached_by"]) for one in owner["steps"]]

    assert steps(ctr) == [
        ("own", "site2-ctr-dns1", None),
        ("host", "site2-vm-app01", "host"),
        ("host", "site2-esx-01", "host"),
        # The cluster the server is a member of.
        ("device_group", "site2-esx-cluster", "member"),
    ]
    assert steps(disk)[1] == ("parent_item", "site2-vm-app01", "parent")
    # The cluster a machine runs on is a group's step, reached as its host.
    assert steps(on_cluster)[-1] == ("device_group", "site2-esx-cluster", "host")
    # A group's own walk reaches the group it is nested in as its parent.
    domain = make.group("site2-dc", "custom")
    _patch(make, f"/device-groups/{lab.cluster['hid']}", parent_group_hid=domain["hid"])
    walk = make.get(f"/device-groups/{lab.cluster['hid']}/resolution")["fields"][0]["steps"]
    assert [one["reached_by"] for one in walk] == [None, "parent"]
