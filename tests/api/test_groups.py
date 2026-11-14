"""Device groups: stacks, clusters, controller domains, nesting and dated membership."""

from fastapi.testclient import TestClient

from tests.api.inventory import API, Maker, errors

NOBODY = "01900000-0000-7000-8000-000000000000"
# A day that is after whichever day the test runs on, when a member joins "today".
LATER, LATER_STILL = "2099-01-01", "2099-01-02"


def _switches(make: Maker, count: int = 4, prefix: str = "site2-sw-stack1", **more) -> list[dict]:
    vendors = make.get("/vendors", filter="name:eq:Cisco")["items"]
    vendor = vendors[0] if vendors else make.vendor()
    entries = make.get("/catalog-entries", filter="pid:eq:C9300-48P")["items"]
    entry = entries[0] if entries else make.entry(vendor)
    return make.switches(entry, prefix, count, **more)


def _role(make: Maker, group: dict, member: dict, role: str, expect: int = 200) -> dict:
    return make.patch(
        f"/device-groups/{group['hid']}/members/{member['hid']}",
        {"row_version": member["row_version"], "role": role},
        expect,
    )


def _leave(make: Maker, group: dict, member: dict, on: str, expect: int = 200) -> dict:
    return make.patch(
        f"/device-groups/{group['hid']}/members/{member['hid']}",
        {"row_version": member["row_version"], "left_on": on},
        expect,
    )


# --- stacks --------------------------------------------------------------------------


def test_a_stack_is_made_with_its_members_and_reads_its_serial_from_the_master(
    make: Maker,
) -> None:
    switches = _switches(make)
    stack = make.stack("site2-sw-stack1", switches, hostname="site2-sw-stack1")

    assert (stack["type"], stack["member_count"], stack["record_status"]) == ("stack", 4, "active")
    assert stack["serial_number"] == switches[0]["serial_number"]
    assert stack["master"]["hid"] == switches[0]["hid"]
    members = make.members(stack)
    assert [(member["role"], member["position"]) for member in members] == [
        ("master", 1),
        ("member", 2),
        ("member", 3),
        ("member", 4),
    ]
    assert all(member["left_on"] is None and member["joined_on"] for member in members)
    assert members[0]["item"]["serial_number"] == switches[0]["serial_number"]
    # Each member says which stack it is in.
    item = make.get(f"/items/{switches[1]['hid']}")
    assert [(group["name"], group["type"], group["role"]) for group in item["groups"]] == [
        ("site2-sw-stack1", "stack", "member")
    ]
    actions = [event["action"] for event in make.audit(record_type="device_group_member")]
    assert actions == ["create"] * 4
    assert make.audit(record_hid=stack["hid"])[0]["action"] == "create"


def test_a_stack_may_be_one_switch_alone_and_needs_no_master(make: Maker) -> None:
    switches = _switches(make)

    # One switch is a stack: one that waits for a member, or has lost one.
    alone = make.group("alone", "stack", [(switches[3], "master")])
    assert (alone["member_count"], alone["serial_number"]) == (1, switches[3]["serial_number"])
    # No rule depends on a master: the intended one is marked when somebody knows it.
    plain = make.group("plain", "stack", [(switches[0], "member"), (switches[1], "member")])
    assert (plain["member_count"], plain["master"], plain["serial_number"]) == (2, None, None)
    # At most one member is marked.
    problem = make.group(
        "two",
        "stack",
        [(make.item(name="one"), "master"), (make.item(name="other"), "master")],
        expect=422,
    )
    assert "more than one" in errors(problem)["role"]
    # Nothing of a refused stack is kept.
    assert make.get("/device-groups", include_drafts="true")["total"] == 2
    assert len(make.audit(record_type="device_group_member")) == 3


def test_a_stack_is_filled_a_member_at_a_time_or_several_at_once(make: Maker) -> None:
    switches = _switches(make, 3)
    stack = make.group("site2-sw-stack1", "stack")
    assert (stack["member_count"], stack["serial_number"], stack["master"]) == (0, None, None)

    make.add(stack, [{"item_hid": switches[0]["hid"], "position": 1}])
    made = make.add(
        stack,
        [
            {"item_hid": switches[1]["hid"], "role": "master", "position": 2},
            {"item_hid": switches[2]["hid"], "position": 3, "joined_on": "2026-01-05"},
        ],
    )
    assert [(member["role"], member["joined_on"] is not None) for member in made] == [
        ("master", True),
        ("member", True),
    ]
    assert made[1]["joined_on"] == "2026-01-05"
    filled = make.get(f"/device-groups/{stack['hid']}")
    assert (filled["member_count"], filled["serial_number"]) == (3, switches[1]["serial_number"])


