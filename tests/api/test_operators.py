"""The operator: the person of the team who looks after an item or a device group."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.api.inventory import Maker, errors
from tests.api.test_files import Files


@pytest.fixture
def files(client: TestClient, inventory: dict[str, str]) -> Files:
    return Files(client, inventory)


def _in_force(make: Maker, item: dict[str, Any]) -> tuple[str | None, str, str | None]:
    found = make.get(f"/items/{item['hid']}")["effective"]["operator_hid"]
    return found["label"], found["source"], found["source_hid"]


def _team(make: Maker) -> dict[str, dict[str, Any]]:
    names = ("Dana Whitfield", "Lee Marchetti", "Robin Achterberg", "Priya Raman")
    return {name.split()[0].lower(): make.contact(name) for name in names}


def test_an_item_has_its_own_operator_or_the_one_from_above(make: Maker) -> None:
    team = _team(make)
    switches = make.switches(make.entry(make.vendor()), "site2-sw-core", 3)
    supply = make.item(name="PS-A", parent_item_hid=switches[0]["hid"])
    optic = make.item(name="SFP-1", parent_item_hid=supply["hid"])
    alone = make.item(hostname="site2-sw-lab-01")

    # Nobody is assigned to anything yet.
    assert _in_force(make, switches[0]) == (None, "none", None)
    assert make.get("/items", filter="effective.operator_hid:empty:true")["total"] == 6

    # The stack is given an operator once, and its switches have it, with what is in them.
    stack = make.stack("site2-sw-core", switches, operator_hid=team["lee"]["hid"])
    assert stack["operator"]["name"] == "Lee Marchetti"
    assert stack["effective"]["operator_hid"] == {
        "value": team["lee"]["hid"],
        "label": "Lee Marchetti",
        "source": "own",
        "source_hid": stack["hid"],
        "source_label": None,
    }
    named = make.get(f"/items/{supply['hid']}")["effective"]["operator_hid"]["source_label"]
    assert named == "site2-sw-core"
    for item in (*switches, supply, optic):
        assert _in_force(make, item) == ("Lee Marchetti", "device_group", stack["hid"])
    assert _in_force(make, alone) == (None, "none", None)
    # Nothing was copied down: no item was written to.
    now = make.get(f"/items/{switches[1]['hid']}")
    assert (now["operator_hid"], now["operator"], now["row_version"]) == (None, None, 1)

    # One switch is looked after by somebody else, and so is what is in it; a part of
    # it that is given its own has that.
    first = make.get(f"/items/{switches[0]['hid']}")
    make.patch(
        f"/items/{first['hid']}",
        {"row_version": first["row_version"], "operator_hid": team["robin"]["hid"]},
    )
    assert _in_force(make, switches[0]) == ("Robin Achterberg", "own", switches[0]["hid"])
    assert _in_force(make, optic) == ("Robin Achterberg", "parent_item", switches[0]["hid"])
    make.patch(f"/items/{supply['hid']}", {"row_version": 1, "operator_hid": team["dana"]["hid"]})
    assert _in_force(make, optic) == ("Dana Whitfield", "parent_item", supply["hid"])
    assert _in_force(make, switches[2]) == ("Lee Marchetti", "device_group", stack["hid"])

    # The list finds each by the operator in force, and what nobody looks after.
    assert make.found(filter="operator.name:eq:lee marchetti") == [
        "site2-sw-core-02",
        "site2-sw-core-03",
    ]
    assert make.found(filter=f"effective.operator_hid:eq:{team['dana']['hid']}") == [
        "PS-A",
        "SFP-1",
    ]
    assert make.found(filter=f"operator_hid:eq:{team['dana']['hid']}") == ["PS-A"]
    assert make.found(filter="effective.operator_hid:empty:true") == ["site2-sw-lab-01"]
    assert make.found(filter="operator.email:contains:robin", sort="-operator.name") == [
        "site2-sw-core-01"
    ]
    # Cleared, the switch has the operator of its stack again.
    first = make.get(f"/items/{switches[0]['hid']}")
    make.patch(
        f"/items/{first['hid']}", {"row_version": first["row_version"], "operator_hid": None}
    )
    assert _in_force(make, switches[0]) == ("Lee Marchetti", "device_group", stack["hid"])
    assert make.get(f"/contacts/{team['lee']['hid']}")["uses"] == 1


def test_a_stack_decides_before_a_cluster_and_a_group_has_it_from_the_one_it_is_in(
    make: Maker,
) -> None:
    team = _team(make)
    entry = make.entry(make.vendor())
    controllers = make.switches(entry, "site2-wlc", 2)
    points = make.switches(entry, "site2-ap", 2)
    domain = make.group(
        "site2-wireless",
        "controller_domain",
        [(point, "endpoint") for point in points],
        operator_hid=team["priya"]["hid"],
    )
    cluster = make.group(
        "site2-wlc-ha",
        "cluster",
        [(controllers[0], "active"), (controllers[1], "standby")],
        parent_group_hid=domain["hid"],
    )

    # The cluster has none of its own: it has that of the domain it is nested in, and
    # so have its members. The access points have it as members of the domain.
    assert cluster["operator"] is None
    assert cluster["effective"]["operator_hid"] == {
        "value": team["priya"]["hid"],
        "label": "Priya Raman",
        "source": "device_group",
        "source_hid": domain["hid"],
        "source_label": "site2-wireless",
    }
    for item in (*controllers, *points):
        assert _in_force(make, item) == ("Priya Raman", "device_group", domain["hid"])

    # A controller is in a stack as well: the stack decides before the cluster, when
    # it has an operator, and not while it has none.
    stack = make.group("site2-wlc-stack", "stack", [(controllers[0], "member")])
    assert _in_force(make, controllers[0]) == ("Priya Raman", "device_group", domain["hid"])
    make.patch(
        f"/device-groups/{stack['hid']}",
        {"row_version": stack["row_version"], "operator_hid": team["lee"]["hid"]},
    )
    assert _in_force(make, controllers[0]) == ("Lee Marchetti", "device_group", stack["hid"])
    assert _in_force(make, controllers[1]) == ("Priya Raman", "device_group", domain["hid"])
    # The cluster given its own, its members have that, and the access points do not.
    cluster = make.patch(
        f"/device-groups/{cluster['hid']}",
        {"row_version": cluster["row_version"], "operator_hid": team["dana"]["hid"]},
    )
    assert cluster["effective"]["operator_hid"]["source"] == "own"
    assert _in_force(make, controllers[1]) == ("Dana Whitfield", "device_group", cluster["hid"])
    assert _in_force(make, points[0]) == ("Priya Raman", "device_group", domain["hid"])
    # A member that has left has it no longer, and a retired group gives none.
    member = make.members(domain)[0]
    make.patch(
        f"/device-groups/{domain['hid']}/members/{member['hid']}",
        {"row_version": member["row_version"], "left_on": member["joined_on"]},
    )
    gone = next(point for point in points if point["hid"] == member["item_hid"])
    assert _in_force(make, gone) == (None, "none", None)
    assert make.get("/device-groups", filter="operator.name:contains:priya")["total"] == 1


def test_the_list_and_the_record_agree_on_who_looks_after_every_item(make: Maker) -> None:
    """The operator in force is worked out twice, for a record and for the database to
    filter by. Whatever the inventory holds, the two agree."""
    team = _team(make)
    entry = make.entry(make.vendor())
    switches = make.switches(entry, "sw", 6)
    make.item(name="PS-A", parent_item_hid=switches[0]["hid"], operator_hid=team["dana"]["hid"])
    module = make.item(name="MOD-1", parent_item_hid=switches[1]["hid"])
    make.item(name="SFP-1", parent_item_hid=module["hid"])
    make.stack("stack-b", switches[:2], operator_hid=team["lee"]["hid"])
    outer = make.group("domain", "controller_domain", operator_hid=team["priya"]["hid"])
    make.group(
        "cluster-a",
        "cluster",
        [(switches[1], "active"), (switches[2], "standby")],
        parent_group_hid=outer["hid"],
    )
    make.group("custom-a", "custom", [(switches[3], "member")], operator_hid=team["robin"]["hid"])
    make.group("custom-b", "custom", [(switches[3], "member")], operator_hid=team["dana"]["hid"])
    make.group("empty-handed", "custom", [(switches[4], "member")])

    everything = make.get("/items", limit=1000)["items"]
    by_record: dict[str | None, set[str]] = {}
    for item in everything:
        by_record.setdefault(item["effective"]["operator_hid"]["value"], set()).add(item["hid"])
    assert len(by_record) == 5
    for operator, hids in by_record.items():
        condition = (
            "effective.operator_hid:empty:true"
            if operator is None
            else f"effective.operator_hid:eq:{operator}"
        )
        listed = {row["hid"] for row in make.get("/items", filter=condition, limit=1000)["items"]}
        assert listed == hids, operator
    # Of two groups of one type, the first by name decides.
    assert _in_force(make, switches[3])[0] == "Robin Achterberg"


def test_what_nobody_looks_after_is_a_row_of_the_report(make: Maker) -> None:
    team = _team(make)
    entry = make.entry(make.vendor(), support_weight="1", est_value="1000.00")
    switches = make.switches(entry, "sw", 4, lifecycle_state="Prod")
    make.stack("stack-a", switches[:2], operator_hid=team["lee"]["hid"])
    make.patch(
        f"/items/{switches[2]['hid']}", {"row_version": 1, "operator_hid": team["dana"]["hid"]}
    )

    summary = make.get("/reports/summary", by="operator")
    assert [(row["label"], row["component_count"]) for row in summary["rows"]] == [
        ("Dana Whitfield", 1),
        ("Lee Marchetti", 2),
        (None, 1),
    ]
    assert summary["rows"][1]["key"] == team["lee"]["hid"]
    money = make.get("/reports/management", by="operator")
    assert [(row["label"], row["est_value"]) for row in money["rows"]] == [
        ("Dana Whitfield", "1000.00"),
        ("Lee Marchetti", "2000.00"),
        (None, "1000.00"),
    ]


def test_an_operator_is_a_contact_that_is_there_and_not_retired(make: Maker) -> None:
    team = _team(make)
    nobody = "01900000-0000-7000-8000-000000000000"
    item = make.item(hostname="sw-1", operator_hid=team["lee"]["hid"])
    assert item["operator"]["email"] == "lee.marchetti@example.net"

    assert "operator_hid" in errors(
        make.post("/items", {"hostname": "x", "operator_hid": nobody}, 422)
    )
    group = {"type": "stack", "name": "s", "operator_hid": nobody}
    assert "operator_hid" in errors(make.post("/device-groups", group, 422))
    # A contact that is retired is given nothing further, and stays where it was.
    lee = team["lee"]
    make.post(f"/contacts/{lee['hid']}/retire", {"row_version": lee["row_version"]}, 200)
    refused = make.post("/items", {"hostname": "sw-2", "operator_hid": lee["hid"]}, 422)
    assert "retired" in errors(refused)["operator_hid"]
    kept = make.patch(
        f"/items/{item['hid']}", {"row_version": item["row_version"], "comments": "x"}
    )
    assert kept["operator"]["record_status"] == "retired"
    # Each change is in the history of the item, like any other.
    given = make.patch(
        f"/items/{item['hid']}",
        {"row_version": kept["row_version"], "operator_hid": team["dana"]["hid"]},
    )
    assert given["operator"]["name"] == "Dana Whitfield"
    changes = make.get(f"/items/{item['hid']}/history")["items"][0]["changes"]
    assert changes == [{"field": "operator_hid", "old": lee["hid"], "new": team["dana"]["hid"]}]


def test_the_operator_travels_in_files_and_is_set_on_many_at_once(
    make: Maker, files: Files
) -> None:
    team = _team(make)
    entry = make.entry(make.vendor())
    switches = make.switches(entry, "site2-sw-core", 2)
    make.item(name="PS-A", parent_item_hid=switches[0]["hid"])
    lee, robin = "lee.marchetti@example.net", "robin.achterberg@example.net"

    files.load("device_groups", f"name,type,operator\nsite2-sw-core,stack,{lee}\n")
    files.load(
        "device_group_members",
        "group,item,role\nsite2-sw-core,SITE2-SW-CORE-001,master\n"
        "site2-sw-core,SITE2-SW-CORE-002,member\n",
    )
    # A file of the values in force holds the operator for every row, and loading it
    # makes no override of what an item has anyway.
    exported = files.export("items", columns=["serial_number", "name", "operator"])
    assert exported.count(lee) == 3
    again = files.preview("items", exported)
    assert (again["job"]["unchanged"], again["job"]["rejected"]) == (3, 0)
    files.apply(again)
    assert make.get(f"/items/{switches[1]['hid']}")["operator_hid"] is None
    sources = files.export("items", columns=["name", "operator"], include_sources=True)
    assert "device_group" in sources
    # A row that names another gives the item its own, by email address or by name,
    # and `!clear` returns it to the one from above.
    files.load("items", f"hid,operator\n{switches[1]['hid']},Robin Achterberg\n")
    assert _in_force(make, switches[1])[:2] == ("Robin Achterberg", "own")
    files.load("items", f"hid,operator\n{switches[1]['hid']},!clear\n")
    assert _in_force(make, switches[1])[:2] == ("Lee Marchetti", "device_group")
    unknown = files.preview("items", f"hid,operator\n{switches[1]['hid']},nobody@example.net\n")
    assert unknown["rows"][0]["reasons"][0]["field"] == "operator"
    # Every file comes back as it went.
    for entity in ("items", "device_groups"):
        back = files.preview(entity, files.export(entity, own_values=True))
        assert back["job"]["unchanged"] == back["job"]["row_count"], (entity, back["rows"])
    # A bulk edit gives many items an operator at once.
    more = make.switches(entry, "site2-sw-access", 3)
    edit = make.post(
        "/items/bulk-update",
        {"filter": "hostname:prefix:site2-sw-access", "set": {"operator": robin}},
        201,
    )
    assert edit["job"]["updated"] == 3
    make.post(f"/items/bulk-update/{edit['job']['hid']}/apply", {}, 200)
    assert _in_force(make, more[2])[:2] == ("Robin Achterberg", "own")
    assert make.get(f"/contacts/{team['robin']['hid']}")["uses"] == 3
