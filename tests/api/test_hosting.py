"""What runs on a host: a virtual machine, a virtual context and a container (P-246)."""

from datetime import UTC, datetime, timedelta

import pytest

from tests.api.inventory import API, Maker, errors

NOBODY = "01900000-0000-7000-8000-000000000000"


class Lab:
    """Models of each kind under an invented vendor, and a host of each sort."""

    def __init__(self, make: Maker) -> None:
        self.make = make
        virtual = make.vendor("Example Virtual")
        cisco = make.vendor("Cisco")
        self.vm_model = make.entry(virtual, "VM", kind="virtual_machine")
        self.vdc_model = make.entry(virtual, "VDC", kind="virtual_context")
        self.ctr_model = make.entry(virtual, "CTR", kind="container")
        self.server_model = make.entry(virtual, "SRV-2U")
        self.switch_model = make.entry(cisco, "N7K-C7010")
        self.software = make.entry(virtual, "HYPERVISOR-OS", kind="software")
        self.esx = make.item(
            catalog_entry_hid=self.server_model["hid"],
            serial_number="SRV0000X001",
            name="site2-esx-01",
        )
        self.esx2 = make.item(
            catalog_entry_hid=self.server_model["hid"],
            serial_number="SRV0000X002",
            name="site2-esx-02",
        )
        self.n7k = make.item(
            catalog_entry_hid=self.switch_model["hid"],
            serial_number="JAF0000X001",
            name="site2-n7k-01",
        )
        self.cluster = make.group(
            "site2-esx-cluster", "cluster", [(self.esx, "member"), (self.esx2, "member")]
        )

    def vm(self, name: str = "site2-vm-app01", expect: int = 201, **more: object) -> dict:
        body = {"catalog_entry_hid": self.vm_model["hid"], "name": name, **more}
        return self.make.post("/items", body, expect)

    def vdc(self, name: str = "site2-n7k-01-vdc2", expect: int = 201, **more: object) -> dict:
        body = {"catalog_entry_hid": self.vdc_model["hid"], "name": name, **more}
        return self.make.post("/items", body, expect)

    def ctr(self, name: str = "site2-ctr-dns1", expect: int = 201, **more: object) -> dict:
        body = {"catalog_entry_hid": self.ctr_model["hid"], "name": name, **more}
        return self.make.post("/items", body, expect)

    def get(self, item: dict) -> dict:
        return self.make.get(f"/items/{item['hid']}")

    def patch(self, item: dict, expect: int = 200, **fields: object) -> dict:
        current = self.get(item)
        body = {"row_version": current["row_version"], **fields}
        return self.make.patch(f"/items/{item['hid']}", body, expect)


@pytest.fixture
def lab(make: Maker) -> Lab:
    return Lab(make)


def test_a_virtual_machine_names_the_server_it_runs_on(lab: Lab) -> None:
    vm = lab.vm(host_item_hid=lab.esx["hid"])

    assert (vm["host_item_hid"], vm["host_group_hid"]) == (lab.esx["hid"], None)
    assert vm["host"] == {
        "item_hid": lab.esx["hid"],
        "group_hid": None,
        "name": "site2-esx-01",
        "type": None,
        "pid": "SRV-2U",
        "lifecycle_state": None,
        "record_status": "active",
    }
    assert vm["is_major"] is True
    assert (vm["observed_host"], vm["host_differs"], vm["review"]) == (None, None, [])
    assert lab.get(lab.esx)["hosted_count"] == 1
    created = lab.make.audit(record_hid=vm["hid"])[0]
    assert {"field": "host_item_hid", "old": None, "new": lab.esx["hid"]} in created["changes"]


def test_a_virtual_machine_runs_on_a_cluster_and_naming_one_host_clears_the_other(
    lab: Lab,
) -> None:
    vm = lab.vm(host_group_hid=lab.cluster["hid"])
    assert vm["host"]["group_hid"] == lab.cluster["hid"]
    assert (vm["host"]["name"], vm["host"]["type"]) == ("site2-esx-cluster", "cluster")
    assert lab.make.get(f"/device-groups/{lab.cluster['hid']}")["hosted_count"] == 1

    moved = lab.patch(vm, host_item_hid=lab.esx2["hid"])
    assert (moved["host_item_hid"], moved["host_group_hid"]) == (lab.esx2["hid"], None)
    assert lab.make.get(f"/device-groups/{lab.cluster['hid']}")["hosted_count"] == 0
    cleared = lab.patch(moved, host_item_hid=None)
    assert (cleared["host_item_hid"], cleared["host"]) == (None, None)


