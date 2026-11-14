"""Write `examples/`: fictional CSV and JSON files for every record type.

The files are not written by hand. A small example inventory is built in a database of
its own, through the same rules as any other change, and then exported, so the examples
can never drift from what the importer takes. Every name, serial number, date and
amount is invented. Manufacturer and model names are real, because an inventory that
could not say "Catalyst 9300" would explain nothing.

    uv run python scripts/seed_examples.py           write examples/
    uv run python scripts/seed_examples.py --check   say whether examples/ is current
"""

import csv
import io
import json
import sys
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hirdir.config import Config
from hirdir.db import migrate
from hirdir.db.engine import make_engine, make_sessions
from hirdir.domain import (
    addresses,
    audit,
    catalog,
    contacts,
    geography,
    groups,
    items,
    operators,
    owners,
    tags,
)
from hirdir.io import exports, files
from hirdir.io.entities import ENTITIES, LOAD_ORDER

TARGET = Path(__file__).resolve().parent.parent / "examples"
# The moment at which the examples were last looked at: fixed, so the files do not change.
SEEN = datetime(2026, 11, 2, 15, 0, tzinfo=UTC)
SEED = audit.SYSTEM
DOMAIN = "example.net"

TAGS = (
    ("critical", "#d1242f", "An outage here is felt at once"),
    ("lab", "#8250df", "Not in service: for trying things out"),
    ("refresh-2028", "#bf8700", "Planned for replacement in 2028"),
    ("refresh-2030", "#1f6feb", "Planned for replacement in 2030"),
)

VENDORS = (
    ("Canonical", [], "Ubuntu support"),
    ("Cisco", ["Cisco Systems"], None),
    ("Example Cloud", [], "A fictional provider of hosted services"),
    ("Example Software", [], "A fictional maker of network management software"),
    ("Fluke Networks", [], None),
    ("Juniper", ["Juniper Networks"], None),
    ("Palo Alto Networks", ["PAN"], None),
)

# vendor, PID, model name, kind, type, function, value, weight, cost, LDoS, and the rest
ENTRIES: tuple[tuple[Any, ...], ...] = (
    (
        "Cisco",
        "C9300-48P",
        "Catalyst 9300 48-port PoE+",
        "hardware",
        "switch",
        "access",
        "18000",
        "1",
        "1450",
        "2034-04-30",
        {},
    ),
    (
        "Cisco",
        "C9200L-48P-4G",
        "Catalyst 9200L 48-port PoE+",
        "hardware",
        "switch",
        "access",
        "6500",
        "1",
        "520",
        "2031-10-31",
        {"end_of_sale": date(2026, 10, 31), "successor": "C9300-48P", "tags": ["refresh-2030"]},
    ),
    (
        "Cisco",
        "C9500-24Y4C",
        "Catalyst 9500 24-port 25G",
        "hardware",
        "switch",
        "core",
        "42000",
        "2.5",
        "3900",
        "2035-01-31",
        {},
    ),
    (
        "Cisco",
        "ISR4331/K9",
        "ISR 4331",
        "hardware",
        "router",
        "wan",
        "5200",
        "1.5",
        "610",
        "2028-11-30",
        {
            "end_of_sale": date(2023, 11, 30),
            "end_of_sw_support": date(2026, 11, 30),
            "end_of_hw_support": date(2028, 11, 30),
            "tags": ["refresh-2028"],
        },
    ),
    (
        "Cisco",
        "C9800-40-K9",
        "Catalyst 9800-40 wireless controller",
        "hardware",
        "wireless-controller",
        "wireless",
        "38000",
        "3",
        "4200",
        "2033-07-31",
        {},
    ),
    (
        "Cisco",
        "C9130AXI-B",
        "Catalyst 9130AX access point",
        "hardware",
        "access-point",
        "wireless",
        "1400",
        "0.2",
        "95",
        "2032-05-31",
        {},
    ),
    (
        "Cisco",
        "CP-8851-K9",
        "IP Phone 8851",
        "hardware",
        "phone",
        "voice",
        "420",
        "0.1",
        None,
        "2030-06-30",
        {},
    ),
    (
        "Juniper",
        "EX4400-48P",
        "EX4400 48-port PoE+",
        "hardware",
        "switch",
        "access",
        "15500",
        "1",
        "1300",
        "2035-03-31",
        {"stack_discount_pct": Decimal("30")},
    ),
    (
        "Juniper",
        "SRX345",
        "SRX345 services gateway",
        "hardware",
        "firewall",
        "edge",
        "3900",
        "1.5",
        "480",
        "2029-08-31",
        {},
    ),
    (
        "Palo Alto Networks",
        "PA-3410",
        "PA-3410",
        "hardware",
        "firewall",
        "security",
        "31000",
        "3",
        "7400",
        "2034-12-31",
        {},
    ),
    (
        "Fluke Networks",
        "LIQ-100",
        "LinkIQ cable and network tester",
        "hardware",
        "test-equipment",
        "lab",
        "2100",
        None,
        None,
        None,
        {},
    ),
    (
        "Canonical",
        "UBUNTU-SERVER-VM",
        "Ubuntu Server virtual machine",
        "virtual_machine",
        "virtual-machine",
        "management",
        None,
        "0.5",
        "500",
        None,
        {},
    ),
    (
        "Example Software",
        "NETCONFIG-MANAGER",
        "Configuration backup and compliance",
        "software",
        "application",
        "management",
        None,
        "2",
        "12000",
        None,
        {},
    ),
    (
        "Example Cloud",
        "SECONDARY-DNS",
        "Hosted secondary DNS",
        "service",
        "service",
        "management",
        None,
        "0.5",
        "3600",
        None,
        {},
    ),
    (
        "Cisco",
        "PWR-C1-715WAC-P",
        "715 W AC power supply",
        "hardware",
        "power-supply",
        None,
        "900",
        None,
        None,
        None,
        {},
    ),
    (
        "Cisco",
        "C9300-NM-8X",
        "Catalyst 9300 8-port 10G network module",
        "hardware",
        "module",
        None,
        "2400",
        None,
        None,
        None,
        {},
    ),
)

