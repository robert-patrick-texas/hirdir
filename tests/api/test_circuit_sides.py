"""The two sides of a circuit (P-317, P-319, P-320): the Z side's dates, read as the A
side's where blank and held to their order on what is in force; the dates of the side
`cost_side` names deciding its service, its cost and its weight; and the carrier network
a Z side reaches, a circuit group of the kind network, which lists the circuits whose Z
side names it."""

import csv
import io
import json
from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from hirdir.db.models import Circuit
from hirdir.domain import records
from hirdir.io.circuit_costs import circuit_costs
from tests.api.inventory import API, errors
from tests.api.test_circuits import Desk
from tests.api.test_files import Files, counts, table

TODAY = date.today()


@pytest.fixture
def desk(client: TestClient, inventory: dict[str, str]) -> Desk:
    return Desk(client, inventory)


@pytest.fixture
def places(desk: Desk) -> dict[str, dict[str, Any]]:
    return desk.places()


@pytest.fixture
def files(client: TestClient, inventory: dict[str, str]) -> Files:
    return Files(client, inventory)


def _network(desk: Desk, name: str = "Example MPLS East", **more: Any) -> dict[str, Any]:
    return desk.post("/circuit-groups", {"name": name, "kind": "network", **more})


def _members(desk: Desk, group: dict[str, Any]) -> list[tuple[str, bool, bool]]:
    """Return each circuit of a group: its name, whether it has a membership, and
    whether its Z side names the group."""
    found = desk.get(f"/circuit-groups/{group['hid']}/members")
    assert found["total"] == len(found["items"])
    return [
        (one["circuit"]["name"], one["hid"] is not None, one["z_side"]) for one in found["items"]
    ]


def _retire(desk: Desk, path: str, record: dict[str, Any], expect: int = 200) -> Any:
    now = desk.get(f"{path}/{record['hid']}")
    return desk.post(f"{path}/{record['hid']}/retire", {"row_version": now["row_version"]}, expect)


def _csv(row: dict[str, str]) -> str:
    """Return one row of a file, with its header, as an export writes it."""
    written = io.StringIO()
    writer = csv.DictWriter(written, fieldnames=list(row))
    writer.writeheader()
    writer.writerow(row)
    return written.getvalue()


# --- the Z side's dates --------------------------------------------------------------


def test_a_blank_date_of_the_z_side_is_the_a_sides_with_its_source_and_is_not_copied(
    desk: Desk, places: dict[str, dict[str, Any]]
) -> None:
    made = desk.circuit(
        "Site-2 to Site-3",
        a_location_hid=places["room"]["hid"],
        z_location_hid=places["annex"]["hid"],
        a_installed_on="2027-03-29",
        a_activated_on="2027-04-10",
        z_installed_on="2027-04-02",
    )
    assert (made["a_installed_on"], made["a_activated_on"], made["a_disconnected_on"]) == (
        "2027-03-29",
        "2027-04-10",
        None,
    )
    assert (made["z_installed_on"], made["z_activated_on"], made["z_disconnected_on"]) == (
        "2027-04-02",
        None,
        None,
    )
    effective = made["effective"]
    assert effective["z_installed_on"] == {
        "value": "2027-04-02",
        "source": "own",
        "source_hid": None,
    }
    assert effective["z_activated_on"] == {
        "value": "2027-04-10",
        "source": "a_side",
        "source_hid": None,
    }
    assert effective["z_disconnected_on"] == {"value": None, "source": "none", "source_hid": None}
    created = desk.audit(record_type="circuit", record_hid=made["hid"])[0]
    assert {"field": "z_installed_on", "old": None, "new": "2027-04-02"} in created["changes"]
    # A change of the A side's activation is read on the Z side: nothing was copied.
    moved = desk.patch(
        f"/circuits/{made['hid']}",
        {"row_version": made["row_version"], "a_activated_on": "2027-04-12"},
    )
    assert moved["z_activated_on"] is None
    assert moved["effective"]["z_activated_on"]["value"] == "2027-04-12"
    # The list filters and sorts by each side's own dates and by the Z side's in force.
    desk.circuit(
        "Site-3 internet",
        a_location_hid=places["annex"]["hid"],
        z_note="carrier network",
        a_activated_on="2027-05-01",
    )
    assert desk.names(filter="effective.z_activated_on:eq:2027-04-12") == ["Site-2 to Site-3"]
    assert desk.names(filter="z_activated_on:empty:true") == ["Site-2 to Site-3", "Site-3 internet"]
    assert desk.names(filter="z_installed_on:empty:false") == ["Site-2 to Site-3"]
    assert desk.names(sort="-effective.z_activated_on") == ["Site-3 internet", "Site-2 to Site-3"]
    assert desk.names(filter="a_activated_on:gt:2027-04-30") == ["Site-3 internet"]
    # Any Z side has dates of its own: one with a note alone among them.
    noted = desk.get("/circuits", filter="name:eq:Site-3 internet")["items"][0]
    changed = desk.patch(
        f"/circuits/{noted['hid']}",
        {"row_version": noted["row_version"], "z_activated_on": "2027-05-03"},
    )
    assert changed["effective"]["z_activated_on"]["source"] == "own"


