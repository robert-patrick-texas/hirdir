"""Networks and addresses: what an item or a group is reached at, and under which label."""

from fastapi.testclient import TestClient

from tests.api.inventory import API, Maker, errors

NOBODY = "01900000-0000-7000-8000-000000000000"


def _switch(make: Maker, name: str = "site2-sw-access-01") -> dict:
    return make.item(hostname=name)


def test_an_address_is_kept_in_one_form_whatever_notation_it_came_in(make: Maker) -> None:
    switch = _switch(make)
    red = make.network("Red")

    first = make.address(switch, " 192.0.2.10 ", red, is_primary=True)
    second = make.address(switch, "2001:0DB8:0000:0000:0000:0000:0000:0010", role="loopback")

    assert (first["address"], first["role"], first["is_primary"]) == (
        "192.0.2.10",
        "management",
        True,
    )
    assert first["network"] == {"hid": red["hid"], "label": "Red"}
    assert first["item"]["name"] == "site2-sw-access-01"
    assert (second["address"], second["network"], second["group"]) == ("2001:db8::10", None, None)
    # The item lists its addresses, the primary one first.
    item = make.get(f"/items/{switch['hid']}")
    assert [(one["address"], one["network"], one["is_primary"]) for one in item["addresses"]] == [
        ("192.0.2.10", "Red", True),
        ("2001:db8::10", None, False),
    ]
    assert make.get("/networks")["items"][0]["uses"] == 1


def test_what_is_not_an_address_is_refused(make: Maker) -> None:
    switch = _switch(make)

    for given, expected in (
        ("192.0.2.0/24", "no prefix length"),
        ("fe80::1%eth0", "no prefix length"),
        ("192.0.2.300", "such as 192.0.2.10"),
        ("site2-sw-access-01", "such as 192.0.2.10"),
    ):
        problem = make.address(switch, given, expect=422)
        assert expected in errors(problem)["address"], given
    problem = make.post(
        "/addresses", {"item_hid": switch["hid"], "address": "192.0.2.1", "role": "gateway"}, 422
    )
    assert problem["status"] == 422
    problem = make.post(
        "/addresses",
        {"item_hid": switch["hid"], "address": "192.0.2.1", "network_hid": NOBODY},
        422,
    )
    assert "there is no network" in errors(problem)["network_hid"]


def test_an_address_belongs_to_an_item_or_to_a_group_and_stays_there(make: Maker) -> None:
    switch = _switch(make)
    stack = make.group("site2-sw-stack1", "stack")

    for body in (
        {"address": "192.0.2.1"},
        {"address": "192.0.2.1", "item_hid": switch["hid"], "group_hid": stack["hid"]},
    ):
        problem = make.post("/addresses", body, expect=422)
        assert errors(problem) == {"item_hid": "give an item or a group, and not both"}
    problem = make.post("/addresses", {"address": "192.0.2.1", "item_hid": NOBODY}, expect=422)
    assert "there is no item" in errors(problem)["item_hid"]

    held = make.address(stack, "192.0.2.1", is_primary=True)
    assert (held["group"]["name"], held["item"]) == ("site2-sw-stack1", None)
    group = make.get(f"/device-groups/{stack['hid']}")
    assert [one["address"] for one in group["addresses"]] == ["192.0.2.1"]
    assert make.get("/device-groups", filter="address:eq:192.0.2.1")["total"] == 1


