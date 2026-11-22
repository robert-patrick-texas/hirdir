"""Scenarios S47 to S50 of docs/build-plan.md, against a real server process: a circuit
with its two sides, its carriers and their numbers and the devices at each end, a dark
fiber known by the enterprise's own ID, what circuits cost by carrier, site and group,
the site contacts and the carrier's account manager of a circuit, and circuits carried
to an empty inventory in files and back."""

import csv
import io
from pathlib import Path
from typing import Any

import pytest

from tests.acceptance.conftest import ADMIN, Server, started
from tests.acceptance.test_file_scenarios import Desk as Files
from tests.acceptance.test_geography_scenarios import Geography
from tests.acceptance.test_item_scenarios import IVY

# What S50 carries from one inventory to the other, in the order it is loaded.
CARRIED = (
    "vendors",
    "regions",
    "sites",
    "locations",
    "circuits",
    "circuit_carriers",
    "circuit_costs",
)


class Desk(Geography):
    """A signed-in Inventory user who enters circuits and what they name."""

    def vendor(self, name: str) -> dict[str, Any]:
        return self.post("/vendors", {"name": name})

    def circuit(self, name: str, expect: int = 201, **fields: Any) -> dict[str, Any]:
        return self.post("/circuits", {"name": name, **fields}, expect)

    def part(self, circuit: dict[str, Any], kind: str, body: dict[str, Any]) -> Any:
        return self.post(f"/circuits/{circuit['hid']}/{kind}", body)

    def names(self, **params: Any) -> list[str]:
        return [row["name"] for row in self.get("/circuits", **params)["items"]]


def _person(server: Server) -> Desk:
    admin = server.sign_in(*ADMIN)
    made = admin.post(
        "/users", json={"username": IVY[0], "access_code": IVY[1], "role": "inventory"}
    )
    assert made.status_code == 201, made.text
    return Desk(server.sign_in(*IVY))


@pytest.fixture
def desk(server: Server) -> Desk:
    return _person(server)


def _two_sites(desk: Desk) -> dict[str, dict[str, Any]]:
    """Site-2 with Building 1 and Room 102 in it, and Site-3 with an Annex."""
    found = desk.layout()
    found["site3"] = desk.site("Site-3", found["central"])
    found["annex"] = desk.location("Annex", found["site3"], kind="building")
    return found