def test_each_sides_dates_keep_their_order_on_what_is_in_force(
    desk: Desk, places: dict[str, dict[str, Any]]
) -> None:
    sides: dict[str, Any] = {
        "a_location_hid": places["room"]["hid"],
        "z_location_hid": places["annex"]["hid"],
    }

    def refused(**dates: str) -> dict[str, str]:
        return errors(desk.circuit("Out of order", 422, **sides, **dates))

    # The Z side's own activation before its own installation, or before the A side's
    # where it has none; its disconnection before its activation in force.
    assert "z_activated_on" in refused(z_installed_on="2027-04-05", z_activated_on="2027-04-04")
    assert "z_activated_on" in refused(a_installed_on="2027-04-05", z_activated_on="2027-04-01")
    assert "z_disconnected_on" in refused(
        a_activated_on="2027-04-10", z_disconnected_on="2027-04-09"
    )
    assert "z_disconnected_on" in refused(
        z_installed_on="2027-04-10", z_disconnected_on="2027-04-09"
    )
    # A Z side installed later than the A side's activation needs its own activation.
    assert "z_activated_on" in refused(a_activated_on="2027-04-10", z_installed_on="2027-04-12")
    # The A side's own order is the A side's, as before.
    assert "a_activated_on" in refused(a_installed_on="2027-04-05", a_activated_on="2027-04-01")
    made = desk.circuit(
        "Site-2 to Site-3",
        **sides,
        a_installed_on="2027-03-29",
        a_activated_on="2027-04-10",
        z_activated_on="2027-04-17",
    )

    def moved(**dates: str) -> dict[str, str]:
        now = desk.again(made)
        body = {"row_version": now["row_version"], **dates}
        return errors(desk.patch(f"/circuits/{made['hid']}", body, 422))

    # A change of the A side's dates that puts the Z side's in force out of order is
    # refused at the Z side's field it breaks: the A side installed after the Z side's
    # activation, which is then before the Z side's installation in force; and the A side
    # disconnected before it, the Z side's disconnection in force being the A side's.
    assert set(moved(a_installed_on="2027-04-20", a_activated_on="2027-04-25")) == {
        "z_activated_on"
    }
    assert set(moved(a_disconnected_on="2027-04-15")) == {"z_disconnected_on"}
    shown = desk.again(made)
    assert (shown["a_installed_on"], shown["a_disconnected_on"]) == ("2027-03-29", None)
    # With the Z side's own disconnection, the A side may end first.
    both = desk.patch(
        f"/circuits/{made['hid']}",
        {
            "row_version": shown["row_version"],
            "a_disconnected_on": "2027-04-15",
            "z_disconnected_on": "2027-04-30",
        },
    )
    assert both["effective"]["z_disconnected_on"]["source"] == "own"


