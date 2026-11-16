"""The contacts of a carrier and of a circuit (P-149): the account team and the support
desk named once on the carrier, what a circuit names of its own, and the site contacts
of its two sides, resolved from their locations.

Circuits are made here through the ORM, by `Circuits`: their own routes come with the
records of circuits, and these tests need only what a circuit holds.
"""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from typer.testing import CliRunner, Result

from hirdir.api import shapes
from hirdir.cli import client as cli_client
from hirdir.cli import inventory as cli_inventory
from hirdir.cli.main import app
from hirdir.config import Config
from hirdir.db.engine import make_engine, make_sessions
from hirdir.db.models import Circuit
from hirdir.domain import records
from tests.api.inventory import API, Maker, errors
from tests.api.test_files import Files, counts, table

NOBODY = "0193a1f4-6c2e-7b41-9d0a-5e3f8c1a7b22"
runner = CliRunner()


class Circuits:
    """Makes circuits in the database of a test, and reads what they have in force."""

    def __init__(self, config: Config) -> None:
        self.engine = make_engine(config.database_url)
        self.sessions = make_sessions(self.engine)

    def make(
        self,
        name: str,
        a: dict[str, Any] | None = None,
        z: dict[str, Any] | None = None,
        carrier: dict[str, Any] | None = None,
        **more: Any,
    ) -> str:
        """Make a circuit with a side at each location given, and a note for a side with
        none. Return its HID."""
        enterprise = more.pop("enterprise_circuit_id", None)
        with self.sessions() as db:
            circuit = Circuit(
                name=name,
                name_key=records.key(name),
                enterprise_circuit_id=enterprise,
                enterprise_circuit_id_key=records.key(enterprise) if enterprise else None,
                a_location_hid=a["hid"] if a else None,
                a_note=None if a else "carrier network",
                z_location_hid=z["hid"] if z else None,
                z_note=None if z else "carrier network",
                carrier_hid=carrier["hid"] if carrier else None,
                **more,
            )
            db.add(circuit)
            db.commit()
            return circuit.hid

    def retire(self, hid: str) -> None:
        with self.sessions() as db:
            circuit = db.get_one(Circuit, hid)
            circuit.record_status = "retired"
            circuit.row_version += 1
            db.commit()

    def in_force(self, *hids: str) -> dict[str, dict[str, Any]]:
        """Return what each circuit has in force, as its record answers it in `effective`,
        with what it names of its own under `contacts`."""
        with self.sessions() as db:
            found = list(db.scalars(select(Circuit).where(Circuit.hid.in_(hids))))
            shaped = shapes.circuits_contacts(db, found)
        return {
            hid: {"contacts": [one.model_dump(mode="json") for one in own]}
            | effective.model_dump(mode="json")
            for hid, (own, effective) in shaped.items()
        }

    def statements(self, *hids: str) -> int:
        """Return how many statements reading the contacts of the circuits takes."""
        counted = []

        def count(*_: Any) -> None:
            counted.append(1)

        event.listen(self.engine, "before_cursor_execute", count)
        try:
            with self.sessions() as db:
                found = list(db.scalars(select(Circuit).where(Circuit.hid.in_(hids))))
                counted.clear()
                shapes.circuits_contacts(db, found)
        finally:
            event.remove(self.engine, "before_cursor_execute", count)
        return len(counted)


@pytest.fixture
def circuits(config: Config, client: TestClient) -> Iterator[Circuits]:
    made = Circuits(config)
    yield made
    made.engine.dispose()


@pytest.fixture
def make(client: TestClient, inventory: dict[str, str]) -> Maker:
    return Maker(client, inventory)


@pytest.fixture
def files(client: TestClient, inventory: dict[str, str]) -> Files:
    return Files(client, inventory)


def _name(make: Maker, path: str, contact: dict[str, Any], role: str, expect: int = 201, **more):
    return make.post(
        f"{path}/contacts", {"contact_hid": contact["hid"], "role": role, **more}, expect
    )


def _people(found: dict[str, Any]) -> tuple[list[str], str, str | None]:
    return [one["contact"]["name"] for one in found["value"]], found["source"], found["source_hid"]