def test_a_draft_stack_is_made_active_as_it_is(make: Maker) -> None:
    switches = _switches(make, 2)
    stack = make.group("site2-sw-stack1", "stack", record_status="draft")
    for switch in switches:
        make.add(stack, [{"item_hid": switch["hid"]}])
    stack = make.get(f"/device-groups/{stack['hid']}")
    assert stack["member_count"] == 2

    active = make.patch(
        f"/device-groups/{stack['hid']}",
        {"row_version": stack["row_version"], "record_status": "active"},
    )
    assert (active["record_status"], active["serial_number"]) == ("active", None)
    _role(make, stack, make.members(stack)[0], "master")
    assert (
        make.get(f"/device-groups/{stack['hid']}")["serial_number"] == switches[0]["serial_number"]
    )


def test_making_another_member_master_makes_the_former_master_a_member(make: Maker) -> None:
    switches = _switches(make)
    stack = make.stack("site2-sw-stack1", switches)
    first, _, third, _ = make.members(stack)

    changed = _role(make, stack, third, "master")

    assert changed["role"] == "master"
    roles = {member["item_hid"]: member["role"] for member in make.members(stack)}
    assert roles[switches[2]["hid"]] == "master"
    assert roles[switches[0]["hid"]] == "member"
    assert (
        make.get(f"/device-groups/{stack['hid']}")["serial_number"] == switches[2]["serial_number"]
    )
    # Both memberships changed, in one request, and each change is on record.
    events = make.audit(record_type="device_group_member", action="update")
    assert {event["record_hid"] for event in events} == {first["hid"], third["hid"]}
    assert len({event["request_id"] for event in events}) == 1
    # The copy of the former master that was read before is stale now.
    problem = _role(make, stack, first, "master", expect=409)
    assert problem["status"] == 409


def test_members_leave_one_by_one_the_master_among_them(make: Maker) -> None:
    switches = _switches(make, 3)
    stack = make.stack("site2-sw-stack1", switches)
    master, second, third = make.members(stack)

    # The intended master leaves while the stack has others: nothing stops it, and the
    # stack has no intended master until somebody marks one.
    ended = _leave(make, stack, master, LATER)
    assert ended["left_on"] == LATER
    after = make.get(f"/device-groups/{stack['hid']}")
    assert (after["member_count"], after["master"], after["serial_number"]) == (2, None, None)
    assert [member["hid"] for member in make.members(stack)] == [second["hid"], third["hid"]]
    # A membership is ended with a date and kept.
    every = make.members(stack, include_past="true")
    assert [member["hid"] for member in every] == [second["hid"], third["hid"], master["hid"]]
    assert make.get(f"/items/{switches[0]['hid']}")["groups"] == []
    # The rest leave too, and the stack is a shell again.
    _leave(make, stack, second, LATER)
    _leave(make, stack, third, LATER)
    again = make.get(f"/device-groups/{stack['hid']}")
    assert (again["member_count"], again["record_status"]) == (0, "active")


def test_a_membership_that_has_ended_is_corrected_in_its_dates_only(make: Maker) -> None:
    switches = _switches(make, 3)
    stack = make.stack("site2-sw-stack1", switches)
    third = make.members(stack)[2]
    path = f"/device-groups/{stack['hid']}/members/{third['hid']}"
    ended = make.patch(path, {"row_version": third["row_version"], "left_on": LATER})

    problem = make.patch(path, {"row_version": ended["row_version"], "role": "master"}, 422)
    assert "only its dates are corrected" in errors(problem)["left_on"]
    problem = make.patch(path, {"row_version": ended["row_version"], "left_on": None}, 422)
    assert "added again" in errors(problem)["left_on"]
    problem = make.patch(path, {"row_version": ended["row_version"], "left_on": "1999-01-01"}, 422)
    assert errors(problem) == {"left_on": "must not be before the day it joined"}
    fixed = make.patch(path, {"row_version": ended["row_version"], "left_on": LATER_STILL})
    assert fixed["left_on"] == LATER_STILL

    # The item that is back joins again, with a new membership.
    again = make.add(stack, [{"item_hid": switches[2]["hid"], "position": 3}])
    assert again[0]["hid"] != third["hid"]
    assert make.get(f"/device-groups/{stack['hid']}/members", include_past="true")["total"] == 4


