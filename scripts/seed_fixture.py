"""Fill a database of its own with a large, fictional inventory, for timing.

    uv run python scripts/seed_fixture.py                  fixture-data/, 50,000 items
    uv run python scripts/seed_fixture.py PATH             the same, in another folder
    uv run python scripts/seed_fixture.py --items 2000     a smaller one of the same shape

`make fixture` runs the first. The folder is given `hirdir.db` at the newest schema,
`fixture.json`, which says what is in it and how to sign in, and a `config.toml`, so
that the inventory can be looked at in a browser with
`HIRDIR_CONFIG=fixture-data/config.toml uv run hirdir admin serve --dev`, on
127.0.0.1:8726. A folder is filled again only if this script made it.

This is for timing, and it bypasses the rules. What there are few of, the catalog,
the places, the owners, the agreements, the contracts, the purchase requests and their
lines, and the device groups with their members, is made through `hirdir.domain`, as
any change is. The items, their tags,
their addresses and their coverage under contracts are written in bulk, straight into
their tables, because 50,000 items made one at a time take many minutes. Those rows
are what an import of the same inventory from a file would have written: HIDs from
`hirdir.ids`, the keys that are compared, the standing each lifecycle state gives on
entry, row versions, bookkeeping, and an audit event for each change. An item that has
left service has a coverage that ended on the day it left and says so, as
`hirdir.domain.contracts.end_for_item` leaves it, unless the vendor has been told. Many
of the items bought in the last two years arrived on a line of a purchase request, and
a few of those are of another model than their line's, as 0.6.0 let in.

The shape is that of the target in docs/requirements.md: 30% of the items are major
items that are not phones, 44% are phones, and the rest are power supplies, modules,
line cards and optics in them. Dates are counted from the day it is built, so that
what has lapsed, what is pending renewal and what runs out soon are so on that day.
The choices are made by a hash of a seed and a key, so the same seed always gives the
same inventory.

Every value is invented. Names are under example.net and example.com, addresses come
from 2001:db8::/32, MAC addresses are locally administered ones (02-5E-...) that no
manufacturer has, and serial numbers, asset tags, contract and agreement numbers and
request numbers are counted up from one. Manufacturer and model names are real, as in
`seed_examples.py`; the variants of a model, `-V01` and on, are not.

What 0.7.0 added is there too: some of the older models are not to be renewed, and a
few items say otherwise of themselves; a few contracts in agreements are marked to end
with their present term, and a few that share an agreement's period still say their
renewal is pending or that they have expired, which puts them on the list to review;
and the operations team has capacity lines, by region and by site, some that multiply
the staff lines, a draft or two and one that has ended, with the balance recorded for
each of the last four weeks.
"""

import argparse
import hashlib
import ipaddress
import json
import shutil
import sys
import time
from collections import defaultdict
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from hirdir import clock
from hirdir.config import Config
from hirdir.db import migrate
from hirdir.db.engine import make_engine, make_sessions
from hirdir.db.models import (
    Address,
    Agreement,
    AuditEvent,
    CapacityLine,
    CapacityRecord,
    CatalogEntry,
    Contract,
    ContractCoverage,
    DeviceGroup,
    DeviceGroupMember,
    Item,
    LifecycleRule,
    PurchaseLine,
    PurchaseRequest,
    Region,
    TagLink,
)
from hirdir.domain import (
    accounts,
    addresses,
    audit,
    capacity,
    catalog,
    contacts,
    contracts,
    geography,
    groups,
    items,
    lifecycle,
    operators,
    owners,
    purchases,
    records,
    settings,
    tags,
)
from hirdir.ids import new_hid
from hirdir.io import balance

ROOT = Path(__file__).resolve().parent.parent
FOLDER = ROOT / "fixture-data"
FACTS = "fixture.json"
CONFIG = '[server]\nstate_dir = "."\nlisten = "127.0.0.1:8726"\n'
SEED = audit.SYSTEM
# What is written in bulk is written as an import of a file would write it.
IMPORTED = replace(SEED, via="import")
DOMAIN = "example.net"
MAIL = "example.com"
ITEMS = 50_000
LEAST = 200
# The account the timing signs in with, made in the fixture's database and nowhere else.
USERNAME = "timing"
ACCESS_CODE = "timing-viewer-code"
CHUNK = 2_000


# --- choosing, the same way every time ------------------------------------------------


class Dice:
    """Choices made by a hash of a seed and a key: the same key always chooses the same."""

    def __init__(self, seed: str) -> None:
        self.seed = seed

    def share(self, *key: object) -> float:
        """Return a number from 0 up to 1 for the key."""
        text = ":".join(str(part) for part in (self.seed, *key))
        digest = hashlib.blake2b(text.encode(), digest_size=8).digest()
        return int.from_bytes(digest) / 2**64

    def chance(self, odds: float, *key: object) -> bool:
        """Say yes for about that share of keys."""
        return self.share(*key) < odds

    def between(self, low: int, high: int, *key: object) -> int:
        """Return a whole number from low to high, both included."""
        return low + int(self.share(*key) * (high - low + 1))

    def pick[T](self, choices: Sequence[T], *key: object) -> T:
        """Return one of the choices."""
        return choices[int(self.share(*key) * len(choices))]

    def weighted[T](self, pairs: Sequence[tuple[T, float]], *key: object) -> T:
        """Return one of the choices, each as often as its weight."""
        point = self.share(*key) * sum(weight for _, weight in pairs)
        for choice, weight in pairs:
            point -= weight
            if point < 0:
                return choice
        return pairs[-1][0]


def apportion(total: int, shares: Sequence[tuple[str, float]]) -> dict[str, int]:
    """Split a total by shares into whole numbers that add up to it exactly."""
    whole = sum(weight for _, weight in shares)
    exact = [(name, total * weight / whole) for name, weight in shares]
    counts = {name: int(value) for name, value in exact}
    left = total - sum(counts.values())
    by_remainder = sorted(exact, key=lambda pair: pair[1] - int(pair[1]), reverse=True)
    for name, _ in by_remainder[:left]:
        counts[name] += 1
    return counts


# --- what the inventory is made of ----------------------------------------------------


@dataclass(frozen=True)
class Shape:
    """How many of each there are, for an inventory of a number of items."""

    items: int

    def scaled(self, at_full: int, least: int) -> int:
        """Return a count that is at_full for 50,000 items, and in step for fewer."""
        return max(least, round(at_full * self.items / ITEMS))

    @property
    def kinds(self) -> dict[str, int]:
        """Return how many items there are of each use, and how many minor items."""
        major = round(self.items * 0.30)
        phones = round(self.items * 0.44)
        counts = apportion(major, NETWORK_SHARES)
        counts["phone"] = phones
        counts["minor"] = self.items - major - phones
        return counts

    @property
    def sites(self) -> int:
        return self.scaled(120, 2)

    @property
    def stacks(self) -> int:
        return self.scaled(360, 2)

    @property
    def clusters(self) -> int:
        return self.scaled(80, 1)

    @property
    def domains(self) -> int:
        return self.scaled(30, 1)

    @property
    def agreements(self) -> int:
        return self.scaled(24, 6)

    @property
    def contracts(self) -> int:
        return self.scaled(320, 24)

    @property
    def owners(self) -> int:
        return self.scaled(40, 6)


