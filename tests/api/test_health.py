"""Condition, observation and health, the two masters of a stack, and how a cluster is managed.

Release 0.4.1: the answers to the proposals of 0.4.0, decisions D-91 to D-107.
"""

import itertools
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from hirdir.domain import health
from tests.api.inventory import API, Maker, errors
from tests.api.test_files import Files, changes, counts, table

CONDITIONS = (None, "untested", "good", "degraded", "suspect", "failed", "dead")
OBSERVED = (None, "online", "degraded", "unreachable", "present")
SEEN = "2026-11-02T15:00:00Z"


@pytest.fixture
def files(client: TestClient, inventory: dict[str, str]) -> Files:
    return Files(client, inventory)


def _entry(make: Maker, pid: str = "C9300-48P", **more: Any) -> dict:
    vendors = make.get("/vendors", filter="name:eq:Cisco")["items"]
    vendor = vendors[0] if vendors else make.vendor()
    return make.entry(vendor, pid, **more)


def _patch(make: Maker, path: str, **fields: Any) -> dict:
    current = make.get(path)
    return make.patch(path, {"row_version": current["row_version"], **fields})


# --- the condition of an item, and what is observed of it -------------------------------


def test_an_item_has_a_condition_from_a_list_that_can_be_edited(make: Maker) -> None:
    listed = [choice["value"] for choice in make.get("/choices", list="item_condition")]
    assert listed == ["untested", "good", "degraded", "suspect", "failed", "dead"]

    item = make.item(name="site2-sw-access-01", condition="Good")
    assert (item["condition"], item["health"]["value"]) == ("good", "good")
    changed = _patch(make, f"/items/{item['hid']}", condition="suspect")
    assert changed["health"] == {"value": "degraded", "reasons": ["its condition is suspect"]}
    event = make.audit(record_hid=item["hid"])[0]
    assert event["changes"] == [{"field": "condition", "old": "good", "new": "suspect"}]
    cleared = _patch(make, f"/items/{item['hid']}", condition=None)
    assert (cleared["condition"], cleared["health"]["value"]) == (None, "unknown")

    problem = make.post("/items", {"name": "x", "condition": "shiny"}, expect=422)
    assert "condition" in errors(problem)
    # A site adds a condition of its own. It says nothing of health either way, and the
    # reason says that, and not that nothing is said.
    make.post("/choices", {"list": "item_condition", "value": "on-loan", "label": "On loan"})
    assert _patch(make, f"/items/{item['hid']}", condition="on-loan")["health"] == {
        "value": "unknown",
        "reasons": [
            "its condition is on-loan, which says nothing of its health, and nothing is observed"
        ],
    }
    assert _patch(make, f"/items/{item['hid']}", condition="untested")["health"] == {
        "value": "unknown",
        "reasons": ["its condition is untested, and nothing is observed"],
    }
    # What is observed decides it then, and is the reason.
    seen = _patch(make, f"/items/{item['hid']}", condition="on-loan", observed_status="present")
    assert seen["health"] == {"value": "good", "reasons": ["it is observed present"]}
    _patch(make, f"/items/{item['hid']}", observed_status=None)
    # A condition moves the item nowhere in the lifecycle.
    assert cleared["lifecycle_state"] is None


def test_what_is_observed_is_kept_with_the_moment_it_was_seen(make: Maker) -> None:
    item = make.item(name="site2-sw-access-01")
    assert (item["observed_status"], item["observed_at"]) == (None, None)

    seen = _patch(make, f"/items/{item['hid']}", observed_status="online")
    assert seen["observed_status"] == "online"
    assert seen["observed_at"] is not None
    # A person who states it again, as it is, has looked again: the moment is now.
    again = _patch(make, f"/items/{item['hid']}", observed_status="online")
    assert again["observed_at"] > seen["observed_at"]
    assert again["row_version"] == seen["row_version"] + 1
    # A moment that is given is the one kept, and may be given with the status as it is.
    dated = _patch(make, f"/items/{item['hid']}", observed_status="online", observed_at=SEEN)
    assert dated["observed_at"] == SEEN
    other = _patch(make, f"/items/{item['hid']}", observed_status="unreachable")
    assert other["observed_at"] != SEEN
    # Clearing the status clears the moment.
    cleared = _patch(make, f"/items/{item['hid']}", observed_status=None)
    assert (cleared["observed_status"], cleared["observed_at"]) == (None, None)

    path = f"/items/{item['hid']}"
    problem = make.patch(path, {"row_version": cleared["row_version"], "observed_at": SEEN}, 422)
    assert errors(problem) == {"observed_at": "give observed_status with it"}
    problem = make.patch(
        path, {"row_version": cleared["row_version"], "observed_status": "sleeping"}, 422
    )
    assert problem["status"] == 422


def test_present_is_what_a_person_saw_of_what_is_never_on_the_network(make: Maker) -> None:
    tester = make.item(name="fibre tester")
    assert tester["health"]["value"] == "unknown"

    checked = _patch(make, f"/items/{tester['hid']}", observed_status="present", observed_at=SEEN)

    assert checked["health"] == {"value": "good", "reasons": ["it is observed present"]}
    assert checked["observed_at"] == SEEN
    # It is never held against the network, having no intent to be online.
    assert checked["expected_online"] is None
    assert make.found(filter="observed_status:eq:present") == ["fibre tester"]
    assert make.found(filter="observed_at:lt:2026-12-01T00:00:00Z") == ["fibre tester"]
    assert make.found(filter="observed_at:gt:2026-12-01T00:00:00Z") == []