def test_an_item_is_in_one_stack_at_a_time_and_once(make: Maker) -> None:
    switches = _switches(make, 3)
    stack = make.stack("site2-sw-stack1", switches[:2])

    problem = make.group(
        "site2-sw-stack2",
        "stack",
        [(switches[1], "master"), (switches[2], "member")],
        expect=409,
    )
    assert "one stack at a time: site2-sw-stack1" in errors(problem)["item_hid"]
    problem = make.add(stack, [{"item_hid": switches[0]["hid"]}], expect=409)
    assert errors(problem) == {"item_hid": "this item is a member of the group already"}

    # A stack and a cluster are different things, and an item may be in one of each.
    cluster = make.group("site2-ha", "cluster", [(switches[0], "active")])
    assert cluster["member_count"] == 1
    names = [group["name"] for group in make.get(f"/items/{switches[0]['hid']}")["groups"]]
    assert names == ["site2-ha", "site2-sw-stack1"]


def test_the_members_of_a_stack_are_major_items(make: Maker) -> None:
    switches = _switches(make, 3)
    part = make.item(name="PS-A", parent_item_hid=switches[0]["hid"])

    problem = make.group(
        "site2-sw-stack1", "stack", [(switches[1], "master"), (part, "member")], expect=422
    )
    assert "major items" in errors(problem)["item_hid"]

    make.stack("site2-sw-stack1", switches[:2])
    # And a member of a stack is not put inside another item.
    problem = make.patch(
        f"/items/{switches[1]['hid']}",
        {"row_version": switches[1]["row_version"], "parent_item_hid": switches[2]["hid"]},
        expect=422,
    )
    assert "end that membership first" in errors(problem)["parent_item_hid"]
    # A group that is not a stack or a cluster takes any item.
    custom = make.group("spares-shelf", "custom", [(part, "member")])
    assert custom["member_count"] == 1


def test_retiring_a_group_ends_its_memberships_and_frees_its_items(make: Maker) -> None:
    switches = _switches(make, 2)
    stack = make.stack("site2-sw-stack1", switches)

    retired = make.post(
        f"/device-groups/{stack['hid']}/retire", {"row_version": stack["row_version"]}, 200
    )

    assert (retired["record_status"], retired["member_count"]) == ("retired", 0)
    assert retired["serial_number"] is None
    past = make.members(stack, include_past="true")
    assert len(past) == 2
    assert all(member["left_on"] == member["joined_on"] for member in past)
    assert make.get("/device-groups")["total"] == 0
    assert make.get("/device-groups", include_archived="true")["total"] == 1
    # The items are free to be a stack again.
    assert make.stack("site2-sw-stack2", switches)["member_count"] == 2
    problem = make.add(stack, [{"item_hid": switches[0]["hid"]}], expect=422)
    assert "a retired group takes no members" in errors(problem)["members"]


# --- the group itself ----------------------------------------------------------------


def test_a_group_needs_a_name_of_its_own_and_a_type(make: Maker) -> None:
    make.group("site2-sw-stack1", "stack")

    problem = make.group("SITE2-SW-STACK1 ", "cluster", expect=409)
    assert errors(problem) == {"name": "another device group has this name"}
    problem = make.post("/device-groups", {"type": "ring", "name": "x"}, expect=422)
    assert problem["status"] == 422
    problem = make.post("/device-groups", {"type": "stack", "name": "  "}, expect=422)
    assert errors(problem) == {"name": "must not be blank"}


def test_a_group_is_changed_with_the_version_it_was_read_at(make: Maker) -> None:
    owner = make.owner()
    make.tag("critical")
    group = make.group("site2-sw-stack1", "stack")

    changed = make.patch(
        f"/device-groups/{group['hid']}",
        {
            "row_version": group["row_version"],
            "name": "site2-sw-stack-a",
            "hostname": "site2-sw-stack-a",
            "fqdn": "site2-sw-stack-a.example.net",
            "owner_hid": owner["hid"],
            "tags": ["critical"],
        },
    )

    assert changed["row_version"] == group["row_version"] + 1
    assert (changed["name"], changed["owner"]["label"], changed["tags"]) == (
        "site2-sw-stack-a",
        "Network Engineering",
        ["critical"],
    )
    stale = make.patch(
        f"/device-groups/{group['hid']}",
        {"row_version": group["row_version"], "hostname": "other"},
        expect=409,
    )
    assert stale["status"] == 409
    fields = {change["field"] for change in make.audit(record_hid=group["hid"])[0]["changes"]}
    assert fields == {"name", "hostname", "fqdn", "owner_hid", "tags"}
    listed = make.get("/device-groups", filter="tags:has:critical owner.label:prefix:network")
    assert [row["name"] for row in listed["items"]] == ["site2-sw-stack-a"]