def _sides(found: dict[str, Any], side: str) -> dict[str, tuple[list[str], str, str | None]]:
    """Return the site contacts in force of one side, by role: who, and where from."""
    return {one["role"]: _people(one) for one in found["site_contacts"][side]}


# --- the contacts of a vendor --------------------------------------------------------


def test_a_vendor_names_its_account_team_and_support_desk_each_once_in_a_role(
    make: Maker,
) -> None:
    carrier = make.vendor("Example Telecom")
    path = f"/vendors/{carrier['hid']}"
    morgan = make.contact("Morgan Ellis", organization="Example Telecom", phone="+1 555 0160")
    riley = make.contact("Riley Brandt", organization="Example Telecom")
    repair = make.contact("Repair Desk", email="repair@example.org", phone="+1 555 0161")
    first = _name(make, path, morgan, "account_manager")
    second = _name(make, path, riley, "account_manager")
    # Left out, the priority is one more than the highest of the vendor and the role.
    assert (first["priority"], second["priority"]) == (1, 2)
    assert first["vendor_hid"] == carrier["hid"]
    assert first["contact"] == {
        "hid": morgan["hid"],
        "name": "Morgan Ellis",
        "organization": "Example Telecom",
        "email": "morgan.ellis@example.net",
        "phone": "+1 555 0160",
        "record_status": "active",
    }
    assert _name(make, path, repair, "support_contact")["priority"] == 1
    assert _name(make, path, morgan, "support_contact", priority=5)["priority"] == 5
    # Named once for one vendor and one role; a role of a place is not a carrier's.
    assert "contact_hid" in errors(_name(make, path, morgan, "account_manager", expect=409))
    assert "role" in errors(_name(make, path, riley, "technical", expect=422))
    nobody = {"contact_hid": NOBODY, "role": "account_manager"}
    assert "contact_hid" in errors(make.post(f"{path}/contacts", nobody, 422))
    make.get(f"/vendors/{NOBODY}/contacts", 404)
    make.post(f"/vendors/{NOBODY}/contacts", {"contact_hid": morgan["hid"], "role": "x"}, 422)

    listed = make.get(f"{path}/contacts")
    assert [(one["role"], one["contact"]["name"]) for one in listed["items"]] == [
        ("account_manager", "Morgan Ellis"),
        ("account_manager", "Riley Brandt"),
        ("support_contact", "Repair Desk"),
        ("support_contact", "Morgan Ellis"),
    ]
    # The record of the vendor answers them, and so does the list of vendors.
    shown = make.get(path)
    assert [one["hid"] for one in shown["contacts"]] == [one["hid"] for one in listed["items"]]
    rows = make.get("/vendors", filter="name:eq:Example Telecom")["items"]
    assert [one["hid"] for one in rows[0]["contacts"]] == [one["hid"] for one in listed["items"]]
    assert make.vendor("Northwind Fiber")["contacts"] == []

    # The order is changed by the priority, and one priority is listed by name.
    moved = make.patch(
        f"{path}/contacts/{first['hid']}", {"row_version": first["row_version"], "priority": 3}
    )
    assert moved["row_version"] == first["row_version"] + 1
    names = [one["contact"]["name"] for one in make.get(f"{path}/contacts")["items"]]
    assert names[:2] == ["Riley Brandt", "Morgan Ellis"]
    make.patch(f"{path}/contacts/{first['hid']}", {"row_version": 1, "priority": 2}, 409)
    make.patch(f"{path}/contacts/{first['hid']}", {"row_version": 2, "priority": 2})
    names = [one["contact"]["name"] for one in make.get(f"{path}/contacts")["items"]]
    assert names[:2] == ["Morgan Ellis", "Riley Brandt"]
    # A naming may take another contact, or another role, where it is not named so.
    clash = {"row_version": second["row_version"], "contact_hid": morgan["hid"]}
    assert "contact_hid" in errors(make.patch(f"{path}/contacts/{second['hid']}", clash, 409))
    to_support = {"row_version": second["row_version"], "role": "support_contact"}
    assert make.patch(f"{path}/contacts/{second['hid']}", to_support)["role"] == "support_contact"

    # A naming is reached through its own vendor only, and removed outright.
    other = make.vendor("Northwind Telecom")
    elsewhere = f"/vendors/{other['hid']}/contacts/{first['hid']}"
    make.patch(elsewhere, {"row_version": 1, "priority": 5}, 404)
    make.delete(elsewhere, 404)
    make.delete(f"{path}/contacts/{first['hid']}")
    make.delete(f"{path}/contacts/{first['hid']}", 404)
    assert make.get(f"{path}/contacts")["total"] == 3


