"""Operators: the labels that stand for who of the team looks after what."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.api.inventory import API, Maker, errors
from tests.api.test_files import Files


@pytest.fixture
def files(client: TestClient, inventory: dict[str, str]) -> Files:
    return Files(client, inventory)


def _in_force(make: Maker, item: dict[str, Any]) -> tuple[str | None, str, str | None]:
    found = make.get(f"/items/{item['hid']}")["effective"]["operator_hid"]
    return found["label"], found["source"], found["source_hid"]


def _team(make: Maker) -> dict[str, dict[str, Any]]:
    """Make four people and a label for each: LM, RA, DW and PR."""
    marks = {}
    for label, name in (
        ("LM", "Lee Marchetti"),
        ("RA", "Robin Achterberg"),
        ("DW", "Dana Whitfield"),
        ("PR", "Priya Raman"),
    ):
        contact = make.contact(name)
        marks[label] = make.post("/operators", {"label": label, "contact_hid": contact["hid"]})
    return marks


def _patch(make: Maker, path: str, **fields: Any) -> dict[str, Any]:
    now = make.get(path)
    return make.patch(path, {"row_version": now["row_version"], **fields})


def test_an_operator_is_a_label_with_a_person_behind_it(
    make: Maker, client: TestClient, viewer: dict[str, str]
) -> None:
    lee = make.contact("Lee Marchetti")
    made = make.post(
        "/operators",
        {"label": "LM", "description": "Core", "colour": "#1F6FEB", "contact_hid": lee["hid"]},
    )
    assert (made["label"], made["colour"], made["is_open"], made["uses"]) == (
        "LM",
        "#1f6feb",
        False,
        0,
    )
    assert made["contact"]["name"] == "Lee Marchetti"
    assert "label" in errors(make.post("/operators", {"label": "lm"}, 409))
    assert "label" in errors(make.post("/operators", {"label": "x" * 41}, 422))
    assert "label" in errors(make.post("/operators", {"label": "A;B"}, 422))
    assert "colour" in errors(make.post("/operators", {"label": "X", "colour": "blue"}, 422))
    nobody = "01900000-0000-7000-8000-000000000000"
    assert "contact_hid" in errors(
        make.post("/operators", {"label": "X", "contact_hid": nobody}, 422)
    )
    # A label may stand with nobody behind it: an open assignment.
    spare = make.post("/operators", {"label": "Op2"})
    assert (spare["contact"], spare["is_open"]) == (None, True)
    assert [one["label"] for one in make.get("/operators", filter="is_open:eq:true")["items"]] == [
        "Op2"
    ]
    assert make.get("/operators", filter="contact.name:contains:lee")["total"] == 1
    assert make.get(f"/contacts/{lee['hid']}")["uses"] == 1
    # Only Inventory changes it, and each change is in the audit trail.
    for method, path, body in (
        ("POST", "/operators", {"label": "Y"}),
        ("PATCH", f"/operators/{made['hid']}", {"row_version": 1, "description": "x"}),
        ("POST", f"/operators/{made['hid']}/retire", {"row_version": 1}),
    ):
        assert client.request(method, API + path, json=body, headers=viewer).status_code == 403
        assert client.request(method, API + path, json=body).status_code == 401
    assert client.get(f"{API}/operators", headers=viewer).status_code == 200
    events = make.audit(record_type="operator", record_hid=made["hid"])
    assert [event["action"] for event in events] == ["create"]


def test_an_item_has_its_own_operator_or_the_one_from_above(make: Maker) -> None:
    marks = _team(make)
    switches = make.switches(make.entry(make.vendor()), "site2-sw-core", 3)
    supply = make.item(name="PS-A", parent_item_hid=switches[0]["hid"])
    optic = make.item(name="SFP-1", parent_item_hid=supply["hid"])
    alone = make.item(hostname="site2-sw-lab-01")

    # Nobody is assigned to anything yet.
    assert _in_force(make, switches[0]) == (None, "none", None)
    assert make.get("/items", filter="effective.operator_hid:empty:true")["total"] == 6

    # The stack is given an operator once, and its switches have it, with what is in them.
    stack = make.stack("site2-sw-core", switches, operator_hid=marks["LM"]["hid"])
    assert stack["operator"] == {
        "hid": marks["LM"]["hid"],
        "label": "LM",
        "colour": None,
        "contact_hid": marks["LM"]["contact_hid"],
        "contact": "Lee Marchetti",
        "is_open": False,
        "record_status": "active",
    }
    assert stack["effective"]["operator_hid"] == {
        "value": marks["LM"]["hid"],
        "label": "LM",
        "source": "own",
        "source_hid": stack["hid"],
        "source_label": None,
        "colour": None,
        "contact_hid": marks["LM"]["contact_hid"],
        "contact": "Lee Marchetti",
        "is_open": False,
    }
    for item in (*switches, supply, optic):
        assert _in_force(make, item) == ("LM", "device_group", stack["hid"])
    named = make.get(f"/items/{supply['hid']}")["effective"]["operator_hid"]
    assert (named["source_label"], named["contact"]) == ("site2-sw-core", "Lee Marchetti")
    assert _in_force(make, alone) == (None, "none", None)
    # Nothing was copied down: no item was written to.
    now = make.get(f"/items/{switches[1]['hid']}")
    assert (now["operator_hid"], now["operator"], now["row_version"]) == (None, None, 1)

    # One switch is looked after by somebody else, and so is what is in it; a part of
    # it that is given its own has that.
    _patch(make, f"/items/{switches[0]['hid']}", operator_hid=marks["RA"]["hid"])
    assert _in_force(make, switches[0]) == ("RA", "own", switches[0]["hid"])
    assert _in_force(make, optic) == ("RA", "parent_item", switches[0]["hid"])
    _patch(make, f"/items/{supply['hid']}", operator_hid=marks["DW"]["hid"])
    assert _in_force(make, optic) == ("DW", "parent_item", supply["hid"])
    assert _in_force(make, switches[2]) == ("LM", "device_group", stack["hid"])

    # The list finds each by the operator in force, and what nobody looks after.
    assert make.found(filter="operator.label:eq:lm") == ["site2-sw-core-02", "site2-sw-core-03"]
    assert make.found(filter=f"effective.operator_hid:eq:{marks['DW']['hid']}") == [
        "PS-A",
        "SFP-1",
    ]
    assert make.found(filter=f"operator_hid:eq:{marks['DW']['hid']}") == ["PS-A"]
    assert make.found(filter="effective.operator_hid:empty:true") == ["site2-sw-lab-01"]
    assert make.found(filter="operator.contact:contains:robin", sort="-operator.label") == [
        "site2-sw-core-01"
    ]
    # Cleared, the switch has the operator of its stack again.
    _patch(make, f"/items/{switches[0]['hid']}", operator_hid=None)
    assert _in_force(make, switches[0]) == ("LM", "device_group", stack["hid"])
    assert make.get(f"/operators/{marks['LM']['hid']}")["uses"] == 1


def test_a_stack_decides_before_a_cluster_and_a_group_has_it_from_the_one_it_is_in(
    make: Maker,
) -> None:
    marks = _team(make)
    entry = make.entry(make.vendor())
    controllers = make.switches(entry, "site2-wlc", 2)
    points = make.switches(entry, "site2-ap", 2)
    domain = make.group(
        "site2-wireless",
        "controller_domain",
        [(point, "endpoint") for point in points],
        operator_hid=marks["PR"]["hid"],
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
    in_force = cluster["effective"]["operator_hid"]
    assert (in_force["label"], in_force["source"], in_force["source_hid"]) == (
        "PR",
        "device_group",
        domain["hid"],
    )
    assert in_force["source_label"] == "site2-wireless"
    for item in (*controllers, *points):
        assert _in_force(make, item) == ("PR", "device_group", domain["hid"])

    # A controller is in a stack as well: the stack decides before the cluster, when
    # it has an operator, and not while it has none.
    stack = make.group("site2-wlc-stack", "stack", [(controllers[0], "member")])
    assert _in_force(make, controllers[0]) == ("PR", "device_group", domain["hid"])
    _patch(make, f"/device-groups/{stack['hid']}", operator_hid=marks["LM"]["hid"])
    assert _in_force(make, controllers[0]) == ("LM", "device_group", stack["hid"])
    assert _in_force(make, controllers[1]) == ("PR", "device_group", domain["hid"])
    # The cluster given its own, its members have that, and the access points do not.
    cluster = _patch(make, f"/device-groups/{cluster['hid']}", operator_hid=marks["DW"]["hid"])
    assert cluster["effective"]["operator_hid"]["source"] == "own"
    assert _in_force(make, controllers[1]) == ("DW", "device_group", cluster["hid"])
    assert _in_force(make, points[0]) == ("PR", "device_group", domain["hid"])
    # A member that has left has it no longer.
    member = make.members(domain)[0]
    make.patch(
        f"/device-groups/{domain['hid']}/members/{member['hid']}",
        {"row_version": member["row_version"], "left_on": member["joined_on"]},
    )
    gone = next(point for point in points if point["hid"] == member["item_hid"])
    assert _in_force(make, gone) == (None, "none", None)
    assert make.get("/device-groups", filter="operator.label:eq:pr")["total"] == 1


def test_what_is_at_a_place_has_the_operator_of_the_place(make: Maker) -> None:
    marks = _team(make)
    places = make.layout()
    room, building, site, central = (
        places[name] for name in ("room", "building", "site", "central")
    )
    switch = make.item(hostname="site2-sw-access-01", location_hid=room["hid"])
    supply = make.item(name="PS-A", parent_item_hid=switch["hid"])
    nowhere = make.item(hostname="spare-01")

    # The region is given an operator: a device that arrives there is never nobody's.
    _patch(make, f"/regions/{central['hid']}", operator_hid=marks["DW"]["hid"])
    assert _in_force(make, switch) == ("DW", "region", central["hid"])
    found = make.get(f"/items/{supply['hid']}")["effective"]["operator_hid"]
    assert (found["label"], found["source"], found["source_label"]) == (
        "DW",
        "region",
        "Americas > Central",
    )
    assert _in_force(make, nowhere) == (None, "none", None)
    # The nearer place decides: the site before the region, the building before the
    # site, the room before the building.
    for level, place, label in (
        ("site", site, "RA"),
        ("location", building, "LM"),
        ("location", room, "PR"),
    ):
        _patch(make, f"/{level}s/{place['hid']}", operator_hid=marks[label]["hid"])
        assert _in_force(make, switch) == (label, level, place["hid"])
    # A group the item is in decides before the place, and its own before both.
    stack = make.group("stack-1", "stack", [(switch, "member")], operator_hid=marks["DW"]["hid"])
    assert _in_force(make, switch) == ("DW", "device_group", stack["hid"])
    _patch(make, f"/items/{switch['hid']}", operator_hid=marks["RA"]["hid"])
    assert _in_force(make, switch) == ("RA", "own", switch["hid"])

    # What a place has in force says its operator, the level it came from, and what
    # it overrides.
    here = make.get(f"/locations/{room['hid']}/effective")["operator"]
    assert (here["value"]["label"], here["source"], here["overrides_path"]) == (
        "PR",
        "own",
        "Americas > Central > Site-2 > Building 1",
    )
    floor = make.location("Floor 2", parent=building)
    there = make.get(f"/locations/{floor['hid']}/effective")["operator"]
    assert (there["value"]["contact"], there["source"], there["source_path"]) == (
        "Lee Marchetti",
        "location",
        "Americas > Central > Site-2 > Building 1",
    )
    assert make.get(f"/sites/{site['hid']}")["operator"]["label"] == "RA"
    assert make.get("/sites", filter=f"operator_hid:eq:{marks['RA']['hid']}")["total"] == 1
    nobody = "01900000-0000-7000-8000-000000000000"
    assert "operator_hid" in errors(
        make.patch(f"/sites/{site['hid']}", {"row_version": 99, "operator_hid": nobody}, 422)
    )


def test_a_label_is_handed_over_left_open_and_released_in_one_change(make: Maker) -> None:
    marks = _team(make)
    places = make.layout()
    switches = make.switches(make.entry(make.vendor()), "sw", 3, lifecycle_state="Prod")
    for switch in switches:
        _patch(make, f"/items/{switch['hid']}", location_hid=places["room"]["hid"])
    stack = make.stack("stack-1", switches[:2], operator_hid=marks["LM"]["hid"])
    _patch(make, f"/sites/{places['site']['hid']}", operator_hid=marks["RA"]["hid"])
    versions = [make.get(f"/items/{switch['hid']}")["row_version"] for switch in switches]
    lm = f"/operators/{marks['LM']['hid']}"

    # A new hire takes over what LM looks after: one change, of the label alone.
    hire = make.contact("Sam Okafor")
    handed = _patch(make, lm, contact_hid=hire["hid"])
    assert (handed["contact"]["name"], handed["uses"]) == ("Sam Okafor", 1)
    found = make.get(f"/items/{switches[0]['hid']}")["effective"]["operator_hid"]
    assert (found["label"], found["contact"], found["is_open"]) == ("LM", "Sam Okafor", False)
    assert make.found(filter="operator.contact:eq:sam okafor") == ["sw-01", "sw-02"]

    # The person leaves: the label stands open, and what it is on stays together.
    opened = _patch(make, lm, contact_hid=None)
    assert (opened["contact"], opened["is_open"]) == (None, True)
    found = make.get(f"/items/{switches[0]['hid']}")["effective"]["operator_hid"]
    assert (found["label"], found["contact"], found["is_open"]) == ("LM", None, True)
    assert make.found(filter="operator.is_open:eq:true") == ["sw-01", "sw-02"]
    assert make.get("/items", filter="effective.operator_hid:empty:true")["total"] == 0
    # A label whose person is retired is open too.
    back = _patch(make, lm, contact_hid=hire["hid"])
    assert back["is_open"] is False
    make.post(f"/contacts/{hire['hid']}/retire", {"row_version": hire["row_version"]}, 200)
    assert make.get(lm)["is_open"] is True
    assert make.found(filter="operator.is_open:eq:true") == ["sw-01", "sw-02"]

    # Released, the label stands for nothing: each switch has the operator of the next
    # level up, here that of the site.
    released = make.post(f"{lm}/retire", {"row_version": make.get(lm)["row_version"]}, 200)
    assert released["record_status"] == "retired"
    assert _in_force(make, switches[0]) == ("RA", "site", places["site"]["hid"])
    assert make.found(filter="operator.label:eq:ra") == ["sw-01", "sw-02", "sw-03"]
    assert make.get("/operators")["total"] == 3
    group = make.get(f"/device-groups/{stack['hid']}")
    assert (group["operator"]["record_status"], group["effective"]["operator_hid"]["value"]) == (
        "retired",
        None,
    )
    # A released label is given to nothing further.
    assert "operator_hid" in errors(
        make.post("/items", {"hostname": "x", "operator_hid": marks["LM"]["hid"]}, 422)
    )
    # With the site's label released as well, nobody is assigned.
    make.post(f"/operators/{marks['RA']['hid']}/retire", {"row_version": 1}, 200)
    assert make.get("/items", filter="effective.operator_hid:empty:true")["total"] == 3
    summary = make.get("/reports/summary", by="operator")
    assert [(row["label"], row["component_count"]) for row in summary["rows"]] == [(None, 3)]
    # Brought back, it is on everything it was on, and none of it was ever written to.
    _patch(make, lm, record_status="active")
    assert _in_force(make, switches[1]) == ("LM", "device_group", stack["hid"])
    assert [make.get(f"/items/{switch['hid']}")["row_version"] for switch in switches] == versions


def test_the_list_and_the_record_agree_on_who_looks_after_every_item(make: Maker) -> None:
    """The operator in force is worked out twice, for a record and for the database to
    filter by. Whatever the inventory holds, the two agree."""
    marks = _team(make)
    places = make.layout()
    east = make.region("East", places["americas"], operator_hid=marks["DW"]["hid"])
    dock = make.location("Dock", make.site("Site-9", east))
    entry = make.entry(make.vendor())
    switches = make.switches(entry, "sw", 9)
    make.item(name="PS-A", parent_item_hid=switches[0]["hid"], operator_hid=marks["DW"]["hid"])
    module = make.item(name="MOD-1", parent_item_hid=switches[1]["hid"])
    make.item(name="SFP-1", parent_item_hid=module["hid"])
    make.stack("stack-b", switches[:2], operator_hid=marks["LM"]["hid"])
    outer = make.group("domain", "controller_domain", operator_hid=marks["PR"]["hid"])
    make.group(
        "cluster-a",
        "cluster",
        [(switches[1], "active"), (switches[2], "standby")],
        parent_group_hid=outer["hid"],
    )
    make.group("custom-a", "custom", [(switches[3], "member")], operator_hid=marks["RA"]["hid"])
    make.group("custom-b", "custom", [(switches[3], "member")], operator_hid=marks["DW"]["hid"])
    make.group("empty-handed", "custom", [(switches[4], "member")])
    # By place: in the room under a building that has one, at the dock under a region
    # that has one, and in a group whose label is released, so that the place decides.
    _patch(make, f"/locations/{places['building']['hid']}", operator_hid=marks["RA"]["hid"])
    _patch(make, f"/items/{switches[5]['hid']}", location_hid=places["room"]["hid"])
    _patch(make, f"/items/{switches[6]['hid']}", location_hid=dock["hid"])
    gone = make.post("/operators", {"label": "Gone"})
    make.group("released", "custom", [(switches[7], "member")], operator_hid=gone["hid"])
    _patch(make, f"/items/{switches[7]['hid']}", location_hid=dock["hid"])
    _patch(make, f"/items/{switches[8]['hid']}", operator_hid=gone["hid"])
    make.post(f"/operators/{gone['hid']}/retire", {"row_version": 1}, 200)

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
    # Of two groups of one type, the first by name decides; a released label does not.
    assert _in_force(make, switches[3])[0] == "RA"
    assert _in_force(make, switches[7])[:2] == ("DW", "region")
    assert _in_force(make, switches[8]) == (None, "none", None)


def test_what_nobody_looks_after_is_a_row_of_the_report(make: Maker) -> None:
    marks = _team(make)
    entry = make.entry(make.vendor(), support_weight="1", est_value="1000.00")
    switches = make.switches(entry, "sw", 4, lifecycle_state="Prod")
    make.stack("stack-a", switches[:2], operator_hid=marks["LM"]["hid"])
    _patch(make, f"/items/{switches[2]['hid']}", operator_hid=marks["DW"]["hid"])

    summary = make.get("/reports/summary", by="operator")
    assert [(row["label"], row["component_count"]) for row in summary["rows"]] == [
        ("DW", 1),
        ("LM", 2),
        (None, 1),
    ]
    assert summary["rows"][1]["key"] == marks["LM"]["hid"]
    money = make.get("/reports/management", by="operator")
    assert [(row["label"], row["est_value"]) for row in money["rows"]] == [
        ("DW", "1000.00"),
        ("LM", "2000.00"),
        (None, "1000.00"),
    ]


def test_operators_travel_in_files_and_are_set_on_many_at_once(make: Maker, files: Files) -> None:
    make.contact("Lee Marchetti")
    make.contact("Robin Achterberg")
    places = make.layout()
    entry = make.entry(make.vendor())
    switches = make.switches(entry, "site2-sw-core", 2)
    make.item(name="PS-A", parent_item_hid=switches[0]["hid"])

    files.load(
        "operators",
        "label,description,colour,contact\n"
        "LM,Core,#1f6feb,lee.marchetti@example.net\nRA,Access,,Robin Achterberg\nOp2,Spare,,\n",
    )
    labels = make.get("/operators")["items"]
    assert [(one["label"], one["is_open"]) for one in labels] == [
        ("LM", False),
        ("Op2", True),
        ("RA", False),
    ]
    files.load("device_groups", "name,type,operator\nsite2-sw-core,stack,LM\n")
    files.load(
        "device_group_members",
        "group,item,role\nsite2-sw-core,SITE2-SW-CORE-001,master\n"
        "site2-sw-core,SITE2-SW-CORE-002,member\n",
    )
    files.load("sites", "name,region,operator\nSite-2,Americas > Central,RA\n")
    assert make.get(f"/sites/{places['site']['hid']}")["operator"]["label"] == "RA"
    # A file of the values in force holds the label for every row, and loading it
    # makes no override of what an item has anyway, from its group or from its place.
    spare = make.item(hostname="spare-01", location_hid=places["room"]["hid"])
    exported = files.export("items", columns=["serial_number", "name", "hostname", "operator"])
    assert (exported.count(",LM"), exported.count(",RA")) == (3, 1)
    again = files.preview("items", exported)
    assert (again["job"]["unchanged"], again["job"]["rejected"]) == (4, 0)
    files.apply(again)
    assert make.get(f"/items/{switches[1]['hid']}")["operator_hid"] is None
    assert make.get(f"/items/{spare['hid']}")["operator_hid"] is None
    sources = files.export("items", columns=["name", "operator"], include_sources=True)
    assert "device_group" in sources
    assert ",site" in sources
    # A row that names another gives the item its own, and `!clear` returns it.
    files.load("items", f"hid,operator\n{switches[1]['hid']},ra\n")
    assert _in_force(make, switches[1])[:2] == ("RA", "own")
    files.load("items", f"hid,operator\n{switches[1]['hid']},!clear\n")
    assert _in_force(make, switches[1])[:2] == ("LM", "device_group")
    unknown = files.preview("items", f"hid,operator\n{switches[1]['hid']},ZZ\n")
    assert unknown["rows"][0]["reasons"][0]["field"] == "operator"
    # The person behind a label is changed, and the label left open, by a file too.
    files.load("operators", "label,contact\nLM,robin.achterberg@example.net\nRA,!clear\n")
    assert _in_force(make, switches[0])[0] == "LM"
    found = make.get(f"/items/{switches[0]['hid']}")["effective"]["operator_hid"]
    assert found["contact"] == "Robin Achterberg"
    assert make.get("/operators", filter="label:eq:RA")["items"][0]["is_open"] is True
    # Every file comes back as it went.
    for entity in ("operators", "items", "device_groups", "sites"):
        back = files.preview(entity, files.export(entity, own_values=True))
        assert back["job"]["unchanged"] == back["job"]["row_count"], (entity, back["rows"])
    # A bulk edit gives many items an operator at once.
    more = make.switches(entry, "site2-sw-access", 3)
    edit = make.post(
        "/items/bulk-update",
        {"filter": "hostname:prefix:site2-sw-access", "set": {"operator": "Op2"}},
        201,
    )
    assert edit["job"]["updated"] == 3
    make.post(f"/items/bulk-update/{edit['job']['hid']}/apply", {}, 200)
    assert _in_force(make, more[2])[:2] == ("Op2", "own")
    assert make.get("/operators", filter="label:eq:Op2")["items"][0]["uses"] == 3