def test_one_primary_management_address_to_a_record(make: Maker) -> None:
    switch = _switch(make)
    first = make.address(switch, "192.0.2.10", is_primary=True)

    second = make.address(switch, "192.0.2.11", is_primary=True)

    # Marking the second took the mark off the first, in the same request.
    assert second["is_primary"] is True
    again = make.get(f"/addresses/{first['hid']}")
    assert (again["is_primary"], again["row_version"]) == (False, first["row_version"] + 1)
    events = make.audit(record_type="address")
    assert [event["action"] for event in events] == ["update", "create", "create"]
    assert events[0]["request_id"] == events[1]["request_id"]
    # And back again, by a change.
    make.patch(
        f"/addresses/{again['hid']}", {"row_version": again["row_version"], "is_primary": True}
    )
    assert make.get(f"/addresses/{second['hid']}")["is_primary"] is False

    problem = make.address(switch, "2001:db8::1", role="loopback", is_primary=True, expect=422)
    assert "role management" in errors(problem)["is_primary"]
    current = make.get(f"/addresses/{first['hid']}")
    problem = make.patch(
        f"/addresses/{first['hid']}",
        {"row_version": current["row_version"], "role": "virtual"},
        expect=422,
    )
    assert "role management" in errors(problem)["is_primary"]


def test_an_address_is_changed_and_removed_and_the_trail_holds_what_it_was(make: Maker) -> None:
    switch = _switch(make)
    red, black = make.network("Red"), make.network("Black")
    held = make.address(switch, "192.0.2.10", red)

    moved = make.patch(
        f"/addresses/{held['hid']}",
        {"row_version": held["row_version"], "address": "192.0.2.20", "network_hid": black["hid"]},
    )
    assert (moved["address"], moved["network"]["label"]) == ("192.0.2.20", "Black")
    stale = make.patch(
        f"/addresses/{held['hid']}",
        {"row_version": held["row_version"], "role": "secondary"},
        expect=409,
    )
    assert stale["status"] == 409

    make.delete(f"/addresses/{held['hid']}")
    make.get(f"/addresses/{held['hid']}", expect=404)
    removal = make.audit(record_hid=held["hid"])[0]
    assert removal["action"] == "delete"
    assert {"field": "address", "old": "192.0.2.20", "new": None} in removal["changes"]
    assert {"field": "item_hid", "old": switch["hid"], "new": None} in removal["changes"]
    assert make.get(f"/items/{switch['hid']}")["addresses"] == []


def test_a_network_has_a_label_of_its_own_and_goes_only_when_empty(make: Maker) -> None:
    red = make.network("Red")
    assert (red["label"], red["kind"], red["uses"]) == ("Red", "vrf", 0)
    assert make.post("/networks", {"label": "Lab"})["kind"] == "network"

    problem = make.post("/networks", {"label": " red "}, expect=409)
    assert errors(problem) == {"label": "another network has this label"}
    renamed = make.patch(
        f"/networks/{red['hid']}", {"row_version": red["row_version"], "label": "Crimson"}
    )
    assert renamed["label"] == "Crimson"

    held = make.address(_switch(make), "192.0.2.10", red)
    problem_response = make.client.delete(f"{API}/networks/{red['hid']}", headers=make.headers)
    assert problem_response.status_code == 409
    assert "1 addresses are under Crimson" in problem_response.json()["detail"]
    make.delete(f"/addresses/{held['hid']}")
    make.delete(f"/networks/{red['hid']}")
    assert [network["label"] for network in make.get("/networks")["items"]] == ["Lab"]
    assert make.audit(record_hid=red["hid"])[0]["action"] == "delete"


def test_items_are_found_by_any_of_their_addresses(make: Maker) -> None:
    first, second, third = (_switch(make, f"site2-sw-access-0{number}") for number in (1, 2, 3))
    red = make.network("Red")
    make.address(first, "192.0.2.10", red)
    make.address(first, "2001:db8::10")
    make.address(second, "192.0.2.11")

    assert make.found(filter="address:eq:192.0.2.10") == ["site2-sw-access-01"]
    # Any common notation is taken, and compared in the stored form.
    assert make.found(filter="address:eq:2001:0db8:0:0:0:0:0:10") == ["site2-sw-access-01"]
    assert make.found(filter="address:prefix:192.0.2.") == [
        "site2-sw-access-01",
        "site2-sw-access-02",
    ]
    assert make.found(filter="address:in:192.0.2.11,192.0.2.99") == ["site2-sw-access-02"]
    assert make.found(filter="network.label:eq:red") == ["site2-sw-access-01"]
    # None of its addresses is that one: the item with no address is among them.
    assert make.found(filter="address:ne:192.0.2.10") == [
        "site2-sw-access-02",
        "site2-sw-access-03",
    ]
    assert make.found(filter="address:empty:true") == ["site2-sw-access-03"]
    assert make.found(filter="network.label:empty:true") == [
        "site2-sw-access-02",
        "site2-sw-access-03",
    ]
    assert third["addresses"] == []