NETWORKS = (("Guest", "vrf"), ("Management", "network"), ("Voice", "vrf"))

# item, position, PID, serial number, and what the minor item has of its own
MINOR_ITEMS: tuple[tuple[str, str, str, str, dict[str, Any]], ...] = (
    ("site2-sw-access-01", "PS-A", "PWR-C1-715WAC-P", "LIT0000X001", {}),
    ("site2-sw-access-01", "PS-B", "PWR-C1-715WAC-P", "LIT0000X002", {}),
    ("site2-sw-access-01", "Slot 1", "C9300-NM-8X", "FOC0000X001", {}),
    ("site2-sw-access-02", "PS-A", "PWR-C1-715WAC-P", "LIT0000X003", {}),
    (
        "site2-sw-access-02",
        "PS-B",
        "PWR-C1-715WAC-P",
        "LIT0000X004",
        # The one that failed goes its own way; the others follow their switch.
        {
            "lifecycle_state": "Pending-Removal",
            "state_reason": "rma",
            "comments": "Failed in service; waiting for the return label",
        },
    ),
)

# name, type, what else the group has, and its members: item, role, position, joined, left
GROUPS: tuple[tuple[str, str, dict[str, Any], tuple[tuple[Any, ...], ...]], ...] = (
    (
        "site2-sw-core",
        "stack",
        {
            "hostname": "site2-sw-core",
            "fqdn": f"site2-sw-core.{DOMAIN}",
            "tags": ["critical"],
            "observed_status": "online",
            "observed_at": SEEN,
            # The second switch came up first after the last power work, and is master.
            "seen_master": "site2-sw-core-02",
        },
        (
            ("site2-sw-core-01", "master", 1, "2023-09-04", None),
            ("site2-sw-core-02", "member", 2, "2023-09-04", None),
        ),
    ),
    (
        "site2-sw-floor",
        "stack",
        # Meant to have three members: it is one short since the third was taken out.
        {"hostname": "site2-sw-floor", "fqdn": f"site2-sw-floor.{DOMAIN}", "expected_members": 3},
        (
            ("site2-sw-floor-01", "master", 1, "2021-06-14", None),
            ("site2-sw-floor-02", "member", 2, "2021-06-14", None),
            # Left the stack when it was replaced, and is on its way out.
            ("site2-sw-floor-03", "member", 3, "2021-06-14", "2026-06-30"),
        ),
    ),
    (
        "site2-wireless",
        "controller_domain",
        {},
        tuple(
            (f"site2-ap-{number:02d}", "endpoint", None, "2024-05-20", None)
            for number in (1, 2, 3, 4)
        ),
    ),
    (
        "site2-wlc-ha",
        "cluster",
        # One device on the network: the pair has one address to manage.
        {
            "hostname": "site2-wlc",
            "fqdn": f"site2-wlc.{DOMAIN}",
            "parent": "site2-wireless",
            "managed_as": "one",
        },
        (
            ("site2-wlc-01", "active", None, "2024-05-06", None),
            ("site2-wlc-02", "standby", None, "2024-05-06", None),
        ),
    ),
    (
        "site2-fw-edge",
        "cluster",
        # Each firewall is managed at its own address, and they share virtual ones.
        {"managed_as": "members", "tags": ["critical"]},
        (
            ("site2-fw-edge-01", "active", None, "2025-01-13", None),
            ("site2-fw-edge-02", "standby", None, "2025-01-13", None),
        ),
    ),
    (
        "site2-rtr-wan",
        "cluster",
        {"managed_as": "members"},
        (
            ("site2-rtr-wan-01", "active", None, "2020-02-10", None),
            ("site2-rtr-wan-02", "standby", None, "2020-02-10", None),
        ),
    ),
)