# The major items that are not phones, by use.
NETWORK_SHARES = (
    ("switch", 0.39),
    ("router", 0.045),
    ("firewall", 0.02),
    ("controller", 0.004),
    ("ap", 0.50),
    ("server", 0.026),
    ("chassis", 0.015),
)
MAJOR_USES = (*(use for use, _ in NETWORK_SHARES), "phone")
VENDORS = (
    ("Cisco", ["Cisco Systems"], None),
    ("Juniper", ["Juniper Networks"], None),
    ("Aruba", ["HPE Aruba Networking"], None),
    ("Palo Alto Networks", ["PAN"], None),
    ("Dell", ["Dell Technologies"], None),
    ("Poly", ["Polycom"], None),
    ("Example Reseller", [], "A fictional reseller of hardware and support"),
    ("Example Integrator", [], "A fictional integrator that resells support"),
)
RESELLERS = ("Example Reseller", "Example Integrator")
# The models, by use and type: vendor, PID, model name, function, value, support weight,
# and annual support cost. A part has neither a weight nor a cost of its own.
FAMILIES: tuple[tuple[str, str, tuple[tuple[str, str, str, str, int, str, int], ...]], ...] = (
    (
        "switch",
        "switch",
        (
            ("Cisco", "C9300-48P", "Catalyst 9300 48-port PoE+", "access", 18000, "1", 1450),
            ("Cisco", "C9300-24P", "Catalyst 9300 24-port PoE+", "access", 12000, "1", 980),
            ("Cisco", "C9200L-48P-4G", "Catalyst 9200L 48-port PoE+", "access", 6500, "1", 520),
            ("Cisco", "C9200L-24P-4G", "Catalyst 9200L 24-port PoE+", "access", 4300, "1", 360),
            ("Cisco", "C9500-24Y4C", "Catalyst 9500 24-port 25G", "core", 42000, "2.5", 3900),
            ("Cisco", "C9500-48Y4C", "Catalyst 9500 48-port 25G", "core", 61000, "2.5", 5200),
            ("Juniper", "EX4300-48P", "EX4300 48-port PoE+", "access", 14000, "1", 1100),
            ("Juniper", "EX2300-48P", "EX2300 48-port PoE+", "access", 5200, "1", 430),
            ("Juniper", "EX4650-48Y", "EX4650 48-port 25G", "aggregation", 38000, "2", 3100),
            ("Aruba", "CX-6300M-48", "CX 6300M 48-port", "access", 11000, "1", 900),
            ("Aruba", "CX-6200F-48", "CX 6200F 48-port", "access", 5900, "1", 480),
        ),
    ),
    (
        "router",
        "router",
        (
            ("Cisco", "ISR4331/K9", "ISR 4331", "wan", 9500, "1.5", 800),
            ("Cisco", "ISR4451-X/K9", "ISR 4451", "wan", 24000, "2", 1900),
            ("Cisco", "C8300-1N1S-6T", "Catalyst 8300", "edge", 21000, "2", 1700),
            ("Cisco", "ASR1001-X", "ASR 1001-X", "edge", 38000, "2.5", 3000),
            ("Juniper", "MX204", "MX204", "edge", 52000, "3", 4400),
        ),
    ),
    (
        "firewall",
        "firewall",
        (
            ("Palo Alto Networks", "PA-3220", "PA-3220", "security", 46000, "2", 6100),
            ("Palo Alto Networks", "PA-5220", "PA-5220", "security", 120000, "3", 14500),
            ("Palo Alto Networks", "PA-440", "PA-440", "security", 4100, "1", 700),
            ("Juniper", "SRX345", "SRX345", "security", 6400, "1.5", 900),
            ("Cisco", "FPR2130-NGFW-K9", "Firepower 2130", "security", 31000, "2", 4200),
        ),
    ),
    (
        "controller",
        "wireless-controller",
        (
            ("Cisco", "C9800-40-K9", "Catalyst 9800-40", "wireless", 33000, "2", 2600),
            ("Cisco", "C9800-L-C-K9", "Catalyst 9800-L", "wireless", 9000, "1.5", 800),
            ("Aruba", "7210", "7210 Mobility Controller", "wireless", 21000, "2", 1800),
        ),
    ),
    (
        "ap",
        "access-point",
        (
            ("Cisco", "C9120AXI-B", "Catalyst 9120AX", "wireless", 1300, "0.2", 90),
            ("Cisco", "C9130AXI-B", "Catalyst 9130AX", "wireless", 1800, "0.2", 120),
            ("Cisco", "C9136I-B", "Catalyst 9136", "wireless", 2400, "0.2", 160),
            ("Aruba", "AP-515", "AP-515", "wireless", 1100, "0.2", 80),
            ("Aruba", "AP-535", "AP-535", "wireless", 1600, "0.2", 110),
        ),
    ),
    (
        "server",
        "server",
        (
            ("Dell", "R650", "PowerEdge R650", "management", 9800, "1", 700),
            ("Dell", "R750", "PowerEdge R750", "management", 14500, "1", 950),
        ),
    ),
    (
        "chassis",
        "chassis",
        (
            ("Cisco", "C9410R", "Catalyst 9410R", "core", 28000, "3", 2400),
            ("Cisco", "C9407R", "Catalyst 9407R", "aggregation", 21000, "3", 1900),
            ("Juniper", "EX9208", "EX9208", "core", 35000, "3", 2900),
        ),
    ),
    (
        "phone",
        "phone",
        (
            ("Cisco", "CP-8841-K9", "IP Phone 8841", "voice", 260, "0.05", 12),
            ("Cisco", "CP-8851-K9", "IP Phone 8851", "voice", 330, "0.05", 14),
            ("Cisco", "CP-7841-K9", "IP Phone 7841", "voice", 190, "0.05", 10),
            ("Cisco", "CP-8865-K9", "IP Phone 8865", "voice", 520, "0.05", 18),
            ("Poly", "VVX-450", "VVX 450", "voice", 240, "0.05", 11),
            ("Poly", "CCX-500", "CCX 500", "voice", 380, "0.05", 15),
        ),
    ),
    (
        "psu",
        "power-supply",
        (
            ("Cisco", "PWR-C1-715WAC", "715W AC power supply", "access", 900, "", 0),
            ("Cisco", "C9400-PWR-3200AC", "3200W AC power supply", "core", 1800, "", 0),
            ("Juniper", "JPSU-350-AC-AFO", "350W AC power supply", "access", 600, "", 0),
            ("Aruba", "PSU-CX-680W", "680W power supply", "access", 700, "", 0),
            (
                "Palo Alto Networks",
                "PAN-PSU-650W-AC",
                "650W AC power supply",
                "security",
                800,
                "",
                0,
            ),
            ("Dell", "PSU-800W", "800W power supply", "management", 400, "", 0),
        ),
    ),
    (
        "module",
        "module",
        (
            ("Cisco", "C9300-NM-8X", "8 x 10G uplink module", "access", 1500, "", 0),
            ("Cisco", "NIM-2GE-CU-SFP", "2-port GE network interface module", "wan", 1100, "", 0),
            ("Juniper", "EX-UM-4X4SFP", "4-port SFP+ uplink module", "access", 900, "", 0),
        ),
    ),
    (
        "linecard",
        "line-card",
        (
            ("Cisco", "C9400-LC-48P", "48-port PoE line card", "core", 7200, "", 0),
            ("Juniper", "EX9200-40T", "40-port line card", "core", 6400, "", 0),
        ),
    ),
    (
        "optic",
        "module",
        (
            ("Cisco", "SFP-10G-SR", "10GBASE-SR SFP+", "access", 300, "", 0),
            ("Juniper", "EX-SFP-10GE-SR", "10GBASE-SR SFP+", "access", 280, "", 0),
        ),
    ),
)
VARIANTS = 6
# Which maker makes how many of the items of a use.
MAKERS: dict[str, tuple[tuple[str, float], ...]] = {
    "switch": (("Cisco", 60), ("Juniper", 25), ("Aruba", 15)),
    "router": (("Cisco", 75), ("Juniper", 25)),
    "firewall": (("Palo Alto Networks", 70), ("Juniper", 15), ("Cisco", 15)),
    "controller": (("Cisco", 70), ("Aruba", 30)),
    "ap": (("Cisco", 65), ("Aruba", 35)),
    "server": (("Dell", 100),),
    "chassis": (("Cisco", 80), ("Juniper", 20)),
    "phone": (("Cisco", 75), ("Poly", 25)),
}
# What is put in a major item of each use: the use of the minor item, how many at most,
# and how its place in the item is named. An optic goes one level further down, in a
# module or a line card.
INSIDE: dict[str, tuple[tuple[str, int, str], ...]] = {
    "chassis": (("psu", 4, "PS"), ("linecard", 6, "slot ")),
    "router": (("psu", 2, "PS"), ("module", 2, "NIM ")),
    "firewall": (("psu", 2, "PS"),),
    "server": (("psu", 2, "PSU "),),
    "switch": (("psu", 2, "PS"), ("module", 1, "NM ")),
    "controller": (("psu", 2, "PS"),),
}
OPTICS_IN = {"linecard": 4, "module": 4}
# The lifecycle state of a major item, and how often it is in it.
STATES = (
    ("Prod", 80.0),
    ("Assigned", 3.0),
    ("Test", 1.0),
    ("Down", 1.0),
    ("Delivered", 2.0),
    ("Purchased", 1.0),
    ("Pending-Removal", 3.0),
    ("Released", 4.0),
    ("Archived", 5.0),
)
LEFT = ("Released", "Archived")
REASONS = {
    "Prod": "deployed",
    "Assigned": "staged",
    "Test": "staged",
    "Down": "maintenance",
    "Delivered": "received",
    "Pending-Removal": "decommissioned",
    "Released": "returned",
    "Archived": "disposed",
}
TAGS = (
    ("critical", "#d1242f", "An outage here is felt at once"),
    ("lab", "#8250df", "Not in service: for trying things out"),
    ("refresh-2028", "#bf8700", "Planned for replacement in 2028"),
    ("refresh-2030", "#1f6feb", "Planned for replacement in 2030"),
    ("pci", "#0e8a16", "In the scope of a card-data audit"),
)
REGIONS = (
    ("Americas", "AM", ("North", "South", "East", "West")),
    ("Europe", "EU", ("North", "South", "Central", "West")),
    ("Asia Pacific", "AP", ("North", "South", "East", "Oceania")),
)
TEAMS = (
    "Network Engineering",
    "Voice Services",
    "Wireless Engineering",
    "Data Center Operations",
    "Security Operations",
    "Field Services",
)
TEAM_OF = {
    "phone": "Voice Services",
    "ap": "Wireless Engineering",
    "controller": "Wireless Engineering",
    "server": "Data Center Operations",
    "firewall": "Security Operations",
}
SHORT = {"switch": "sw", "router": "rtr", "firewall": "fw", "controller": "wlc"}