def test_the_type_of_a_group_that_has_had_members_is_not_changed(make: Maker) -> None:
    switches = _switches(make, 2)
    empty = make.group("empty", "stack")
    changed = make.patch(
        f"/device-groups/{empty['hid']}", {"row_version": empty["row_version"], "type": "cluster"}
    )
    assert changed["type"] == "cluster"

    stack = make.stack("site2-sw-stack1", switches)
    problem = make.patch(
        f"/device-groups/{stack['hid']}",
        {"row_version": stack["row_version"], "type": "cluster"},
        expect=422,
    )
    assert "is not changed" in problem["detail"]


def test_roles_belong_to_the_type_of_the_group(make: Maker) -> None:
    switches = _switches(make, 2)

    problem = make.group("site2-ha", "cluster", [(switches[0], "master")], expect=422)
    assert errors(problem) == {"role": "in a cluster, one of member, active, standby"}
    problem = make.group("domain", "controller_domain", [(switches[0], "member")], expect=422)
    assert errors(problem) == {"role": "in a controller domain, one of endpoint, controller"}
    # Left out, the role is the plain one of the type.
    domain = make.post(
        "/device-groups",
        {
            "type": "controller_domain",
            "name": "domain",
            "members": [{"item_hid": switches[0]["hid"]}],
        },
    )
    assert make.members(domain)[0]["role"] == "endpoint"
    problem = make.add(domain, [{"item_hid": NOBODY}], expect=422)
    assert "there is no item" in errors(problem)["item_hid"]


def test_groups_nest_and_a_group_is_never_within_itself(make: Maker) -> None:
    domain = make.group("site2-wireless", "controller_domain")
    cluster = make.group("site2-wlc-ha", "cluster", parent_group_hid=domain["hid"])

    assert cluster["parent"] == {
        "hid": domain["hid"],
        "name": "site2-wireless",
        "type": "controller_domain",
    }
    again = make.get(f"/device-groups/{domain['hid']}")
    assert [group["name"] for group in again["groups"]] == ["site2-wlc-ha"]
    assert make.get("/device-groups", filter="parent.name:eq:site2-wireless")["total"] == 1

    for parent in (domain, cluster):
        problem = make.patch(
            f"/device-groups/{domain['hid']}",
            {"row_version": domain["row_version"], "parent_group_hid": parent["hid"]},
            expect=422,
        )
        assert "within it" in errors(problem)["parent_group_hid"]
    problem = make.group("lost", "custom", parent_group_hid=NOBODY, expect=422)
    assert "there is no device group" in errors(problem)["parent_group_hid"]


def test_groups_nest_at_most_eight_deep(make: Maker) -> None:
    parent = None
    for level in range(1, 9):
        more = {"parent_group_hid": parent["hid"]} if parent else {}
        parent = make.group(f"level-{level}", "custom", **more)
    assert parent is not None
    problem = make.group("level-9", "custom", parent_group_hid=parent["hid"], expect=422)
    assert errors(problem) == {"parent_group_hid": "groups nest at most 8 deep"}


def test_an_endpoint_lists_the_controllers_of_its_domain(make: Maker) -> None:
    controllers = _switches(make, 3, "site2-wlc")
    points = _switches(make, 2, "site2-ap")
    domain = make.group(
        "site2-wireless",
        "controller_domain",
        [(points[0], "endpoint"), (points[1], "endpoint"), (controllers[2], "controller")],
    )
    make.group(
        "site2-wlc-ha",
        "cluster",
        [(controllers[0], "active"), (controllers[1], "standby")],
        parent_group_hid=domain["hid"],
    )

    for point in points:
        item = make.get(f"/items/{point['hid']}")
        # A controller of its own, and the members of the cluster nested in the domain,
        # each with the cluster it is in.
        assert [(one["cluster"], one["name"]) for one in item["controllers"]] == [
            (None, "site2-wlc-03"),
            ("site2-wlc-ha", "site2-wlc-01"),
            ("site2-wlc-ha", "site2-wlc-02"),
        ]
    # A controller is not its own endpoint.
    assert make.get(f"/items/{controllers[2]['hid']}")["controllers"] == []
    assert make.found(filter="group.name:eq:site2-wireless") == [
        "site2-ap-01",
        "site2-ap-02",
        "site2-wlc-03",
    ]
    assert make.found(filter="group.type:eq:cluster") == ["site2-wlc-01", "site2-wlc-02"]
    assert make.found(filter="group.name:empty:true") == []
    assert make.found(filter="group.name:ne:site2-wlc-ha", sort="name")[:2] == [
        "site2-ap-01",
        "site2-ap-02",
    ]
    # Which group it is, by its HID, has no order. Its name has: the first of them.
    assert "sort" in errors(make.get("/items", expect=422, sort="group.hid"))
    assert make.found(sort="group.name,name")[:3] == ["site2-ap-01", "site2-ap-02", "site2-wlc-03"]


