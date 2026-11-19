"""What runs on a host has, where it has none of its own, its host's location, planned
location, owner and operator (P-246): in the record, in the list, which filters, sorts
and counts by the same walk, in the summary and the tree, and in the walk shown."""

from typing import Any

import pytest

from tests.api.inventory import Maker
from tests.api.test_hosting import Lab


def _patch(make: Maker, record: dict[str, Any], path: str = "/items", **fields: Any) -> dict:
    now = make.get(f"{path}/{record['hid']}")
    return make.patch(f"{path}/{record['hid']}", {"row_version": now["row_version"], **fields})


def _in_force(make: Maker, item: dict[str, Any], field: str) -> tuple[Any, str, Any]:
    found = make.get(f"/items/{item['hid']}")["effective"][field]
    return found["value"], found["source"], found["source_hid"]


def _listed(make: Maker, condition: str) -> set[str]:
    page = make.get("/items", filter=condition, limit=1000)
    return {row["hid"] for row in page["items"]}


class Placed:
    """The lab, with the server at Room 102 of Site-2, owned and looked after."""

    def __init__(self, make: Maker) -> None:
        self.make = make
        self.lab = Lab(make)
        self.places = make.layout()
        self.elsewhere = make.location("Lab", make.site("Site-3", self.places["central"]))
        self.network = make.owner("Network Engineering")
        self.servers = make.owner("Server Team")
        self.op = make.post("/operators", {"label": "OP2"})
        self.esx = _patch(
            make,
            self.lab.esx,
            location_hid=self.places["room"]["hid"],
            owner_hid=self.servers["hid"],
            operator_hid=self.op["hid"],
        )


@pytest.fixture
def placed(make: Maker) -> Placed:
    return Placed(make)


def test_a_virtual_machine_is_where_its_server_is_and_whose_it_is(placed: Placed) -> None:
    make, lab = placed.make, placed.lab
    vm = lab.vm(host_item_hid=lab.esx["hid"])
    room, esx = placed.places["room"]["hid"], lab.esx["hid"]

    assert _in_force(make, vm, "location_hid") == (room, "host", esx)
    assert _in_force(make, vm, "owner_hid") == (placed.servers["hid"], "host", esx)
    assert _in_force(make, vm, "operator_hid") == (placed.op["hid"], "host", esx)
    shown = make.get(f"/items/{vm['hid']}")["effective"]["location_hid"]
    assert (shown["source_label"], shown["site"]) == ("site2-esx-01", "Site-2")
    # Nothing is copied down: the machine holds none of it.
    record = make.get(f"/items/{vm['hid']}")
    assert (record["location_hid"], record["owner_hid"], record["operator_hid"]) == (None,) * 3

    # The list filters by the same walk, by the place and by the site.
    assert vm["hid"] in _listed(make, f"effective.location_hid:eq:{room}")
    assert vm["hid"] in _listed(make, f"location:within:{placed.places['site']['hid']}")
    assert vm["hid"] in _listed(make, f"effective.owner_hid:eq:{placed.servers['hid']}")
    assert vm["hid"] in _listed(make, "effective.operator_hid.source:eq:host")
    # The server's own operator is its own, held by it, as the machine's is.
    assert _listed(make, f"effective.operator_hid.source_hid:eq:{esx}") == {vm["hid"], esx}

    # Moving the server moves the machine, and writes to none of it.
    _patch(make, lab.esx, location_hid=placed.elsewhere["hid"])
    assert _in_force(make, vm, "location_hid")[0] == placed.elsewhere["hid"]
    assert make.get(f"/items/{vm['hid']}")["row_version"] == record["row_version"]
    # A value of its own overrides.
    _patch(make, vm, owner_hid=placed.network["hid"])
    assert _in_force(make, vm, "owner_hid")[:2] == (placed.network["hid"], "own")


def test_nothing_of_a_hosts_standing_is_passed_on(placed: Placed) -> None:
    make, lab = placed.make, placed.lab
    make.move(make.get(f"/items/{lab.esx['hid']}"), "Assigned")
    vm = lab.vm(host_item_hid=lab.esx["hid"])
    record = make.get(f"/items/{vm['hid']}")
    assert record["effective"]["lifecycle_state"]["value"] is None
    assert vm["hid"] not in _listed(make, "effective.lifecycle_state:eq:Assigned")