def test_the_dates_of_the_side_cost_side_names_decide_service_cost_and_weight(
    desk: Desk, places: dict[str, dict[str, Any]], client: TestClient, db: Session
) -> None:
    room, annex = places["room"]["hid"], places["annex"]["hid"]
    later = (TODAY + timedelta(days=20)).isoformat()
    sides: dict[str, Any] = {
        "a_location_hid": room,
        "z_location_hid": annex,
        "a_activated_on": "2025-01-01",
    }
    # The Z side is activated in twenty days; the A side was long ago.
    by_z = desk.circuit("Counted at Z", **sides, cost_side="z", z_activated_on=later)
    by_a = desk.circuit("Counted at A", **sides, cost_side="a", z_activated_on=later)
    for made in (by_z, by_a):
        desk.part(made, "costs", {"description": "Port", "monthly_cost": "1000"})
    assert (desk.again(by_z)["in_service"], desk.again(by_a)["in_service"]) == (False, True)
    assert (desk.again(by_z)["monthly_cost"], desk.again(by_a)["monthly_cost"]) == (
        "0.00",
        "1000.00",
    )
    assert desk.names(filter="in_service:eq:true") == ["Counted at A"]
    assert desk.names(filter="monthly_cost:gt:0") == ["Counted at A"]
    # The weight: the A side disconnected ten days ago, the Z side in ten days.
    gone, going = (TODAY - timedelta(days=10)), (TODAY + timedelta(days=10))
    for name, side in (("Weighed at Z", "z"), ("Weighed at A", "a")):
        db.add(
            Circuit(
                name=name,
                name_key=records.key(name),
                a_location_hid=room,
                z_location_hid=annex,
                cost_side=side,
                support_weight=4 if side == "z" else 16,
                a_disconnected_on=gone,
                z_disconnected_on=going,
            )
        )
    db.commit()
    report = desk.get("/reports/capacity")
    # The first two carry the default, none; of the others the one counted at Z alone.
    assert report["active"]["circuits_weight"] == "4"
    # What circuits cost: the months by the dates of the side cost_side names.
    year = TODAY.year + 1
    first = desk.circuit(
        "From April",
        a_location_hid=room,
        z_location_hid=annex,
        cost_side="z",
        a_activated_on=f"{year}-01-01",
        z_activated_on=f"{year}-04-10",
    )
    desk.part(first, "costs", {"description": "Port", "monthly_cost": "1000"})
    found = circuit_costs(db, fiscal_year=year, filter_="name:eq:From April")
    assert str(found.totals.cost) == "8700.00"
    # The row's filter lists it by the Z side's dates in force, and not one ended before.
    ended = desk.circuit(
        "Ended before",
        a_location_hid=room,
        z_location_hid=annex,
        cost_side="z",
        a_activated_on="2025-01-01",
        a_disconnected_on=f"{year}-06-30",
        z_disconnected_on=f"{year - 1}-12-31",
    )
    whole = circuit_costs(db, fiscal_year=year, by="site")
    assert whole.totals.filter is not None
    listed = client.post(
        f"{API}/circuits/query",
        json={"filter": whole.totals.filter, "include_archived": True, "limit": 100},
        headers=desk.headers,
    ).json()["items"]
    names = [row["name"] for row in listed]
    assert "From April" in names
    assert ended["name"] not in names


# --- the network a Z side reaches ----------------------------------------------------


