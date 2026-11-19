"""What follows from a host (P-247): retiring a host retires what runs on it, a stack or
a cluster that something runs on is not retired, deleting, and a replacement that hands
over what runs on the item that left.

The host fields are set through the database here, as the rules of naming a host are
another part's (P-246): what is tested is what follows from them.
"""

from datetime import UTC, datetime
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
        values["host_observed_at"] = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)
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


# --- a stack or a cluster that something runs on (P-247) -----------------------------


def test_a_cluster_that_something_runs_on_is_not_retired_and_names_what(
    client: TestClient, make: Maker, inventory: dict[str, str], db: Session
) -> None:
    made = _virtual(make)
    cluster = make.group("site2-esx-cluster", "cluster", [(made["esx"], "member")])
    _host(db, made["app"], group=cluster)
    _host(db, made["web"], group=cluster)
    # One retired already does not stand in the way.
    _host(db, made["dns"], group=cluster)
    dns = _get(make, made["dns"])
    make.post(f"/items/{dns['hid']}/retire", {"row_version": dns["row_version"]}, 200)
    cluster = make.get(f"/device-groups/{cluster['hid']}")

    refused = client.post(
        f"{API}/device-groups/{cluster['hid']}/retire",
        json={"row_version": cluster["row_version"]},
        headers=inventory,
    )

    assert refused.status_code == 409, refused.text
    problem = refused.json()
    running = [
        {"hid": made["app"]["hid"], "record_type": "item", "label": "site2-vm-app01"},
        {"hid": made["web"]["hid"], "record_type": "item", "label": "site2-vm-web01"},
    ]
    assert problem["depends_on"] == running
    assert "2 items run on site2-esx-cluster" in problem["detail"]
    assert make.get(f"/device-groups/{cluster['hid']}")["record_status"] == "active"
    # Several at once: refused among the rest, with the same.
    many = client.post(
        f"{API}/device-groups/retire", json={"hids": [cluster["hid"]]}, headers=inventory
    ).json()
    assert [one["hid"] for one in many["refused"]] == [cluster["hid"]]
    assert many["refused"][0]["depends_on"] == running
    assert many["refused"][0]["detail"].startswith("2 items run on site2-esx-cluster")
    # Its member is retired as any item: what runs on the cluster stays as it is.
    esx = _get(make, made["esx"])
    make.post(f"/items/{esx['hid']}/retire", {"row_version": esx["row_version"]}, 200)
    assert _status(make, made["app"], made["web"]) == ["active", "active"]
    # Each given another host, or retired, first; then the cluster goes.
    _host(db, made["app"], made["other"])
    web = _get(make, made["web"])
    make.post(f"/items/{web['hid']}/retire", {"row_version": web["row_version"]}, 200)
    cluster = make.get(f"/device-groups/{cluster['hid']}")
    make.post(
        f"/device-groups/{cluster['hid']}/retire", {"row_version": cluster["row_version"]}, 200
    )


def test_a_stack_that_a_virtual_context_runs_on_is_not_retired(
    client: TestClient, make: Maker, inventory: dict[str, str], db: Session
) -> None:
    switches = make.switches(make.entry(make.vendor("Example Networks"), "N7K"), "site2-n7k", 2)
    stack = make.stack("site2-n7k-pair", switches)
    context = make.item(name="site2-n7k-01-vdc2")
    _host(db, context, group=stack)

    tried = client.post(
        f"{API}/device-groups/retire",
        json={"hids": [stack["hid"]], "dry_run": True},
        headers=inventory,
    ).json()

    assert tried["dry_run"] is True
    assert tried["hosted"] == []
    assert [one["depends_on"] for one in tried["refused"]] == [
        [{"hid": context["hid"], "record_type": "item", "label": "site2-n7k-01-vdc2"}]
    ]


# --- deleting (P-227, P-247) ---------------------------------------------------------


def _delete(
    client: TestClient, admin: dict[str, str], path: str, hids: list[str], dry_run: bool = False
) -> dict[str, Any]:
    body = {"hids": hids, "reason": "a wrong file", "dry_run": dry_run}
    response = client.post(f"{API}{path}/delete", json=body, headers=admin)
    assert response.status_code == 200, response.text
    return response.json()


def test_a_host_is_not_deleted_while_something_names_it_retired_or_not(
    client: TestClient, make: Maker, admin: dict[str, str], db: Session
) -> None:
    made = _virtual(make)
    _hosted(db, made)
    web = _get(make, made["web"])
    make.post(f"/items/{web['hid']}/retire", {"row_version": web["row_version"]}, 200)

    done = _delete(client, admin, "/items", [made["esx"]["hid"]])

    assert done["deleted"] == []
    assert done["refused"] == [
        {
            "hid": made["esx"]["hid"],
            "label": "site2-esx-01",
            "depends_on": sorted(
                [
                    {"record_type": "item", "hid": made["app"]["hid"], "label": "site2-vm-app01"},
                    {"record_type": "item", "hid": made["web"]["hid"], "label": "site2-vm-web01"},
                ],
                key=lambda one: one["hid"],
            ),
        }
    ]


def test_a_host_deleted_with_what_runs_on_it_goes_last(
    client: TestClient, make: Maker, admin: dict[str, str], db: Session
) -> None:
    made = _virtual(make)
    _hosted(db, made)
    everything = [made[one]["hid"] for one in ("esx", "app", "web", "dns")]

    done = _delete(client, admin, "/items", everything)

    assert sorted(one["hid"] for one in done["deleted"]) == sorted(everything)
    assert done["refused"] == []
    for hid in everything:
        make.get(f"/items/{hid}", 404)


def test_what_was_seen_on_a_deleted_item_is_cleared_of_it_by_an_event_that_says_so(
    client: TestClient, make: Maker, admin: dict[str, str], db: Session
) -> None:
    made = _virtual(make)
    cluster = make.group("site2-esx-cluster", "cluster", [(made["other"], "member")])
    _host(db, made["app"], group=cluster, seen=made["esx"])

    done = _delete(client, admin, "/items", [made["esx"]["hid"]])

    assert [one["hid"] for one in done["deleted"]] == [made["esx"]["hid"]]
    db.expire_all()
    app = db.get_one(Item, made["app"]["hid"])
    assert (app.host_group_hid, app.observed_host_hid, app.host_observed_at) == (
        cluster["hid"],
        None,
        None,
    )
    assert _cause(make, made["app"], "update", "deleted_with") == [made["esx"]["hid"]]


def test_a_group_that_something_runs_on_is_not_deleted(
    client: TestClient, make: Maker, admin: dict[str, str], db: Session
) -> None:
    made = _virtual(make)
    cluster = make.group("site2-esx-cluster", "cluster", [(made["esx"], "member")])
    _host(db, made["app"], group=cluster)
    app = _get(make, made["app"])
    make.post(f"/items/{app['hid']}/retire", {"row_version": app["row_version"]}, 200)

    done = _delete(client, admin, "/device-groups", [cluster["hid"]], dry_run=True)

    assert done["refused"] == [
        {
            "hid": cluster["hid"],
            "label": "site2-esx-cluster",
            "depends_on": [
                {"record_type": "item", "hid": made["app"]["hid"], "label": "site2-vm-app01"}
            ],
        }
    ]