def test_a_container_in_a_machine_on_a_server_and_what_is_installed_in_it(
    placed: Placed,
) -> None:
    make, lab = placed.make, placed.lab
    vm = lab.vm(host_item_hid=lab.esx["hid"])
    ctr = lab.ctr(host_item_hid=vm["hid"])
    disk = make.item(name="site2-vm-app01-disk1", parent_item_hid=vm["hid"])
    room, esx = placed.places["room"]["hid"], lab.esx["hid"]

    assert _in_force(make, ctr, "location_hid") == (room, "host", esx)
    assert _in_force(make, disk, "location_hid") == (room, "host", esx)
    assert {ctr["hid"], disk["hid"], vm["hid"]} <= _listed(
        make, f"effective.location_hid:eq:{room}"
    )
    # The machine's own value is nearer to the container than the server's.
    _patch(make, vm, location_hid=placed.elsewhere["hid"])
    assert _in_force(make, ctr, "location_hid") == (placed.elsewhere["hid"], "host", vm["hid"])
    assert _in_force(make, disk, "location_hid") == (
        placed.elsewhere["hid"],
        "parent_item",
        vm["hid"],
    )


def test_a_server_installed_in_a_chassis_passes_on_the_chassis_place(placed: Placed) -> None:
    make, lab = placed.make, placed.lab
    chassis = make.item(name="site2-chassis-01", location_hid=placed.elsewhere["hid"])
    blade = make.item(name="site2-blade-01", parent_item_hid=chassis["hid"])
    vm = lab.vm(host_item_hid=blade["hid"])
    assert _in_force(make, vm, "location_hid") == (placed.elsewhere["hid"], "host", chassis["hid"])
    assert vm["hid"] in _listed(make, f"effective.location_hid:eq:{placed.elsewhere['hid']}")


def test_a_cluster_that_something_runs_on_answers_as_a_group(placed: Placed) -> None:
    make, lab = placed.make, placed.lab
    domain = make.group("site2-dc", "custom", owner_hid=placed.network["hid"])
    cluster = _patch(
        make,
        lab.cluster,
        "/device-groups",
        location_hid=placed.elsewhere["hid"],
        parent_group_hid=domain["hid"],
    )
    vm = lab.vm(host_group_hid=cluster["hid"])

    # A group holds it, so the source is a group's, as for a member: `host` names an item.
    assert _in_force(make, vm, "location_hid") == (
        placed.elsewhere["hid"],
        "device_group",
        cluster["hid"],
    )
    assert make.get(f"/items/{vm['hid']}")["effective"]["location_hid"]["source_label"] == (
        "site2-esx-cluster"
    )
    assert _in_force(make, vm, "owner_hid") == (
        placed.network["hid"],
        "device_group",
        domain["hid"],
    )
    assert vm["hid"] in _listed(make, f"effective.location_hid:eq:{placed.elsewhere['hid']}")
    assert vm["hid"] in _listed(make, f"effective.owner_hid:eq:{placed.network['hid']}")
    # A container in the machine has the cluster's place from the cluster, a group.
    ctr = lab.ctr(host_item_hid=vm["hid"])
    assert _in_force(make, ctr, "location_hid") == (
        placed.elsewhere["hid"],
        "device_group",
        cluster["hid"],
    )
    by_source = "effective.operator_hid.source:eq:host"
    assert ctr["hid"] not in _listed(make, by_source)
    _patch(make, cluster, "/device-groups", operator_hid=placed.op["hid"])
    assert ctr["hid"] in _listed(make, "effective.operator_hid.source:eq:device_group")
    assert ctr["hid"] in _listed(make, f"effective.operator_hid.source_hid:eq:{cluster['hid']}")
    exported = make.client.post(
        "/api/v1/exports",
        json={
            "entity": "items",
            "hids": [ctr["hid"]],
            "columns": ["name", "location_source", "operator_source"],
        },
        headers=make.headers,
    )
    assert exported.text.splitlines()[1].split(",")[2:] == ["device_group", "device_group"]
    # Where the cluster has none, the hosts' own places do not reach the machine.
    _patch(make, cluster, "/device-groups", location_hid=None)
    assert _in_force(make, vm, "location_hid") == (None, "none", None)