# whose it is (an item's hostname or a group's name), address, network, role, primary
ADDRESSES: tuple[tuple[str, str, str | None, str, bool], ...] = (
    *(
        (
            f"site2-sw-access-{number:02d}",
            f"192.0.2.{10 + number}",
            "Management",
            "management",
            True,
        )
        for number in range(1, 7)
    ),
    ("site2-sw-core", "192.0.2.1", "Management", "management", True),
    # Managed over IPv6 as well: a primary address of each family.
    ("site2-sw-core", "2001:db8::1", "Management", "management", True),
    ("site2-sw-floor", "192.0.2.21", "Management", "management", True),
    ("site2-wlc-ha", "192.0.2.30", "Management", "management", True),
    ("site2-rtr-wan-01", "192.0.2.2", "Management", "management", True),
    ("site2-rtr-wan-01", "2001:db8::2", None, "loopback", False),
    ("site2-rtr-wan-02", "192.0.2.3", "Management", "management", True),
    ("site2-rtr-wan-02", "2001:db8::3", None, "loopback", False),
    # A gateway address that the two routers share is an address of their cluster, held
    # once: it is no duplicate.
    ("site2-rtr-wan", "192.0.2.254", "Management", "virtual", False),
    ("site2-fw-edge-01", "192.0.2.4", "Management", "management", True),
    ("site2-fw-edge-02", "192.0.2.5", "Management", "management", True),
    # The same address under two networks is two addresses.
    ("site2-fw-edge", "203.0.113.1", "Guest", "virtual", False),
    ("site2-fw-edge", "203.0.113.1", "Voice", "virtual", False),
    ("netconfig-01", "198.51.100.10", None, "management", True),
    ("netmon-01", "198.51.100.11", None, "management", True),
    # A mistake: the address of netconfig-01, entered on netmon-01 as well. Held twice
    # under one network, it is accepted, and is in the duplicates report.
    ("netmon-01", "198.51.100.10", None, "secondary", False),
)

# What is known of how some items are doing: condition, observed status, when it was seen
DOING: tuple[tuple[str, str | None, str | None], ...] = (
    *((f"site2-sw-access-{number:02d}", "good", "online") for number in range(1, 7)),
    # A cold spare on its shelf, counted at the last audit, and one nobody has tried yet.
    ("site2-sw-access-07", "good", "present"),
    ("site2-sw-access-08", "untested", None),
    ("site2-sw-core-01", "good", "online"),
    ("site2-sw-core-02", "good", "online"),
    ("site2-sw-floor-01", "degraded", "online"),
    ("site2-sw-floor-02", "good", "online"),
    ("site2-sw-floor-03", "suspect", None),
    ("site2-rtr-wan-01", "good", "online"),
    ("site2-rtr-wan-02", "good", "unreachable"),
    ("LIT0000X004", "failed", None),
    # Test equipment is never on the network: what is observed of it is that it is there.
    ("LQ0000X001", "good", "present"),
)

OWNERS = (
    ("Network Engineering", "Infrastructure Operations", False, None),
    ("Security Operations", "Infrastructure Operations", False, None),
    ("Voice Services", "Infrastructure Operations", False, None),
    (
        "Facilities Management",
        "Corporate Services",
        True,
        "Owns the building management network; the operations team supports its switches",
    ),
)