@pytest.mark.parametrize(
    ("condition", "observed", "online", "expected"),
    [
        (None, None, None, "unknown"),
        ("untested", None, True, "unknown"),
        ("untested", "online", True, "good"),
        ("good", None, False, "good"),
        ("good", "present", None, "good"),
        ("good", "degraded", True, "degraded"),
        ("suspect", "online", True, "degraded"),
        ("good", "unreachable", False, "degraded"),
        ("good", "unreachable", None, "degraded"),
        ("good", "unreachable", True, "failed"),
        ("dead", "online", True, "failed"),
        ("failed", None, None, "failed"),
    ],
)
def test_the_health_of_an_item_is_the_worst_of_what_its_facts_say(
    condition: str | None, observed: str | None, online: bool | None, expected: str
) -> None:
    assert health.of_item(condition, observed, online).value == expected


def test_the_list_filters_by_the_health_that_the_record_shows(make: Maker) -> None:
    entry = _entry(make)
    # Every combination of the three facts, as an item in Prod (online or not) or with
    # no state, so that the database's own cascade is held against the one in Python.
    wanted: dict[str, str] = {}
    every = itertools.product(CONDITIONS, OBSERVED, (True, False, None))
    for number, (condition, observed, online) in enumerate(every, start=1):
        fields: dict[str, Any] = {
            "catalog_entry_hid": entry["hid"],
            "serial_number": f"S{number:03d}",
        }
        if online is not None:
            fields.update(lifecycle_state="Prod", disposition="Spare", expected_online=online)
        if condition:
            fields["condition"] = condition
        if observed:
            fields.update(observed_status=observed, observed_at=SEEN)
        made = make.item(**fields)
        wanted[made["serial_number"]] = health.of_item(condition, observed, online).value
        assert made["health"]["value"] == wanted[made["serial_number"]], fields
    for value in health.HEALTHS:
        page = make.get("/items", filter=f"health:eq:{value}", limit=1000)
        found = {row["serial_number"] for row in page["items"]}
        assert found == {serial for serial, its in wanted.items() if its == value}, value
    by_health = make.get("/reports/summary", by="health")
    assert {row["key"]: row["items"] for row in by_health["rows"]} == {
        value: list(wanted.values()).count(value) for value in health.HEALTHS
    }


def test_a_minor_item_is_held_against_the_intent_it_has_from_above(make: Maker) -> None:
    switch = make.item(name="site2-sw-access-01", lifecycle_state="Prod")
    part = make.item(name="module", parent_item_hid=switch["hid"], observed_status="unreachable")
    # Its switch is expected online, so the module is too, and unreachable is a failure.
    assert part["health"]["value"] == "failed"
    assert make.found(filter="health:eq:failed") == ["module"]
    # Neither the condition nor what is observed is inherited.
    _patch(make, f"/items/{switch['hid']}", condition="failed")
    assert make.get(f"/items/{part['hid']}")["condition"] is None


# --- the health of a stack and a cluster ------------------------------------------------


def test_the_health_of_a_stack_follows_from_its_members(make: Maker) -> None:
    entry = _entry(make)
    switches = make.switches(entry, "site2-sw-stack1", 3, lifecycle_state="Prod", condition="good")
    stack = make.stack("site2-sw-stack1", switches)
    assert stack["health"] == {"value": "good", "reasons": ["every member is good"]}

    def now() -> dict:
        return make.get(f"/device-groups/{stack['hid']}")["health"]

    _patch(make, f"/items/{switches[1]['hid']}", condition="failed")
    assert now() == {"value": "degraded", "reasons": ["1 member is failed"]}
    make.move(make.get(f"/items/{switches[2]['hid']}"), "Down", reason="maintenance")
    assert now()["reasons"] == ["1 member is failed", "1 member is in Down or Pending-Removal"]
    # What is observed of the stack itself comes first.
    _patch(make, f"/device-groups/{stack['hid']}", observed_status="unreachable")
    assert now() == {"value": "failed", "reasons": ["it is observed unreachable"]}
    _patch(make, f"/device-groups/{stack['hid']}", observed_status="online")
    assert now()["value"] == "degraded"
    for switch in switches:
        _patch(make, f"/items/{switch['hid']}", condition="dead")
    assert now() == {"value": "failed", "reasons": ["every member is failed"]}
    # Nothing of it is stored, and nothing moved a member in the lifecycle.
    assert make.get(f"/items/{switches[0]['hid']}")["lifecycle_state"] == "Prod"


def test_a_stack_that_is_short_of_a_member_is_degraded(make: Maker) -> None:
    entry = _entry(make)
    switches = make.switches(entry, "site2-sw-stack1", 3, condition="good")
    alone = make.stack("alone", switches[:1])
    assert alone["health"] == {"value": "degraded", "reasons": ["it is one switch alone"]}
    # Unless one is all it is meant to have.
    meant = _patch(make, f"/device-groups/{alone['hid']}", expected_members=1)
    assert meant["health"]["value"] == "good"

    pair = make.stack("pair", switches[1:], expected_members=3)
    assert pair["health"] == {
        "value": "degraded",
        "reasons": ["it has 2 of the 3 members it is to have"],
    }
    assert make.group("empty", "stack")["health"] == {
        "value": "unknown",
        "reasons": ["it has no members"],
    }
    # A controller domain and a custom group have no health.
    assert make.group("domain", "controller_domain")["health"] is None
    assert make.group("shelf", "custom")["health"] is None
    problem = make.group("x", "stack", expected_members=0, expect=422)
    assert problem["status"] == 422


