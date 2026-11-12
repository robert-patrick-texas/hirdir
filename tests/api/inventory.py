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

    def move(self, item: dict[str, Any], to: str, expect: int = 200, **more: Any) -> dict[str, Any]:
        body = {"to": to, "row_version": item["row_version"], **more}
        return self.post(f"/items/{item['hid']}/transition", body, expect)

    def found(self, path: str = "/items", **params: Any) -> list[str]:
        """Return what a list shows: the name, hostname or serial number of each row."""
        page = self.get(path, **params)
        return [row["name"] or row["hostname"] or row["serial_number"] for row in page["items"]]

    def audit(self, **params: Any) -> list[dict[str, Any]]:
        return self.get("/audit-events", **params)["items"]


def errors(problem: dict[str, Any]) -> dict[str, str]:
    """Return a problem's field errors as a mapping."""
    return {entry["field"]: entry["message"] for entry in problem["errors"]}