# The regions, from the top down: name, code, the region it is in, and what else it has.
REGIONS: tuple[tuple[str, str, str | None, dict[str, Any]], ...] = (
    (
        "Americas",
        "AMER",
        None,
        {"ship_instructions": "Call the Network Operations Desk a day ahead of any delivery"},
    ),
    (
        # The sites of the region take their deliveries at one depot, unless a site
        # says otherwise.
        "Central",
        "CEN",
        "Americas",
        {
            "ship_address1": "500 Depot Road",
            "ship_city": "Springfield",
            "ship_state": "IL",
            "ship_postal_code": "00000",
            "ship_country": "US",
        },
    ),
    ("East", "EAST", "Americas", {}),
)
# The sites: name, code, the path of its region, and what else it has.
SITES: tuple[tuple[str, str, str, dict[str, Any]], ...] = (
    (
        "Site-1",
        "S1",
        "Americas > East",
        {
            # What does arrive for the small office is sent on from another address.
            "ship_address1": "210 Sample Street",
            "ship_address2": "Mail room",
            "ship_city": "Riverton",
            "ship_state": "NY",
            "ship_postal_code": "00000",
            "ship_country": "US",
            "address1": "200 Sample Street",
            "city": "Riverton",
            "state": "NY",
            "postal_code": "00000",
            "country": "US",
            "notes": "A small office: one equipment room",
        },
    ),
    (
        "Site-2",
        "S2",
        "Americas > Central",
        {
            "address1": "100 Example Way",
            "city": "Springfield",
            "state": "IL",
            "postal_code": "00000",
            "country": "US",
            # Deliveries go to its own door: the street address is not typed again,
            # and it stands in place of the depot of the region.
            "ship_same_as_address": True,
            "ship_instructions": "Dock B, weekdays 08:00 to 15:00",
            "latitude": Decimal("40.000000"),
            "longitude": Decimal("-89.000000"),
            "tags": ["critical"],
        },
    ),
    (
        "Site-3",
        "S3",
        "Americas > Central",
        {"record_status": "draft", "notes": "Entered ahead of the build; opens next year"},
    ),
)
# The locations, a location before the ones within it: its site, the location it is in,
# from the site down, its name, its kind, and what else it has.
LOCATIONS: tuple[tuple[str, str | None, str, str, dict[str, Any]], ...] = (
    ("Site-1", None, "Comms Room", "room", {}),
    ("Site-2", None, "Building 1", "building", {"code": "B1"}),
    ("Site-2", "Building 1", "Floor 1", "floor", {}),
    (
        "Site-2",
        "Building 1 > Floor 1",
        "Room 102",
        "room",
        {"notes": "The main equipment room"},
    ),
    ("Site-2", "Building 1 > Floor 1 > Room 102", "Rack A1", "rack", {}),
    ("Site-2", "Building 1", "Floor 2", "floor", {}),
    ("Site-2", "Building 1 > Floor 2", "Room 201", "room", {}),
    ("Site-2", "Building 1", "Lab", "room", {}),
    (
        "Site-2",
        None,
        "Store Room",
        "warehouse",
        {"ship_instructions": "Leave with the store keeper; a signature is needed"},
    ),
    ("Site-3", None, "Suite 300", "room", {"record_status": "draft"}),
)
SITE_PATHS = {name: f"{region} > {name}" for name, _, region, _ in SITES}
# Where the examples are, by the start of the host name: the path from the site down.
PLACED = (
    ("site2-sw-core", "Site-2", "Building 1 > Floor 1 > Room 102 > Rack A1"),
    ("site2-rtr-wan", "Site-2", "Building 1 > Floor 1 > Room 102"),
    ("site2-fw-", "Site-2", "Building 1 > Floor 1 > Room 102"),
    ("site2-wlc", "Site-2", "Building 1 > Floor 1 > Room 102"),
    ("netconfig-", "Site-2", "Building 1 > Floor 1 > Room 102"),
    ("netmon-", "Site-2", "Building 1 > Floor 1 > Room 102"),
    ("site2-sw-access", "Site-2", "Building 1 > Floor 2 > Room 201"),
    ("site2-sw-floor", "Site-2", "Building 1 > Floor 2 > Room 201"),
    ("site2-ap-01", "Site-2", "Building 1 > Floor 1"),
    ("site2-ap-02", "Site-2", "Building 1 > Floor 1"),
    ("site2-ap", "Site-2", "Building 1 > Floor 2"),
    ("site2-phone", "Site-2", "Building 1 > Floor 2"),
    ("lab-", "Site-2", "Building 1 > Lab"),
    ("site1-", "Site-1", "Comms Room"),
    ("site3-", "Site-3", "Suite 300"),
)
STORE_ROOM = "Americas > Central > Site-2 > Store Room"
# People and shared mailboxes: name, organization, email address, telephone number.
# The numbers are from the range kept for fiction.
CONTACTS = (
    ("Dana Whitfield", "Infrastructure Operations", "dana.whitfield", "+1 555 0100"),
    ("Robin Achterberg", "Infrastructure Operations", "robin.achterberg", "+1 555 0101"),
    ("Lee Marchetti", "Infrastructure Operations", "lee.marchetti", "+1 555 0102"),
    ("Priya Raman", "Infrastructure Operations", "priya.raman", "+1 555 0103"),
    ("Tomas Lindqvist", "Infrastructure Operations", "tomas.lindqvist", "+1 555 0104"),
    ("Sam Okafor", "Corporate Services", "sam.okafor", "+1 555 0110"),
    ("Network Operations Desk", "Infrastructure Operations", "noc", "+1 555 0199"),
    ("Facilities Help Desk", "Corporate Services", "facilities", "+1 555 0150"),
)
# Who answers for a place, in which role: the path of the place, the role and the
# contact, in the order of their priority. A contact of None says: none here, and do
# not look further up.
ASSIGNMENTS: tuple[tuple[str, str, str | None], ...] = (
    ("Americas", "technical", "Dana Whitfield"),
    ("Americas", "technical", "Robin Achterberg"),
    ("Americas", "operational", "Network Operations Desk"),
    ("Americas", "escalation", "Robin Achterberg"),
    ("Americas > Central > Site-2", "shipping", "Sam Okafor"),
    # The building has a technician of its own, who is asked before the regional lead.
    ("Americas > Central > Site-2 > Building 1", "technical", "Lee Marchetti"),
    # Nothing is shipped to the small office: deliveries for it go to Site-2.
    ("Americas > East > Site-1", "shipping", None),
)
# The people of each owner, the primary first.
OWNER_MEMBERS = (
    ("Network Engineering", ("Dana Whitfield", "Robin Achterberg", "Lee Marchetti")),
    ("Security Operations", ("Priya Raman",)),
    ("Voice Services", ("Tomas Lindqvist", "Dana Whitfield")),
    ("Facilities Management", ("Facilities Help Desk",)),
)