def test_the_groups_of_the_host_come_after_the_host_itself(placed: Placed) -> None:
    make, lab = placed.make, placed.lab
    _patch(make, lab.cluster, "/device-groups", operator_hid=None, owner_hid=placed.network["hid"])
    vm = lab.vm(host_item_hid=lab.esx2["hid"])
    assert _in_force(make, vm, "owner_hid") == (
        placed.network["hid"],
        "device_group",
        lab.cluster["hid"],
    )
    # The server's own owner is nearer than its cluster's.
    assert _in_force(make, lab.vm("site2-vm-app02", host_item_hid=lab.esx["hid"]), "owner_hid")[
        :2
    ] == (placed.servers["hid"], "host")


def test_the_resolution_shows_the_step_of_the_host(placed: Placed) -> None:
    make, lab = placed.make, placed.lab
    vm = lab.vm(host_item_hid=lab.esx["hid"])
    walk = make.get(f"/items/{vm['hid']}/resolution")
    location = next(one for one in walk["fields"] if one["field"] == "location_hid")
    assert (location["source"], location["source_hid"]) == ("host", lab.esx["hid"])
    levels = [(step["level"], step["name"], step["outcome"]) for step in location["steps"]]
    assert levels[0] == ("own", "site2-vm-app01", "nothing")
    assert ("host", "site2-esx-01", "decides") in levels
    # The server's cluster is its group, after it, and passed over.
    assert levels[-1][:2] == ("device_group", "site2-esx-cluster")

    on_cluster = lab.vm("site2-vm-app02", host_group_hid=lab.cluster["hid"])
    walk = make.get(f"/items/{on_cluster['hid']}/resolution")
    location = next(one for one in walk["fields"] if one["field"] == "location_hid")
    last = location["steps"][-1]
    assert (last["level"], last["hid"], last["type"]) == (
        "device_group",
        lab.cluster["hid"],
        "cluster",
    )
    assert (location["source"], location["source_hid"]) == ("none", None)


def test_the_summary_and_the_tree_count_it_where_its_host_is(placed: Placed) -> None:
    make, lab = placed.make, placed.lab
    lab.vm(host_item_hid=lab.esx["hid"])
    by_owner = {row["key"]: row for row in make.get("/reports/summary", by="owner")["rows"]}
    assert by_owner[placed.servers["hid"]]["items"] == 2
    by_operator = make.get("/reports/summary", by="operator")["rows"]
    op_row = next(row for row in by_operator if row["key"] == placed.op["hid"])
    assert op_row["items"] == 2
    by_site = {row["label"]: row for row in make.get("/reports/summary", by="site")["rows"]}
    assert by_site["Americas > Central > Site-2"]["items"] == 2

    tree = make.get("/geography/tree")

    def counted(node: dict[str, Any], name: str) -> int | None:
        if node["name"] == name:
            return node["items"]
        for child in node["children"]:
            found = counted(child, name)
            if found is not None:
                return found
        return None

    assert counted(tree["roots"][0], "Room 102") == 2


def test_what_runs_on_a_host_counts_as_a_component_a_node_and_its_weight_at_its_hosts_site(
    placed: Placed,
) -> None:
    make, lab = placed.make, placed.lab
    for model in (lab.vm_model, lab.vdc_model, lab.ctr_model, lab.server_model, lab.switch_model):
        path = f"/catalog-entries/{model['hid']}"
        make.patch(path, {"row_version": make.get(path)["row_version"], "support_weight": "0.5"})
    _patch(make, lab.n7k, location_hid=placed.places["room"]["hid"])
    vm = lab.vm(host_item_hid=lab.esx["hid"])
    vdc = lab.vdc(host_item_hid=lab.n7k["hid"])
    ctr = lab.ctr(host_item_hid=vm["hid"])
    for one in (lab.esx, lab.n7k, vm, vdc, ctr):
        make.move(make.get(f"/items/{one['hid']}"), "Prod")
    rows = {row["label"]: row for row in make.get("/reports/summary", by="site")["rows"]}
    site = rows["Americas > Central > Site-2"]
    # The server, the switch, and the three that run on them, each one of its own.
    assert (site["items"], site["component_count"], site["managed_node_count"]) == (5, 5, 5)
    assert site["support_weight"] == "2.5"
    kinds = {row["key"]: row for row in make.get("/reports/summary", by="kind")["rows"]}
    for kind in ("virtual_machine", "virtual_context", "container"):
        assert kinds[kind]["component_count"] == 1, kind