# --- the small records, made through the rules -------------------------------------------


@dataclass
class Place:
    """A site and the locations in it, by what they are for."""

    hid: str
    code: str
    weight: float
    region: int
    floors: list[str] = field(default_factory=list)
    rooms: list[str] = field(default_factory=list)
    racks: list[str] = field(default_factory=list)
    store: str | None = None


@dataclass
class Made:
    """What the rules made, for the items to refer to."""

    entries: dict[str, list[str]]
    maker_of: dict[str, str]
    places: list[Place]
    owners: list[tuple[str, float]]
    team_owner: dict[str, str]
    operators: list[str]
    tags: dict[str, str]
    contracts: dict[str, list[Contract]]
    spans: dict[str, contracts.Span]
    # The models that are not to be renewed.
    flagged: set[str] = field(default_factory=set)


def _catalog(
    db: Session, dice: Dice
) -> tuple[dict[str, str], dict[str, list[str]], dict[str, str], set[str]]:
    vendors = {
        name: catalog.create_vendor(
            db, SEED, {"name": name, "aliases": aliases, "notes": notes}
        ).hid
        for name, aliases, notes in VENDORS
    }
    entries: dict[str, list[str]] = defaultdict(list)
    maker_of: dict[str, str] = {}
    flagged: set[str] = set()
    today = clock.today()
    for use, type_, models in FAMILIES:
        for vendor, pid, model, function, value, weight, cost in models:
            for variant in range(VARIANTS):
                fields: dict[str, Any] = {
                    "vendor_hid": vendors[vendor],
                    "pid": pid if variant == 0 else f"{pid}-V{variant:02d}",
                    "model_name": model if variant == 0 else f"{model}, variant {variant:02d}",
                    "type": type_,
                    "function": function,
                    "est_value": Decimal(value + 100 * variant),
                    "support_weight": Decimal(weight) if weight else None,
                    "annual_support_cost": Decimal(cost) if cost else None,
                }
                if dice.chance(0.35, "old", pid, variant):
                    # An older model: no longer sold, and supported for some years more.
                    gone = today - timedelta(days=dice.between(100, 1500, "eos", pid, variant))
                    fields["end_of_sale"] = gone
                    fields["end_of_sw_support"] = gone + timedelta(days=3 * 365)
                    fields["end_of_hw_support"] = gone + timedelta(days=5 * 365)
                    fields["ldos"] = gone + timedelta(days=5 * 365)
                    # Some of the older models are to be let go: their support is not
                    # to be renewed.
                    if dice.chance(0.25, "not renewed", pid, variant):
                        fields["do_not_renew"] = True
                entry = catalog.create_entry(db, SEED, fields)
                entries[f"{vendor}/{use}"].append(entry.hid)
                maker_of[entry.hid] = vendor
                if fields.get("do_not_renew"):
                    flagged.add(entry.hid)
    return vendors, entries, maker_of, flagged


def _location(
    db: Session, site_hid: str, name: str, code: str, kind: str, parent: str | None = None
) -> str:
    fields = {
        "name": name,
        "code": code,
        "kind": kind,
        "site_hid": site_hid,
        "parent_location_hid": parent,
    }
    return geography.create_place(db, SEED, geography.LOCATION, fields).hid


def _places(db: Session, dice: Dice, shape: Shape) -> list[Place]:
    regions: list[str] = []
    for name, code, parts in REGIONS:
        top = geography.create_place(db, SEED, geography.REGION, {"name": name, "code": code})
        for part in parts:
            below = geography.create_place(
                db,
                SEED,
                geography.REGION,
                {"name": part, "code": f"{code}-{part[:2].upper()}", "parent_region_hid": top.hid},
            )
            regions.append(below.hid)
    places = []
    for number in range(1, shape.sites + 1):
        region = (number - 1) % len(regions)
        code = f"S{number:03d}"
        site = geography.create_place(
            db,
            SEED,
            geography.SITE,
            {"name": f"Site {number:03d}", "code": code, "region_hid": regions[region]},
        )
        # A few large campuses, and many small offices.
        place = Place(site.hid, code, 1 + 12 * dice.share("size", number) ** 4, region)
        for building in range(1, dice.between(1, 3, "buildings", number) + 1):
            house = _location(db, site.hid, f"Building {building}", f"B{building}", "building")
            if building == 1:
                core = _location(db, site.hid, "MDF", "B1-MDF", "room", house)
                for rack in range(1, dice.between(2, 6, "racks", number) + 1):
                    place.racks.append(
                        _location(db, site.hid, f"Rack {rack}", f"B1-MDF-R{rack}", "rack", core)
                    )
            for floor in range(1, dice.between(1, 4, "floors", number, building) + 1):
                code = f"B{building}-F{floor}"
                level = _location(db, site.hid, f"Floor {floor}", code, "floor", house)
                place.floors.append(level)
                place.rooms.append(
                    _location(db, site.hid, f"IDF {building}{floor}", f"{code}-IDF", "room", level)
                )
        if dice.chance(0.35, "store", number):
            place.store = _location(db, site.hid, "Store room", "STORE", "warehouse")
        places.append(place)
    return places


def _owners(
    db: Session, dice: Dice, shape: Shape
) -> tuple[list[tuple[str, float]], dict[str, str]]:
    team_owner: dict[str, str] = {}
    weighted: list[tuple[str, float]] = []
    for number in range(shape.owners):
        unit = number - len(TEAMS) + 1
        label = TEAMS[number] if number < len(TEAMS) else f"Business Unit {unit:02d}"
        outside = number >= len(TEAMS) and dice.chance(0.15, "external", number)
        owner = owners.create_owner(
            db,
            SEED,
            {
                "label": label,
                "organization": "Example Corp",
                "is_external": outside,
                "exception_reason": "Run by the business unit's own staff" if outside else None,
            },
        )
        if number < len(TEAMS):
            team_owner[label] = owner.hid
        weighted.append((owner.hid, 30.0 if number == 0 else 1.0))
    return weighted, team_owner


