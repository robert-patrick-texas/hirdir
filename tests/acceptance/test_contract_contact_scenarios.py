"""Scenario S43 of docs/build-plan.md, against a real server process: the contacts of an
agreement and of a contract, linked to contact records."""

from typing import Any

import pytest

from tests.acceptance.conftest import ADMIN, Server
from tests.acceptance.test_geography_scenarios import Geography
from tests.acceptance.test_item_scenarios import IVY


class Desk(Geography):
    """A signed-in Inventory user who enters agreements, contracts and their contacts."""

    def agreement(self, name: str) -> dict[str, Any]:
        cisco = self.get("/vendors", filter="name:eq:Cisco")["items"] or [
            self.post("/vendors", {"name": "Cisco"})
        ]
        body = {"name": name, "vendor_hid": cisco[0]["hid"], "starts_on": "2025-01-01"}
        return self.post("/agreements", body)

    def name(self, record: str, contact: dict[str, Any], role: str) -> dict[str, Any]:
        return self.post(f"{record}/contacts", {"contact_hid": contact["hid"], "role": role})

    def managers(self, record: str) -> dict[str, Any]:
        """Return the account managers a record has in force: who, and from where."""
        found = self.get(record)["effective"]["account_managers"]
        return {
            "names": [one["contact"]["name"] for one in found["value"]],
            "phones": [one["contact"]["phone"] for one in found["value"]],
            "source": found["source"],
            "source_hid": found["source_hid"],
        }


@pytest.fixture
def desk(server: Server) -> Desk:
    admin = server.sign_in(*ADMIN)
    made = admin.post(
        "/users", json={"username": IVY[0], "access_code": IVY[1], "role": "inventory"}
    )
    assert made.status_code == 201, made.text
    return Desk(server.sign_in(*IVY))


def test_s43_a_contract_shows_the_contact_in_force_with_its_source_and_follows_its_record(
    desk: Desk,
) -> None:
    agreement = desk.agreement("Cisco Enterprise Agreement")
    inheriting = desk.post(
        "/contracts", {"number": "CON-2026-0001", "agreement_hid": agreement["hid"]}
    )
    naming = desk.post("/contracts", {"number": "CON-2026-0002", "agreement_hid": agreement["hid"]})
    jordan = desk.post(
        "/contacts",
        {"name": "Jordan Reyes", "email": "jordan.reyes@example.com", "phone": "+1 555 0142"},
    )
    casey = desk.post("/contacts", {"name": "Casey Lund", "email": "casey.lund@example.com"})
    # The account manager of the agreement is a contact record; one contract names another.
    desk.name(f"/agreements/{agreement['hid']}", jordan, "account_manager")
    desk.name(f"/contracts/{naming['hid']}", casey, "account_manager")

    of_agreement = f"/agreements/{agreement['hid']}"
    first, second = f"/contracts/{inheriting['hid']}", f"/contracts/{naming['hid']}"
    assert desk.managers(of_agreement)["source"] == "own"
    assert desk.managers(first) == {
        "names": ["Jordan Reyes"],
        "phones": ["+1 555 0142"],
        "source": "agreement",
        "source_hid": agreement["hid"],
    }
    assert desk.managers(second) == {
        "names": ["Casey Lund"],
        "phones": [None],
        "source": "own",
        "source_hid": naming["hid"],
    }

    # A change of the agreement's contact's telephone number shows on the agreement and on
    # the contract that has it from there; neither record is written to.
    desk.patch(
        f"/contacts/{jordan['hid']}", {"row_version": jordan["row_version"], "phone": "+1 555 0199"}
    )
    assert desk.managers(of_agreement)["phones"] == ["+1 555 0199"]
    assert desk.managers(first)["phones"] == ["+1 555 0199"]
    assert desk.managers(second)["phones"] == [None]
    assert desk.get(first)["row_version"] == inheriting["row_version"]
    assert desk.get(of_agreement)["row_version"] == agreement["row_version"]
