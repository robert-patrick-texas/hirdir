"""The coordinates of a place open a map, at an address that the setting `map_link`
names (P-229, P-236)."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.api.inventory import API, Maker, errors

GOOGLE = "https://www.google.com/maps/search/?api=1&query={latitude},{longitude}"
OTHER = "https://maps.example.net/view?mlat={latitude}&mlon={longitude}&zoom=17"


def _put(
    client: TestClient, headers: dict[str, str], value: Any, expect: int = 200
) -> dict[str, Any]:
    now = {one["key"]: one for one in client.get(f"{API}/settings", headers=headers).json()}
    body = {"row_version": now["map_link"]["row_version"], "value": value}
    response = client.put(f"{API}/settings/map_link", json=body, headers=headers)
    assert response.status_code == expect, response.text
    return response.json()


def test_a_site_and_a_location_answer_the_address_of_a_map_at_their_coordinates(
    client: TestClient, make: Maker, admin: dict[str, str]
) -> None:
    region = make.region("Americas")
    site = make.site("Site-2", region, latitude="41.8781", longitude="-87.6298")
    room = make.location("Room 102", site, latitude="41.878412", longitude="-87.629001")
    bare = make.location("Store Room", site)

    assert site["map_url"] == (
        "https://www.google.com/maps/search/?api=1&query=41.878100,-87.629800"
    )
    assert make.get(f"/locations/{room['hid']}")["map_url"] == (
        "https://www.google.com/maps/search/?api=1&query=41.878412,-87.629001"
    )
    # Coordinates are not inherited: a place with none of its own has no map.
    assert bare["map_url"] is None
    listed = {one["name"]: one["map_url"] for one in make.get("/locations")["items"]}
    assert listed == {"Room 102": room["map_url"], "Store Room": None}
    assert make.get("/sites")["items"][0]["map_url"] == site["map_url"]
    assert "map_url" not in make.get(f"/regions/{region['hid']}")

    # Another map, set by an Admin, then none, then the one from the start again.
    _put(client, admin, OTHER)
    assert make.get(f"/sites/{site['hid']}")["map_url"] == (
        "https://maps.example.net/view?mlat=41.878100&mlon=-87.629800&zoom=17"
    )
    blank = _put(client, admin, "")
    assert (blank["value"], blank["is_default"]) == ("", False)
    assert make.get(f"/sites/{site['hid']}")["map_url"] is None
    assert make.get(f"/locations/{room['hid']}")["map_url"] is None
    back = _put(client, admin, None)
    assert (back["value"], back["is_default"]) == (GOOGLE, True)
    assert make.get(f"/sites/{site['hid']}")["map_url"] == site["map_url"]
    changes = [event["changes"][0]["new"] for event in make.audit(record_type="setting")]
    assert changes == [None, "", OTHER]


def test_the_setting_is_listed_and_takes_a_web_address_with_both_coordinates_or_blank(
    client: TestClient, admin: dict[str, str], inventory: dict[str, str]
) -> None:
    listed = {one["key"]: one for one in client.get(f"{API}/settings", headers=inventory).json()}
    found = listed["map_link"]
    assert (found["value"], found["default"], found["is_default"]) == (GOOGLE, GOOGLE, True)
    assert "{latitude} and {longitude}" in found["accepts"]
    assert found["meaning"]

    _put(client, inventory, OTHER, 403)
    for wrong in (
        "ftp://maps.example.net/{latitude}/{longitude}",
        "https://maps.example.net/?q={latitude}",
        "https://maps.example.net/?q={longitude}",
        "https://maps.example.net/?q={latitude}, {longitude}",
        "javascript:alert({latitude},{longitude})",
        5,
        ["https://maps.example.net/{latitude}/{longitude}"],
    ):
        refused = _put(client, admin, wrong, 422)
        assert "{latitude} and {longitude}" in errors(refused)["value"], wrong
    assert _put(client, admin, "   ")["value"] == ""


@pytest.mark.parametrize("value", [OTHER, ""])
def test_a_place_without_coordinates_never_has_a_map(
    client: TestClient, make: Maker, admin: dict[str, str], value: str
) -> None:
    _put(client, admin, value)
    site = make.site("Site-3", make.region("Americas"))
    assert site["map_url"] is None
