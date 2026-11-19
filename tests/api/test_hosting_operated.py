"""What an operator is on adds up where items have it from what they run on (P-246, P-177)."""

from tests.api.inventory import Maker
from tests.api.test_hosting import Lab


def test_what_has_its_operator_from_its_host_counts_from_an_item(make: Maker) -> None:
    lab = Lab(make)
    op = make.post("/operators", {"label": "OP2"})
    esx = make.get(f"/items/{lab.esx['hid']}")
    make.patch(
        f"/items/{esx['hid']}", {"row_version": esx["row_version"], "operator_hid": op["hid"]}
    )
    vm = lab.vm(host_item_hid=lab.esx["hid"])
    lab.ctr(host_item_hid=vm["hid"])
    lab.make.item(name="site2-esx-01-psu1", parent_item_hid=lab.esx["hid"])

    found = make.get(f"/operators/{op['hid']}/assignments")
    assert found["totals"]["count"] == 4
    assert (found["own"]["count"], found["from_item"]["count"]) == (1, 3)
    parts = found["own"]["count"] + found["from_item"]["count"]
    parts += sum(one["items"]["count"] for one in (*found["places"], *found["groups"]))
    assert parts == found["totals"]["count"]
    # The filter it gives lists the same items.
    listed = make.post(
        "/items/query", {"filter": found["from_item"]["filter"], "limit": 100}, expect=200
    )
    assert listed["total"] == 3
    shortly = make.get(
        "/items", filter="effective.operator_hid.source:in:parent_item,host", limit=100
    )
    assert shortly["total"] == 3
    # The report by operator counts them so too.
    rows = make.get("/reports/summary", by="operator")["rows"]
    row = next(one for one in rows if one["key"] == op["hid"])
    assert (row["own"], row["from_item"]) == (1, 3)