def test_a_virtual_context_and_a_container_name_their_hosts(lab: Lab) -> None:
    vdc = lab.vdc(host_item_hid=lab.n7k["hid"])
    vm = lab.vm(host_item_hid=lab.esx["hid"])
    ctr = lab.ctr(host_item_hid=vm["hid"])
    assert vdc["host"]["name"] == "site2-n7k-01"
    assert ctr["host"]["item_hid"] == vm["hid"]


def test_an_item_with_a_host_and_its_host_are_refused_where_the_rules_do_not_allow_them(
    lab: Lab,
) -> None:
    make = lab.make

    def refused(expect_field: str, **body: object) -> str:
        problem = make.post("/items", {"name": "site2-vm-x", **body}, 422)
        found = errors(problem)
        assert expect_field in found, problem
        return found[expect_field]

    vm_model = lab.vm_model["hid"]
    both = refused(
        "host_group_hid",
        catalog_entry_hid=vm_model,
        host_item_hid=lab.esx["hid"],
        host_group_hid=lab.cluster["hid"],
    )
    assert "not both" in both
    assert "runs on nothing" in refused(
        "host_item_hid", catalog_entry_hid=lab.server_model["hid"], host_item_hid=lab.esx["hid"]
    )
    assert "no model" in refused("host_item_hid", host_item_hid=lab.esx["hid"])
    assert "installed in another" in refused(
        "host_item_hid",
        catalog_entry_hid=vm_model,
        parent_item_hid=lab.esx["hid"],
        host_item_hid=lab.esx2["hid"],
    )
    assert "there is no item" in refused(
        "host_item_hid", catalog_entry_hid=vm_model, host_item_hid=NOBODY
    )
    container = lab.ctr("site2-ctr-free")
    assert "hosts nothing" in refused(
        "host_item_hid", catalog_entry_hid=vm_model, host_item_hid=container["hid"]
    )
    tool = make.item(catalog_entry_hid=lab.software["hid"], name="site2-esx-os")
    assert "software" in refused(
        "host_item_hid", catalog_entry_hid=vm_model, host_item_hid=tool["hid"]
    )
    custom = make.group("site2-lab", "custom")
    assert "stack or a cluster" in refused(
        "host_group_hid", catalog_entry_hid=vm_model, host_group_hid=custom["hid"]
    )
    assert "observed_host_hid" in refused(
        "host_observed_at",
        catalog_entry_hid=vm_model,
        host_observed_at="2026-11-01T10:00:00Z",
    )
    ahead = (datetime.now(UTC) + timedelta(days=3)).isoformat()
    refused(
        "host_observed_at",
        catalog_entry_hid=vm_model,
        observed_host_hid=lab.esx["hid"],
        host_observed_at=ahead,
    )

    # A host that is retired, or has left the team's hands, hosts nothing new.
    gone = make.post(
        f"/items/{lab.esx2['hid']}/retire", {"row_version": lab.esx2["row_version"]}, 200
    )
    assert "retired" in refused(
        "host_item_hid", catalog_entry_hid=vm_model, host_item_hid=gone["hid"]
    )
    old = make.item(catalog_entry_hid=lab.server_model["hid"], serial_number="SRV0000X009")
    old = make.move(make.move(old, "Pending-Removal"), "Released")
    assert "Released" in refused(
        "host_item_hid", catalog_entry_hid=vm_model, host_item_hid=old["hid"]
    )


