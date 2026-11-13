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
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hirdir.config import Config
from hirdir.db import migrate
from hirdir.db.engine import make_engine, make_sessions
from hirdir.domain import audit, catalog, items, owners, tags
from hirdir.io import exports, files
from hirdir.io.entities import ENTITIES, LOAD_ORDER

TARGET = Path(__file__).resolve().parent.parent / "examples"
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
        1,
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
        comments="Traded in when Site-1 closed",
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
            "quantity": 250,
            "lifecycle_state": "Prod",
            "owner": "Network Engineering",
            "description": "Licensed for 250 devices",
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
    for item in _items():
        fields = {name: value for name, value in item.items() if value is not None}
        fields["catalog_entry_hid"] = entries[fields.pop("vendor"), fields.pop("pid")].hid
        if "owner" in fields:
            fields["owner_hid"] = its_owners[fields.pop("owner")].hid
        items.create_item(db, SEED, fields)
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
                    entity,
                    format_=format_,
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