def _operators(db: Session, dice: Dice, places: list[Place]) -> list[str]:
    """Make the operators, and give one to some of the sites."""
    marks = []
    for number in range(1, 13):
        person = contacts.create_contact(
            db,
            SEED,
            {"name": f"Operator {number:02d}", "email": f"operator{number:02d}@{MAIL}"},
        )
        fields = {
            "label": f"OPS-{number:02d}",
            "description": "A member of the field team",
            # Some are open: nobody is behind the label at the moment.
            "contact_hid": person.hid if number % 5 else None,
        }
        marks.append(operators.create_operator(db, SEED, fields).hid)
    for place in places:
        if dice.chance(0.4, "site operator", place.code):
            site = geography.get_site(db, place.hid)
            geography.update_place(
                db,
                SEED,
                geography.SITE,
                site.hid,
                site.row_version,
                {"operator_hid": dice.pick(marks, "operator", place.code)},
            )
    return marks


def _agreements(db: Session, dice: Dice, shape: Shape, vendors: dict[str, str]) -> list[Any]:
    """Make the agreements: most running, some lapsed, pending renewal or renewed ahead."""
    today = clock.today()
    makers = ("Cisco", "Cisco", "Cisco", "Juniper", "Aruba", "Palo Alto Networks", "Dell")
    made = []
    for number in range(1, shape.agreements + 1):
        vendor = makers[(number - 1) % len(makers)]
        starts = today - timedelta(days=dice.between(120, 900, "agreement start", number))
        ends = starts + timedelta(days=3 * 365 - 1)
        status = "active"
        if number % 9 == 3:
            # Lapsed: its period is over and nobody has said what happened.
            ends = today - timedelta(days=dice.between(5, 60, "lapsed", number))
            starts = ends - timedelta(days=3 * 365 - 1)
        elif number % 9 == 6:
            status = "renewal_pending"
            ends = today - timedelta(days=dice.between(1, 40, "pending", number))
            starts = ends - timedelta(days=3 * 365 - 1)
        agreement = contracts.create_agreement(
            db,
            SEED,
            {
                "name": f"{vendor} Enterprise Agreement {number:02d}",
                "number": f"EA-{number:05d}",
                "vendor_hid": vendors[vendor],
                "starts_on": starts,
                "ends_on": ends,
                "status": status,
                "support_level": "24x7x4",
                "account_manager": f"account.manager{number:02d}@{MAIL}",
                "support_contact": f"support@{MAIL}",
                "annual_cost": Decimal(dice.between(50, 900, "agreement cost", number) * 1000),
            },
        )
        if number % 9 == 1 and ends > today:
            # Renewed ahead: the next term is entered and begins when this one ends.
            contracts.renew_agreement(
                db,
                SEED,
                agreement.hid,
                agreement.row_version,
                {
                    "number": f"EA-{number + 500:05d}",
                    "starts_on": ends + timedelta(days=1),
                    "ends_on": ends + timedelta(days=3 * 365),
                },
            )
        made.append(agreement)
    return made


CONTRACT_MAKERS = (
    ("Cisco", 45.0),
    ("Juniper", 15.0),
    ("Aruba", 10.0),
    ("Palo Alto Networks", 10.0),
    ("Dell", 8.0),
    ("Poly", 5.0),
)


def _contract_fields(
    dice: Dice, number: int, vendor: str, agreement: Any | None, vendors: dict[str, str]
) -> dict[str, Any]:
    """Return what one contract is made with: its dates, its status and any next term."""
    today = clock.today()
    fields: dict[str, Any] = {
        "number": f"CN-{number:06d}",
        "vendor_hid": vendor,
        "agreement_hid": agreement.hid if agreement is not None else None,
        "annual_cost": Decimal(dice.between(2, 400, "cost", number) * 500),
        "purchase_reference": f"RITM{number:07d}",
        "support_level": dice.pick(("8x5xNBD", "24x7x4", "24x7x2"), "level", number),
    }
    if dice.chance(0.25, "resold", number):
        fields["reseller_hid"] = vendors[dice.pick(RESELLERS, "reseller", number)]
    # Most in an agreement take its period: they are co-termed with it.
    co_termed = agreement is not None and dice.chance(0.6, "co-termed", number)
    starts = today - timedelta(days=dice.between(30, 700, "start", number))
    ends = starts + timedelta(days=dice.pick((365, 730, 1095), "length", number) - 1)
    if ends < today:
        ends = today + timedelta(days=dice.between(10, 700, "end", number))
    roll = dice.share("status", number)
    if roll < 0.06:
        # Lapsed: still said to be active, and its period has ended.
        ends = today - timedelta(days=dice.between(1, 90, "lapsed", number))
        co_termed = False
    elif roll < 0.13:
        fields["status"] = "renewal_pending"
        ends = today - timedelta(days=dice.between(1, 120, "pending", number))
        co_termed = False
    elif roll < 0.17:
        fields["status"] = "expired"
        ends = today - timedelta(days=dice.between(30, 400, "expired", number))
        co_termed = False
    elif roll < 0.19:
        fields["status"] = "cancelled"
    elif roll < 0.21:
        # Bought, and not begun.
        fields["status"] = "pending"
        starts = today + timedelta(days=dice.between(5, 90, "begins", number))
        ends = starts + timedelta(days=364)
        co_termed = False
    elif roll < 0.33:
        # Renewed ahead: the next term waits for its period. For some of them that
        # period has begun since, and the next term is the one in force.
        begins = ends + timedelta(days=1)
        if roll < 0.24:
            begins = today - timedelta(days=dice.between(1, 60, "began", number))
            ends = begins - timedelta(days=1)
            starts = min(starts, ends - timedelta(days=364))
        fields["next_number"] = f"CN-{number + 500_000:06d}"
        fields["next_starts_on"] = begins
        fields["next_ends_on"] = begins + timedelta(days=364)
        co_termed = False
    elif agreement is not None and not co_termed and dice.chance(0.3, "let go", number):
        # The team marked it not to renew: it ends with its present term, soon (P-129).
        fields["ends_with_term"] = True
        ends = today + timedelta(days=dice.between(5, 200, "let go on", number))
    elif co_termed and dice.chance(0.15, "to review", number):
        # It shares its agreement's period and still says what it said before the
        # agreement was renewed: a person is to look at it.
        fields["status"] = dice.pick(contracts.ENDED_BY_A_TERM, "review status", number)
    if starts > ends:
        starts = ends - timedelta(days=364)
    if not co_termed:
        fields["starts_on"], fields["ends_on"] = starts, ends
    return fields


def _contracts(
    db: Session, dice: Dice, shape: Shape, vendors: dict[str, str]
) -> dict[str, list[Contract]]:
    """Make the contracts, in their agreements and by themselves, in every status."""
    by_vendor: dict[str, list[Any]] = defaultdict(list)
    for agreement in _agreements(db, dice, shape, vendors):
        by_vendor[agreement.vendor_hid].append(agreement)
    made: dict[str, list[Contract]] = defaultdict(list)
    for number in range(1, shape.contracts + 1):
        maker = dice.weighted(CONTRACT_MAKERS, "contract vendor", number)
        within = by_vendor.get(vendors[maker], [])
        agreement = (
            dice.pick(within, "agreement", number)
            if within and dice.chance(0.6, "in agreement", number)
            else None
        )
        fields = _contract_fields(dice, number, vendors[maker], agreement, vendors)
        contract = contracts.create_contract(db, SEED, fields)
        if dice.chance(0.015, "retired", number):
            contracts.retire_contract(db, SEED, contract.hid, contract.row_version)
        made[maker].append(contract)
    return made


def build_small(db: Session, dice: Dice, shape: Shape) -> Made:
    """Make what there are few of, through the rules."""
    vendors, entries, maker_of, flagged = _catalog(db, dice)
    places = _places(db, dice, shape)
    weighted, team_owner = _owners(db, dice, shape)
    marks = _operators(db, dice, places)
    labels = {
        label: tags.create_tag(
            db, SEED, {"label": label, "colour": colour, "description": description}
        ).hid
        for label, colour, description in TAGS
    }
    made = _contracts(db, dice, shape, vendors)
    today = clock.today()
    spans = {
        contract.hid: contracts.period(contract, today)
        for listed in made.values()
        for contract in listed
    }
    db.flush()
    return Made(
        entries, maker_of, places, weighted, team_owner, marks, labels, made, spans, flagged
    )