def test_s47_a_circuit_shows_its_sides_carriers_and_devices_and_a_dark_fiber_its_own_id(
    desk: Desk,
) -> None:
    places = _two_sites(desk)
    telecom, exchange = desk.vendor("Example Telecom"), desk.vendor("Example Local Exchange")
    model = desk.entry("C8300-1N1S-6T")
    routers = [
        desk.post(
            "/items",
            {
                "catalog_entry_hid": model["hid"],
                "serial_number": f"FDO0000R00{number}",
                "hostname": hostname,
            },
        )
        for number, hostname in ((1, "site2-rtr-01"), (2, "site3-rtr-01"))
    ]
    circuit = desk.circuit(
        "Site-2 to Site-3",
        enterprise_circuit_id="EC-0042",
        circuit_type="point_to_point",
        port_mbps="1000",
        a_location_hid=places["room"]["hid"],
        z_location_hid=places["annex"]["hid"],
        carrier_hid=telecom["hid"],
        carrier_circuit_number="EXT/12345/000/EXTL",
    )
    desk.part(
        circuit,
        "carriers",
        {"vendor_hid": exchange["hid"], "role": "local_exchange", "circuit_number": "LEC-778-0001"},
    )
    desk.part(
        circuit,
        "devices",
        {
            "devices": [
                {"item_hid": routers[0]["hid"], "side": "a"},
                {"item_hid": routers[1]["hid"], "side": "z"},
            ]
        },
    )

    # The first shows both sides, both carriers and both devices.
    shown = desk.get(f"/circuits/{circuit['hid']}")
    assert shown["a_side"]["path"] == "Americas > Central > Site-2 > Building 1 > Room 102"
    assert shown["z_side"]["path"] == "Americas > Central > Site-3 > Annex"
    assert (shown["carrier"]["name"], shown["carrier_circuit_number"]) == (
        "Example Telecom",
        "EXT/12345/000/EXTL",
    )
    assert [(one["vendor"], one["role"], one["circuit_number"]) for one in shown["carriers"]] == [
        ("Example Local Exchange", "local_exchange", "LEC-778-0001")
    ]
    assert [(one["name"], one["side"]) for one in shown["devices"]] == [
        ("site2-rtr-01", "a"),
        ("site3-rtr-01", "z"),
    ]
    # Each router shows it, with its side.
    for router, side in zip(routers, ("a", "z"), strict=True):
        on = desk.get(f"/items/{router['hid']}")["circuits"]
        assert [(one["hid"], one["enterprise_circuit_id"], one["side"]) for one in on] == [
            (circuit["hid"], "EC-0042", side)
        ]
    # And each location: the list finds the circuits with a side there, as its page asks.
    for place in ("room", "annex"):
        assert desk.names(filter=f"location:within:{places[place]['hid']}") == ["Site-2 to Site-3"]
    # Both carriers find it by the number each gives it.
    for number in ("EXT/12345/000/EXTL", "lec-778-0001"):
        assert desk.names(filter=f"carriers.circuit_number:eq:{number}") == ["Site-2 to Site-3"]

    # Then a dark fiber between two buildings, with an enterprise circuit ID and no
    # carrier's number, from a business partner that is a vendor too.
    partner = desk.vendor("Northwind Fiber")
    fiber = desk.circuit(
        "Building 1 to Annex dark fiber",
        enterprise_circuit_id="EC-0103",
        circuit_type="dark_fiber",
        port_mbps="10000",
        a_location_hid=places["building"]["hid"],
        z_location_hid=places["annex"]["hid"],
        carrier_hid=partner["hid"],
    )
    assert (fiber["carrier_circuit_number"], fiber["speed"]) == (None, "10G")
    found = desk.post(
        "/circuits/query",
        {"filter": {"field": "enterprise_circuit_id", "op": "eq", "value": "ec-0103"}},
        200,
    )["items"]
    assert [one["hid"] for one in found] == [fiber["hid"]]
    # That ID is refused for another circuit.
    refused = desk.circuit(
        "Another",
        409,
        enterprise_circuit_id="EC-0103",
        a_location_hid=places["room"]["hid"],
        z_note="carrier network",
    )
    assert [one["field"] for one in refused["errors"]] == ["enterprise_circuit_id"]


def _without_hids(text: str) -> str:
    """Return an exported file with its HIDs left blank: they name the records of the
    inventory it came from, as `examples/` are written."""
    rows = list(csv.reader(io.StringIO(text, newline="")))
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(rows[0])
    writer.writerows(["", *row[1:]] for row in rows[1:])
    return out.getvalue()