def test_a_group_says_when_a_member_has_another_owner(make: Maker) -> None:
    ours, theirs = make.owner(), make.owner("Voice Services")
    switches = _switches(make, 2, owner_hid=ours["hid"])
    stack = make.stack("site2-sw-stack1", switches, owner_hid=ours["hid"])
    assert stack["members_disagree"] == []

    make.patch(
        f"/items/{switches[1]['hid']}",
        {"row_version": switches[1]["row_version"], "owner_hid": theirs["hid"]},
    )
    again = make.get(f"/device-groups/{stack['hid']}")
    assert (again["owner"]["label"], again["members_disagree"]) == (
        "Network Engineering",
        ["owner_hid"],
    )


def test_groups_are_read_by_all_and_changed_by_the_inventory_role(
    client: TestClient, make: Maker, viewer: dict
) -> None:
    switches = _switches(make, 2)
    stack = make.stack("site2-sw-stack1", switches)
    member = make.members(stack)[1]

    for path in ("/device-groups", f"/device-groups/{stack['hid']}/members"):
        assert client.get(API + path, headers=viewer).status_code == 200
    assert client.get(API + "/device-groups").status_code == 401
    refusals = (
        client.post(API + "/device-groups", json={"type": "custom", "name": "x"}, headers=viewer),
        client.patch(
            f"{API}/device-groups/{stack['hid']}",
            json={"row_version": stack["row_version"], "name": "x"},
            headers=viewer,
        ),
        client.post(
            f"{API}/device-groups/{stack['hid']}/retire",
            json={"row_version": stack["row_version"]},
            headers=viewer,
        ),
        client.post(
            f"{API}/device-groups/{stack['hid']}/members",
            json={"members": [{"item_hid": switches[0]["hid"]}]},
            headers=viewer,
        ),
        client.patch(
            f"{API}/device-groups/{stack['hid']}/members/{member['hid']}",
            json={"row_version": member["row_version"], "role": "master"},
            headers=viewer,
        ),
    )
    assert [response.status_code for response in refusals] == [403] * 5
    make.get(f"/device-groups/{NOBODY}", expect=404)
    make.patch(
        f"/device-groups/{stack['hid']}/members/{NOBODY}",
        {"row_version": 1, "role": "master"},
        expect=404,
    )


# --- the grid of groups, sorted by its columns -------------------------------------------