def test_a_retired_contact_stays_where_a_vendor_names_it_and_is_named_nowhere_new(
    make: Maker,
) -> None:
    carrier = make.vendor("Example Telecom")
    path = f"/vendors/{carrier['hid']}"
    morgan = make.contact("Morgan Ellis")
    link = _name(make, path, morgan, "account_manager")
    make.post(f"/contacts/{morgan['hid']}/retire", {"row_version": morgan["row_version"]}, 200)
    marked = make.get(path)["contacts"][0]["contact"]
    assert (marked["name"], marked["record_status"]) == ("Morgan Ellis", "retired")
    assert "contact_hid" in errors(_name(make, path, morgan, "support_contact", expect=422))
    # It may still be put in another place in the list where it stands.
    assert make.patch(f"{path}/contacts/{link['hid']}", {"row_version": 1, "priority": 2})


def test_the_contacts_of_vendors_and_circuits_are_role_checked_and_audited(
    make: Maker, circuits: Circuits, client: TestClient, viewer: dict[str, str]
) -> None:
    carrier = make.vendor("Example Telecom")
    place = make.layout()
    circuit = circuits.make("Site-2 internet", a=place["room"], carrier=carrier)
    morgan = make.contact("Morgan Ellis")
    for path, kind, role, side in (
        (f"/vendors/{carrier['hid']}", "vendor_contact", "account_manager", None),
        (f"/circuits/{circuit}", "circuit_contact", "technical", "a"),
    ):
        body = {"contact_hid": morgan["hid"], "role": role, "side": side}
        if side is None:
            del body["side"]
        assert client.post(f"{API}{path}/contacts", json=body, headers=viewer).status_code == 403
        link = make.post(f"{path}/contacts", body)
        assert client.get(f"{API}{path}/contacts", headers=viewer).status_code == 200
        one = f"{API}{path}/contacts/{link['hid']}"
        moved = {"row_version": 1, "priority": 2}
        assert client.patch(one, json=moved, headers=viewer).status_code == 403
        assert client.delete(one, headers=viewer).status_code == 403
        make.patch(f"{path}/contacts/{link['hid']}", moved)
        make.delete(f"{path}/contacts/{link['hid']}")

        removed, changed, made = make.audit(record_type=kind, record_hid=link["hid"])
        assert [made["action"], changed["action"], removed["action"]] == [
            "create",
            "update",
            "delete",
        ]
        assert changed["changes"] == [{"field": "priority", "old": 1, "new": 2}]
        # The removal holds what it was.
        holder = "vendor_hid" if side is None else "circuit_hid"
        held = {one["field"]: one["old"] for one in removed["changes"]}
        assert held == {
            holder: carrier["hid"] if side is None else circuit,
            **({} if side is None else {"side": "a"}),
            "role": role,
            "contact_hid": morgan["hid"],
            "priority": 2,
        }


# --- the contacts of a circuit -------------------------------------------------------