def test_a_z_side_names_a_network_and_never_a_collection_nor_a_location_beside_it(
    desk: Desk, places: dict[str, dict[str, Any]]
) -> None:
    telecom = desk.vendor("Example Telecom")
    network = _network(desk, carrier_hid=telecom["hid"])
    assert (network["kind"], network["carrier"]) == (
        "network",
        {"hid": telecom["hid"], "name": "Example Telecom"},
    )
    collection = desk.post("/circuit-groups", {"name": "Internet access"})
    assert (collection["kind"], collection["carrier_hid"]) == ("collection", None)
    room, annex = places["room"]["hid"], places["annex"]["hid"]
    # A Z side that names a network needs no note.
    made = desk.circuit("Site-2 MPLS", a_location_hid=room, z_group_hid=network["hid"])
    assert (made["z_side"], made["z_note"]) == (None, None)
    assert made["z_group"] == {
        "hid": network["hid"],
        "name": "Example MPLS East",
        "kind": "network",
        "z_side": True,
        "record_status": "active",
    }
    assert [(one["name"], one["z_side"]) for one in made["groups"]] == [("Example MPLS East", True)]
    assert made["cost_site_hid"] == places["site"]["hid"]
    # Never a collection, nor one there is not, nor a location and a network both, and
    # the A side is a location where the Z side is none.
    assert "z_group_hid" in errors(
        desk.circuit("Collected", 422, a_location_hid=room, z_group_hid=collection["hid"])
    )
    assert "z_group_hid" in errors(
        desk.circuit("Nowhere", 422, a_location_hid=room, z_group_hid=places["room"]["hid"])
    )
    both = errors(
        desk.circuit(
            "Both", 422, a_location_hid=room, z_location_hid=annex, z_group_hid=network["hid"]
        )
    )
    assert {"z_location_hid", "z_group_hid"} <= set(both)
    assert "a_location_hid" in errors(
        desk.circuit("No site", 422, a_note="carrier network", z_group_hid=network["hid"])
    )
    # A change to a location takes the network away in the same change, or is refused.
    assert "z_group_hid" in errors(
        desk.patch(
            f"/circuits/{made['hid']}",
            {"row_version": made["row_version"], "z_location_hid": annex},
            422,
        )
    )
    moved = desk.patch(
        f"/circuits/{made['hid']}",
        {"row_version": made["row_version"], "z_location_hid": annex, "z_group_hid": None},
    )
    assert (moved["z_group"], moved["z_side"]["name"]) == (None, "Annex")
    assert _members(desk, network) == []
    # Without the network nor a location, the Z side says where it ends.
    assert "z_note" in errors(
        desk.patch(
            f"/circuits/{made['hid']}",
            {"row_version": moved["row_version"], "z_location_hid": None},
            422,
        )
    )


def test_a_group_is_a_network_with_a_carrier_or_a_collection_and_stays_a_network_while_named(
    desk: Desk, places: dict[str, dict[str, Any]]
) -> None:
    telecom = desk.vendor("Example Telecom")
    assert "kind" in errors(desk.post("/circuit-groups", {"name": "Odd", "kind": "region"}, 422))
    assert "carrier_hid" in errors(
        desk.post("/circuit-groups", {"name": "Odd", "carrier_hid": telecom["hid"]}, 422)
    )
    network = _network(desk, carrier_hid=telecom["hid"])
    # A network made a collection keeps no carrier.
    assert "carrier_hid" in errors(
        desk.patch(
            f"/circuit-groups/{network['hid']}",
            {"row_version": network["row_version"], "kind": "collection"},
            422,
        )
    )
    made = desk.circuit(
        "Site-2 MPLS", a_location_hid=places["room"]["hid"], z_group_hid=network["hid"]
    )
    _retire(desk, "/circuits", made)
    # Named on a Z side, by a retired circuit too, it stays a network.
    now = desk.get(f"/circuit-groups/{network['hid']}")
    refused = desk.patch(
        f"/circuit-groups/{network['hid']}",
        {"row_version": now["row_version"], "kind": "collection", "carrier_hid": None},
        422,
    )
    assert "kind" in errors(refused)
    assert "1 circuit" in refused["detail"]
    # The lists of groups and of circuits find them by kind, carrier and network.
    desk.post("/circuit-groups", {"name": "Internet access"})
    assert desk.names("/circuit-groups", filter="kind:eq:network") == ["Example MPLS East"]
    assert desk.names("/circuit-groups", filter="carrier.name:eq:example telecom") == [
        "Example MPLS East"
    ]
    assert desk.names("/circuit-groups", sort="kind") == ["Internet access", "Example MPLS East"]
    assert desk.names(filter=f"z_group_hid:eq:{network['hid']}", include_archived=True) == [
        "Site-2 MPLS"
    ]
    assert desk.names(filter="z_group.name:eq:example mpls east", include_archived=True) == [
        "Site-2 MPLS"
    ]