def test_the_columns_of_a_group_that_are_worked_out_are_sorted_by(make: Maker) -> None:
    def item(name: str, serial: str) -> dict:
        return make.item(name=name, serial_number=serial)

    for label in ("Zulu", "beta", "alpha"):
        make.tag(label)
    yankee, bravo = item("Yankee", "ZZ-1"), item("bravo", "aa-2")
    # The stack booted and made its second switch master: its serial number is that one's.
    floated = make.stack("stack-a", [yankee, bravo], tags=["Zulu", "beta"])
    make.patch(
        f"/device-groups/{floated['hid']}",
        {"row_version": floated["row_version"], "observed_master_hid": bravo["hid"]},
    )
    three = make.stack(
        "stack-b", [item("alpha", "MM-1"), item("m2", "MM-2"), item("m3", "MM-3")], tags=["alpha"]
    )
    pair = make.group("cluster-c", "cluster", [(item("x", "XX-1"), "active")])
    make.group("empty-d", "stack")
    make.address(floated, "192.0.2.20", is_primary=True)
    make.address(floated, "192.0.2.9", make.network("Red"), role="virtual")
    make.address(three, "192.0.2.100", make.network("blue"), is_primary=True)
    make.address(pair, "2001:db8::5", is_primary=True)

    def by(field: str) -> list[str]:
        return make.found("/device-groups", sort=f"{field},name")

    shown = {row["name"]: row for row in make.get("/device-groups")["items"]}
    # The serial number the record reports: of the master that is seen, or else of the
    # one intended, without regard to case, and a group with none last either way.
    assert [shown[name]["serial_number"] for name in by("serial_number")] == [
        "aa-2",
        "MM-1",
        None,
        None,
    ]
    assert by("-serial_number") == ["stack-b", "stack-a", "cluster-c", "empty-d"]
    # The masters, by the names their cells show.
    assert by("master.name") == ["stack-b", "stack-a", "cluster-c", "empty-d"]
    assert by("-master.name") == ["stack-a", "stack-b", "cluster-c", "empty-d"]
    assert by("observed_master.name") == ["stack-a", "cluster-c", "empty-d", "stack-b"]
    assert by("-observed_master.name") == ["stack-a", "cluster-c", "empty-d", "stack-b"]
    # The number of current members is the one the record shows, sorted as a number.
    assert [shown[name]["member_count"] for name in by("member_count")] == [0, 1, 2, 3]
    assert by("-member_count") == ["stack-b", "stack-a", "cluster-c", "empty-d"]
    # Addresses, networks and tags as on the item list: the least of them.
    assert by("address") == ["stack-a", "stack-b", "cluster-c", "empty-d"]
    assert by("-address") == ["cluster-c", "stack-b", "stack-a", "empty-d"]
    assert by("mgmt_address") == ["stack-a", "stack-b", "cluster-c", "empty-d"]
    assert by("network.label") == ["stack-b", "stack-a", "cluster-c", "empty-d"]
    assert by("tags") == ["stack-b", "stack-a", "cluster-c", "empty-d"]
    assert by("-tags") == ["stack-a", "stack-b", "cluster-c", "empty-d"]
    # They are to sort by, and the filter does not know them.
    for field in ("serial_number", "master.name", "member_count", "health"):
        problem = make.get("/device-groups", 422, filter=f"{field}:empty:true")
        assert f"{field} is not a field" in errors(problem)["filter"]


def test_the_members_of_a_group_are_sorted_by_the_columns_of_their_table(make: Maker) -> None:
    vendor = make.vendor()
    small, large = make.entry(vendor, "C9200L-24T"), make.entry(vendor, "C9300-48P")

    def switch(name: str, serial: str, entry: dict) -> dict:
        return make.item(name=name, serial_number=serial, catalog_entry_hid=entry["hid"])

    first, second, third = (
        switch("Delta", "S-30", large),
        switch("alpha", "S-10", large),
        switch("Charlie", "S-20", small),
    )
    stack = make.stack("site2-sw-stack1", [first, second, third])
    gone = make.item(name="bravo", serial_number="S-05")
    past = make.add(stack, [{"item_hid": gone["hid"], "position": 4}])[0]
    _leave(make, stack, past, LATER)
    make.patch(
        f"/device-groups/{stack['hid']}",
        {"row_version": make.get(f"/device-groups/{stack['hid']}")["row_version"]}
        | {"observed_master_hid": third["hid"]},
    )

    def names(**params) -> list[str]:
        return [member["item"]["name"] for member in make.members(stack, **params)]

    # As it was: by position, and with those that have left after the current ones.
    assert names() == ["Delta", "alpha", "Charlie"]
    assert names(include_past="true") == ["Delta", "alpha", "Charlie", "bravo"]
    assert names(sort="item.name") == ["alpha", "Charlie", "Delta"]
    assert names(sort="-item.name", include_past="true") == ["Delta", "Charlie", "bravo", "alpha"]
    assert names(sort="item.serial_number") == ["alpha", "Charlie", "Delta"]
    # The model, and within one model the order the table always had.
    assert names(sort="item.pid") == ["Charlie", "Delta", "alpha"]
    assert names(sort="-item.pid") == ["Delta", "alpha", "Charlie"]
    assert names(sort="role") == ["Delta", "alpha", "Charlie"]
    assert names(sort="-role") == ["alpha", "Charlie", "Delta"]
    assert names(sort="-position") == ["Charlie", "alpha", "Delta"]
    # The member that is seen as master comes first, whichever way round.
    assert names(sort="observed_master")[0] == names(sort="-observed_master")[0] == "Charlie"
    assert names(sort="left_on", include_past="true")[0] == "bravo"
    assert names(sort="-joined_on,item.name", limit=2, offset=1) == ["Charlie", "Delta"]
    path = f"/device-groups/{stack['hid']}/members"
    assert "nope is not a field" in errors(make.get(path, 422, sort="nope"))["sort"]