def test_the_address_list_filters_and_sorts(make: Maker) -> None:
    switch = _switch(make)
    stack = make.group("site2-sw-stack1", "stack")
    red = make.network("Red")
    make.address(switch, "192.0.2.10", red, is_primary=True)
    make.address(switch, "192.0.2.12", role="secondary")
    make.address(stack, "192.0.2.11", red)

    def listed(**params) -> list[str]:
        return [row["address"] for row in make.get("/addresses", **params)["items"]]

    assert listed() == ["192.0.2.10", "192.0.2.11", "192.0.2.12"]
    assert listed(filter="network.label:eq:Red") == ["192.0.2.10", "192.0.2.11"]
    assert listed(filter="is_primary:eq:true") == ["192.0.2.10"]
    assert listed(filter="role:eq:secondary") == ["192.0.2.12"]
    assert listed(filter="group.name:eq:site2-sw-stack1") == ["192.0.2.11"]
    assert listed(filter=f"item_hid:eq:{switch['hid']}", sort="-address") == [
        "192.0.2.12",
        "192.0.2.10",
    ]
    assert listed(filter="item.name:prefix:site2-sw") == ["192.0.2.10", "192.0.2.12"]
    page = make.post(
        "/addresses/query", {"filter": {"field": "address", "op": "contains", "value": ".1"}}, 200
    )
    assert page["total"] == 3
    # The list is in the order of addresses and not of their text, IPv4 before IPv6.
    make.address(stack, "192.0.2.9")
    make.address(stack, "2001:db8::1")
    assert (
        listed()
        == listed(sort="address")
        == [
            "192.0.2.9",
            "192.0.2.10",
            "192.0.2.11",
            "192.0.2.12",
            "2001:db8::1",
        ]
    )
    assert listed(sort="-address")[:2] == ["2001:db8::1", "192.0.2.12"]


def test_the_same_address_twice_under_one_network_is_reported_not_refused(make: Maker) -> None:
    first, second = _switch(make, "site2-rtr-wan-01"), _switch(make, "site2-rtr-wan-02")
    stack = make.group("site2-sw-stack1", "stack")
    red, black = make.network("Red"), make.network("Black")

    make.address(first, "192.0.2.254", red)
    make.address(first, "192.0.2.254", black)
    make.address(first, "198.51.100.1")
    assert make.get("/reports/duplicates") == {"items": [], "total": 0, "limit": 100, "offset": 0}

    make.address(second, "192.0.2.254", red, role="virtual")
    # With no network, the unlabelled address space is one network of its own.
    make.address(stack, "198.51.100.1")
    report = make.get("/reports/duplicates")

    assert report["total"] == 2
    red_pair, plain_pair = report["items"]
    assert (red_pair["address"], red_pair["network"], red_pair["count"]) == (
        "192.0.2.254",
        "Red",
        2,
    )
    assert sorted(holder["name"] for holder in red_pair["holders"]) == [
        "site2-rtr-wan-01",
        "site2-rtr-wan-02",
    ]
    assert (plain_pair["address"], plain_pair["network"], plain_pair["network_hid"]) == (
        "198.51.100.1",
        None,
        None,
    )
    assert sorted(holder["name"] for holder in plain_pair["holders"]) == [
        "site2-rtr-wan-01",
        "site2-sw-stack1",
    ]
    assert (
        make.get("/reports/duplicates", limit=1, offset=1)["items"][0]["address"] == "198.51.100.1"
    )