def test_a_circuit_names_contacts_of_the_carrier_and_of_each_side_once_each(
    make: Maker, circuits: Circuits
) -> None:
    place = make.layout()
    circuit = circuits.make("Site-2 internet", a=place["room"])
    path = f"/circuits/{circuit}"
    casey = make.contact("Casey Lund")
    lee = make.contact("Lee Marchetti")
    # With no side, one of the carrier's two roles; with a side, a role of a place.
    carrier_own = _name(make, path, casey, "account_manager")
    assert (carrier_own["side"], carrier_own["circuit_hid"]) == (None, circuit)
    assert "role" in errors(_name(make, path, casey, "technical", expect=422))
    assert "role" in errors(_name(make, path, casey, "account_manager", side="a", expect=422))
    assert "side" in errors(_name(make, path, casey, "technical", side="b", expect=422))
    on_a = _name(make, path, casey, "technical", side="a")
    assert (on_a["side"], on_a["role"], on_a["priority"]) == ("a", "technical", 1)
    assert _name(make, path, lee, "technical", side="a")["priority"] == 2
    # A side with no location takes its own site contacts.
    assert _name(make, path, lee, "technical", side="z")["priority"] == 1
    # Once for one circuit, side and role; the same contact elsewhere is another naming.
    assert "contact_hid" in errors(_name(make, path, casey, "technical", side="a", expect=409))
    assert "contact_hid" in errors(_name(make, path, casey, "account_manager", expect=409))
    _name(make, path, casey, "support_contact")
    _name(make, path, casey, "escalation", side="a")

    listed = make.get(f"{path}/contacts")["items"]
    # The carrier's first, then each side's, each by role and then by priority.
    assert [(one["side"], one["role"], one["contact"]["name"]) for one in listed] == [
        (None, "account_manager", "Casey Lund"),
        (None, "support_contact", "Casey Lund"),
        ("a", "escalation", "Casey Lund"),
        ("a", "technical", "Casey Lund"),
        ("a", "technical", "Lee Marchetti"),
        ("z", "technical", "Lee Marchetti"),
    ]

    # A change may move a naming to another side, as long as its role is one the side
    # takes, and as long as the contact is not named so there already.
    version = {"row_version": on_a["row_version"]}
    assert "role" in errors(
        make.patch(f"{path}/contacts/{on_a['hid']}", {**version, "side": None}, 422)
    )
    to_z = make.patch(f"{path}/contacts/{on_a['hid']}", {**version, "side": "z"})
    assert (to_z["side"], to_z["role"]) == ("z", "technical")
    clash = {"row_version": to_z["row_version"], "contact_hid": lee["hid"]}
    assert "contact_hid" in errors(make.patch(f"{path}/contacts/{on_a['hid']}", clash, 409))
    carrier_again = {"row_version": to_z["row_version"], "side": None, "role": "account_manager"}
    assert "contact_hid" in errors(make.patch(f"{path}/contacts/{on_a['hid']}", carrier_again, 409))

    # A retired circuit takes no new contact, and what it names stays.
    circuits.retire(circuit)
    assert "circuit_hid" in errors(_name(make, path, lee, "shipping", side="a", expect=422))
    assert make.get(f"{path}/contacts")["total"] == 6
    make.get(f"/circuits/{NOBODY}/contacts", 404)
    make.post(f"/circuits/{NOBODY}/contacts", {"contact_hid": lee["hid"], "role": "x"}, 404)
    other = circuits.make("Site-2 backup", a=place["room"])
    make.delete(f"/circuits/{other}/contacts/{on_a['hid']}", 404)


