"""The colours a form offers and the one the next operator is given (P-285)."""

from collections import Counter

from fastapi.testclient import TestClient

from hirdir.domain import colours, tags
from tests.api.inventory import Maker

API = "/api/v1"


def test_the_grid_is_64_colours_the_slider_32_of_them_and_each_is_a_colour() -> None:
    assert [len(row) for row in colours.GRID] == [8] * 8
    every = [colour for row in colours.GRID for colour in row]
    assert len(set(every)) == 64
    assert all(tags.COLOUR.fullmatch(colour) for colour in every)
    # A hue is a column, in the order of the rainbow, and a row is a shade.
    assert tuple(row[0] for row in colours.GRID) == colours.HUES[0][1]
    assert colours.GRID[0] == tuple(shades[0] for _, shades in colours.HUES)

    assert len(colours.SLIDER) == len(set(colours.SLIDER)) == 32
    # The four middle shades of each hue, hue after hue.
    assert colours.SLIDER[:4] == colours.HUES[0][1][2:6]
    assert colours.SLIDER[-4:] == colours.HUES[-1][1][2:6]
    # The order a new operator is given a colour in goes through the same 32, and its
    # first eight are of eight hues.
    assert sorted(colours.NEXT_ORDER) == sorted(colours.SLIDER)
    first = set(colours.NEXT_ORDER[:8])
    assert all(len(first & set(shades)) == 1 for _, shades in colours.HUES)


def test_the_next_colour_is_the_first_unused_and_then_the_least_used() -> None:
    order = colours.NEXT_ORDER
    assert colours.next_of(Counter()) == order[0]
    assert colours.next_of(Counter({order[0]: 1, order[2]: 4, "#123456": 9})) == order[1]
    # All taken: the least used, and of those the earliest in the order.
    taken = Counter(dict.fromkeys(order, 2))
    assert colours.next_of(taken) == order[0]
    taken[order[0]] = 3
    taken[order[7]] = 1
    taken[order[9]] = 1
    assert colours.next_of(taken) == order[7]


def test_every_role_reads_the_colours_and_a_retired_operator_frees_its_own(
    make: Maker, client: TestClient, viewer: dict[str, str]
) -> None:
    order = colours.NEXT_ORDER
    answer = make.get("/colours")
    assert answer == {
        "grid": [list(row) for row in colours.GRID],
        "slider": list(colours.SLIDER),
        "next_for_operators": order[0],
    }
    assert client.get(f"{API}/colours", headers=viewer).json() == answer
    assert client.get(f"{API}/colours").status_code == 401

    # A colour typed in capitals is held as the same colour, and one outside the grid
    # takes none of it.
    first = make.post("/operators", {"label": "EX1", "colour": order[0].upper()})
    make.post("/operators", {"label": "EX2", "colour": "#123456"})
    make.post("/operators", {"label": "EX3"})
    assert make.get("/colours")["next_for_operators"] == order[1]
    make.post(f"/operators/{first['hid']}/retire", {"row_version": first["row_version"]}, 200)
    assert make.get("/colours")["next_for_operators"] == order[0]