def test_a_cluster_has_a_health_and_untested_members_are_not_known_good(make: Maker) -> None:
    entry = _entry(make)
    first, second = make.switches(entry, "site2-fw-edge", 2)
    cluster = make.group("site2-fw-edge", "cluster", [(first, "active"), (second, "standby")])
    assert cluster["health"]["value"] == "unknown"

    _patch(make, f"/items/{first['hid']}", condition="good")
    _patch(make, f"/items/{second['hid']}", condition="untested")
    assert make.get(f"/device-groups/{cluster['hid']}")["health"]["value"] == "unknown"
    # Seen by a person, the cluster is good, whatever is not yet said of a member.
    seen = _patch(make, f"/device-groups/{cluster['hid']}", observed_status="present")
    assert seen["health"] == {"value": "good", "reasons": ["it is observed present"]}


# --- the master that is intended, and the master that is seen ---------------------------


def test_a_stack_needs_no_master_and_has_at_most_one_intended(make: Maker) -> None:
    entry = _entry(make)
    switches = make.switches(entry, "site2-sw-stack1", 4)
    stack = make.group("site2-sw-stack1", "stack", [(switch, "member") for switch in switches[:3]])
    assert (stack["master"], stack["serial_number"], stack["serial_source"]) == (None, None, None)

    members = make.members(stack)
    path = f"/device-groups/{stack['hid']}/members"
    make.patch(f"{path}/{members[0]['hid']}", {"row_version": 1, "role": "master"})
    make.patch(f"{path}/{members[1]['hid']}", {"row_version": 1, "role": "master"})
    roles = [member["role"] for member in make.members(stack)]
    assert roles == ["member", "master", "member"]
    # One that is added as the master takes the mark as well.
    make.add(stack, [{"item_hid": switches[3]["hid"], "role": "master", "position": 4}])
    assert [member["role"] for member in make.members(stack)].count("master") == 1
    assert make.get(f"/device-groups/{stack['hid']}")["master"]["hid"] == switches[3]["hid"]
    problem = make.group(
        "two", "stack", [(make.item(name="a"), "master"), (make.item(name="b"), "master")], 422
    )
    assert "more than one" in errors(problem)["role"]


def test_the_serial_number_of_a_stack_is_read_from_the_master_that_is_seen(make: Maker) -> None:
    entry = _entry(make)
    switches = make.switches(entry, "site2-sw-stack1", 3)
    stack = make.stack("site2-sw-stack1", switches)
    assert (stack["serial_number"], stack["serial_source"]) == (
        switches[0]["serial_number"],
        "intended",
    )
    assert (stack["observed_master"], stack["master_as_intended"]) == (None, None)

    # The stack booted and made its third switch master: an observation, not a wish.
    seen = _patch(
        make,
        f"/device-groups/{stack['hid']}",
        observed_master_hid=switches[2]["hid"],
        master_observed_at=SEEN,
    )

    assert (seen["serial_number"], seen["serial_source"]) == (
        switches[2]["serial_number"],
        "observed",
    )
    assert seen["observed_master"]["hid"] == switches[2]["hid"]
    assert (seen["master_observed_at"], seen["master_as_intended"]) == (SEEN, False)
    # The intended master is as it was, and a floated master is no fault.
    assert seen["master"]["hid"] == switches[0]["hid"]
    assert seen["health"]["value"] == "unknown"
    assert [member["role"] for member in make.members(stack)] == ["master", "member", "member"]
    agreed = _patch(make, f"/device-groups/{stack['hid']}", observed_master_hid=switches[0]["hid"])
    assert agreed["master_as_intended"] is True
    assert agreed["master_observed_at"] != SEEN

    outsider = make.item(name="not in the stack")
    path = f"/device-groups/{stack['hid']}"
    body = {"row_version": agreed["row_version"], "observed_master_hid": outsider["hid"]}
    assert "not a current member" in errors(make.patch(path, body, 422))["observed_master_hid"]
    cluster = make.group("site2-ha", "cluster", [(outsider, "active")])
    body = {"row_version": cluster["row_version"], "observed_master_hid": outsider["hid"]}
    problem = make.patch(f"/device-groups/{cluster['hid']}", body, 422)
    assert "recorded on a stack" in errors(problem)["observed_master_hid"]


def test_a_stack_is_found_by_the_serial_number_of_any_member(make: Maker) -> None:
    entry = _entry(make)
    stack = make.stack("site2-sw-stack1", make.switches(entry, "site2-sw-stack1", 3))
    make.stack("site2-sw-stack2", make.switches(entry, "site2-sw-stack2", 2))

    for number in (1, 2, 3):
        serial = f"site2-sw-stack1-00{number}"
        found = make.get("/device-groups", filter=f"member.serial_number:eq:{serial}")["items"]
        assert [group["hid"] for group in found] == [stack["hid"]]
    both = make.get("/device-groups", filter="member.serial_number:prefix:SITE2-SW-STACK")
    assert both["total"] == 2
    assert make.get("/device-groups", filter="member.serial_number:eq:nobody")["total"] == 0