def test_a_circuit_has_its_carriers_contacts_in_each_role_until_it_names_its_own(
    make: Maker, circuits: Circuits
) -> None:
    """Scenario S49, as far as the carrier goes, and the rest of the rule."""
    carrier = make.vendor("Example Telecom")
    vendor_path = f"/vendors/{carrier['hid']}"
    morgan = make.contact("Morgan Ellis", phone="+1 555 0160")
    repair = make.contact("Repair Desk", email="repair@example.org")
    casey = make.contact("Casey Lund")
    _name(make, vendor_path, morgan, "account_manager")
    _name(make, vendor_path, repair, "support_contact")
    place = make.layout()
    first = circuits.make("Site-2 internet", a=place["room"], carrier=carrier)
    second = circuits.make("Site-2 backup", a=place["room"], carrier=carrier)
    alone = circuits.make("Dark fiber", a=place["room"], z=place["building"])
    own = _name(make, f"/circuits/{second}", casey, "account_manager")

    found = circuits.in_force(first, second, alone)
    assert _people(found[first]["account_managers"]) == (["Morgan Ellis"], "vendor", carrier["hid"])
    assert _people(found[first]["support_contacts"]) == (["Repair Desk"], "vendor", carrier["hid"])
    assert found[first]["contacts"] == []
    # One that names its own in a role has them, all of them, in place of the
    # carrier's; the other role is still the carrier's.
    assert _people(found[second]["account_managers"]) == (["Casey Lund"], "own", second)
    assert _people(found[second]["support_contacts"]) == (["Repair Desk"], "vendor", carrier["hid"])
    assert [one["hid"] for one in found[second]["contacts"]] == [own["hid"]]
    # A circuit with no carrier has its own or none.
    assert _people(found[alone]["account_managers"]) == ([], "none", None)
    # Each is the naming it comes by, with the contact as its record is now.
    named = found[first]["account_managers"]["value"][0]
    assert set(named) == {"hid", "role", "priority", "contact_hid", "contact"}
    assert (named["role"], named["priority"], named["contact_hid"]) == (
        "account_manager",
        1,
        morgan["hid"],
    )

    # Nothing is copied: a new number of the carrier's desk shows on every circuit.
    make.patch(
        f"/contacts/{repair['hid']}", {"row_version": repair["row_version"], "phone": "+1 555 0199"}
    )
    again = circuits.in_force(first, second)
    for hid in (first, second):
        assert again[hid]["support_contacts"]["value"][0]["contact"]["phone"] == "+1 555 0199"
    # A retired contact stays in force where it is named, marked so.
    make.post(f"/contacts/{morgan['hid']}/retire", {"row_version": morgan["row_version"]}, 200)
    marked = circuits.in_force(first)[first]["account_managers"]["value"][0]["contact"]
    assert (marked["name"], marked["record_status"]) == ("Morgan Ellis", "retired")
    # Once its own are removed, a circuit has its carrier's again.
    make.delete(f"/circuits/{second}/contacts/{own['hid']}")
    assert circuits.in_force(second)[second]["account_managers"]["source"] == "vendor"


def test_the_site_contacts_of_a_circuit_are_those_of_its_sides_with_the_level_they_came_from(
    make: Maker, circuits: Circuits
) -> None:
    place = make.layout()
    dana = make.contact("Dana Whitfield")
    lee = make.contact("Lee Marchetti")
    sam = make.contact("Sam Okafor")
    casey = make.contact("Casey Lund")
    make.assign(dana, "technical", region_hid=place["americas"]["hid"])
    make.assign(dana, "escalation", region_hid=place["americas"]["hid"])
    make.assign(sam, "shipping", site_hid=place["site"]["hid"])
    make.assign(lee, "technical", location_hid=place["building"]["hid"])
    # The site says it has nobody for escalation, and nothing above it is looked at.
    make.assign(None, "escalation", site_hid=place["site"]["hid"], stop_inheritance=True)
    both = circuits.make("Building link", a=place["room"], z=place["building"])
    outside = circuits.make("Site-2 internet", a=place["room"])
    _name(make, f"/circuits/{both}", casey, "technical", side="z")
    _name(make, f"/circuits/{outside}", casey, "operational", side="z")

    found = circuits.in_force(both, outside)
    building, site = place["building"]["hid"], place["site"]["hid"]
    # The room has the building's technician and the site's shipping contact, in the
    # order of the list of roles; a role with nobody in force is left out.
    assert _sides(found[both], "a") == {
        "shipping": (["Sam Okafor"], "site", site),
        "technical": (["Lee Marchetti"], "location", building),
    }
    assert [one["role"] for one in found[both]["site_contacts"]["a"]] == ["shipping", "technical"]
    # What the building has of its own is, for the circuit, from the location; what the
    # circuit names for the side stands in place of it in that role.
    assert _sides(found[both], "z") == {
        "shipping": (["Sam Okafor"], "site", site),
        "technical": (["Casey Lund"], "own", both),
    }
    # A side with no location has only its own.
    assert _sides(found[outside], "z") == {"operational": (["Casey Lund"], "own", outside)}
    assert _sides(found[outside], "a") == _sides(found[both], "a")
    entry = found[both]["site_contacts"]["a"][0]["value"][0]
    assert entry["contact"]["name"] == "Sam Okafor"
    assert entry["role"] == "shipping"
    assert entry["priority"] == 1

    # Nothing is copied: a technician of the region shows wherever nothing nearer has one.
    nearer = make.in_force(place["building"])["by_role"]["technical"]["contacts"][0]
    make.delete(f"/contact-assignments/{nearer['assignment_hid']}")
    shown = circuits.in_force(both)[both]
    assert _sides(shown, "a")["technical"] == (
        ["Dana Whitfield"],
        "region",
        place["americas"]["hid"],
    )


