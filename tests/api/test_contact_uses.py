"""Where a contact is named (P-205): `GET /contacts/{hid}/uses` lists, by kind, every
record that names a contact, and holds the very numbers the list of contacts counts."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from hirdir.app import create_app
from hirdir.config import Config
from hirdir.db import migrate
from hirdir.db.engine import make_engine, make_sessions
from hirdir.domain import accounts, audit, contacts
from hirdir.io import examples
from tests.api.inventory import Maker
from tests.conftest import VIEWER_CODE, sign_in

KINDS = ("places", "owners", "operators", "agreements", "contracts", "vendors", "circuits")


@pytest.fixture(scope="module")
def stocked(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Maker]:
    """The fictional examples, loaded once for this module, read by a View-only user."""
    config = Config(state_dir=tmp_path_factory.mktemp("uses"), trusted_proxies=("testclient",))
    migrate.upgrade(config.database_url)
    with make_sessions(make_engine(config.database_url))() as session:
        examples.load(session, examples.folder())
        user, _ = accounts.create_user(
            session, audit.SYSTEM, username="vic", access_code=VIEWER_CODE
        )
        accounts.grant_role(session, audit.SYSTEM, role="viewer", user_hid=user.hid)
        session.commit()
    with TestClient(create_app(config)) as client:
        yield Maker(client, sign_in(client, "vic", VIEWER_CODE))


def test_what_each_contact_of_the_examples_is_named_by_is_what_its_record_counts(
    stocked: Maker,
) -> None:
    listed = stocked.get("/contacts", limit=1000, include_archived="true", include_drafts="true")
    assert listed["total"] == len(listed["items"]) > 0
    named_somewhere = 0
    for contact in listed["items"]:
        uses = stocked.get(f"/contacts/{contact['hid']}/uses")
        assert uses["contact_hid"] == contact["hid"]
        assert uses["total"] == contact["uses"], contact["name"]
        assert sum(uses[kind]["total"] for kind in KINDS) == contact["uses"]
        for kind in KINDS:
            # No contact of the examples is named by more of a kind than are listed.
            assert len(uses[kind]["records"]) == uses[kind]["total"], (contact["name"], kind)
        named_somewhere += contact["uses"] > 0
    assert named_somewhere > 0


def test_every_kind_names_its_records_with_the_role_the_contact_has_there(
    make: Maker,
) -> None:
    person = make.contact("Example Named")
    region = make.region("Example North")
    site = make.site("Example Yard", region)
    make.assign(person, "technical", site_hid=site["hid"])
    make.assign(person, "escalation", region_hid=region["hid"])
    owner = make.owner("Example Owners")
    make.post(f"/owners/{owner['hid']}/members", {"contact_hid": person["hid"]})
    operator = make.post(
        "/operators", {"label": "ex-ops", "contact_hid": person["hid"], "colour": "#336699"}
    )
    vendor = make.vendor("Example Carrier")
    agreement = make.post("/agreements", {"name": "Example Cover", "vendor_hid": vendor["hid"]})
    contract = make.post(
        "/contracts", {"number": "EX-1001", "vendor_hid": vendor["hid"], "starts_on": "2026-01-01"}
    )
    for path, role in (
        (f"/agreements/{agreement['hid']}/contacts", "account_manager"),
        (f"/contracts/{contract['hid']}/contacts", "support_contact"),
        (f"/vendors/{vendor['hid']}/contacts", "support_contact"),
    ):
        make.post(path, {"contact_hid": person["hid"], "role": role})
    uses = make.get(f"/contacts/{person['hid']}/uses")
    assert uses["total"] == make.get(f"/contacts/{person['hid']}")["uses"] == 7

    def shown(kind: str) -> list[tuple]:
        return [
            (one["record_type"], one["hid"], one["label"], one["role"])
            for one in uses[kind]["records"]
        ]

    # Places by their paths, each with its role.
    assert shown("places") == [
        ("region", region["hid"], "Example North", "escalation"),
        ("site", site["hid"], "Example North > Example Yard", "technical"),
    ]
    assert shown("owners") == [("owner", owner["hid"], "Example Owners", "primary")]
    assert shown("operators") == [("operator", operator["hid"], "ex-ops", None)]
    assert uses["operators"]["records"][0]["colour"] == "#336699"
    assert shown("agreements") == [
        ("agreement", agreement["hid"], "Example Cover", "account_manager")
    ]
    assert shown("contracts") == [
        ("contract", contract["hid"], "EX-1001 (Example Carrier)", "support_contact")
    ]
    assert shown("vendors") == [("vendor", vendor["hid"], "Example Carrier", "support_contact")]
    assert uses["circuits"] == {"total": 0, "records": []}

    # A retired record is named as the count counts it, and says that it is retired.
    retired = make.post(
        f"/operators/{operator['hid']}/retire", {"row_version": operator["row_version"]}, 200
    )
    assert retired["record_status"] == "retired"
    after = make.get(f"/contacts/{person['hid']}/uses")
    assert after["total"] == 7
    assert after["operators"]["records"][0]["record_status"] == "retired"


def test_a_contact_named_by_many_lists_at_most_a_page_of_each_kind_and_says_how_many(
    make: Maker, monkeypatch: pytest.MonkeyPatch
) -> None:
    person = make.contact("Example Busy")
    for place in range(3):
        make.post("/operators", {"label": f"ex-busy-{place}", "contact_hid": person["hid"]})
    monkeypatch.setattr(contacts, "MAX_NAMED", 2)
    uses = make.get(f"/contacts/{person['hid']}/uses")
    assert uses["operators"]["total"] == 3
    assert [one["label"] for one in uses["operators"]["records"]] == ["ex-busy-0", "ex-busy-1"]
    assert uses["total"] == 3


def test_there_is_no_uses_of_a_contact_that_is_not_there(make: Maker) -> None:
    make.get("/contacts/no-such-contact/uses", 404)