# --- the items, written in bulk ------------------------------------------------------------


@dataclass
class Planned:
    """One item as it is to be written, with what is to be done with it after."""

    row: dict[str, Any]
    use: str
    place: Place
    labels: list[str] = field(default_factory=list)
    left_on: date | None = None
    retired: bool = False
    group: str | None = None
    depth: int = 0


class Writer:
    """Rows written in bulk, with the audit events the rules would have written."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.events: list[dict[str, Any]] = []
        self.now = clock.now()

    def event(self, action: str, record_type: str, hid: str, changes: list[dict[str, Any]]) -> None:
        self.events.append(
            {
                "hid": new_hid(),
                "at": self.now,
                "actor_hid": IMPORTED.actor_hid,
                "via": IMPORTED.via,
                "request_id": "",
                "action": action,
                "record_type": record_type,
                "record_hid": hid,
                "changes": changes,
            }
        )

    def created(
        self,
        record_type: str,
        row: dict[str, Any],
        names: Sequence[str],
        more: Sequence[dict[str, Any]] = (),
    ) -> None:
        """Audit the creation of a row, with every field that was given a value."""
        given = [
            audit.change(name, None, records.jsonable(row[name], name))
            for name in names
            if row.get(name) not in (None, [], "")
        ]
        self.event("create", record_type, row["hid"], [*given, *more])

    def write(self, model: Any, rows: Sequence[dict[str, Any]]) -> None:
        for start in range(0, len(rows), CHUNK):
            self.db.execute(insert(model), list(rows[start : start + CHUNK]))

    def write_events(self) -> None:
        self.write(AuditEvent, self.events)
        self.events = []


def bookkeeping(now: datetime, version: int = 1) -> dict[str, Any]:
    """Return the columns every editable row has, as a change made now sets them."""
    return {
        "created_at": now,
        "updated_at": now,
        "created_by": IMPORTED.actor_hid,
        "updated_by": IMPORTED.actor_hid,
        "row_version": version,
    }


def _blank_item(now: datetime) -> dict[str, Any]:
    row: dict[str, Any] = {column.key: None for column in Item.__table__.columns}
    row.update(hid=new_hid(), quantity=1, record_status="active", **bookkeeping(now))
    return row


def _major(
    dice: Dice,
    made: Made,
    rules: dict[str, LifecycleRule],
    use: str,
    number: int,
    serial: int,
    now: datetime,
) -> Planned:
    """Return one major item of a use."""
    today = now.date()
    place = dice.weighted([(one, one.weight) for one in made.places], "site", use, number)
    maker = dice.weighted(MAKERS[use], "maker", use, number)
    state = dice.weighted(STATES, "state", use, number)
    row = _blank_item(now)
    row["catalog_entry_hid"] = dice.pick(made.entries[f"{maker}/{use}"], "model", use, number)
    row["serial_number"] = f"EXA{serial:07d}"
    row["serial_key"] = records.key(row["serial_number"])
    short = SHORT.get(use, use)
    if use == "phone":
        row["mac_address"] = f"025e{serial:08x}"
        row["hostname"] = f"SEP{row['mac_address'].upper()}"
    else:
        row["hostname"] = f"{place.code.lower()}-{short}-{number:05d}"
        row["fqdn"] = f"{row['hostname']}.{DOMAIN}"
        if use == "ap":
            row["mac_address"] = f"025e{serial:08x}"
        if dice.chance(0.2, "named", use, number):
            row["name"] = f"{place.code} {short.upper()} {number:05d}"
    if dice.chance(0.2 if use == "phone" else 0.75, "tagged", use, number):
        row["asset_tag"] = f"AT-{serial:07d}"
        row["asset_tag_key"] = records.key(row["asset_tag"])
    where = {"ap": place.floors, "phone": place.floors, "switch": place.rooms + place.racks}
    row["location_hid"] = dice.pick(where.get(use, place.racks), "where", use, number)
    if state in ("Purchased", "Delivered"):
        # Not in use yet: on the shelf, if the site has one, and going where it will be.
        row["planned_location_hid"] = row["location_hid"]
        row["location_hid"] = place.store
    if dice.chance(0.9, "owned", use, number):
        row["owner_hid"] = (
            made.team_owner[TEAM_OF.get(use, TEAMS[0])]
            if dice.chance(0.8, "team", use, number)
            else dice.weighted(made.owners, "owner", use, number)
        )
    if dice.chance(0.03, "operator", use, number):
        row["operator_hid"] = dice.pick(made.operators, "which operator", use, number)
    bought = today - timedelta(days=dice.between(40, 2600, "bought", use, number))
    row["procured_on"] = bought
    if state != "Purchased":
        row["delivered_on"] = bought + timedelta(days=dice.between(5, 30, "delivered", number))
        row["warranty_start"] = row["delivered_on"]
        row["warranty_end"] = row["delivered_on"] + timedelta(days=365 * (1 + number % 3))
    if state not in ("Purchased", "Delivered", "Assigned"):
        row["in_service_on"] = row["delivered_on"] + timedelta(
            days=dice.between(3, 9, "in", number)
        )
    row["lifecycle_state"] = state
    row["disposition"], row["expected_online"] = lifecycle.entry_standing(rules[state], None)
    row["state_reason"] = REASONS.get(state)
    row["state_changed_at"] = now
    if use != "phone" and state == "Prod" and dice.chance(0.6, "observed", use, number):
        row["observed_status"] = dice.weighted(
            (("online", 97.0), ("degraded", 1.5), ("unreachable", 1.5)), "seen", use, number
        )
        row["observed_at"] = now - timedelta(minutes=dice.between(1, 600, "seen at", number))
    if dice.chance(0.1, "condition", use, number):
        row["condition"] = dice.weighted(
            (("good", 90.0), ("degraded", 4.0), ("suspect", 3.0), ("failed", 3.0)),
            "how",
            use,
            number,
        )
    if dice.chance(0.04, "override", use, number):
        row["ldos"] = today + timedelta(days=dice.between(200, 2500, "own ldos", number))
    # An item's own word on renewing its support, against its model's: one to be let go
    # of a model that is renewed, or one to be kept of a model that is not.
    flagged = row["catalog_entry_hid"] in made.flagged
    if dice.chance(0.15 if flagged else 0.01, "own flag", use, number):
        row["do_not_renew"] = not flagged
    if state == "Purchased" and dice.chance(0.1, "draft", use, number):
        row["record_status"] = "draft"
    planned = Planned(row, use, place)
    if state in (*LEFT, "Pending-Removal"):
        # The day it left service, which its coverage ended on.
        planned.left_on = today - timedelta(days=dice.between(1, 540, "left", use, number))
    planned.retired = state in LEFT and dice.chance(0.2, "retired", use, number)
    if dice.chance(0.06, "labels", use, number):
        planned.labels = [dice.pick(sorted(made.tags), "label", use, number)]
    return planned


def _minor(
    dice: Dice,
    choices: Sequence[str],
    parent: Planned,
    use: str,
    position: str,
    serial: int,
    now: datetime,
) -> Planned:
    """Return one minor item in another. Most have the standing of the item above."""
    row = _blank_item(now)
    row.update(
        catalog_entry_hid=dice.pick(choices, "part model", use, serial),
        serial_number=f"EXB{serial:07d}",
        parent_item_hid=parent.row["hid"],
        position=position,
        procured_on=parent.row["procured_on"],
    )
    row["serial_key"] = records.key(row["serial_number"])
    if parent.row["lifecycle_state"] == "Prod" and dice.chance(0.03, "failed part", serial):
        # A part that failed in an item in service: down, by a state of its own.
        row["lifecycle_state"] = "Down"
        row["state_reason"] = "rma"
        row["state_changed_at"] = now
        row["condition"] = "failed"
        row["expected_online"] = False
    return Planned(row, use, parent.place, depth=parent.depth + 1)


class Serials:
    """The next serial number to give."""

    def __init__(self, start: int) -> None:
        self.number = start

    def __next__(self) -> int:
        self.number += 1
        return self.number


def _parts(
    dice: Dice, made: Made, host: Planned, serials: Serials, now: datetime
) -> Iterator[Planned]:
    """Yield the minor items in a major item, and the optics in those."""
    maker = made.maker_of[host.row["catalog_entry_hid"]]
    optics = made.entries.get(f"{maker}/optic") or made.entries["Cisco/optic"]
    for use, most, label in INSIDE[host.use]:
        choices = made.entries.get(f"{maker}/{use}") or made.entries[f"Cisco/{use}"]
        for slot in range(1, dice.between(1, most, "count", use, host.row["hid"]) + 1):
            part = _minor(dice, choices, host, use, f"{label}{slot}", next(serials), now)
            yield part
            for port in range(
                1, dice.between(0, OPTICS_IN.get(use, 0), "optics", slot, part.row["hid"]) + 1
            ):
                yield _minor(dice, optics, part, "optic", f"port {port}", next(serials), now)


def plan_items(
    dice: Dice, made: Made, shape: Shape, rules: dict[str, LifecycleRule], now: datetime
) -> list[Planned]:
    """Return every item to be made: the major ones, then what is in them."""
    kinds = shape.kinds
    planned: list[Planned] = []
    serials = Serials(0)
    for use in MAJOR_USES:
        for number in range(1, kinds[use] + 1):
            planned.append(_major(dice, made, rules, use, number, next(serials), now))
    # Which items have parts in them, in an order that is the same every time.
    hosts = sorted(
        (one for one in planned if one.use in INSIDE),
        key=lambda one: dice.share("host", one.row["serial_number"]),
    )
    wanted = kinds["minor"]
    minor: list[Planned] = []
    serials = Serials(0)
    for host in hosts:
        for part in _parts(dice, made, host, serials, now):
            minor.append(part)
            if len(minor) == wanted:
                return planned + minor
    raise SystemExit("the major items have too few places for the minor items")


# --- purchase requests, made through the rules before the items arrive on them -------------


def plan_purchases(db: Session, dice: Dice, planned: list[Planned]) -> None:
    """Put many of the major items bought in the last two years on a line of a request.

    A site's purchases of a quarter are one request, with a line for each model. A line
    asked for what arrived on it, and some for a few more that are still to come; a
    request that has all it asked for is received. A few items are on the line of
    another model of the same request, as 0.6.0 let in.
    """
    today = clock.today()
    bought: dict[tuple[str, int], list[Planned]] = defaultdict(list)
    for one in planned:
        row = one.row
        days = (today - row["procured_on"]).days
        if one.depth or row["record_status"] != "active" or days > 730:
            continue
        if dice.chance(0.4, "on a line", row["serial_number"]):
            bought[one.place.hid, days // 91].append(one)
    for number, ((site, quarter), arrived) in enumerate(sorted(bought.items()), start=1):
        lines: dict[str, list[Planned]] = defaultdict(list)
        for one in arrived:
            lines[one.row["catalog_entry_hid"]].append(one)
        models = sorted(lines)
        for one in arrived if len(models) > 1 else []:
            if dice.chance(0.03, "wrong line", one.row["serial_number"]):
                own = one.row["catalog_entry_hid"]
                other = dice.pick([model for model in models if model != own], "other", own)
                lines[own].remove(one)
                lines[other].append(one)
        to_come = {
            model: dice.between(1, 3, "to come", number, model)
            if dice.chance(0.3, "more", number, model)
            else 0
            for model in models
        }
        request = purchases.create_request(
            db,
            SEED,
            {
                "reference": f"RITM{2_000_000 + number:07d}",
                "requested_on": min(one.row["procured_on"] for one in arrived) - timedelta(days=7),
                "status": "ordered" if any(to_come.values()) else "received",
                "notes": f"What one site bought in quarter {quarter}, counted back from today",
            },
        )
        for model in models:
            if not lines[model] and not to_come[model]:
                continue
            line = purchases.add_line(
                db,
                SEED,
                request.hid,
                {
                    "catalog_entry_hid": model,
                    "quantity": len(lines[model]) + to_come[model],
                    "destination_site_hid": site,
                    "expected_on": today + timedelta(days=30) if to_come[model] else None,
                },
            )
            for one in lines[model]:
                one.row["purchase_line_hid"] = line.hid
    db.flush()


# --- groups, made through the rules once the items are there ---------------------------------


def plan_groups(dice: Dice, planned: list[Planned], shape: Shape) -> list[dict[str, Any]]:
    """Return the stacks, clusters and controller domains, with the items in each.

    A member of a stack has the stack's place and owner half of the time, and none of
    its own.
    """
    serving = [
        one
        for one in planned
        if one.depth == 0
        and one.row["lifecycle_state"] == "Prod"
        and one.row["record_status"] == "active"
    ]
    by_site: dict[str, dict[str, list[Planned]]] = defaultdict(lambda: defaultdict(list))
    for one in serving:
        by_site[one.place.hid][one.use].append(one)
    sites = sorted(by_site, key=lambda hid: dice.share("group site", hid))
    made: list[dict[str, Any]] = []

    def take(use: str, how_many: int) -> Iterator[tuple[Place, list[Planned]]]:
        """Yield groups of free items of a use, a group from each site in turn."""
        taken, turn = 0, 0
        while taken < how_many:
            before = taken
            for number, hid in enumerate(sites):
                size = dice.between(2, 5, use, turn, number) if use == "switch" else 2
                free = [one for one in by_site[hid][use] if one.group is None][:size]
                if len(free) == size and taken < how_many:
                    for one in free:
                        one.group = use
                    taken += 1
                    yield free[0].place, free
            if taken == before:
                return
            turn += 1

    for number, (place, members) in enumerate(take("switch", shape.stacks), start=1):
        name = f"{place.code.lower()}-stk-{number:04d}"
        located, owned = members[0].row["location_hid"], members[0].row["owner_hid"]
        for one in members:
            if dice.chance(0.5, "follows", one.row["serial_number"]):
                one.row["location_hid"] = None
                one.row["owner_hid"] = None
        made.append(
            {
                "name": name,
                "type": "stack",
                "hostname": name,
                "fqdn": f"{name}.{DOMAIN}",
                "location_hid": located,
                "owner_hid": owned,
                "members": [
                    {
                        "item_hid": one.row["hid"],
                        "role": groups.MASTER if position == 1 else groups.PLAIN,
                        "position": position,
                        "joined_on": one.row["in_service_on"],
                    }
                    for position, one in enumerate(members, start=1)
                ],
            }
        )
    for number, (place, pair) in enumerate(take("firewall", shape.clusters), start=1):
        name = f"{place.code.lower()}-fwc-{number:03d}"
        made.append(
            {
                "name": name,
                "type": "cluster",
                "hostname": name,
                "location_hid": pair[0].row["location_hid"],
                "managed_as": "one",
                "members": [
                    {
                        "item_hid": one.row["hid"],
                        "role": role,
                        "joined_on": one.row["in_service_on"],
                    }
                    for role, one in zip(("active", "standby"), pair, strict=True)
                ],
            }
        )
    # A controller domain is the access points of some regions under one or two controllers.
    heads = [one for one in serving if one.use == "controller"]
    points = [
        one for one in serving if one.use == "ap" and dice.chance(0.7, "joined", one.row["hid"])
    ]
    domains = max(1, min(shape.domains, len(heads)))
    for number in range(domains):
        mine = [one for one in points if one.place.region % domains == number % domains]
        its_heads = heads[number::domains][:2]
        if not mine or not its_heads:
            continue
        points = [one for one in points if one.place.region % domains != number % domains]
        made.append(
            {
                "name": f"wireless-domain-{number + 1:02d}",
                "type": "controller_domain",
                "members": [
                    {
                        "item_hid": one.row["hid"],
                        "role": role,
                        "joined_on": one.row["in_service_on"],
                    }
                    for role, listed in (("controller", its_heads), ("endpoint", mine))
                    for one in listed
                ],
            }
        )
    return made


def make_groups(db: Session, planned_groups: list[dict[str, Any]]) -> None:
    """Make the groups through the rules, as many members at a time as one request may
    add."""
    at_once = settings.max_items(db)
    for fields in planned_groups:
        members = fields.pop("members")
        group = groups.create_group(db, SEED, fields)
        for start in range(0, len(members), at_once):
            groups.add_members(db, SEED, group.hid, members[start : start + at_once])


# --- the capacity of the operations team, made through the rules ---------------------------

# The staff lines of each region: the position, how many units one gives, and how many
# there are at most.
STAFF_LINES = (
    ("Network engineer", "1", 6),
    ("Senior network engineer", "1.8", 2),
    ("Junior network engineer", "0.6", 3),
)
# Other work that calls on the team beside the infrastructure: name, units, and whether
# it is only a draft, a what-if.
OTHER_WORK = (
    ("Site consolidation project", "1.5", False),
    ("Refresh 2028 planning", "0.8", False),
    ("Security audit remediation", "0.6", False),
    ("Data center move", "2", True),
)
WEEKS_RECORDED = 4


def make_capacity(db: Session, dice: Dice, places: list[Place]) -> None:
    """Make the capacity lines of the operations team, and record the balance of each of
    the last four weeks, as the server records it each Monday.

    Each top region has its staff lines. Partners and smart hands at a few sites add to
    them, an automation platform and a monitoring service multiply some of them, an
    assistant that would multiply them more is a draft, and a contract engineer's line
    has ended. Some lines began in the last weeks, so the weeks recorded differ.
    """
    today = clock.today()
    tops = db.scalars(
        select(Region).where(Region.parent_region_hid.is_(None)).order_by(Region.code_key)
    ).all()
    staff: dict[str, list[str]] = defaultdict(list)
    for region in tops:
        for name, each, most in STAFF_LINES:
            began = today - timedelta(days=dice.between(1, 4, "began", region.code, name) * 7)
            line = capacity.create_line(
                db,
                SEED,
                {
                    "side": capacity.SUPPLY,
                    "category": capacity.STAFF,
                    "name": f"{name}, {region.name}",
                    "quantity": Decimal(dice.between(1, most, "staff", region.code, name)),
                    "units_each": Decimal(each),
                    "region_hid": region.hid,
                    # Most were there before the weeks recorded; a few joined since.
                    "starts_on": began if dice.chance(0.3, "joined", region.code, name) else None,
                },
            )
            staff[name].append(line.hid)
    # Partners, by contract, and smart hands at the largest sites. The contract
    # engineer's line ended a month ago.
    adding: list[dict[str, Any]] = [
        {"category": "professional_services", "name": "Escalation partner", "cost": 48000},
        {
            "category": "professional_services",
            "name": "Contract engineer",
            "cost": 60000,
            "starts_on": today - timedelta(days=180),
            "ends_on": today - timedelta(days=30),
        },
    ]
    adding += [
        {
            "category": "smart_hands",
            "name": f"Smart hands, {place.code}",
            "cost": 9000,
            "units_each": Decimal("0.5"),
            "site_hid": place.hid,
        }
        for place in sorted(places, key=lambda one: -one.weight)[:6]
    ]
    for fields in adding:
        cost = Decimal(fields.pop("cost"))
        capacity.create_line(
            db,
            SEED,
            {"side": capacity.SUPPLY, "units_each": Decimal(1), "annual_cost": cost, **fields},
        )
    engineers = [*staff["Network engineer"], *staff["Senior network engineer"]]
    multiplying = (
        ("tools", "Automation platform", "1.25", "0.6", engineers, 17, "active"),
        ("services", "Monitoring service", "1.1", "1", staff["Network engineer"], None, "active"),
        ("services", "AI assistant", "1.15", "0.5", engineers, None, "draft"),
    )
    for category, name, factor, share, targets, days, status in multiplying:
        capacity.create_line(
            db,
            SEED,
            {
                "side": capacity.SUPPLY,
                "category": category,
                "name": name,
                "effect": capacity.MULTIPLY,
                "factor": Decimal(factor),
                "share": Decimal(share),
                "applies_to": targets,
                "annual_cost": Decimal(24000),
                "starts_on": None if days is None else today - timedelta(days=days),
                "record_status": status,
            },
        )
    for name, units, draft in OTHER_WORK:
        capacity.create_line(
            db,
            SEED,
            {
                "side": capacity.DEMAND,
                "name": name,
                "units_each": Decimal(units),
                "record_status": "draft" if draft else "active",
            },
        )
    db.flush()
    now = clock.now()
    for weeks in range(WEEKS_RECORDED, 0, -1):
        balance.record(db, SEED, now - timedelta(days=7 * weeks))


# --- writing the items, their addresses and their coverage ----------------------------------


def write_items(writer: Writer, planned: list[Planned], tag_hids: dict[str, str]) -> None:
    """Write the items, those above first, with their tags and a retirement where there is one."""
    for depth in (0, 1, 2):
        rows = []
        for one in planned:
            if one.depth != depth:
                continue
            row = one.row
            labelled = [audit.change("tags", [], one.labels)] if one.labels else []
            writer.created(items.RECORD_TYPE, row, items.FIELDS, labelled)
            if one.retired:
                row["record_status"] = "retired"
                row["row_version"] += 1
                writer.event(
                    "retire",
                    items.RECORD_TYPE,
                    row["hid"],
                    [audit.change("record_status", "active", "retired")],
                )
            rows.append(row)
        writer.write(Item, rows)
    links = [
        {"tag_hid": tag_hids[label], "record_type": items.RECORD_TYPE, "record_hid": one.row["hid"]}
        for one in planned
        for label in one.labels
    ]
    writer.write(TagLink, links)


def write_addresses(writer: Writer, dice: Dice, planned: list[Planned]) -> None:
    """Give most network devices a management address, from 2001:db8::/32."""
    rows = []
    for number, one in enumerate(planned, start=1):
        if one.depth or one.use in ("phone", "ap", "server") or one.group == "switch":
            continue
        if not dice.chance(0.9, "addressed", one.row["serial_number"]):
            continue
        given = f"2001:db8:{number // 65536:x}::{number % 65536:x}"
        row = {
            "hid": new_hid(),
            "item_hid": one.row["hid"],
            "group_hid": None,
            "address": str(ipaddress.IPv6Address(given)),
            "network_hid": None,
            "role": "management",
            "is_primary": True,
            **bookkeeping(writer.now),
        }
        writer.created(addresses.RECORD_TYPE, row, addresses.FIELDS)
        rows.append(row)
    writer.write(Address, rows)


def _cover(
    writer: Writer,
    made: Made,
    contract: Contract,
    item: Planned,
    starts_on: date | None = None,
    ends_on: date | None = None,
    left_service: bool = False,
) -> dict[str, Any]:
    """Return a coverage of an item under a contract, its dates kept as the rules keep them."""
    span = made.spans[contract.hid]
    row = {
        "hid": new_hid(),
        "contract_hid": contract.hid,
        "item_hid": item.row["hid"],
        # A day that is the contract's own is kept as blank, and follows the contract.
        "starts_on": None if starts_on == span.starts_on else starts_on,
        "ends_on": None if ends_on == span.ends_on else ends_on,
        "left_service": left_service,
        **bookkeeping(writer.now),
    }
    told = contracts.COVERAGE_FIELDS if left_service else contracts.COVERAGE_FIELDS[:-1]
    writer.created(contracts.COVERAGE_TYPE, row, told)
    return row


def write_coverage(writer: Writer, dice: Dice, made: Made, planned: list[Planned]) -> None:
    """Put most items under a contract of their maker.

    Contracts are bought for a region and a kind of thing, so each covers a part of the
    inventory. Some items are under two at once, some were under another before, and
    the coverage of an item that left service ended on the day it left and is marked
    so, unless somebody has told the vendor since. A part is under the contract of the
    item it is in, when it is under one.
    """
    today = writer.now.date()
    rows: list[dict[str, Any]] = []
    under: dict[str, Contract] = {}
    for one in planned:
        offered = made.contracts.get(made.maker_of[one.row["catalog_entry_hid"]], [])
        key = one.row["serial_number"]
        state = one.row["lifecycle_state"]
        if one.depth:
            contract = under.get(one.row["parent_item_hid"])
            if contract is None or not dice.chance(0.12, "part covered", key):
                continue
        else:
            odds = 0.35 if one.use == "phone" else 0.9
            if state in ("Purchased", "Delivered"):
                odds = 0.2
            if not offered or one.row["record_status"] == "draft":
                continue
            if not dice.chance(odds, "covered", key):
                continue
            bucket = one.place.region * len(MAJOR_USES) + MAJOR_USES.index(one.use)
            contract = offered[(bucket + dice.between(0, 2, "spread", key)) % len(offered)]
        span = made.spans[contract.hid]
        starts = None
        if span.starts_on is not None and dice.chance(0.25, "added later", key):
            starts = min(today, span.starts_on + timedelta(days=dice.between(1, 200, "on", key)))
        ends = one.left_on if state in LEFT else None
        if ends is not None:
            if span.starts_on is not None and span.starts_on > ends:
                # It left before this contract began, so it never was under it.
                continue
            if starts is not None and starts > ends:
                starts = None
        # Ended on the day it left, and marked so; unless the vendor has been told since.
        left = ends is not None and not dice.chance(0.25, "vendor told", key)
        rows.append(_cover(writer, made, contract, one, starts, ends, left))
        under[one.row["hid"]] = contract
        others = [other for other in offered if other.hid != contract.hid]
        if one.depth or not others or ends is not None:
            continue
        if dice.chance(0.05, "second", key):
            # Under another as well, as happens when one was bought before the last ended.
            second = dice.pick(others, "second contract", key)
            rows.append(_cover(writer, made, second, one))
        elif dice.chance(0.06, "before", key):
            # Under another before, which ended some time ago.
            earlier = dice.pick(others, "earlier contract", key)
            ended = today - timedelta(days=dice.between(30, 400, "ended", key))
            began = made.spans[earlier.hid].starts_on
            if began is None or began <= ended:
                rows.append(_cover(writer, made, earlier, one, ends_on=ended))
    writer.write(ContractCoverage, rows)


# --- the folder --------------------------------------------------------------------------


def prepare(folder: Path) -> Config:
    """Return the configuration of a fixture folder, emptied and ready to fill.

    A folder that holds anything but a fixture is left alone.
    """
    if folder.exists() and any(folder.iterdir()):
        if not (folder / FACTS).is_file():
            raise SystemExit(f"{folder} holds something that is not a fixture: it is left alone")
        shutil.rmtree(folder)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "config.toml").write_text(CONFIG, encoding="utf-8")
    return Config(state_dir=folder)


def counts(db: Session) -> dict[str, int]:
    """Return how many of each the fixture holds."""

    def of(model: Any, *where: Any) -> int:
        return db.scalar(select(func.count()).select_from(model).where(*where)) or 0

    major = Item.parent_item_hid.is_(None)
    phones = select(CatalogEntry.hid).where(CatalogEntry.type == "phone")
    return {
        "items": of(Item),
        "major items that are not phones": of(Item, major, Item.catalog_entry_hid.not_in(phones)),
        "phones": of(Item, Item.catalog_entry_hid.in_(phones)),
        "minor items": of(Item, ~major),
        "items in Pending-Removal": of(Item, Item.lifecycle_state == "Pending-Removal"),
        "items in Released": of(Item, Item.lifecycle_state == "Released"),
        "items in Archived": of(Item, Item.lifecycle_state == "Archived"),
        "retired items": of(Item, Item.record_status == "retired"),
        "draft items": of(Item, Item.record_status == "draft"),
        "catalog entries": of(CatalogEntry),
        "stacks": of(DeviceGroup, DeviceGroup.type == "stack"),
        "device groups": of(DeviceGroup),
        "group members": of(DeviceGroupMember),
        "agreements": of(Agreement),
        "contracts": of(Contract),
        "contracts in agreements": of(Contract, Contract.agreement_hid.is_not(None)),
        "contracts pending renewal": of(Contract, Contract.status == contracts.RENEWAL_PENDING),
        "contracts with a next term": of(Contract, Contract.next_starts_on.is_not(None)),
        "contracts to end with their term": of(Contract, Contract.ends_with_term.is_(True)),
        "contracts to review": of(Contract, contracts.to_review_value()),
        "catalog entries not to be renewed": of(CatalogEntry, CatalogEntry.do_not_renew.is_(True)),
        "items with their own word on renewing": of(Item, Item.do_not_renew.is_not(None)),
        "purchase requests": of(PurchaseRequest),
        "purchase lines": of(PurchaseLine),
        "items on a purchase line": of(Item, Item.purchase_line_hid.is_not(None)),
        "items of another model than their line's": of(
            Item,
            select(PurchaseLine.hid)
            .where(
                PurchaseLine.hid == Item.purchase_line_hid,
                PurchaseLine.catalog_entry_hid != Item.catalog_entry_hid,
            )
            .exists(),
        ),
        "coverages": of(ContractCoverage),
        "coverages ended on leaving service": of(
            ContractCoverage, ContractCoverage.left_service.is_(True)
        ),
        "capacity lines": of(CapacityLine),
        "capacity lines that multiply": of(CapacityLine, CapacityLine.effect == capacity.MULTIPLY),
        "capacity records": of(CapacityRecord),
        "audit events": of(AuditEvent),
    }


def build(folder: Path, items_wanted: int = ITEMS, seed: str = "hirdir") -> dict[str, Any]:
    """Make a fixture in folder and return what it says of itself."""
    started = time.monotonic()
    config = prepare(folder)
    migrate.upgrade(config.database_url)
    engine = make_engine(config.database_url)
    dice = Dice(seed)
    shape = Shape(items_wanted)
    try:
        with make_sessions(engine)() as db:
            user, _ = accounts.create_user(db, SEED, username=USERNAME, access_code=ACCESS_CODE)
            accounts.grant_role(db, SEED, role="viewer", user_hid=user.hid)
            made = build_small(db, dice, shape)
            rules = {rule.state: rule for rule in db.scalars(select(LifecycleRule))}
            writer = Writer(db)
            planned = plan_items(dice, made, shape, rules, writer.now)
            planned_groups = plan_groups(dice, planned, shape)
            plan_purchases(db, dice, planned)
            write_items(writer, planned, made.tags)
            write_addresses(writer, dice, planned)
            write_coverage(writer, dice, made, planned)
            writer.write_events()
            make_groups(db, planned_groups)
            make_capacity(db, dice, made.places)
            db.commit()
            facts = {
                "made_by": "scripts/seed_fixture.py",
                "built_on": clock.today().isoformat(),
                "seed": seed,
                "username": USERNAME,
                "access_code": ACCESS_CODE,
                "counts": counts(db),
                "seconds": round(time.monotonic() - started, 1),
            }
    finally:
        engine.dispose()
    (folder / FACTS).write_text(json.dumps(facts, indent=2) + "\n", encoding="utf-8")
    return facts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fill a database with a fictional inventory.")
    parser.add_argument("folder", nargs="?", type=Path, default=FOLDER)
    parser.add_argument("--items", type=int, default=ITEMS, help="how many, 50,000 unless said")
    parser.add_argument("--seed", default="hirdir", help="another seed gives another inventory")
    given = parser.parse_args(argv)
    if given.items < LEAST:
        parser.error(f"--items is {LEAST} at the least, for every kind of item to be there")
    facts = build(given.folder, given.items, given.seed)
    width = max(len(name) for name in facts["counts"])
    for name, count in facts["counts"].items():
        print(f"{name:<{width}}  {count:>7,}")
    print(f"made in {facts['seconds']} s, in {given.folder}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
