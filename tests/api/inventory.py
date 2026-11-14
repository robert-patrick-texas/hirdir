"""Helpers for the tests of the inventory: short ways to make its records."""

from typing import Any

from fastapi.testclient import TestClient

API = "/api/v1"


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

    def totals(self, **params: Any) -> dict[str, Any]:
        return self.get("/reports/summary", **params)["totals"]

    def found(self, path: str = "/items", **params: Any) -> list[str]:
        """Return what a list shows: the name, hostname or serial number of each row."""
        page = self.get(path, **params)
        return [row["name"] or row["hostname"] or row["serial_number"] for row in page["items"]]

    def audit(self, **params: Any) -> list[dict[str, Any]]:
        return self.get("/audit-events", **params)["items"]


def errors(problem: dict[str, Any]) -> dict[str, str]:
    """Return a problem's field errors as a mapping."""
    return {entry["field"]: entry["message"] for entry in problem["errors"]}