def test_the_duplicates_report_leaves_out_what_a_list_leaves_out(make: Maker) -> None:
    first, second = _switch(make, "site2-rtr-wan-01"), _switch(make, "site2-rtr-wan-02")
    make.address(first, "192.0.2.254")
    make.address(second, "192.0.2.254")
    assert make.get("/reports/duplicates")["total"] == 1

    make.post(f"/items/{second['hid']}/retire", {"row_version": second["row_version"]}, 200)

    assert make.get("/reports/duplicates")["total"] == 0
    assert make.get("/reports/duplicates", include_archived="true")["total"] == 1


def test_addresses_are_read_by_all_and_changed_by_the_inventory_role(
    client: TestClient, make: Maker, viewer: dict
) -> None:
    switch = _switch(make)
    red = make.network("Red")
    held = make.address(switch, "192.0.2.10", red)

    for path in ("/addresses", "/networks", "/reports/duplicates", f"/addresses/{held['hid']}"):
        assert client.get(API + path, headers=viewer).status_code == 200
        assert client.get(API + path).status_code == 401
    refusals = (
        client.post(API + "/networks", json={"label": "Blue"}, headers=viewer),
        client.patch(
            f"{API}/networks/{red['hid']}", json={"row_version": 1, "label": "Blue"}, headers=viewer
        ),
        client.delete(f"{API}/networks/{red['hid']}", headers=viewer),
        client.post(
            API + "/addresses",
            json={"item_hid": switch["hid"], "address": "192.0.2.1"},
            headers=viewer,
        ),
        client.patch(
            f"{API}/addresses/{held['hid']}",
            json={"row_version": 1, "role": "virtual"},
            headers=viewer,
        ),
        client.delete(f"{API}/addresses/{held['hid']}", headers=viewer),
    )
    assert [response.status_code for response in refusals] == [403] * 6


def test_the_duplicates_report_is_sorted_by_its_columns(make: Maker) -> None:
    red, blue = make.network("Red"), make.network("blue")
    delta, alpha, charlie, bravo, echo = (
        _switch(make, name) for name in ("Delta", "alpha", "Charlie", "bravo", "echo")
    )
    for holder in (delta, charlie, echo):
        make.address(holder, "192.0.2.9", red)
    for holder in (alpha, bravo):
        make.address(holder, "192.0.2.10", blue)
    for holder in (delta, bravo):
        make.address(holder, "192.0.2.100")

    def report(**params) -> list[str]:
        found = make.get("/reports/duplicates", **params)
        assert found["total"] == 3
        return [row["address"].rpartition(".")[2] for row in found["items"]]

    # As it was, by the address as text. Asked for, by the address as an address.
    assert report() == ["10", "100", "9"]
    assert report(sort="address") == ["9", "10", "100"]
    assert report(sort="-address") == ["100", "10", "9"]
    # By the label of the network, and the unlabelled address space last either way.
    assert report(sort="network") == ["10", "9", "100"]
    assert report(sort="-network") == ["9", "10", "100"]
    # By how many hold it, and what that leaves tied is in the order it always had.
    assert report(sort="count") == ["10", "100", "9"]
    assert report(sort="-count") == ["9", "10", "100"]
    # By the first of its holders by name: alpha, bravo, Charlie.
    assert report(sort="holders") == ["10", "100", "9"]
    assert report(sort="-holders") == ["9", "100", "10"]
    # A page of a sorted report holds the holders of its own rows.
    second = make.get("/reports/duplicates", sort="-holders", limit=1, offset=1)["items"]
    assert [row["address"] for row in second] == ["192.0.2.100"]
    assert sorted(holder["name"] for holder in second[0]["holders"]) == ["Delta", "bravo"]
    problem = make.get("/reports/duplicates", 422, sort="role")
    assert "role is not a field" in errors(problem)["sort"]