def test_a_line_of_hosts_is_three_long_and_never_a_circle(lab: Lab) -> None:
    vm = lab.vm(host_item_hid=lab.esx["hid"])
    inner = lab.vm("site2-vm-nested", host_item_hid=vm["hid"])
    # A container in a virtual machine in a virtual machine on a server is too long.
    problem = lab.ctr(expect=422, host_item_hid=inner["hid"])
    assert "at most 3" in errors(problem)["host_item_hid"]
    # A machine does not run on what runs on it, nor on itself.
    assert (
        "runs on this item"
        in errors(lab.patch(vm, 422, host_item_hid=inner["hid"]))["host_item_hid"]
    )
    assert "itself" in errors(lab.patch(vm, 422, host_item_hid=vm["hid"]))["host_item_hid"]
    # Moved onto a cluster, what runs on it still fits: the cluster ends the line.
    lab.patch(vm, host_group_hid=lab.cluster["hid"])
    assert lab.ctr(host_item_hid=inner["hid"], expect=422)["status"] == 422


def test_an_item_that_runs_on_a_host_is_installed_in_nothing(lab: Lab) -> None:
    vm = lab.vm(host_item_hid=lab.esx["hid"])
    problem = lab.patch(vm, 422, parent_item_hid=lab.esx2["hid"])
    assert "clear its host first" in errors(problem)["parent_item_hid"]


def test_a_model_is_not_made_a_kind_that_runs_on_nothing_while_an_item_of_it_has_a_host(
    lab: Lab,
) -> None:
    lab.vm(host_item_hid=lab.esx["hid"])
    model = lab.vm_model
    body = {"row_version": model["row_version"], "kind": "hardware"}
    problem = lab.make.patch(f"/catalog-entries/{model['hid']}", body, 422)
    assert "site2-vm-app01" in errors(problem)["kind"]
    # Another kind that runs on a host is let through.
    body["kind"] = "container"
    assert lab.make.patch(f"/catalog-entries/{model['hid']}", body)["kind"] == "container"


def test_the_host_seen_is_an_observation_with_its_moment(lab: Lab) -> None:
    vm = lab.vm(host_group_hid=lab.cluster["hid"], observed_host_hid=lab.esx2["hid"])
    assert vm["observed_host"]["hid"] == lab.esx2["hid"]
    assert vm["host_observed_at"] is not None
    # A current member of the cluster named agrees with it.
    assert vm["host_differs"] is False

    on_server = lab.patch(vm, host_item_hid=lab.esx["hid"])
    assert on_server["host_differs"] is True
    seen = lab.patch(
        on_server, observed_host_hid=lab.esx["hid"], host_observed_at="2026-11-01T10:00:00Z"
    )
    assert (seen["host_differs"], seen["host_observed_at"]) == (False, "2026-11-01T10:00:00Z")
    cleared = lab.patch(seen, observed_host_hid=None)
    assert (cleared["observed_host"], cleared["host_observed_at"], cleared["host_differs"]) == (
        None,
        None,
        None,
    )
    problem = lab.patch(cleared, 422, observed_host_hid=cleared["hid"])
    assert "itself" in errors(problem)["observed_host_hid"]


def test_a_view_only_user_is_refused_a_host(lab: Lab, client, viewer) -> None:
    vm = lab.vm()
    response = client.patch(
        f"{API}/items/{vm['hid']}",
        json={"row_version": vm["row_version"], "host_item_hid": lab.esx["hid"]},
        headers=viewer,
    )
    assert response.status_code == 403


def test_a_virtual_context_shows_its_hosts_serial_number_and_is_never_found_by_it(
    lab: Lab,
) -> None:
    vdc = lab.vdc(host_item_hid=lab.n7k["hid"])
    assert vdc["serial_number"] is None
    assert vdc["effective"]["serial_number"] == {
        "value": "JAF0000X001",
        "source": "host",
        "source_hid": lab.n7k["hid"],
    }
    # A machine shows none but its own, and the switch its own.
    vm = lab.vm(host_item_hid=lab.esx["hid"])
    assert vm["effective"]["serial_number"] == {"value": None, "source": "none", "source_hid": None}
    assert lab.get(lab.n7k)["effective"]["serial_number"]["source"] == "own"
    # It is not stored, nor what a filter finds the context by.
    found = lab.make.get("/items", filter="serial_number:eq:JAF0000X001")["items"]
    assert [row["hid"] for row in found] == [lab.n7k["hid"]]
    # One given a serial number of its own shows that.
    own = lab.patch(vdc, serial_number="VDC0000X002")
    assert own["effective"]["serial_number"]["source"] == "own"