def test_the_contacts_of_a_page_of_circuits_cost_what_those_of_one_circuit_cost(
    make: Maker, circuits: Circuits
) -> None:
    place = make.layout()
    carrier = make.vendor("Example Telecom")
    morgan = make.contact("Morgan Ellis")
    _name(make, f"/vendors/{carrier['hid']}", morgan, "account_manager")
    make.assign(morgan, "technical", site_hid=place["site"]["hid"])
    other = make.location("Building 2", place["site"])
    hids = [
        circuits.make(f"Circuit {number}", a=place["room"], z=other, carrier=carrier)
        for number in range(12)
    ]
    _name(make, f"/circuits/{hids[3]}", morgan, "support_contact")
    assert circuits.statements(*hids) == circuits.statements(hids[0])


# --- the lists of roles --------------------------------------------------------------


def test_a_role_a_circuit_names_for_a_side_is_in_use_and_the_carriers_roles_are_not(
    make: Maker, circuits: Circuits
) -> None:
    place = make.layout()
    circuit = circuits.make("Site-2 internet", a=place["room"])
    casey = make.contact("Casey Lund")
    noc = make.post("/choices", {"list": "contact_role", "value": "noc", "label": "NOC"})
    # A value of the list that is spelled as a carrier's role is not in use by those.
    same = make.post("/choices", {"list": "contact_role", "value": "account_manager"})
    _name(make, f"/circuits/{circuit}", casey, "account_manager")
    link = _name(make, f"/circuits/{circuit}", casey, "noc", side="a")
    make.delete(f"/choices/{noc['hid']}", 409)
    make.delete(f"/choices/{same['hid']}")
    make.delete(f"/circuits/{circuit}/contacts/{link['hid']}")
    make.delete(f"/choices/{noc['hid']}")
    # A contact named for a carrier or a circuit is counted among its uses.
    assert make.get(f"/contacts/{casey['hid']}")["uses"] == 1


# --- files ---------------------------------------------------------------------------


def test_the_contacts_of_vendors_travel_in_files(make: Maker, files: Files) -> None:
    make.vendor("Example Telecom")
    make.contact("Morgan Ellis")
    make.contact("Repair Desk", email="repair@example.org")
    loaded = files.load(
        "vendor_contacts",
        "vendor,role,contact,priority\n"
        "Example Telecom,account_manager,morgan.ellis@example.net,\n"
        "Example Telecom,support_contact,Repair Desk,\n"
        "Northwind Fiber,support_contact,Repair Desk,3\n",
    )
    assert counts(loaded) == (3, 0, 0, 0)
    # A carrier that is no vendor yet is made one, to be reviewed, as for every file.
    made = make.get("/vendors", filter="name:eq:Northwind Fiber")["items"][0]
    assert made["review_status"] == "unreviewed"
    assert [(one["role"], one["priority"]) for one in made["contacts"]] == [("support_contact", 3)]

    exported = files.export("vendor_contacts")
    assert [row["vendor"] for row in table(exported)] == [
        "Example Telecom",
        "Example Telecom",
        "Northwind Fiber",
    ]
    again = files.preview("vendor_contacts", exported)
    assert again["job"]["unchanged"] == again["job"]["row_count"] == 3, again["rows"]
    moved = files.load(
        "vendor_contacts",
        "vendor,role,contact,priority\nExample Telecom,account_manager,Morgan Ellis,7\n",
    )
    assert counts(moved) == (0, 1, 0, 0)
    rows = files.preview(
        "vendor_contacts",
        "vendor,role,contact\n"
        "Example Telecom,technical,Morgan Ellis\n"
        "Example Telecom,account_manager,nobody@example.net\n",
    )["rows"]
    assert [row["outcome"] for row in rows] == ["rejected"] * 2
    assert [row["reasons"][0]["field"] for row in rows] == ["role", "contact"]