def test_s50_circuits_go_to_an_empty_inventory_in_files_and_a_second_load_changes_nothing(
    desk: Desk, tmp_path: Path
) -> None:
    places = _two_sites(desk)
    telecom, exchange = desk.vendor("Example Telecom"), desk.vendor("Example Local Exchange")
    internet = desk.circuit(
        "Site-2 internet",
        enterprise_circuit_id="EC-0042",
        circuit_type="internet",
        port_mbps="1000",
        down_mbps="200",
        up_mbps="20",
        a_location_hid=places["room"]["hid"],
        z_note="carrier network",
        carrier_hid=telecom["hid"],
        carrier_circuit_number="EXT/12345/000/EXTL",
        billing_account="BA-100200",
        a_activated_on="2026-04-10",
    )
    desk.part(
        internet,
        "carriers",
        {"vendor_hid": exchange["hid"], "role": "local_exchange", "circuit_number": "LEC-1"},
    )
    for description, cost, more in (
        ("Port", "850.00", {}),
        ("Local loop", "200.00", {"vendor_hid": exchange["hid"]}),
        ("Promotional credit", "-50.00", {"ends_on": "2026-12-31"}),
    ):
        desk.part(internet, "costs", {"description": description, "monthly_cost": cost, **more})
    # One known by its carrier's number alone, and counted at its far end.
    link = desk.circuit(
        "Site-2 to Site-3",
        circuit_type="point_to_point",
        port_mbps="100",
        a_location_hid=places["building"]["hid"],
        z_location_hid=places["annex"]["hid"],
        cost_side="z",
        carrier_hid=telecom["hid"],
        carrier_circuit_number="EXT/12346/000/EXTL",
    )
    desk.part(link, "costs", {"description": "Port", "monthly_cost": "400.00"})

    exported = {}
    for entity in CARRIED:
        response = desk.client.post(
            "/exports",
            json={"entity": entity, "format": "csv", "own_values": True, "include_drafts": True},
        )
        assert response.status_code == 200, response.text
        exported[entity] = _without_hids(response.text)
    before = {
        circuit["name"]: circuit
        for circuit in desk.get("/circuits", fields="name,a_side,z_side,carriers,costs")["items"]
    }

    with started(tmp_path / "empty") as other:
        empty = _person(other)
        loading = Files(empty.client)
        assert empty.get("/circuits")["total"] == 0
        for entity in CARRIED:
            rows = len(exported[entity].splitlines()) - 1
            preview = loading.preview(entity, exported[entity])
            assert preview["job"]["rejected"] == 0, (entity, preview["rows"])
            job = loading.apply(preview)
            assert (job["status"], job["created"]) == ("applied", rows), entity
        # Every circuit is created with its sides, carriers, numbers and cost lines.
        after = {
            circuit["name"]: circuit
            for circuit in empty.get("/circuits", fields="name,a_side,z_side,carriers,costs")[
                "items"
            ]
        }
        assert sorted(after) == ["Site-2 internet", "Site-2 to Site-3"]
        for name, was in before.items():
            now = after[name]
            for side in ("a_side", "z_side"):
                assert (now[side] or {}).get("path") == (was[side] or {}).get("path"), name
            assert [
                (one["vendor"], one["role"], one["circuit_number"]) for one in now["carriers"]
            ] == [(one["vendor"], one["role"], one["circuit_number"]) for one in was["carriers"]], (
                name
            )
            assert [
                (line["description"], line["monthly_cost"], line["vendor"], line["ends_on"])
                for line in now["costs"]
            ] == [
                (line["description"], line["monthly_cost"], line["vendor"], line["ends_on"])
                for line in was["costs"]
            ], name
        moved = empty.post(
            "/circuits/query",
            {"filter": {"field": "enterprise_circuit_id", "op": "eq", "value": "EC-0042"}},
            200,
        )["items"][0]
        whole = empty.get(f"/circuits/{moved['hid']}")
        assert (whole["speed"], whole["carrier"]["name"], whole["carrier_circuit_number"]) == (
            "1G / 200M / 20M",
            "Example Telecom",
            "EXT/12345/000/EXTL",
        )
        assert (whole["billing_account"], whole["a_activated_on"]) == ("BA-100200", "2026-04-10")
        counted = empty.names(filter="cost_location:within:Americas > Central > Site-3")
        assert counted == ["Site-2 to Site-3"]

        # The second load changes nothing.
        events = empty.get("/audit-events", limit=1)["total"]
        for entity in CARRIED:
            preview = loading.preview(entity, exported[entity])
            job = preview["job"]
            assert (job["created"], job["updated"], job["rejected"]) == (0, 0, 0), (
                entity,
                preview["rows"],
            )
            assert job["unchanged"] == job["row_count"] > 0, entity
            assert loading.apply(preview)["status"] == "applied"
        # The only events since are the previews and the applies, each begun and ended.
        assert empty.get("/audit-events", limit=1)["total"] - events == 3 * len(CARRIED)