def test_no_rule_stops_a_member_leaving_and_the_master_that_left_is_forgotten(
    make: Maker,
) -> None:
    entry = _entry(make)
    switches = make.switches(entry, "site2-sw-stack1", 3, lifecycle_state="Prod")
    stack = make.stack("site2-sw-stack1", switches)
    _patch(make, f"/device-groups/{stack['hid']}", observed_master_hid=switches[0]["hid"])

    # The switch that is both masters fails and is retired, while the stack has others.
    current = make.get(f"/items/{switches[0]['hid']}")
    retired = make.post(
        f"/items/{switches[0]['hid']}/retire", {"row_version": current["row_version"]}, 200
    )

    assert (retired["record_status"], retired["groups"]) == ("retired", [])
    after = make.get(f"/device-groups/{stack['hid']}")
    assert (after["member_count"], after["master"], after["observed_master"]) == (2, None, None)
    assert (after["serial_number"], after["master_observed_at"]) == (None, None)
    past = make.members(stack, include_past="true")
    assert past[-1]["left_on"] is not None


@pytest.mark.parametrize("state", ["Released", "Archived"])
def test_an_item_that_leaves_the_teams_hands_is_in_no_group_any_more(
    make: Maker, admin: dict, state: str
) -> None:
    entry = _entry(make)
    switches = make.switches(entry, "site2-sw-stack1", 3, lifecycle_state="Prod")
    stack = make.stack("site2-sw-stack1", switches)
    make.group("site2-campus", "custom", [(switches[2], "member")])
    leaving = switches[2]

    # A move to any other state leaves memberships as they are.
    moved = make.move(leaving, "Pending-Removal", reason="rma")
    assert len(moved["groups"]) == 2
    assert make.get(f"/device-groups/{stack['hid']}")["health"]["value"] == "degraded"

    gone = Maker(make.client, admin).move(moved, state, reason="disposed", force=True)

    assert gone["groups"] == []
    assert make.get(f"/device-groups/{stack['hid']}")["member_count"] == 2
    ended = [member for member in make.members(stack, include_past="true") if member["left_on"]]
    assert [member["item_hid"] for member in ended] == [leaving["hid"]]
    assert make.audit(record_type="device_group_member", action="update")[0]["request_id"]


def test_a_replacement_hands_over_the_role_and_not_what_was_seen(make: Maker) -> None:
    entry = _entry(make)
    switches = make.switches(entry, "site2-sw-stack1", 2)
    stack = make.stack("site2-sw-stack1", switches)
    _patch(
        make,
        f"/device-groups/{stack['hid']}",
        observed_master_hid=switches[0]["hid"],
        master_observed_at=SEEN,
    )
    old = make.get(f"/items/{switches[0]['hid']}")

    make.post(
        f"/items/{old['hid']}/replace",
        {
            "row_version": old["row_version"],
            "reason": "rma",
            "new_item": {"catalog_entry_hid": entry["hid"], "serial_number": "FCW0000X999"},
        },
    )

    after = make.get(f"/device-groups/{stack['hid']}")
    # The new switch is the intended master, as the old one was. Nobody has seen it as
    # master yet, so the stack has no master that is seen.
    assert after["master"]["serial_number"] == "FCW0000X999"
    assert (after["serial_number"], after["serial_source"]) == ("FCW0000X999", "intended")
    assert (after["observed_master"], after["master_observed_at"]) == (None, None)
    assert after["member_count"] == 2


# --- how a cluster is managed, and what a stack saves -----------------------------------


def test_a_cluster_says_how_it_is_managed_and_is_counted_so(make: Maker) -> None:
    entry = _entry(make, support_weight="1")
    units = make.switches(entry, "site2-fw-edge", 3, lifecycle_state="Prod")
    cluster = make.group("site2-fw-edge", "cluster", [(unit, "member") for unit in units])
    # Left out, a cluster is one device on the network, as a pair of controllers is.
    assert cluster["managed_as"] == "one"

    def nodes() -> tuple[int, int]:
        totals = make.totals()
        return totals["component_count"], totals["managed_node_count"]

    assert nodes() == (3, 1)
    _patch(make, f"/device-groups/{cluster['hid']}", managed_as="members")
    assert nodes() == (3, 3)
    _patch(make, f"/device-groups/{cluster['hid']}", managed_as="members_and_cluster")
    assert nodes() == (3, 4)
    # The support weight does not depend on it: the discount is a stack's.
    assert make.totals()["support_weight"] == "3"

    stack = make.group("site2-sw-stack1", "stack")
    assert stack["managed_as"] is None
    body = {"row_version": stack["row_version"], "managed_as": "members"}
    problem = make.patch(f"/device-groups/{stack['hid']}", body, 422)
    assert "always one managed node" in errors(problem)["managed_as"]
    problem = make.group("x", "cluster", managed_as="pairs", expect=422)
    assert problem["status"] == 422