# The operators: a short label for each member of the team who looks after equipment,
# its description, its colour and who is behind it. One is open: the person has moved
# on, and what the label is on stays together until somebody takes it over.
OPERATORS: tuple[tuple[str, str, str, str | None], ...] = (
    ("LM", "Core and distribution", "#1f6feb", "Lee Marchetti"),
    ("RA", "Access and the lab", "#8250df", "Robin Achterberg"),
    ("TL", "Wireless and voice", "#1a7f37", "Tomas Lindqvist"),
    ("DW", "WAN", "#bf8700", "Dana Whitfield"),
    ("PR", "Security", "#d1242f", "Priya Raman"),
    ("OP6", "The small offices", "#6e7781", None),
)
# Who looks after what. A group is given its operator once, and its members have it:
# the switches of a stack, the access points of the controller domain, and the pair of
# controllers in it, through the domain their cluster is nested in. One switch has an
# operator of its own. A place may have one as well, for what is there and has none
# from elsewhere: the lab, and the small office, whose label is open. What is named
# nowhere here is looked after by nobody in particular, and a report by operator says
# how much that is.
GROUP_OPERATORS = {
    "site2-sw-core": "LM",
    "site2-sw-floor": "RA",
    "site2-wireless": "TL",
    "site2-rtr-wan": "DW",
    "site2-fw-edge": "PR",
}
ITEM_OPERATORS = {"site2-sw-access-01": "RA", "site2-fw-oob-01": "PR"}
# What is meant for a place that is not in use yet. The parked switch is in the store
# room and is counted there; when Site-3 is made active it is moved in by that change.
PLANNED = {"site2-sw-access-08": "Americas > Central > Site-3 > Suite 300"}
PLACE_OPERATORS = {
    "Americas > Central > Site-2 > Building 1 > Lab": "RA",
    "Americas > East > Site-1": "OP6",
}


def _placed(item: dict[str, Any]) -> str | None:
    """Return the path of the location an example item is at, or None for nowhere."""
    host = item.get("hostname") or ""
    if not host.startswith("site2-") or (
        item.get("disposition") != "Spare" and item.get("lifecycle_state") != "Assigned"
    ):
        for prefix, site, within in PLACED:
            if host.startswith(prefix):
                return f"{SITE_PATHS[site]} > {within}"
        return None
    # A spare on the shelf, and a switch that is parked until it is needed.
    return STORE_ROOM


def _mac(number: int) -> str:
    """Return a MAC address from the block reserved for documentation, 00-00-5E-00-53-xx."""
    return f"00005e0053{number:02x}"


def _hardware(
    pid: str, vendor: str, prefix: str, count: int, serial: str, first_tag: int, **more: Any
) -> list[dict[str, Any]]:
    """Return count items of one model, numbered from 01."""
    made = []
    for number in range(1, count + 1):
        hostname = f"{prefix}-{number:02d}"
        made.append(
            {
                "vendor": vendor,
                "pid": pid,
                "serial_number": f"{serial}{number:03d}",
                "asset_tag": f"AT-{first_tag + number:06d}",
                "hostname": hostname,
                "fqdn": f"{hostname}.{DOMAIN}",
                "mac_address": _mac(first_tag % 200 + number),
                "owner": "Network Engineering",
                "lifecycle_state": "Prod",
                **more,
            }
        )
    return made