def test_a_network_lists_the_circuits_its_z_sides_name_and_those_added_each_once(
    desk: Desk, places: dict[str, dict[str, Any]], db: Session
) -> None:
    room, annex = places["room"]["hid"], places["annex"]["hid"]
    network = _network(desk)
    reaching = desk.circuit("A reaching", a_location_hid=room, z_group_hid=network["hid"])
    added = desk.circuit("B added", a_location_hid=room, z_location_hid=annex)
    both = desk.circuit("C both", a_location_hid=annex, z_group_hid=network["hid"])
    for made, cost in ((reaching, "100"), (added, "200"), (both, "400")):
        desk.part(made, "costs", {"description": "Port", "monthly_cost": cost})
    # Added by hand while its Z side names it: accepted, and kept.
    desk.post(
        f"/circuit-groups/{network['hid']}/members", {"circuit_hids": [added["hid"], both["hid"]]}
    )
    assert _members(desk, network) == [
        ("A reaching", False, True),
        ("B added", True, False),
        ("C both", True, True),
    ]
    alone = desk.get(f"/circuit-groups/{network['hid']}/members")["items"][0]
    assert (alone["hid"], alone["created_at"], alone["group_hid"]) == (None, None, network["hid"])
    shown = desk.get(f"/circuit-groups/{network['hid']}")
    assert (shown["circuits"], shown["in_service"], shown["monthly_cost"]) == (3, 3, "700.00")
    listed = desk.get("/circuit-groups", fields="name,circuits,in_service,monthly_cost")["items"][0]
    assert (listed["circuits"], listed["in_service"], listed["monthly_cost"]) == (3, 3, "700.00")
    assert desk.names("/circuit-groups", filter="monthly_cost:eq:700") == ["Example MPLS East"]
    paged = desk.get(f"/circuit-groups/{network['hid']}/members", limit=2, offset=2)
    assert (paged["total"], [one["circuit"]["name"] for one in paged["items"]]) == (3, ["C both"])
    # The circuit's groups say which it names on its Z side; the list finds them by any.
    assert [(one["name"], one["z_side"]) for one in desk.again(both)["groups"]] == [
        ("Example MPLS East", True)
    ]
    assert desk.names(filter=f"groups.hid:eq:{network['hid']}") == [
        "A reaching",
        "B added",
        "C both",
    ]
    assert desk.names(filter="groups.name:empty:true") == []
    # What circuits cost by group counts each once in the network's row.
    by_group = circuit_costs(db, by="group")
    (row,) = [one for one in by_group.rows if one.key == network["hid"]]
    assert (row.circuits, str(row.monthly_cost)) == (3, "700.00")
    # Taken out by hand, the one its Z side names stays; its Z side changed, it leaves.
    member = desk.get(f"/circuit-groups/{network['hid']}/members")["items"][2]
    desk.delete(f"/circuit-groups/{network['hid']}/members/{member['hid']}")
    now = desk.again(reaching)
    desk.patch(
        f"/circuits/{reaching['hid']}",
        {"row_version": now["row_version"], "z_group_hid": None, "z_note": "carrier network"},
    )
    assert _members(desk, network) == [("B added", True, False), ("C both", False, True)]