def test_s48_what_circuits_cost_by_carrier_by_site_and_by_group(desk: Desk) -> None:
    places = _two_sites(desk)
    telecom = desk.vendor("Example Telecom")
    first = desk.circuit(
        "Site-2 to Site-3",
        a_location_hid=places["room"]["hid"],
        z_location_hid=places["annex"]["hid"],
        carrier_hid=telecom["hid"],
    )
    for description, monthly in (("Port", "800.00"), ("Local loop", "150.00"), ("Access", "50.00")):
        desk.part(first, "costs", {"description": description, "monthly_cost": monthly})
    second = desk.circuit(
        "Site-3 internet",
        a_location_hid=places["annex"]["hid"],
        z_note="carrier network",
        carrier_hid=telecom["hid"],
    )
    desk.part(second, "costs", {"description": "Port", "monthly_cost": "500.00"})
    group = desk.post("/circuit-groups", {"name": "Wide area network"})
    desk.post(
        f"/circuit-groups/{group['hid']}/members", {"circuit_hids": [first["hid"], second["hid"]]}
    )
    # The monthly cost of each is the sum of its lines, and its annual cost twelve times it.
    record = desk.get(f"/circuits/{first['hid']}")
    assert (record["monthly_cost"], record["annual_cost"]) == ("1000.00", "12000.00")
    assert desk.get(f"/circuits/{second['hid']}")["annual_cost"] == "6000.00"

    def rows(by: str) -> dict[str | None, tuple[int, str, str]]:
        found = desk.get("/reports/circuit-costs", by=by)
        assert (found["totals"]["annual_cost"], found["totals"]["monthly_cost"]) == (
            "18000.00",
            "1500.00",
        )
        return {
            row["label"]: (row["circuits"], row["annual_cost"], row["monthly_cost"])
            for row in found["rows"]
        }

    # The report totals both by carrier, by site at the A side of each, and by the group.
    assert rows("carrier") == {"Example Telecom": (2, "18000.00", "1500.00")}
    assert rows("site") == {
        "Americas > Central > Site-2": (1, "12000.00", "1000.00"),
        "Americas > Central > Site-3": (1, "6000.00", "500.00"),
    }
    assert rows("group") == {"Wide area network": (2, "18000.00", "1500.00")}
    assert desk.get(f"/circuit-groups/{group['hid']}")["annual_cost"] == "18000.00"
    # Each row leads to its circuits.
    by_site = desk.get("/reports/circuit-costs", by="site")["rows"]
    (site3,) = [row for row in by_site if row["label"].endswith("Site-3")]
    listed = desk.post("/circuits/query", {"filter": site3["filter"]}, 200)
    assert [one["hid"] for one in listed["items"]] == [second["hid"]]


def test_s49_a_circuit_shows_its_site_contacts_and_its_carriers_account_manager(
    desk: Desk,
) -> None:
    places = _two_sites(desk)
    telecom = desk.vendor("Example Telecom")
    robin = desk.contact("Robin Achterberg")
    jordan = desk.post("/contacts", {"name": "Jordan Reyes", "email": "jordan.reyes@example.com"})
    casey = desk.post("/contacts", {"name": "Casey Lund", "email": "casey.lund@example.com"})
    # The A side's site has a site contact; the carrier has an account manager.
    desk.assign(robin, "technical", site_hid=places["site"]["hid"])
    desk.post(
        f"/vendors/{telecom['hid']}/contacts",
        {"contact_hid": jordan["hid"], "role": "account_manager"},
    )
    circuit = desk.circuit(
        "Site-2 to Site-3",
        a_location_hid=places["room"]["hid"],
        z_location_hid=places["annex"]["hid"],
        carrier_hid=telecom["hid"],
    )
    other = desk.circuit(
        "Site-3 internet",
        a_location_hid=places["annex"]["hid"],
        z_note="carrier network",
        carrier_hid=telecom["hid"],
    )
    desk.part(other, "contacts", {"contact_hid": casey["hid"], "role": "account_manager"})
    effective = desk.get(f"/circuits/{circuit['hid']}")["effective"]
    # The site contacts of each side are resolved from its location, with their source.
    (technical,) = [one for one in effective["site_contacts"]["a"] if one["role"] == "technical"]
    assert (technical["source"], technical["source_hid"]) == ("site", places["site"]["hid"])
    assert [one["contact"]["name"] for one in technical["value"]] == ["Robin Achterberg"]
    assert all(one["role"] != "technical" for one in effective["site_contacts"]["z"])
    # The carrier's account manager, from the carrier.
    managers = effective["account_managers"]
    assert (managers["source"], managers["source_hid"]) == ("vendor", telecom["hid"])
    assert [one["contact"]["name"] for one in managers["value"]] == ["Jordan Reyes"]
    # The second circuit names its own, in place of the carrier's.
    own = desk.get(f"/circuits/{other['hid']}")["effective"]["account_managers"]
    assert own["source"] == "own"
    assert [one["contact"]["name"] for one in own["value"]] == ["Casey Lund"]