def test_the_contacts_of_circuits_travel_in_files(
    make: Maker, files: Files, circuits: Circuits
) -> None:
    place = make.layout()
    first = circuits.make("Site-2 internet", a=place["room"], enterprise_circuit_id="EC-0042")
    second = circuits.make("Building link", a=place["room"], z=place["building"])
    circuits.make("Twin", a=place["room"])
    circuits.make("Twin", a=place["building"])
    make.contact("Casey Lund")
    make.contact("Lee Marchetti")
    loaded = files.load(
        "circuit_contacts",
        "circuit,side,role,contact,priority\n"
        "EC-0042,,account_manager,Casey Lund,\n"
        "ec-0042,a,technical,Lee Marchetti,\n"
        f"{second},z,technical,casey.lund@example.net,4\n"
        "Building link,a,shipping,Lee Marchetti,\n",
    )
    assert counts(loaded) == (4, 0, 0, 0)
    named = {
        (one["side"], one["role"]): one["contact"]["name"]
        for one in make.get(f"/circuits/{first}/contacts")["items"]
    }
    assert named == {(None, "account_manager"): "Casey Lund", ("a", "technical"): "Lee Marchetti"}

    # An export names a circuit by its enterprise ID, then by its name.
    exported = files.export("circuit_contacts")
    assert sorted((row["circuit"], row["side"], row["role"]) for row in table(exported)) == [
        ("Building link", "a", "shipping"),
        ("Building link", "z", "technical"),
        ("EC-0042", "", "account_manager"),
        ("EC-0042", "a", "technical"),
    ]
    again = files.preview("circuit_contacts", exported)
    assert again["job"]["unchanged"] == again["job"]["row_count"] == 4, again["rows"]
    as_json = files.preview(
        "circuit_contacts", json.loads(files.export("circuit_contacts", format="json"))
    )
    assert as_json["job"]["unchanged"] == 4, as_json["rows"]
    # A blank side is the carrier's: the same contact named for a side is another row.
    moved = files.load(
        "circuit_contacts",
        "circuit,side,role,contact,priority\n"
        "EC-0042,,account_manager,Casey Lund,2\n"
        "EC-0042,z,technical,Casey Lund,\n",
    )
    assert counts(moved) == (1, 1, 0, 0)
    # An import removes none.
    assert make.get(f"/circuits/{first}/contacts")["total"] == 3
    rows = files.preview(
        "circuit_contacts",
        "circuit,side,role,contact\n"
        "Twin,a,technical,Casey Lund\n"
        "Nowhere,a,technical,Casey Lund\n"
        "EC-0042,a,account_manager,Casey Lund\n"
        "EC-0042,,technical,Casey Lund\n",
    )["rows"]
    assert [row["outcome"] for row in rows] == ["rejected"] * 4
    assert [row["reasons"][0]["field"] for row in rows] == ["circuit", "circuit", "role", "role"]


def test_an_export_names_a_circuit_by_its_hid_where_another_answers_to_its_name(
    make: Maker, files: Files, circuits: Circuits
) -> None:
    place = make.layout()
    twin = circuits.make("Twin", a=place["room"])
    circuits.make("Twin", a=place["building"])
    called = circuits.make("EC-0007", a=place["room"])
    circuits.make("Other", a=place["room"], enterprise_circuit_id="ec-0007")
    casey = make.contact("Casey Lund")
    for hid in (twin, called):
        _name(make, f"/circuits/{hid}", casey, "account_manager")
    exported = {row["circuit"] for row in table(files.export("circuit_contacts"))}
    # A name that another circuit has, or that is another's enterprise ID, which is
    # looked for first, is no name to find it by.
    assert exported == {twin, called}
    again = files.preview("circuit_contacts", files.export("circuit_contacts"))
    assert again["job"]["unchanged"] == 2, again["rows"]


# --- the command line ----------------------------------------------------------------


