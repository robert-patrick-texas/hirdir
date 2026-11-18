"""What follows from a host (P-247): retiring a host retires what runs on it, a stack or
a cluster that something runs on is not retired, deleting, and a replacement that hands
over what runs on the item that left.

The host fields are set through the database here, as the rules of naming a host are
another part's (P-246): what is tested is what follows from them.
"""

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import Session

from hirdir.db.models import Item
from tests.api.inventory import API, Maker

NOBODY = "01900000-0000-7000-8000-000000000000"


def _host(
    db: Session,
    item: dict[str, Any],
    host: dict[str, Any] | None = None,
    group: dict[str, Any] | None = None,
    seen: dict[str, Any] | None = None,
) -> None:
    """Say what an item runs on, and what it was seen on, as the record holds it."""
    values: dict[str, Any] = {
        "host_item_hid": host["hid"] if host else None,
        "host_group_hid": group["hid"] if group else None,
    }
    if seen is not None:
        values["observed_host_hid"] = seen["hid"]
    db.execute(update(Item).where(Item.hid == item["hid"]).values(**values))
    db.commit()


def _get(make: Maker, item: dict[str, Any]) -> dict[str, Any]:
    return make.get(f"/items/{item['hid']}")


def _status(make: Maker, *found: dict[str, Any]) -> list[str]:
    return [_get(make, one)["record_status"] for one in found]


def _cause(make: Maker, item: dict[str, Any], action: str, field: str) -> list[Any]:
    """Return what each event of an action on an item says in one of its entries."""
    return [
        entry["new"]
        for event in make.audit(record_hid=item["hid"])
        if event["action"] == action
        for entry in event["changes"]
        if entry["field"] == field
    ]


def _virtual(make: Maker) -> dict[str, dict[str, Any]]:
    """A hypervisor with two virtual machines, a container in one, and a server of its own."""
    vendor = make.vendor("Example Virtual")
    machine = make.entry(vendor, "VM", kind="virtual_machine")
    container = make.entry(vendor, "CTR", kind="virtual_machine")
    server = make.entry(make.vendor("Example Servers"), "ESX-1U")
    made = {
        "esx": make.item(
            catalog_entry_hid=server["hid"], serial_number="EX-ESX-01", name="site2-esx-01"
        ),
        "other": make.item(
            catalog_entry_hid=server["hid"], serial_number="EX-ESX-02", name="site2-esx-02"
        ),
        "app": make.item(catalog_entry_hid=machine["hid"], name="site2-vm-app01"),
        "web": make.item(catalog_entry_hid=machine["hid"], name="site2-vm-web01"),
        "dns": make.item(catalog_entry_hid=container["hid"], name="site2-ctr-dns1"),
    }
    return made


def _hosted(db: Session, made: dict[str, dict[str, Any]]) -> None:
    _host(db, made["app"], made["esx"])
    _host(db, made["web"], made["esx"])
    _host(db, made["dns"], made["app"])


# --- retiring a host (P-247) ---------------------------------------------------------


def test_retiring_a_host_retires_what_runs_on_it_and_what_runs_on_that(
    make: Maker, db: Session
) -> None:
    made = _virtual(make)
    _hosted(db, made)
    group = make.group("site2-vm-apps", "custom", [(made["app"], "member")])
    esx = _get(make, made["esx"])

    make.post(f"/items/{esx['hid']}/retire", {"row_version": esx["row_version"]}, 200)

    assert _status(make, made["esx"], made["app"], made["web"], made["dns"]) == ["retired"] * 4
    # Each went by its own retire event, which names the item it ran on.
    assert _cause(make, made["app"], "retire", "retired_with") == [made["esx"]["hid"]]
    assert _cause(make, made["web"], "retire", "retired_with") == [made["esx"]["hid"]]
    assert _cause(make, made["dns"], "retire", "retired_with") == [made["app"]["hid"]]
    assert _cause(make, made["esx"], "retire", "retired_with") == []
    # In the one change, and as any item retired: its memberships end.
    requests = {
        event["request_id"]
        for one in ("esx", "app", "web", "dns")
        for event in make.audit(record_hid=made[one]["hid"])
        if event["action"] == "retire"
    }
    assert len(requests) == 1
    assert make.members(group) == []
    # The other server is not touched.
    assert _status(make, made["other"]) == ["active"]