def _items() -> list[dict[str, Any]]:
    """Return the example items: a small site's worth, in every state of the lifecycle."""
    access = _hardware(
        "C9300-48P",
        "Cisco",
        "site2-sw-access",
        8,
        "FCW0000X",
        100,
        in_service_on=date(2024, 3, 18),
        warranty_start=date(2024, 2, 1),
        warranty_end=date(2025, 1, 31),
    )
    access[0]["tags"] = ["critical"]
    access[6].update(
        lifecycle_state="Prod",
        disposition="Spare",
        expected_online=False,
        comments="Cold spare on the shelf in the site's store room",
    )
    access[7].update(
        lifecycle_state="Assigned",
        disposition="Spare",
        comments="Parked with the team until a site asks for it",
    )
    core = _hardware(
        "C9500-24Y4C",
        "Cisco",
        "site2-sw-core",
        2,
        "FCW0000Y",
        120,
        tags=["critical"],
        in_service_on=date(2023, 9, 4),
    )
    older = _hardware(
        "C9200L-48P-4G",
        "Cisco",
        "site2-sw-floor",
        3,
        "JAE0000X",
        130,
        tags=["refresh-2030"],
        in_service_on=date(2021, 6, 14),
    )
    older[2].update(
        lifecycle_state="Pending-Removal",
        disposition="Excess",
        state_reason="retired",
        comments="Replaced by site2-sw-access-06",
    )
    routers = _hardware(
        "ISR4331/K9",
        "Cisco",
        "site2-rtr-wan",
        2,
        "FDO0000X",
        140,
        tags=["critical", "refresh-2028"],
        in_service_on=date(2020, 2, 10),
    )
    routers[1].update(lifecycle_state="Down", disposition="Production", state_reason="maintenance")
    staged = _hardware(
        "EX4400-48P",
        "Juniper",
        "lab-sw-ex",
        2,
        "JN0000X",
        150,
        lifecycle_state="Test",
        tags=["lab"],
        delivered_on=date(2026, 9, 21),
    )
    firewalls = _hardware(
        "PA-3410",
        "Palo Alto Networks",
        "site2-fw-edge",
        2,
        "PA0000X",
        160,
        owner="Security Operations",
        tags=["critical"],
        in_service_on=date(2025, 1, 13),
    )
    # One unit carries a threat-prevention licence the model's figure leaves out.
    firewalls[0].update(est_value=Decimal("36500"), annual_support_cost=Decimal("9100"))
    gateway = _hardware(
        "SRX345",
        "Juniper",
        "site2-fw-oob",
        1,
        "CW0000X",
        170,
        lifecycle_state="Delivered",
        owner="Security Operations",
        procured_on=date(2026, 8, 3),
        delivered_on=date(2026, 10, 12),
    )
    controller = _hardware(
        "C9800-40-K9",
        "Cisco",
        "site2-wlc",
        2,
        "TTM0000X",
        180,
        tags=["critical"],
        in_service_on=date(2024, 5, 6),
    )
    access_points = _hardware(
        "C9130AXI-B",
        "Cisco",
        "site2-ap",
        4,
        "FJC0000X",
        190,
        in_service_on=date(2024, 5, 20),
    )
    phones = _hardware(
        "CP-8851-K9",
        "Cisco",
        "site2-phone",
        3,
        "FCH0000X",
        200,
        owner="Voice Services",
    )
    phones[2].update(lifecycle_state="Purchased", procured_on=date(2026, 10, 5))
    retired = _hardware(
        "C9200L-48P-4G",
        "Cisco",
        "site1-sw-floor",
        1,
        "JAE0000Y",
        210,
        lifecycle_state="Archived",
        state_reason="disposed",
        owner="Facilities Management",
        comments="Traded in when the office was rewired",
    )
    planned = _hardware(
        "C9300-48P",
        "Cisco",
        "site3-sw-access",
        1,
        "FCW0000Z",
        220,
        lifecycle_state=None,
        record_status="draft",
        comments="Entered ahead of the Site-3 build; not counted until made active",
    )
    others = [
        # A piece of test equipment is a complete record with this much and no more.
        {
            "vendor": "Fluke Networks",
            "pid": "LIQ-100",
            "serial_number": "LQ0000X001",
            "owner": "Network Engineering",
        },
        {
            "vendor": "Canonical",
            "pid": "UBUNTU-SERVER-VM",
            "name": "netconfig-01",
            "hostname": "netconfig-01",
            "fqdn": f"netconfig-01.{DOMAIN}",
            "lifecycle_state": "Prod",
            "owner": "Network Engineering",
            "description": "Runs the configuration backup",
        },
        {
            "vendor": "Canonical",
            "pid": "UBUNTU-SERVER-VM",
            "name": "netmon-01",
            "hostname": "netmon-01",
            "fqdn": f"netmon-01.{DOMAIN}",
            "lifecycle_state": "Prod",
            "owner": "Network Engineering",
            "description": "Collects flow records",
        },
        {
            "vendor": "Example Software",
            "pid": "NETCONFIG-MANAGER",
            "name": "NetConfig Manager",
            # One licence. For software a quantity multiplies the weight and the cost
            # of its catalog entry, which here are those of the whole licence.
            "lifecycle_state": "Prod",
            "owner": "Network Engineering",
            "description": "One licence, for 250 devices",
        },
        {
            "vendor": "Example Cloud",
            "pid": "SECONDARY-DNS",
            "name": "Secondary DNS",
            "lifecycle_state": "Prod",
            "owner": "Network Engineering",
        },
    ]
    return [
        *access,
        *core,
        *older,
        *routers,
        *staged,
        *firewalls,
        *gateway,
        *controller,
        *access_points,
        *phones,
        *retired,
        *planned,
        *others,
    ]