@pytest.fixture
def hirdir(
    client: TestClient,
    inventory: dict[str, str],
    circuits: Circuits,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Run `hirdir` as the Inventory user, with its calls going to the test client.

    A circuit is found by the circuits' own routes, which come with the records of
    circuits: here it is found in the database by its name.
    """
    monkeypatch.setattr(
        cli_client.httpx2,
        "request",
        lambda method, url, timeout=None, **more: client.request(method, url, **more),
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("HIRDIR_URL", "http://testserver")
    monkeypatch.setenv("HIRDIR_TOKEN", inventory["Authorization"].removeprefix("Bearer "))

    def find_circuit(_: Any, text: str) -> dict[str, Any]:
        with circuits.sessions() as db:
            found = db.scalars(select(Circuit).where(Circuit.name_key == records.key(text)))
            return next({"hid": one.hid, "name": one.name} for one in found)

    monkeypatch.setattr(cli_inventory, "find_circuit", find_circuit)

    def run(*arguments: str, expect: int = 0) -> Result:
        result = runner.invoke(app, list(arguments))
        assert result.exit_code == expect, result.output
        return result

    return run


def test_contacts_are_named_for_a_carrier_and_a_circuit_at_the_command_line(
    hirdir, make: Maker, circuits: Circuits
) -> None:
    carrier = make.vendor("Example Telecom")
    place = make.layout()
    circuit = circuits.make("Site-2 internet", a=place["room"], carrier=carrier)
    make.contact("Morgan Ellis")
    make.contact("Lee Marchetti")

    named = hirdir(
        "vendors", "add-contact", "Example Telecom", "morgan.ellis@example.net", "--role",
        "account_manager",
    )  # fmt: skip
    assert "Example Telecom names Morgan Ellis as account_manager, number 1 of the list" in (
        named.stdout
    )
    hirdir("vendors", "add-contact", "Example Telecom", "Morgan Ellis", "--role",
           "account_manager", expect=5)  # fmt: skip
    hirdir("vendors", "add-contact", "Example Telecom", "Morgan Ellis", "--role", "technical",
           expect=4)  # fmt: skip
    found = make.get(f"/vendors/{carrier['hid']}")["contacts"]
    assert [one["contact"]["name"] for one in found] == ["Morgan Ellis"]

    on_side = hirdir(
        "circuits", "add-contact", "Site-2 internet", "Lee Marchetti", "--role", "technical",
        "--side", "a",
    )  # fmt: skip
    assert (
        "Site-2 internet names Lee Marchetti as technical on the A side, number 1 of the list"
        in on_side.stdout
    )
    own = hirdir("circuits", "add-contact", "Site-2 internet", "Lee Marchetti", "--role",
                 "account_manager", "--priority", "3")  # fmt: skip
    assert "as account_manager, number 3 of the list" in own.stdout
    hirdir("circuits", "add-contact", "Site-2 internet", "Lee Marchetti", "--role",
           "account_manager", "--side", "a", expect=4)  # fmt: skip
    in_force = circuits.in_force(circuit)[circuit]
    assert _people(in_force["account_managers"])[:2] == (["Lee Marchetti"], "own")

    # A contact is removed from the side and the role it is named for, and no other.
    hirdir("circuits", "remove-contact", "Site-2 internet", "Lee Marchetti", "--role",
           "technical", expect=4)  # fmt: skip
    removed = hirdir("circuits", "remove-contact", "Site-2 internet", "Lee Marchetti", "--role",
                     "technical", "--side", "a")  # fmt: skip
    assert "Site-2 internet no longer names Lee Marchetti as technical on the A side" in (
        removed.stdout
    )
    hirdir("circuits", "remove-contact", "Site-2 internet", "Lee Marchetti", "--role",
           "account_manager")  # fmt: skip
    assert _people(circuits.in_force(circuit)[circuit]["account_managers"])[:2] == (
        ["Morgan Ellis"],
        "vendor",
    )
    gone = hirdir("vendors", "remove-contact", "Example Telecom", "Morgan Ellis", "--role",
                  "account_manager")  # fmt: skip
    assert "Example Telecom no longer names Morgan Ellis as account_manager" in gone.stdout
    hirdir("vendors", "remove-contact", "Example Telecom", "Morgan Ellis", "--role",
           "account_manager", expect=4)  # fmt: skip