def test_bringing_a_host_back_brings_back_nothing_that_went_with_it(
    make: Maker, db: Session
) -> None:
    made = _virtual(make)
    _hosted(db, made)
    esx = _get(make, made["esx"])
    make.post(f"/items/{esx['hid']}/retire", {"row_version": esx["row_version"]}, 200)

    back = _get(make, made["esx"])
    make.patch(
        f"/items/{back['hid']}", {"row_version": back["row_version"], "record_status": "active"}
    )

    assert _status(make, made["esx"], made["app"], made["web"], made["dns"]) == [
        "active",
        "retired",
        "retired",
        "retired",
    ]
    # Retired again, it takes nothing with it that is retired already, and says nothing
    # more of them.
    again = _get(make, made["esx"])
    make.post(f"/items/{again['hid']}/retire", {"row_version": again["row_version"]}, 200)
    assert _cause(make, made["app"], "retire", "retired_with") == [made["esx"]["hid"]]


def test_what_runs_on_a_cluster_stays_with_it_when_one_host_of_it_is_retired(
    make: Maker, db: Session
) -> None:
    made = _virtual(make)
    cluster = make.group(
        "site2-esx-cluster", "cluster", [(made["esx"], "member"), (made["other"], "member")]
    )
    _host(db, made["app"], group=cluster, seen=made["esx"])
    esx = _get(make, made["esx"])

    make.post(f"/items/{esx['hid']}/retire", {"row_version": esx["row_version"]}, 200)

    assert _status(make, made["app"]) == ["active"]
    assert _get(make, made["app"])["record_status"] == "active"


def test_retiring_several_says_what_went_with_them_and_a_dry_run_changes_nothing(
    client: TestClient, make: Maker, inventory: dict[str, str], db: Session
) -> None:
    made = _virtual(make)
    _hosted(db, made)
    named = [made["esx"]["hid"], made["app"]["hid"], NOBODY]

    tried = client.post(
        f"{API}/items/retire", json={"hids": named, "dry_run": True}, headers=inventory
    )
    assert tried.status_code == 200, tried.text
    would = tried.json()
    assert _status(make, made["esx"], made["app"], made["web"], made["dns"]) == ["active"] * 4
    assert make.audit(record_hid=made["esx"]["hid"], action="retire") == []

    done = client.post(f"{API}/items/retire", json={"hids": named}, headers=inventory).json()

    expected = {
        # The virtual machine that is named, and runs on the server named, is counted once.
        "retired": [
            {"hid": made["esx"]["hid"], "label": "site2-esx-01"},
            {"hid": made["app"]["hid"], "label": "site2-vm-app01"},
        ],
        "already": [],
        "refused": [],
        "missing": [NOBODY],
        "hosted": sorted(
            [
                {
                    "hid": made["web"]["hid"],
                    "label": "site2-vm-web01",
                    "host_hid": made["esx"]["hid"],
                },
                {
                    "hid": made["dns"]["hid"],
                    "label": "site2-ctr-dns1",
                    "host_hid": made["app"]["hid"],
                },
            ],
            key=lambda one: one["hid"],
        ),
    }
    for answer, dry in ((would, True), (done, False)):
        assert {**answer, "hosted": sorted(answer["hosted"], key=lambda one: one["hid"])} == {
            **expected,
            "dry_run": dry,
        }
    assert _status(make, made["esx"], made["app"], made["web"], made["dns"]) == ["retired"] * 4


def test_a_virtual_machine_named_before_its_host_is_retired_once(
    client: TestClient, make: Maker, inventory: dict[str, str], db: Session
) -> None:
    made = _virtual(make)
    _hosted(db, made)
    named = [made["app"]["hid"], made["esx"]["hid"]]

    done = client.post(f"{API}/items/retire", json={"hids": named}, headers=inventory).json()

    assert [one["hid"] for one in done["retired"]] == named
    assert sorted(one["hid"] for one in done["hosted"]) == sorted(
        [made["web"]["hid"], made["dns"]["hid"]]
    )
    assert _cause(make, made["app"], "retire", "retired_with") == []
