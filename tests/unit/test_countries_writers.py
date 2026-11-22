"""A change of the lists of countries and states takes the one writer's place before it
looks at what the addresses hold, as a change of a place does before it looks at the
lists: of a site saved with a country and an Admin removing that country at the same
moment, the second waits and then sees the first (the review of 0.9.18, finding 6)."""

from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy.orm import Session

from hirdir.auth.roles import Role
from hirdir.db import dialect
from hirdir.db.models import Country, State
from hirdir.domain import audit, countries

ADMIN = Role.ADMIN


def _land(db: Session) -> tuple[Country, State]:
    land = countries.create_country(db, audit.SYSTEM, {"code": "XA", "name": "Example"}, ADMIN)
    north = countries.create_state(
        db, audit.SYSTEM, {"country": "XA", "code": "N", "name": "North"}, ADMIN
    )
    db.flush()
    return land, north


@pytest.mark.parametrize(
    "change",
    [
        lambda db, land, north: countries.update_country(
            db, audit.SYSTEM, land.hid, land.row_version, {"code": "XB"}, ADMIN
        ),
        lambda db, land, north: countries.delete_country(db, audit.SYSTEM, land.hid, ADMIN),
        lambda db, land, north: countries.update_state(
            db, audit.SYSTEM, north.hid, north.row_version, {"code": "S"}, ADMIN
        ),
        lambda db, land, north: countries.delete_state(db, audit.SYSTEM, north.hid, ADMIN),
    ],
    ids=["update_country", "delete_country", "update_state", "delete_state"],
)
def test_the_writers_place_is_taken_before_what_addresses_hold_is_read(
    db: Session, monkeypatch: pytest.MonkeyPatch, change: Callable[..., Any]
) -> None:
    land, north = _land(db)
    said: list[str] = []
    hold, holders = dialect.hold_other_writers, countries._holders

    def held_first(session: Any) -> None:
        said.append("hold")
        hold(session)

    def looked(session: Session, holds: Any) -> tuple[int, str]:
        said.append("look")
        return holders(session, holds)

    monkeypatch.setattr(dialect, "hold_other_writers", held_first)
    monkeypatch.setattr(countries, "_holders", looked)
    change(db, land, north)
    assert "look" in said
    assert said[0] == "hold"


@pytest.mark.parametrize(
    ("make", "checked"),
    [
        (
            lambda db: countries.create_country(
                db, audit.SYSTEM, {"code": "XC", "name": "Another Example"}, ADMIN
            ),
            "_checked_country",
        ),
        (
            lambda db: countries.create_state(
                db, audit.SYSTEM, {"country": "XA", "code": "S", "name": "South"}, ADMIN
            ),
            "_checked_state",
        ),
    ],
    ids=["create_country", "create_state"],
)
def test_a_country_or_a_state_is_added_holding_the_writers_place(
    db: Session, monkeypatch: pytest.MonkeyPatch, make: Callable[..., Any], checked: str
) -> None:
    """A state added while its country is removed or recoded, on PostgreSQL, would
    otherwise be left with a country that is no longer there (the second review of
    0.9.18)."""
    _land(db)
    said: list[str] = []
    hold, check = dialect.hold_other_writers, getattr(countries, checked)

    def held_first(session: Any) -> None:
        said.append("hold")
        hold(session)

    def looked(*given: Any) -> Any:
        said.append("check")
        return check(*given)

    monkeypatch.setattr(dialect, "hold_other_writers", held_first)
    monkeypatch.setattr(countries, checked, looked)
    make(db)
    assert said[:2] == ["hold", "check"]