def test_a_network_is_not_retired_while_a_circuit_reaches_it_nor_a_circuit_brought_back(
    desk: Desk, places: dict[str, dict[str, Any]]
) -> None:
    room = places["room"]["hid"]
    network = _network(desk)
    made = desk.circuit(
        "Site-2 MPLS",
        enterprise_circuit_id="EC-0051",
        a_location_hid=room,
        z_group_hid=network["hid"],
    )
    refused = _retire(desk, "/circuit-groups", network, 409)
    assert "1 circuit" in refused["detail"]
    assert "EC-0051" in refused["detail"]
    assert refused["depends_on"] == [
        {"hid": made["hid"], "record_type": "circuit", "label": "EC-0051"}
    ]
    assert desk.get(f"/circuit-groups/{network['hid']}")["record_status"] == "active"
    # Retired, the circuit lets it go; a retired network is named by no new circuit.
    _retire(desk, "/circuits", made)
    assert _retire(desk, "/circuit-groups", network)["record_status"] == "retired"
    assert "z_group_hid" in errors(
        desk.circuit("Another", 422, a_location_hid=room, z_group_hid=network["hid"])
    )
    # Brought back while its network is retired, a circuit is refused.
    now = desk.again(made)
    assert "record_status" in errors(
        desk.patch(
            f"/circuits/{made['hid']}",
            {"row_version": now["row_version"], "record_status": "active"},
            422,
        )
    )
    back = desk.patch(
        f"/circuits/{made['hid']}",
        {
            "row_version": now["row_version"],
            "record_status": "active",
            "z_group_hid": None,
            "z_note": "carrier network",
        },
    )
    assert back["record_status"] == "active"
    # The retired network still lists what named it, retired or since changed: nothing.
    assert _members(desk, network) == []


# --- in files ------------------------------------------------------------------------


def test_files_carry_the_z_sides_dates_in_force_and_its_network_and_load_back_unchanged(
    desk: Desk, files: Files, places: dict[str, dict[str, Any]]
) -> None:
    files.load(
        "circuit_groups",
        "name,kind,carrier,description\n"
        "Example MPLS East,network,Example Telecom,The carrier's network\n"
        "Inter-site links,,,\n",
    )
    groups = desk.get("/circuit-groups", fields="name,kind,carrier")["items"]
    assert [(one["name"], one["kind"], (one["carrier"] or {}).get("name")) for one in groups] == [
        ("Example MPLS East", "network", "Example Telecom"),
        ("Inter-site links", "collection", None),
    ]
    room = "Americas > Central > Site-2 > Building 1 > Room 102"
    text = (
        "name,enterprise_circuit_id,a_location,z_group,z_note,a_installed_on,a_activated_on,"
        "z_installed_on,z_activated_on,groups\n"
        f"Site-2 MPLS,EC-0051,{room},Example MPLS East,,2027-03-29,2027-04-10,2027-04-02,"
        "2027-04-10,Inter-site links\n"
    )
    files.load("circuits", text)
    (made,) = desk.get("/circuits", fields="z_group,z_installed_on,z_activated_on,groups")["items"]
    # The Z side's activation that is the A side's is left to be read from it (D-65).
    assert (made["z_group"]["name"], made["z_installed_on"], made["z_activated_on"]) == (
        "Example MPLS East",
        "2027-04-02",
        None,
    )
    assert [(one["name"], one["z_side"]) for one in made["groups"]] == [
        ("Example MPLS East", True),
        ("Inter-site links", False),
    ]
    # An export writes the dates in force, with their sources, and the groups it was
    # added to alone, so that loaded back it makes no membership of the Z side.
    (row,) = table(files.export("circuits", include_sources=True))
    assert (row["z_group"], row["groups"]) == ("Example MPLS East", "Inter-site links")
    assert (row["z_installed_on"], row["z_installed_on_source"]) == ("2027-04-02", "own")
    assert (row["z_activated_on"], row["z_activated_on_source"]) == ("2027-04-10", "a_side")
    assert (row["z_disconnected_on"], row["z_disconnected_on_source"]) == ("", "none")
    (own,) = table(files.export("circuits", own_values=True))
    assert (own["z_installed_on"], own["z_activated_on"]) == ("2027-04-02", "")
    as_json = json.loads(files.export("circuits", format="json"))
    for exported in (files.export("circuits"), as_json):
        preview = files.preview("circuits", exported)
        assert counts(preview["job"]) == (0, 0, 1, 0), preview["rows"]
    assert counts(files.preview("circuit_groups", files.export("circuit_groups"))["job"]) == (
        0,
        0,
        2,
        0,
    )
    # A collection on the Z side, and a network that is not, are refused at z_group.
    refused = files.preview(
        "circuits",
        f"name,a_location,z_group\nCollected,{room},Inter-site links\nNowhere,{room},No such\n",
    )
    assert refused["job"]["rejected"] == 2
    assert [[reason["field"] for reason in one["reasons"]] for one in refused["rows"]] == [
        ["z_group"],
        ["z_group"],
    ]
    # !clear takes the network away, and the Z side then says where it ends.
    files.load("circuits", "enterprise_circuit_id,z_group,z_note\nEC-0051,!clear,carrier network\n")
    assert desk.get("/circuits", fields="z_group")["items"][0]["z_group"] is None


