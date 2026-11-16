"""The rules of the contacts a circuit has in force (P-149), on records held in memory:
which stand in place of which, and the level each came from."""

from hirdir.db.models import Circuit, CircuitContact, Contact, ContactAssignment, VendorContact
from hirdir.domain import carrier_contacts
from hirdir.domain.geography import RoleContacts

CIRCUIT = "0193a1f4-0000-7000-8000-000000000001"
CARRIER = "0193a1f4-0000-7000-8000-000000000002"
BUILDING = "0193a1f4-0000-7000-8000-000000000003"
SITE = "0193a1f4-0000-7000-8000-000000000004"
ORDER = ("shipping", "technical", "federal", "operational", "escalation")


def _contact(name: str) -> Contact:
    return Contact(hid=f"contact-{name}", name=name, record_status="active")


def _own(side: str | None, role: str, name: str, priority: int = 1):
    contact = _contact(name)
    link = CircuitContact(
        hid=f"own-{side}-{role}-{name}",
        circuit_hid=CIRCUIT,
        side=side,
        role=role,
        contact_hid=contact.hid,
        priority=priority,
    )
    return link, contact


def _theirs(role: str, name: str):
    contact = _contact(name)
    return VendorContact(
        hid=f"vendor-{role}-{name}", role=role, contact_hid=contact.hid, priority=1
    ), contact


def _placed(role: str, source: str, hid: str | None, *names: str, stopped: bool = False):
    held = [
        (
            ContactAssignment(hid=f"assignment-{role}-{name}", role=role, priority=number),
            _contact(name),
        )
        for number, name in enumerate(names, start=1)
    ]
    return RoleContacts(role, role.capitalize(), source, hid, None, stopped, held)


def test_the_carriers_contacts_are_its_own_or_its_carriers_for_each_role_by_itself() -> None:
    circuit = Circuit(hid=CIRCUIT, carrier_hid=CARRIER)
    theirs = [_theirs("account_manager", "Morgan Ellis"), _theirs("support_contact", "Repair")]
    # A site contact in the role of the carrier's is no naming of the carrier's.
    own = [_own(None, "account_manager", "Casey Lund"), _own("a", "support_contact", "Lee")]
    found = carrier_contacts._carrier(circuit, own, theirs)
    managers, support = found["account_manager"], found["support_contact"]
    assert (managers.source, managers.source_hid) == ("own", CIRCUIT)
    assert [one.contact.name for one in managers.named] == ["Casey Lund"]
    assert (support.source, support.source_hid) == ("vendor", CARRIER)
    assert [one.contact.name for one in support.named] == ["Repair"]
    # With no carrier, what a vendor names is nobody's.
    alone = carrier_contacts._carrier(Circuit(hid=CIRCUIT), [], theirs)
    assert {role: its.source for role, its in alone.items()} == {
        "account_manager": "none",
        "support_contact": "none",
    }


def test_a_sides_own_stand_in_place_of_its_locations_and_a_level_says_where_it_came_from() -> None:
    circuit = Circuit(hid=CIRCUIT)
    there = [
        _placed("shipping", "site", SITE, "Sam Okafor"),
        # The location of the side itself is, for the circuit, a location.
        _placed("technical", "own", BUILDING, "Lee Marchetti", "Dana Whitfield"),
        _placed("federal", "none", None),
        _placed("escalation", "site", SITE, stopped=True),
    ]
    # As the circuit names them: by side, by role, then by priority.
    own = [
        _own("a", "shipping", "Robin Achterberg", 1),
        _own("a", "shipping", "Casey Lund", 2),
        _own("z", "operational", "Priya Raman"),
        _own(None, "account_manager", "Morgan Ellis"),
    ]
    found = carrier_contacts._side(circuit, "a", own, there, ORDER)
    assert [(one.role, one.source, one.source_hid) for one in found] == [
        ("shipping", "own", CIRCUIT),
        ("technical", "location", BUILDING),
    ]
    assert [one.contact.name for one in found[0].named] == ["Robin Achterberg", "Casey Lund"]
    assert [(one.hid, one.priority) for one in found[1].named] == [
        ("assignment-technical-Lee Marchetti", 1),
        ("assignment-technical-Dana Whitfield", 2),
    ]
    # A side with no location has its own alone; a role that is of no list comes last.
    other = carrier_contacts._side(
        circuit, "z", [*own, _own("z", "archive", "Sam Okafor")], [], ORDER
    )
    assert [(one.role, one.source) for one in other] == [
        ("operational", "own"),
        ("archive", "own"),
    ]