def test_a_stack_inside_a_cluster_counts_through_the_cluster_only_when_it_is_one(
    make: Maker,
) -> None:
    entry = _entry(make)
    switches = make.switches(entry, "site2-sw-core", 4, lifecycle_state="Prod")
    make.stack("site2-sw-core-a", switches[:2])
    make.stack("site2-sw-core-b", switches[2:])
    cluster = make.group("site2-sw-core", "cluster", [(switch, "member") for switch in switches])
    assert make.totals()["managed_node_count"] == 1

    _patch(make, f"/device-groups/{cluster['hid']}", managed_as="members")
    # Each member counts through its stack, where it is in one.
    assert make.totals()["managed_node_count"] == 2
    _patch(make, f"/device-groups/{cluster['hid']}", managed_as="members_and_cluster")
    assert make.totals()["managed_node_count"] == 3


def test_one_switch_alone_earns_no_stack_discount(make: Maker) -> None:
    entry = _entry(make, support_weight="1")
    switches = make.switches(entry, "site2-sw-stack1", 2, lifecycle_state="Prod")
    stack = make.stack("site2-sw-stack1", switches[:1])
    totals = make.totals(filter="group.name:eq:site2-sw-stack1")
    assert (totals["managed_node_count"], totals["support_weight"]) == (1, "1")

    make.add(stack, [{"item_hid": switches[1]["hid"]}])
    assert make.totals(filter="group.name:eq:site2-sw-stack1")["support_weight"] == "1"
    # Back to one, it takes the full effort again.
    member = make.members(stack)[1]
    make.patch(
        f"/device-groups/{stack['hid']}/members/{member['hid']}",
        {"row_version": member["row_version"], "left_on": member["joined_on"]},
    )
    assert make.totals()["support_weight"] == "2"


def test_the_controllers_of_an_endpoint_are_found_through_nested_groups(make: Maker) -> None:
    entry = _entry(make)
    east = make.switches(entry, "east-wlc", 2)
    west = make.switches(entry, "west-wlc", 2)
    points = make.switches(entry, "site2-ap", 2)
    domain = make.group(
        "Campus Wireless", "controller_domain", [(point, "endpoint") for point in points]
    )
    # Two pairs of controllers, the western one a level further down.
    make.group(
        "east", "cluster", [(unit, "member") for unit in east], parent_group_hid=domain["hid"]
    )
    region = make.group("west region", "custom", parent_group_hid=domain["hid"])
    make.group(
        "west", "cluster", [(unit, "member") for unit in west], parent_group_hid=region["hid"]
    )

    for point in points:
        listed = make.get(f"/items/{point['hid']}")["controllers"]
        assert [(one["cluster"], one["name"]) for one in listed] == [
            ("east", "east-wlc-01"),
            ("east", "east-wlc-02"),
            ("west", "west-wlc-01"),
            ("west", "west-wlc-02"),
        ]
    # Two clusters, each one managed node, and the access points: four components more.
    totals = make.totals()
    assert (totals["component_count"], totals["managed_node_count"]) == (6, 4)


# --- a primary management address of each family ----------------------------------------


def test_a_record_has_a_primary_management_address_of_each_family(make: Maker) -> None:
    switch = make.item(hostname="site2-sw-access-01")
    v4 = make.address(switch, "192.0.2.10", is_primary=True)
    v6 = make.address(switch, "2001:db8::10", is_primary=True)

    assert (v4["family"], v6["family"]) == (4, 6)
    assert make.get(f"/addresses/{v4['hid']}")["is_primary"] is True
    held = make.get(f"/items/{switch['hid']}")["addresses"]
    assert sorted((one["address"], one["family"], one["is_primary"]) for one in held) == [
        ("192.0.2.10", 4, True),
        ("2001:db8::10", 6, True),
    ]
    # Another primary of one family takes the mark from that family alone.
    make.address(switch, "192.0.2.11", is_primary=True)
    assert make.get(f"/addresses/{v4['hid']}")["is_primary"] is False
    assert make.get(f"/addresses/{v6['hid']}")["is_primary"] is True


@pytest.mark.parametrize(
    ("head", "line", "expected"),
    [
        ("hostname", "site2-sw-01", []),
        ("hostname,IP_address", "site2-sw-01,192.0.2.10", ["192.0.2.10"]),
        ("hostname,ip", "site2-sw-01,2001:db8::10", ["2001:db8::10"]),
        ("hostname,IPv4_address", "site2-sw-01,192.0.2.10", ["192.0.2.10"]),
        ("hostname,ipv4,ipv6", "site2-sw-01,,2001:DB8::10", ["2001:db8::10"]),
        (
            "hostname,IPv4_address,IPv6_address",
            "site2-sw-01,192.0.2.10,2001:db8::10",
            ["192.0.2.10", "2001:db8::10"],
        ),
        ("hostname,mgmt_ipv4,mgmt_ipv6", "site2-sw-01,192.0.2.10,", ["192.0.2.10"]),
    ],
)
def test_a_first_file_of_host_names_and_addresses_loads_as_it_is(
    make: Maker, files: Files, head: str, line: str, expected: list[str]
) -> None:
    text = f"{head}\n{line}\n"

    assert counts(files.load("items", text)) == (1, 0, 0, 0)

    item = make.get("/items", filter="hostname:eq:site2-sw-01")["items"][0]
    held = sorted(one["address"] for one in item["addresses"] if one["is_primary"])
    assert held == expected
    assert all(one["role"] == "management" and one["network"] is None for one in item["addresses"])
    # Loaded again, it finds the item by its host name and changes nothing.
    assert counts(files.preview("items", text)["job"]) == (0, 0, 1, 0)