def build(db: Session) -> None:
    """Fill an empty database with the example inventory."""
    for label, colour, description in TAGS:
        tags.create_tag(db, SEED, {"label": label, "colour": colour, "description": description})
    vendors = {}
    for name, aliases, notes in VENDORS:
        vendors[name] = catalog.create_vendor(
            db, SEED, {"name": name, "aliases": aliases, "notes": notes}
        )
    entries: dict[tuple[str, str], Any] = {}
    for vendor, pid, model, kind, type_, function, value, weight, cost, ldos, more in ENTRIES:
        fields = {
            "vendor_hid": vendors[vendor].hid,
            "pid": pid,
            "model_name": model,
            "kind": kind,
            "type": type_,
            "function": function,
            "est_value": Decimal(value) if value else None,
            "support_weight": Decimal(weight) if weight else None,
            "annual_support_cost": Decimal(cost) if cost else None,
            "ldos": date.fromisoformat(ldos) if ldos else None,
            **{name: given for name, given in more.items() if name != "successor"},
        }
        if "successor" in more:
            fields["successor_hid"] = entries[vendor, more["successor"]].hid
        entries[vendor, pid] = catalog.create_entry(db, SEED, fields)
    regions: dict[str, Any] = {}
    for name, code, parent, more in REGIONS:
        path = f"{parent} > {name}" if parent else name
        regions[path] = geography.create_place(
            db,
            SEED,
            geography.REGION,
            {
                "name": name,
                "code": code,
                "parent_region_hid": regions[parent].hid if parent else None,
                **more,
            },
        )
    sites: dict[str, Any] = {}
    for name, code, region, more in SITES:
        sites[name] = geography.create_place(
            db,
            SEED,
            geography.SITE,
            {"name": name, "code": code, "region_hid": regions[region].hid, **more},
        )
    places: dict[str, Any] = {}
    for site, parent, name, kind, more in LOCATIONS:
        within = f"{SITE_PATHS[site]} > {parent}" if parent else SITE_PATHS[site]
        places[f"{within} > {name}"] = geography.create_place(
            db,
            SEED,
            geography.LOCATION,
            {
                "name": name,
                "site_hid": sites[site].hid,
                "parent_location_hid": places[within].hid if parent else None,
                "kind": kind,
                **more,
            },
        )
    marks: dict[str, Any] = {}
    people = {}
    for name, organization, mailbox, phone in CONTACTS:
        people[name] = contacts.create_contact(
            db,
            SEED,
            {
                "name": name,
                "organization": organization,
                "email": f"{mailbox}@{DOMAIN}",
                "phone": phone,
            },
        )
    for label, description, colour, person in OPERATORS:
        marks[label] = operators.create_operator(
            db,
            SEED,
            {
                "label": label,
                "description": description,
                "colour": colour,
                "contact_hid": people[person].hid if person else None,
            },
        )
    for path, label in PLACE_OPERATORS.items():
        place = geography.the_place(db, path, "place")
        geography.update_place(
            db,
            SEED,
            place.level,
            place.hid,
            place.record.row_version,
            {"operator_hid": marks[label].hid},
        )
    for path, role, contact in ASSIGNMENTS:
        place = geography.the_place(db, path, "place")
        contacts.create_assignment(
            db,
            SEED,
            {
                f"{place.level}_hid": place.hid,
                "role": role,
                "contact_hid": people[contact].hid if contact else None,
                "stop_inheritance": contact is None,
            },
        )
    its_owners = {}
    for label, organization, is_external, reason in OWNERS:
        its_owners[label] = owners.create_owner(
            db,
            SEED,
            {
                "label": label,
                "organization": organization,
                "is_external": is_external,
                "exception_reason": reason,
            },
        )
    for label, members in OWNER_MEMBERS:
        for name in members:
            owners.add_member(db, SEED, its_owners[label].hid, {"contact_hid": people[name].hid})
    for item in _items():
        fields = {name: value for name, value in item.items() if value is not None}
        fields["catalog_entry_hid"] = entries[fields.pop("vendor"), fields.pop("pid")].hid
        if "owner" in fields:
            fields["owner_hid"] = its_owners[fields.pop("owner")].hid
        where = _placed(item)
        if where is not None:
            fields["location_hid"] = places[where].hid
        if item.get("hostname") in PLANNED:
            fields["planned_location_hid"] = places[PLANNED[item["hostname"]]].hid
        if item.get("hostname") in ITEM_OPERATORS:
            fields["operator_hid"] = marks[ITEM_OPERATORS[item["hostname"]]].hid
        items.create_item(db, SEED, fields)
    db.flush()

    def item(hostname: str) -> Any:
        return items.the_one(db, hostname, "item")

    for parent, position, pid, serial, more in MINOR_ITEMS:
        items.create_item(
            db,
            SEED,
            {
                "catalog_entry_hid": entries["Cisco", pid].hid,
                "serial_number": serial,
                "parent_item_hid": item(parent).hid,
                "position": position,
                **more,
            },
        )
    made: dict[str, Any] = {}
    for name, type_, more, members in GROUPS:
        fields: dict[str, Any] = {"name": name, "type": type_, **more}
        if "parent" in fields:
            fields["parent_group_hid"] = made[fields.pop("parent")].hid
        if "seen_master" in fields:
            fields["observed_master_hid"] = item(fields.pop("seen_master")).hid
            fields["master_observed_at"] = SEEN
        where = _placed({"hostname": name}) if type_ != "controller_domain" else None
        if where is not None:
            fields["location_hid"] = places[where].hid
        if name in GROUP_OPERATORS:
            fields["operator_hid"] = marks[GROUP_OPERATORS[name]].hid
        fields["members"] = [
            {
                "item_hid": item(hostname).hid,
                "role": role,
                "position": position,
                "joined_on": date.fromisoformat(joined),
                "left_on": date.fromisoformat(left) if left else None,
            }
            for hostname, role, position, joined, left in members
        ]
        made[name] = groups.create_group(db, SEED, fields)
    for known_as, condition, observed in DOING:
        one = item(known_as)
        doing: dict[str, Any] = {"condition": condition}
        if observed is not None:
            doing.update(observed_status=observed, observed_at=SEEN)
        items.update_item(db, SEED, one.hid, one.row_version, doing)
    networks = {
        label: addresses.create_network(db, SEED, {"label": label, "kind": kind})
        for label, kind in NETWORKS
    }
    for holder, address, network, role, is_primary in ADDRESSES:
        whose = (
            {"group_hid": made[holder].hid} if holder in made else {"item_hid": item(holder).hid}
        )
        addresses.create_address(
            db,
            SEED,
            {
                **whose,
                "address": address,
                "network_hid": networks[network].hid if network else None,
                "role": role,
                "is_primary": is_primary,
            },
        )
    db.flush()


