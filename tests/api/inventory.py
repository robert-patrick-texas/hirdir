"""Helpers for the tests of the inventory: short ways to make its records."""

import time
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import Session

from hirdir.db.models import Contact

API = "/api/v1"
# An apply is worked by the server's worker in the background (D-185). A test waits for
# it as a person would, looking at the job, for this long at the most, in seconds.
WAIT_FOR_JOB = 60.0


def wait_for_job(client: TestClient, headers: dict[str, str], hid: str) -> dict[str, Any]:
    """Return the job of an import or a bulk edit once it is no longer being applied."""
    deadline = time.monotonic() + WAIT_FOR_JOB
    while True:
        response = client.get(f"{API}/imports/{hid}", headers=headers)
        assert response.status_code == 200, response.text
        job = response.json()
        if job["status"] not in ("queued", "applying"):
            return job
        assert time.monotonic() < deadline, f"the job {hid} is still {job['status']}"
        time.sleep(0.01)


class Maker:
    """Makes records through the API as one signed-in user."""

    def __init__(self, client: TestClient, headers: dict[str, str]) -> None:
        self.client = client
        self.headers = headers

    def post(self, path: str, body: dict[str, Any], expect: int = 201) -> dict[str, Any]:
        response = self.client.post(API + path, json=body, headers=self.headers)
        assert response.status_code == expect, response.text
        return response.json()

    def patch(self, path: str, body: dict[str, Any], expect: int = 200) -> dict[str, Any]:
        response = self.client.patch(API + path, json=body, headers=self.headers)
        assert response.status_code == expect, response.text
        return response.json()

    def get(self, path: str, expect: int = 200, **params: Any) -> Any:
        response = self.client.get(API + path, params=params, headers=self.headers)
        assert response.status_code == expect, response.text
        return response.json()

    def apply(self, path: str, expect: int = 202, **params: Any) -> dict[str, Any]:
        """Apply a stored preview at path, and return its job once it has been applied.

        An apply answers at once, with 202, and is worked in the background. A refusal
        is returned as it is.
        """
        response = self.client.post(API + path, params=params, headers=self.headers)
        assert response.status_code == expect, response.text
        if expect != 202:
            return response.json()
        return wait_for_job(self.client, self.headers, response.json()["hid"])

    def vendor(self, name: str = "Cisco", **more: Any) -> dict[str, Any]:
        return self.post("/vendors", {"name": name, **more})

    def entry(self, vendor: dict[str, Any], pid: str = "C9300-48P", **more: Any) -> dict[str, Any]:
        return self.post("/catalog-entries", {"vendor_hid": vendor["hid"], "pid": pid, **more})

    def owner(self, label: str = "Network Engineering", **more: Any) -> dict[str, Any]:
        return self.post("/owners", {"label": label, **more})

    def tag(self, label: str, **more: Any) -> dict[str, Any]:
        return self.post("/tags", {"label": label, **more})

    def item(self, **fields: Any) -> dict[str, Any]:
        return self.post("/items", fields)

    def move(
        self, item: dict[str, Any], to: str | None, expect: int = 200, **more: Any
    ) -> dict[str, Any]:
        body = {"to": to, "row_version": item["row_version"], **more}
        return self.post(f"/items/{item['hid']}/transition", body, expect)

    def delete(self, path: str, expect: int = 204) -> None:
        response = self.client.delete(API + path, headers=self.headers)
        assert response.status_code == expect, response.text

    def switches(
        self, entry: dict[str, Any], prefix: str, count: int, **more: Any
    ) -> list[dict[str, Any]]:
        """Make count items of one model, with serial numbers and hostnames from prefix."""
        return [
            self.item(
                catalog_entry_hid=entry["hid"],
                serial_number=f"{prefix.upper()}-{number:03d}",
                hostname=f"{prefix}-{number:02d}",
                **more,
            )
            for number in range(1, count + 1)
        ]

    def group(
        self, name: str, type_: str = "stack", members: Any = (), expect: int = 201, **more: Any
    ) -> dict[str, Any]:
        """Make a device group. Members are (item, role) or (item, role, position)."""
        listed = [
            {"item_hid": member[0]["hid"], "role": member[1], "position": place}
            for place, member in enumerate(members, start=1)
        ]
        body = {"type": type_, "name": name, "members": listed, **more}
        return self.post("/device-groups", body, expect)

    def stack(self, name: str, members: list[dict[str, Any]], **more: Any) -> dict[str, Any]:
        """Make a stack whose first member is the master."""
        roles = [
            (member, "master" if place == 0 else "member") for place, member in enumerate(members)
        ]
        return self.group(name, "stack", roles, **more)

    def add(self, group: dict[str, Any], members: list[dict[str, Any]], expect: int = 201) -> Any:
        """Add members to a group together. Returns the memberships, or the problem."""
        response = self.client.post(
            f"{API}/device-groups/{group['hid']}/members",
            json={"members": members},
            headers=self.headers,
        )
        assert response.status_code == expect, response.text
        return response.json()

    def members(self, group: dict[str, Any], **params: Any) -> list[dict[str, Any]]:
        return self.get(f"/device-groups/{group['hid']}/members", **params)["items"]

    def network(self, label: str, kind: str = "vrf") -> dict[str, Any]:
        return self.post("/networks", {"label": label, "kind": kind})

    def address(
        self,
        holder: dict[str, Any],
        address: str,
        network: dict[str, Any] | None = None,
        expect: int = 201,
        **more: Any,
    ) -> dict[str, Any]:
        """Give an item, or a group, an address."""
        whose = "group_hid" if "member_count" in holder else "item_hid"
        body = {whose: holder["hid"], "address": address, **more}
        if network is not None:
            body["network_hid"] = network["hid"]
        return self.post("/addresses", body, expect)

    def region(self, name: str, parent: dict[str, Any] | None = None, **more: Any) -> dict:
        body = {"name": name, "parent_region_hid": parent["hid"] if parent else None, **more}
        return self.post("/regions", body)

    def site(self, name: str, region: dict[str, Any], **more: Any) -> dict[str, Any]:
        return self.post("/sites", {"name": name, "region_hid": region["hid"], **more})

    def location(
        self,
        name: str,
        site: dict[str, Any] | None = None,
        parent: dict[str, Any] | None = None,
        expect: int = 201,
        **more: Any,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"name": name, **more}
        if site is not None:
            body["site_hid"] = site["hid"]
        if parent is not None:
            body["parent_location_hid"] = parent["hid"]
        return self.post("/locations", body, expect)

    def layout(self) -> dict[str, dict[str, Any]]:
        """Make `Americas > Central`, Site-2, Building 1 and Room 102 within it."""
        americas = self.region("Americas")
        central = self.region("Central", americas)
        site = self.site("Site-2", central)
        building = self.location("Building 1", site, kind="building")
        room = self.location("Room 102", parent=building, kind="room")
        return {
            "americas": americas,
            "central": central,
            "site": site,
            "building": building,
            "room": room,
        }

    def contact(self, name: str, **more: Any) -> dict[str, Any]:
        email = f"{name.lower().replace(' ', '.')}@example.net"
        return self.post("/contacts", {"name": name, "email": email, **more})

    def assign(
        self, contact: dict[str, Any] | None, role: str, expect: int = 201, **place: Any
    ) -> dict[str, Any]:
        body = {"role": role, **place}
        if contact is not None:
            body["contact_hid"] = contact["hid"]
        return self.post("/contact-assignments", body, expect)

    def in_force(self, place: dict[str, Any], level: str = "locations") -> dict[str, Any]:
        """Return what a place has in force, with its contacts by role."""
        found = self.get(f"/{level}/{place['hid']}/effective")
        found["by_role"] = {one["role"]: one for one in found["contacts"]}
        return found

    def totals(self, **params: Any) -> dict[str, Any]:
        return self.get("/reports/summary", **params)["totals"]

    def found(self, path: str = "/items", **params: Any) -> list[str]:
        """Return what a list shows: the name, hostname or serial number of each row."""
        page = self.get(path, **params)
        return [row["name"] or row["hostname"] or row["serial_number"] for row in page["items"]]

    def audit(self, **params: Any) -> list[dict[str, Any]]:
        return self.get("/audit-events", **params)["items"]

    def release(self, operator: dict[str, Any], expect: int = 200) -> dict[str, Any]:
        """Retire an operator and keep everything linked to it that is not retired: its
        contact, the user that contact is and the other operators of that contact, each
        of which a retirement is to say (P-297)."""
        path = f"/operators/{operator['hid']}"
        person = self.get(f"{path}/linked")
        linked: dict[str, Any] = {
            "operators": [
                {"hid": one["hid"], "action": "keep"}
                for one in person["operators"]
                if one["hid"] != operator["hid"] and one["record_status"] != "retired"
            ]
        }
        for name in ("user", "contact"):
            if person[name] is not None and person[name]["record_status"] != "retired":
                linked[name] = "keep"
        body = {"row_version": self.get(path)["row_version"], "linked": linked}
        return self.post(f"{path}/retire", body, expect)


def left_retired(db: Session, contact_hid: str) -> None:
    """Leave a contact retired under the account or the label that stands on it, as a
    release before 0.9.14 could. From 0.9.14 a retirement says what becomes of each, and
    a contact is not retired so (P-297); what was left so before is still read."""
    db.execute(update(Contact).where(Contact.hid == contact_hid).values(record_status="retired"))
    db.commit()


def errors(problem: dict[str, Any]) -> dict[str, str]:
    """Return a problem's field errors as a mapping."""
    return {entry["field"]: entry["message"] for entry in problem["errors"]}
