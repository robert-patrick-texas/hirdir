"""Circuits in files (P-153): the columns of circuits and of their parts, how a row finds
its circuit, and a file that goes out and comes back unchanged."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.api.test_circuits import Desk
from tests.api.test_files import Files, changes, counts, table

HEAD = "name,enterprise_circuit_id,a_location,z_note,carrier,carrier_circuit_number,groups"


@pytest.fixture
def desk(client: TestClient, inventory: dict[str, str]) -> Desk:
    return Desk(client, inventory)


@pytest.fixture
def files(client: TestClient, inventory: dict[str, str]) -> Files:
    return Files(client, inventory)


@pytest.fixture
def places(desk: Desk) -> dict[str, dict[str, Any]]:
    return desk.places()


ROOM = "Americas > Central > Site-2 > Building 1 > Room 102"
ANNEX = "Americas > Central > Site-3 > Annex"


def test_a_file_of_circuits_makes_its_carrier_puts_it_in_its_groups_and_loads_again(
    desk: Desk, files: Files, places: dict[str, dict[str, Any]]
) -> None:
    files.load("circuit_groups", "name,description\nInternet access,Every way out\n")
    text = (
        "name,enterprise_circuit_id,circuit_type,port_mbps,down_mbps,a_location,z_note,"
        "carrier,carrier_circuit_number,groups,tags\n"
        f"Site-2 internet,EC-0042,internet,1000,1000,{ROOM},carrier network,"
        "Example Telecom,EXT/1/000,Internet access,\n"
        f"Site-3 uplink,,mpls,100,20,{ANNEX},carrier network,,,,\n"
    )
    preview = files.preview("circuits", text)
    assert counts(preview["job"]) == (2, 0, 0, 0), preview["rows"]
    assert "creates the vendor Example Telecom, to be reviewed" in preview["rows"][0]["notes"]
    files.apply(preview)
    shown = desk.get("/circuits", fields="name,carrier,down_mbps,groups,cost_side,speed")["items"]
    assert [(row["name"], row["speed"], row["cost_side"]) for row in shown] == [
        ("Site-2 internet", "1G", "a"),
        ("Site-3 uplink", "100M / 20M / 100M", "a"),
    ]
    # A rate that is the full rate of the port leaves it the port's.
    assert shown[0]["down_mbps"] is None
    assert [group["name"] for group in shown[0]["groups"]] == ["Internet access"]
    assert desk.get("/vendors", filter="review_status:eq:unreviewed")["items"][0]["name"] == (
        "Example Telecom"
    )
    # Loaded again it changes nothing.
    again = files.preview("circuits", text)
    assert counts(again["job"]) == (0, 0, 2, 0), again["rows"]

    # A row finds its circuit by its enterprise ID, then by its carrier's number, then by
    # a name that one circuit alone has.
    renamed = files.preview(
        "circuits",
        f"{HEAD}\nSite-2 internet access,EC-0042,,,,,\n"
        ",,,,Example Telecom,ext/1/000,!clear\n"
        "Site-3 uplink,,,,,,Internet access\n",
    )
    rows = renamed["rows"]
    assert [row["outcome"] for row in rows] == ["update", "rejected", "update"], rows
    assert changes(rows[0]) == {"name": ("Site-2 internet", "Site-2 internet access")}
    # The second row is the first circuit again, named once in the file.
    assert "names the same record" in rows[1]["reasons"][0]["message"]
    assert changes(rows[2]) == {"groups": ([], ["Internet access"])}
    files.apply(renamed, skip_rejected="true")
    assert desk.names(filter="groups.name:eq:Internet access") == [
        "Site-2 internet access",
        "Site-3 uplink",
    ]
    # More than one answer is an error on the row, never a guess.
    desk.circuit("Site-3 uplink", a_location_hid=places["annex"]["hid"], z_note="x")
    twice = files.preview("circuits", f"{HEAD}\nSite-3 uplink,,,,,,\n")
    assert twice["rows"][0]["outcome"] == "rejected"
    assert twice["rows"][0]["reasons"][0]["field"] == "name"


def test_what_a_file_of_circuits_refuses_says_which_column(
    files: Files, places: dict[str, dict[str, Any]]
) -> None:
    preview = files.preview(
        "circuits",
        f"{HEAD}\n"
        "Nowhere,,,carrier network,,,\n"
        f"No carrier,,{ROOM},carrier network,,N-1,\n"
        f"Lost,,Americas > Nowhere,x,,,\n"
        f"Grouped,,{ROOM},x,,,No such group\n",
    )
    reasons = [[one["field"] for one in row["reasons"]] for row in preview["rows"]]
    assert reasons == [
        ["a_location", "z_location"],
        ["carrier_circuit_number"],
        ["a_location"],
        ["groups"],
    ]


def test_the_parts_of_circuits_load_after_their_circuits_and_are_never_removed(
    desk: Desk, files: Files, places: dict[str, dict[str, Any]]
) -> None:
    telecom = desk.vendor("Example Telecom")
    entry = desk.entry(desk.vendor("Cisco"), pid="C8300-1N1S-6T")
    desk.item(catalog_entry_hid=entry["hid"], serial_number="FDO0000R001", hostname="site2-rtr-01")
    pair = desk.group("site3-rtr-pair", "custom", [])
    made = desk.circuit(
        "Site-2 to Site-3",
        enterprise_circuit_id="EC-0007",
        a_location_hid=places["room"]["hid"],
        z_location_hid=places["annex"]["hid"],
        carrier_hid=telecom["hid"],
    )
    carriers = files.preview(
        "circuit_carriers",
        "circuit,vendor,role,circuit_number\n"
        "EC-0007,Example Local Exchange,local_exchange,LEC-1\n"
        "Site-2 to Site-3,Example Colocation,cross_connect,\n",
    )
    assert counts(carriers["job"]) == (2, 0, 0, 0), carriers["rows"]
    files.apply(carriers)
    costs = (
        "circuit,description,monthly_cost,vendor,starts_on\n"
        "EC-0007,Port,850.00,,\n"
        "EC-0007,Local loop,200,Example Local Exchange,\n"
        "EC-0007,Credit,'-50.00,,2020-01-01\n"
    )
    files.load("circuit_costs", costs)
    devices = "circuit,side,item,group\nEC-0007,a,site2-rtr-01,\nEC-0007,z,,site3-rtr-pair\n"
    files.load("circuit_devices", devices)
    shown = desk.again(made)
    assert [(one["vendor"], one["priority"]) for one in shown["carriers"]] == [
        ("Example Local Exchange", 1),
        ("Example Colocation", 2),
    ]
    assert (shown["monthly_cost"], shown["annual_cost"]) == ("1000.00", "12000.00")
    assert [(one["name"], one["side"]) for one in shown["devices"]] == [
        ("site2-rtr-01", "a"),
        ("site3-rtr-pair", "z"),
    ]
    assert desk.get(f"/device-groups/{pair['hid']}")["circuits"][0]["side"] == "z"
    # The same files again find every part and change none of them.
    for entity, text in (
        (
            "circuit_carriers",
            "circuit,vendor,role\nEC-0007,Example Local Exchange,local_exchange\n",
        ),
        ("circuit_costs", costs),
        ("circuit_devices", devices),
    ):
        again = files.preview(entity, text)
        assert again["job"]["created"] == again["job"]["updated"] == 0, (entity, again["rows"])
    # A line billed by a vendor that is no carrier of the circuit is refused.
    stranger = files.preview(
        "circuit_costs", "circuit,description,monthly_cost,vendor\nEC-0007,Access,1,Cisco\n"
    )
    assert stranger["rows"][0]["reasons"][0]["field"] == "vendor"
    # An export names the circuit by its enterprise ID, then by its name.
    exported = table(files.export("circuit_costs", own_values=True))
    assert {row["circuit"] for row in exported} == {"EC-0007"}
    assert [row["description"] for row in exported] == ["Credit", "Local loop", "Port"]
    assert exported[0]["monthly_cost"] == "'-50.00"


def test_an_export_of_circuits_writes_what_is_worked_out_and_loads_back_unchanged(
    desk: Desk, files: Files, places: dict[str, dict[str, Any]]
) -> None:
    owner = desk.owner("Example Partner", is_external=True, exception_reason="Theirs")
    made = desk.circuit(
        "Dark fiber",
        enterprise_circuit_id="EC-0103",
        circuit_type="dark_fiber",
        port_mbps="10000",
        a_location_hid=places["building"]["hid"],
        a_note="demarc in the basement",
        z_location_hid=places["annex"]["hid"],
        cost_side="z",
        production=False,
        support_weight="2",
        owner_hid=owner["hid"],
    )
    desk.part(made, "costs", {"description": "Fiber lease", "monthly_cost": "300"})
    columns = [
        "name",
        "speed",
        "monthly_cost",
        "annual_cost",
        "a_site",
        "z_site",
        "cost_site",
        "owner_exception",
        "support_weight",
        "support_weight_source",
        "production",
    ]
    (row,) = table(files.export("circuits", columns=columns))
    assert row == {
        "hid": made["hid"],
        "name": "Dark fiber",
        "speed": "10G",
        "monthly_cost": "300.00",
        "annual_cost": "3600.00",
        "a_site": "Americas > Central > Site-2",
        "z_site": "Americas > Central > Site-3",
        "cost_site": "Americas > Central > Site-3",
        "owner_exception": "true",
        "support_weight": "2",
        "support_weight_source": "own",
        "production": "false",
    }
    whole = files.export("circuits", own_values=True)
    assert table(whole)[0]["a_location"] == "Americas > Central > Site-2 > Building 1"
    again = files.preview("circuits", whole)
    assert counts(again["job"]) == (0, 0, 1, 0), again["rows"]
    # The export of a filter of the list.
    assert table(
        files.export("circuits", filter="cost_location:within:Americas > Central > Site-3")
    )
    assert not table(files.export("circuits", filter="production:eq:true"))