def test_the_management_columns_of_each_family(make: Maker, files: Files) -> None:
    switch = make.item(hostname="site2-sw-01", asset_tag="AT-000101")
    make.network("Red")
    head = "asset_tag,mgmt_ipv4,mgmt_ipv6,mgmt_network\n"
    files.load("items", f"{head}AT-000101,192.0.2.10,2001:db8::10,Red\n")
    held = make.get(f"/items/{switch['hid']}")["addresses"]
    assert sorted((one["address"], one["network"]) for one in held) == [
        ("192.0.2.10", "Red"),
        ("2001:db8::10", "Red"),
    ]

    # One family is cleared and the other left alone.
    files.load("items", f"{head}AT-000101,!clear,,\n")
    assert [one["address"] for one in make.get(f"/items/{switch['hid']}")["addresses"]] == [
        "2001:db8::10"
    ]
    # `mgmt_address` takes either family and files it under its own, and cleared removes both.
    files.load("items", "asset_tag,mgmt_address\nAT-000101,192.0.2.20\n")
    rows = table(
        files.export(
            "items", columns=["asset_tag", "mgmt_address", "mgmt_ipv4", "mgmt_ipv6", "mgmt_network"]
        )
    )
    assert (rows[0]["mgmt_address"], rows[0]["mgmt_ipv4"], rows[0]["mgmt_ipv6"]) == (
        "192.0.2.20",
        "192.0.2.20",
        "2001:db8::10",
    )
    again = files.export("items", columns=["asset_tag", "mgmt_address", "mgmt_ipv4", "mgmt_ipv6"])
    assert counts(files.preview("items", again)["job"]) == (0, 0, 1, 0)
    files.load("items", "asset_tag,mgmt_address\nAT-000101,!clear\n")
    assert make.get(f"/items/{switch['hid']}")["addresses"] == []

    for line, field, expected in (
        ("AT-000101,2001:db8::1,,", "mgmt_ipv4", "an IPv4 address; this one is IPv6"),
        ("AT-000101,,192.0.2.1,", "mgmt_ipv6", "an IPv6 address; this one is IPv4"),
        ("AT-000101,,,Red", "mgmt_network", "give mgmt_address, mgmt_ipv4 or mgmt_ipv6"),
    ):
        preview = files.preview("items", head + line + "\n")
        reasons = {entry["field"]: entry["message"] for entry in preview["rows"][0]["reasons"]}
        assert expected in reasons[field], line
    clash = "asset_tag,mgmt_address,mgmt_ipv4\nAT-000101,192.0.2.1,192.0.2.2\n"
    reasons = files.preview("items", clash)["rows"][0]["reasons"]
    assert "names another IPv4 address" in reasons[0]["message"]


# --- condition and observation in files -------------------------------------------------


def test_a_site_loads_what_it_observed_as_a_file(make: Maker, files: Files) -> None:
    for name in ("site2-sw-01", "site2-sw-02", "fibre tester"):
        make.item(name=name)
    text = (
        "name,condition,observed_status,observed_at\n"
        f"site2-sw-01,good,online,{SEEN}\n"
        "site2-sw-02,suspect,unreachable,2026-11-02T10:00:00-05:00\n"
        "fibre tester,,present,\n"
    )

    preview = files.preview("items", text)

    assert counts(preview["job"]) == (0, 3, 0, 0)
    assert changes(preview["rows"][0]) == {
        "condition": (None, "good"),
        "observed_status": (None, "online"),
        "observed_at": (None, "2026-11-02T15:00:00+00:00"),
    }
    # A moment the row does not give is the moment of the change, and is not part of
    # what the row is said to do: the preview and the apply are made at different ones.
    assert changes(preview["rows"][2]) == {"observed_status": (None, "present")}
    files.apply(preview)
    second = make.get("/items", filter="name:eq:site2-sw-02")["items"][0]
    assert (second["observed_at"], second["health"]["value"]) == (SEEN, "degraded")
    tester = make.get("/items", filter="name:eq:fibre tester")["items"][0]
    assert tester["observed_at"] is not None
    # The same file again changes nothing, and neither does what an export writes.
    assert counts(files.preview("items", text)["job"]) == (0, 0, 3, 0)
    exported = files.export(
        "items", columns=["name", "condition", "observed_status", "observed_at", "health"]
    )
    assert [row["health"] for row in table(exported)] == ["good", "good", "degraded"]
    assert counts(files.preview("items", exported)["job"]) == (0, 0, 3, 0)
    cleared = files.load("items", "name,observed_status\nsite2-sw-01,!clear\n")
    assert counts(cleared) == (0, 1, 0, 0)
    assert make.get("/items", filter="name:eq:site2-sw-01")["items"][0]["observed_at"] is None

    bad = files.preview("items", "name,observed_status,observed_at\nsite2-sw-01,asleep,yesterday\n")
    reasons = {entry["field"] for entry in bad["rows"][0]["reasons"]}
    assert reasons == {"observed_at"}


def test_a_walk_round_the_store_room_is_one_bulk_edit(make: Maker) -> None:
    make.tag("spares")
    for number in (1, 2, 3):
        make.item(name=f"spare-{number}", tags=["spares"])

    preview = make.post(
        "/items/bulk-update",
        {"filter": "tags:has:spares", "set": {"observed_status": "present", "condition": "good"}},
    )
    assert [row["outcome"] for row in preview["rows"]] == ["update"] * 3
    make.post(f"/items/bulk-update/{preview['job']['hid']}/apply", {}, 200)

    assert make.found(filter="health:eq:good") == ["spare-1", "spare-2", "spare-3"]