def test_an_export_of_dates_in_force_whose_a_side_is_changed_copies_no_z_date_down(
    desk: Desk, files: Files, places: dict[str, dict[str, Any]]
) -> None:
    """A row that changes the A side's dates and still holds the Z side's in force, the A
    side's before it, leaves the Z side reading the A side's (D-65, review of 0.9.18)."""
    made = desk.circuit(
        "Site-2 to Site-3",
        enterprise_circuit_id="EC-0052",
        a_location_hid=places["room"]["hid"],
        z_location_hid=places["annex"]["hid"],
        cost_side="z",
        a_installed_on="2026-01-05",
        a_activated_on="2026-01-10",
        a_disconnected_on="2026-12-31",
    )
    (row,) = table(files.export("circuits"))
    assert (row["z_installed_on"], row["z_activated_on"], row["z_disconnected_on"]) == (
        "2026-01-05",
        "2026-01-10",
        "2026-12-31",
    )
    moved = {"a_installed_on": "2026-02-20", "a_activated_on": "2026-03-01"}
    moved["a_disconnected_on"] = "2027-06-30"
    edited = {**row, **moved}
    text = _csv(edited)
    preview = files.preview("circuits", text)
    (only,) = preview["rows"]
    assert not {change["field"] for change in only["changes"]} & {
        "z_installed_on",
        "z_activated_on",
        "z_disconnected_on",
    }
    files.apply(preview)
    shown = desk.again(made)
    assert (shown["z_installed_on"], shown["z_activated_on"], shown["z_disconnected_on"]) == (
        None,
        None,
        None,
    )
    assert {
        name: (shown["effective"][name]["value"], shown["effective"][name]["source"])
        for name in ("z_installed_on", "z_activated_on", "z_disconnected_on")
    } == {
        "z_installed_on": ("2026-02-20", "a_side"),
        "z_activated_on": ("2026-03-01", "a_side"),
        "z_disconnected_on": ("2027-06-30", "a_side"),
    }
    # A Z date of the row that is neither the A side's before it nor after it is its own.
    (row,) = table(files.export("circuits"))
    files.load("circuits", _csv({**row, "z_activated_on": "2026-03-04"}))
    assert desk.again(made)["effective"]["z_activated_on"] == {
        "value": "2026-03-04",
        "source": "own",
        "source_hid": None,
    }