@contextmanager
def seeded() -> Generator[Session]:
    """Yield a session on a database of its own that holds the example inventory."""
    with tempfile.TemporaryDirectory() as state:
        config = Config(state_dir=Path(state))
        migrate.upgrade(config.database_url)
        engine = make_engine(config.database_url)
        with make_sessions(engine)() as db:
            build(db)
            db.commit()
            yield db
        engine.dispose()


def counts() -> dict[str, int]:
    """Return how many records of each entity the example inventory holds."""
    with seeded() as db:
        return {
            name: db.scalar(select(func.count()).select_from(ENTITIES[name].model)) or 0
            for name in LOAD_ORDER
        }


def file_name(entity: str, format_: str) -> str:
    """Return the name of the example file of an entity."""
    return f"{entity.replace('_', '-')}.{format_}"


def _without_hids(text: str, format_: str) -> str:
    """Return an exported file with no HIDs in it.

    An export names every record by its HID, and an import that is given an HID changes
    that record and no other. The examples are for loading into a database that has
    none of these records yet, so they keep the column and leave it blank.
    """
    if format_ == "json":
        envelope = json.loads(text)
        for record in envelope["records"]:
            del record["hid"]
        return "".join(files.write_json(envelope["entity"], [envelope["records"]]))
    rows = list(csv.reader(io.StringIO(text, newline="")))
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(rows[0])
    writer.writerows(["", *row[1:]] for row in rows[1:])
    return out.getvalue()


README = """# Examples

A small, fictional inventory: one file for each kind of record, as CSV and as JSON. The
two formats hold the same records. Every host name, serial number, asset tag, date and
amount here is invented, and so are the end-of-life dates and the prices of the models.
Only the names of manufacturers and models are real.

The files are written by `make examples`, which builds this inventory in a database of
its own and exports it. They are not edited by hand.

## Loading them

Load the files in this order, because a record names the ones it refers to:

{order}

Each command shows a preview and changes nothing. Add `--apply` to load the file.

```bash
{commands}
```

Loaded a second time, every row is `unchanged`. The `hid` column is there and blank:
`hirdir` gives each record its HID as it is created. A file exported from a running
`hirdir` has the column filled in, and a row with an HID changes that record and no
other.

The columns of each file, and what an import does with a blank cell or with `!clear`,
are under "Import and export" in [Interfaces](../docs/interfaces.md#import-and-export).
"""


def render() -> dict[str, str]:
    """Return every file of `examples/` by name."""
    written = {}
    with seeded() as db:
        for entity in LOAD_ORDER:
            for format_ in ("csv", "json"):
                export = exports.plan(
                    db,
                    entity,
                    format_=format_,
                    # By depth, an item stands before the minor items that are in it.
                    sort=["depth", "name"] if entity == "items" else None,
                    own_values=True,
                    include_archived=True,
                    include_drafts=True,
                )
                written[file_name(entity, format_)] = _without_hids(
                    exports.text_of(db, export), format_
                )
    order = "\n".join(
        f"{number}. `{file_name(entity, 'csv')}`" for number, entity in enumerate(LOAD_ORDER, 1)
    )
    commands = "\n".join(
        f"hirdir import examples/{file_name(entity, 'csv')} --entity {entity}"
        for entity in LOAD_ORDER
    )
    written["README.md"] = README.format(order=order, commands=commands)
    return written


def main() -> int:
    """Write the examples, or with --check say whether the files are current."""
    written = render()
    if "--check" in sys.argv:
        stale = [
            name
            for name, text in written.items()
            if not (TARGET / name).is_file() or (TARGET / name).read_text(encoding="utf-8") != text
        ]
        extra = (
            [path.name for path in TARGET.iterdir() if path.name not in written]
            if TARGET.is_dir()
            else []
        )
        if stale or extra:
            print(
                f"examples/ is out of date ({', '.join(sorted(stale + extra))}): "
                "run `make examples`",
                file=sys.stderr,
            )
            return 1
        return 0
    TARGET.mkdir(exist_ok=True)
    for name, text in written.items():
        (TARGET / name).write_text(text, encoding="utf-8")
    print(f"wrote {len(written)} files to examples/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