def test_the_master_that_is_seen_travels_on_the_row_of_its_member(
    make: Maker, files: Files
) -> None:
    entry = _entry(make)
    switches = make.switches(entry, "site2-sw-stack1", 2)
    stack = make.stack("site2-sw-stack1", switches)
    head = "group,item,observed_master,master_observed_at\n"

    preview = files.preview(
        "device_group_members", f"{head}site2-sw-stack1,SITE2-SW-STACK1-002,true,{SEEN}\n"
    )
    assert changes(preview["rows"][0]) == {
        "observed_master": (False, True),
        "master_observed_at": (None, "2026-11-02T15:00:00+00:00"),
    }
    files.apply(preview)
    seen = make.get(f"/device-groups/{stack['hid']}")
    assert (seen["serial_number"], seen["master_observed_at"]) == ("SITE2-SW-STACK1-002", SEEN)
    # The intended master is not touched by it.
    assert seen["master"]["serial_number"] == "SITE2-SW-STACK1-001"

    exported = files.export("device_group_members", own_values=True)
    assert [row["observed_master"] for row in table(exported)] == ["false", "true"]
    assert counts(files.preview("device_group_members", exported)["job"]) == (0, 0, 2, 0)
    files.load("device_group_members", f"{head}site2-sw-stack1,SITE2-SW-STACK1-002,false,\n")
    assert make.get(f"/device-groups/{stack['hid']}")["observed_master"] is None


def test_groups_carry_how_they_are_managed_and_what_is_observed(make: Maker, files: Files) -> None:
    text = (
        "name,type,managed_as,expected_members,observed_status,observed_at,ipv4,ipv6\n"
        f"site2-fw-edge,cluster,members,2,online,{SEEN},192.0.2.4,2001:db8::4\n"
        "site2-wlc-ha,cluster,,,,,,\n"
        "site2-sw-stack1,stack,,3,,,,\n"
    )
    assert counts(files.load("device_groups", text)) == (3, 0, 0, 0)

    groups = {group["name"]: group for group in make.get("/device-groups")["items"]}
    edge = groups["site2-fw-edge"]
    assert (edge["managed_as"], edge["expected_members"], edge["observed_at"]) == (
        "members",
        2,
        SEEN,
    )
    assert sorted(one["address"] for one in edge["addresses"]) == ["192.0.2.4", "2001:db8::4"]
    assert (groups["site2-wlc-ha"]["managed_as"], groups["site2-sw-stack1"]["managed_as"]) == (
        "one",
        None,
    )
    exported = files.export("device_groups", own_values=True)
    assert counts(files.preview("device_groups", exported)["job"]) == (0, 0, 3, 0)
    bad = files.preview("device_groups", "name,type,managed_as\nx,stack,members\n")
    assert bad["rows"][0]["reasons"][0]["field"] == "managed_as"


# --- the two reports ---------------------------------------------------------------------


def test_the_summary_holds_health_and_no_money(make: Maker) -> None:
    entry = _entry(make, est_value="18000", support_weight="1", annual_support_cost="1450")
    fields = {"catalog_entry_hid": entry["hid"], "lifecycle_state": "Prod"}
    make.item(serial_number="A1", condition="good", **fields)
    make.item(serial_number="A2", condition="failed", **fields)
    make.item(serial_number="A3", **fields)
    part = make.item(name="PS-A", parent_item_hid=make.get("/items")["items"][0]["hid"])
    _patch(make, f"/items/{part['hid']}", condition="dead")

    summary = make.get("/reports/summary", by="condition")

    totals = summary["totals"]
    assert set(totals) == {
        "items",
        "component_count",
        "managed_node_count",
        "support_weight",
        "by_health",
        "by_condition",
        "by_kind",
    }
    assert (totals["items"], totals["component_count"], totals["support_weight"]) == (4, 3, "3")
    # The components by health: the minor item is not one of them.
    assert totals["by_health"] == {"good": 1, "degraded": 0, "failed": 1, "unknown": 1}
    assert [
        (one["key"], one["label"], one["component_count"]) for one in totals["by_condition"]
    ] == [
        ("good", "Good", 1),
        ("failed", "Failed", 1),
        ("dead", "Dead", 0),
        (None, None, 1),
    ]
    assert [(row["key"], row["label"], row["items"]) for row in summary["rows"]] == [
        ("dead", "Dead", 1),
        ("failed", "Failed", 1),
        ("good", "Good", 1),
        (None, None, 1),
    ]
    assert all("est_value" not in row and "by_health" in row for row in summary["rows"])


