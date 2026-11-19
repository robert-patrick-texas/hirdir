"""What is to be looked at says so (P-249): the reasons, on the record and in the list."""

from typing import Any

import pytest
from sqlalchemy import update

from hirdir.config import Config
from hirdir.db.engine import make_engine, make_sessions
from hirdir.db.models import DeviceGroup, Registration
from tests.api.inventory import Maker
from tests.api.test_hosting import Lab


@pytest.fixture
def lab(make: Maker) -> Lab:
    return Lab(make)


def _review(lab: Lab, item: dict[str, Any]) -> list[tuple[str, str | None]]:
    marks = lab.get(item)["review"]
    return [(mark["reason"], mark["about"]["label"] if mark["about"] else None) for mark in marks]


def _listed(make: Maker, condition: str, **more: Any) -> list[str]:
    page = make.get("/items", filter=condition, limit=1000, **more)
    return [row["hid"] for row in page["items"]]


def test_an_item_of_a_kind_that_runs_on_a_host_and_names_none_is_to_be_looked_at(
    lab: Lab,
) -> None:
    lost = lab.vm("site2-vm-lost")
    placed = lab.vm(host_item_hid=lab.esx["hid"])
    assert lost["review"] == [{"reason": "no_host", "about": None}]
    assert placed["review"] == []
    # Hardware and an item of no model are to be looked at for nothing.
    assert lab.get(lab.esx)["review"] == []
    assert lab.make.item(name="site2-no-model")["review"] == []

    assert _listed(lab.make, "review:eq:no_host") == [lost["hid"]]
    assert _listed(lab.make, "review:empty:false") == [lost["hid"]]
    assert lost["hid"] not in _listed(lab.make, "review:empty:true")
    assert placed["hid"] in _listed(lab.make, "review:empty:true")
    # Naming its host puts it right.
    lab.patch(lost, host_group_hid=lab.cluster["hid"])
    assert _review(lab, lost) == []
    assert _listed(lab.make, "review:empty:false") == []


def test_a_host_that_is_retired_or_has_left_the_teams_hands_is_gone(
    lab: Lab, config: Config
) -> None:
    make = lab.make
    on_server = lab.vm(host_item_hid=lab.esx["hid"])
    on_cluster = lab.vm("site2-vm-app02", host_group_hid=lab.cluster["hid"])
    vdc = lab.vdc(host_item_hid=lab.n7k["hid"])

    # A switch that leaves the team's hands changes nothing of what runs on it.
    switch = make.move(make.move(lab.get(lab.n7k), "Pending-Removal"), "Released")
    assert switch["lifecycle_state"] == "Released"
    assert _review(lab, vdc) == [("host_gone", "site2-n7k-01")]
    assert lab.get(vdc)["review"][0]["about"]["record_type"] == "item"
    assert lab.get(vdc)["record_status"] == "active"

    # A cluster whose record is retired while something runs on it, which the rules of
    # P-247 refuse: set where it is kept, as a record of an older release may be.
    with make_sessions(make_engine(config.database_url))() as session:
        session.execute(
            update(DeviceGroup)
            .where(DeviceGroup.hid == lab.cluster["hid"])
            .values(record_status="retired")
        )
        session.commit()
    marks = lab.get(on_cluster)["review"]
    assert [(mark["reason"], mark["about"]["record_type"]) for mark in marks] == [
        ("host_gone", "device_group")
    ]
    assert _review(lab, on_server) == []
    assert set(_listed(make, "review:eq:host_gone")) == {vdc["hid"], on_cluster["hid"]}

    # A retired item has no reason.
    make.post(f"/items/{vdc['hid']}/retire", {"row_version": lab.get(vdc)["row_version"]}, 200)
    assert lab.get(vdc)["review"] == []
    assert vdc["hid"] not in _listed(make, "review:empty:false", include_archived="true")


def test_an_item_a_system_reports_no_more_is_to_be_looked_at(lab: Lab, config: Config) -> None:
    make = lab.make
    vm = lab.vm(host_item_hid=lab.esx["hid"])
    system = make.post("/external-systems", {"name": "Example vCenter", "kind": "monitoring"})
    registration = make.post(
        "/registrations",
        {"system_hid": system["hid"], "item_hid": vm["hid"], "external_id": "vm-1001"},
    )
    assert _review(lab, vm) == []
    # Lane S3 gives the status by an import; here it is set where it is kept.
    with make_sessions(make_engine(config.database_url))() as session:
        session.execute(
            update(Registration)
            .where(Registration.hid == registration["hid"])
            .values(status="not_reported")
        )
        session.commit()
    marks = lab.get(vm)["review"]
    assert marks == [
        {
            "reason": "not_reported",
            "about": {
                "hid": system["hid"],
                "record_type": "external_system",
                "label": "Example vCenter",
            },
        }
    ]
    assert _listed(make, "review:eq:not_reported") == [vm["hid"]]
    assert _listed(make, "review:in:no_host,not_reported") == [vm["hid"]]


def test_the_list_sorts_by_review_and_finds_by_what_an_item_runs_on(lab: Lab) -> None:
    make = lab.make
    lost = lab.vm("site2-vm-lost")
    on_server = lab.vm(host_item_hid=lab.esx["hid"], observed_host_hid=lab.esx2["hid"])
    on_cluster = lab.vm("site2-vm-app02", host_group_hid=lab.cluster["hid"])
    rows = make.get("/items", sort="review", filter="catalog.kind:eq:virtual_machine")["items"]
    assert rows[0]["hid"] == lost["hid"]

    assert _listed(make, "host.name:eq:site2-esx-01") == [on_server["hid"]]
    assert _listed(make, "host.name:eq:site2-esx-cluster") == [on_cluster["hid"]]
    assert _listed(make, f"host_item_hid:eq:{lab.esx['hid']}") == [on_server["hid"]]
    assert _listed(make, f"host_group_hid:eq:{lab.cluster['hid']}") == [on_cluster["hid"]]
    assert _listed(make, "observed_host.name:eq:site2-esx-02") == [on_server["hid"]]
    assert _listed(make, "host_differs:eq:true") == [on_server["hid"]]
    assert _listed(make, "hosted_count:gt:0") == [lab.esx["hid"]]
    # The list sorts by the name of what each runs on.
    named = make.get("/items", sort="host.name", filter="host.name:empty:false")["items"]
    assert [row["hid"] for row in named] == [on_server["hid"], on_cluster["hid"]]
    # And a page answers what the record does.
    listed = make.get("/items", filter="host_differs:eq:true", fields="hid,host,review")["items"]
    assert listed[0]["host"]["name"] == "site2-esx-01"