def test_the_management_report_holds_the_money_and_no_health(
    make: Maker, client: TestClient, viewer: dict
) -> None:
    ours, theirs = make.owner(), make.owner("Voice Services")
    switch = _entry(make, est_value="18000", annual_support_cost="1450")
    phone = _entry(make, "CP-8851-K9", est_value="420")
    make.item(catalog_entry_hid=switch["hid"], serial_number="A1", owner_hid=ours["hid"])
    make.item(
        catalog_entry_hid=switch["hid"],
        serial_number="A2",
        owner_hid=ours["hid"],
        est_value="20000",
        annual_support_cost="2000",
    )
    make.item(
        catalog_entry_hid=phone["hid"], serial_number="P1", owner_hid=theirs["hid"], quantity=10
    )

    whole = make.get("/reports/management")
    by_owner = make.get("/reports/management", by="owner")

    # Asked for by nothing, it is by site: nothing is anywhere yet, so all of it is in
    # the one row of the items that are nowhere.
    money = {
        "items": 3,
        "component_count": 3,
        "est_value": "42200.00",
        "annual_support_cost": "3450.00",
    }
    assert whole == {"by": "site", "totals": money, "rows": [{"key": None, "label": None, **money}]}
    assert [
        (row["label"], row["est_value"], row["annual_support_cost"]) for row in by_owner["rows"]
    ] == [
        ("Network Engineering", "38000.00", "3450.00"),
        ("Voice Services", "4200.00", "0.00"),
    ]
    assert Decimal(by_owner["totals"]["est_value"]) == sum(
        Decimal(row["est_value"]) for row in by_owner["rows"]
    )
    filtered = make.get("/reports/management", filter="owner.label:eq:Voice Services")
    assert filtered["totals"]["est_value"] == "4200.00"
    # Neither condition nor health is a way to cut the money.
    assert make.get("/reports/management", expect=422, by="health")["status"] == 422
    assert client.get(f"{API}/reports/management", headers=viewer).status_code == 200
    assert client.get(f"{API}/reports/management").status_code == 401


# --- a site's own file finds the items it has (D-108) ------------------------------------


def test_a_file_of_host_names_finds_the_items_that_have_serial_numbers(
    make: Maker, files: Files
) -> None:
    entry = _entry(make)
    first = make.item(
        catalog_entry_hid=entry["hid"], serial_number="FCW0000X001", hostname="site2-sw-01"
    )
    # An item with a name of its own is found by its host name all the same.
    second = make.item(
        catalog_entry_hid=entry["hid"],
        serial_number="FCW0000X002",
        name="Core switch A",
        hostname="site2-sw-02",
    )
    text = (
        "hostname,observed_status,observed_at,IP_address\n"
        f"site2-sw-01,online,{SEEN},192.0.2.11\n"
        f"SITE2-SW-02,unreachable,{SEEN},192.0.2.12\n"
        "site2-sw-99,present,,\n"
    )

    preview = files.preview("items", text)

    # The two that are there are changed, and no second item is made beside either.
    assert [row["outcome"] for row in preview["rows"]] == ["update", "update", "create"]
    assert [row["record_hid"] for row in preview["rows"][:2]] == [first["hid"], second["hid"]]
    files.apply(preview)
    assert make.get("/items", limit=1)["total"] == 3
    found = make.get(f"/items/{second['hid']}")
    assert (found["name"], found["serial_number"], found["observed_status"]) == (
        "Core switch A",
        "FCW0000X002",
        "unreachable",
    )
    assert [one["address"] for one in found["addresses"]] == ["192.0.2.12"]
    # The same file again changes nothing.
    assert counts(files.preview("items", text)["job"]) == (0, 0, 3, 0)


def test_a_name_that_two_items_answer_to_is_never_a_guess(make: Maker, files: Files) -> None:
    entry = _entry(make)
    for serial in ("FCW0000X001", "FCW0000X002"):
        make.item(catalog_entry_hid=entry["hid"], serial_number=serial, hostname="site2-sw-01")
    make.item(name="spare shelf", hostname="shelf-1")

    preview = files.preview("items", "hostname,condition\nsite2-sw-01,good\n")
    row = preview["rows"][0]
    assert row["outcome"] == "rejected"
    assert "more than one item answers to this" in row["reasons"][0]["message"]
    # A row that gives a name is matched on the name, and a retired item is not found.
    by_name = files.preview("items", "name,condition\nspare shelf,good\n")
    assert by_name["rows"][0]["outcome"] == "update"
    shelf = make.get("/items", filter="name:eq:spare shelf")["items"][0]
    make.post(f"/items/{shelf['hid']}/retire", {"row_version": shelf["row_version"]}, 200)
    assert files.preview("items", "name,condition\nspare shelf,good\n")["rows"][0]["outcome"] == (
        "create"
    )
    # A row with a serial number and its model is still told by those alone.
    with_serial = "vendor,pid,serial_number,hostname\nCisco,C9300-48P,FCW0000X003,site2-sw-01\n"
    assert files.preview("items", with_serial)["rows"][0]["outcome"] == "create"


def test_addresses_are_listed_and_exported_with_their_family(make: Maker, files: Files) -> None:
    switch = make.item(hostname="site2-sw-01")
    make.address(switch, "192.0.2.10")
    make.address(switch, "2001:db8::10")

    six = make.get("/addresses", filter="family:eq:6")["items"]
    assert [one["address"] for one in six] == ["2001:db8::10"]
    assert [one["address"] for one in make.get("/addresses", sort="-family")["items"]] == [
        "2001:db8::10",
        "192.0.2.10",
    ]
    exported = table(files.export("addresses", columns=["address", "family"]))
    assert [(row["address"], row["family"]) for row in exported] == [
        ("192.0.2.10", "4"),
        ("2001:db8::10", "6"),
    ]
