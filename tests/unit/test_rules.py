"""The parts of the item rules that can be tried without the API."""

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from hirdir.auth.roles import Role
from hirdir.db import dialect
from hirdir.db.models import CatalogEntry, Choice, Item, LifecycleRule, Scaled
from hirdir.domain import inheritance, lifecycle
from hirdir.domain.errors import Invalid, NotAllowed
from hirdir.domain.items import mac_digits
from hirdir.domain.lifecycle import UNSET


@pytest.mark.parametrize(
    "written",
    [
        "00:00:5E:00:53:01",
        "00-00-5e-00-53-01",
        "0000.5e00.5301",
        "00005E005301",
        " 00 00 5e 00 53 01 ",
    ],
)
def test_mac_address_is_read_in_any_common_notation(written: str) -> None:
    assert mac_digits(written) == "00005e005301"


def test_part_of_a_mac_address_is_read_for_searching() -> None:
    assert mac_digits("5E:00") == "5e00"
    for bad in ("", "::", "5g", "00005e0053011"):
        with pytest.raises(ValueError, match="twelve hex digits"):
            mac_digits(bad)


def test_decimals_are_stored_as_whole_steps() -> None:
    money = Scaled(2)
    assert money.process_bind_param(Decimal("18000.5"), None) == 1800050
    assert money.process_result_value(1800050, None) == Decimal("18000.50")
    assert str(money.process_result_value(1800000, None)) == "18000.00"
    assert money.process_bind_param(None, None) is None
    with pytest.raises(ValueError, match="2 decimal places"):
        money.process_bind_param(Decimal("0.001"), None)


def test_migration_loads_the_rules_and_the_choices(db: Session) -> None:
    states = list(db.scalars(select(LifecycleRule.state).order_by(LifecycleRule.sort)))
    assert tuple(states) == lifecycle.STATES
    lists = set(db.scalars(select(Choice.list_name)))
    assert lists == {"catalog_type", "catalog_function", "state_reason", "replacement_reason"}
    for rule in lifecycle.list_rules(db):
        assert set(rule.next_states) <= set(lifecycle.STATES)
        assert set(rule.must_be_online) <= set(rule.may_be_online)
        assert rule.entry_disposition is None or rule.entry_disposition in rule.dispositions


# The table of docs/data-model.md, one row for each combination worth naming.
STANDINGS = [
    ("Purchased", None, False, True),
    ("Purchased", None, True, False),
    ("Purchased", "Staging", False, False),
    ("Delivered", None, False, True),
    ("Assigned", "Staging", False, True),
    ("Assigned", "Spare", False, True),
    ("Assigned", "Excess", False, True),
    ("Assigned", "Excess", True, False),
    ("Assigned", "Production", False, False),
    ("Assigned", None, False, False),
    ("Test", "Staging", True, True),
    ("Test", "Staging", False, True),
    ("Test", "Spare", False, False),
    ("Prod", "Production", True, True),
    ("Prod", "Production", False, False),
    ("Prod", "Spare", True, True),
    ("Prod", "Spare", False, True),
    ("Prod", "Excess", False, False),
    ("Prod", "Staging", True, False),
    ("Released", None, False, True),
    ("Archived", "Excess", False, False),
]


@pytest.mark.parametrize(("state", "disposition", "online", "allowed"), STANDINGS)
def test_combinations_the_default_rules_allow(
    db: Session, state: str, disposition: str | None, online: bool, allowed: bool
) -> None:
    errors = lifecycle.standing_errors(lifecycle.rule_of(db, state), disposition, online, None)
    assert (errors == {}) is allowed, errors


def test_states_that_keep_the_disposition_allow_the_one_brought_in(db: Session) -> None:
    down, removal = lifecycle.rule_of(db, "Down"), lifecycle.rule_of(db, "Pending-Removal")
    assert lifecycle.standing_errors(down, "Spare", False, "Spare") == {}
    assert "disposition" in lifecycle.standing_errors(down, "Production", False, "Spare")
    assert "disposition" in lifecycle.standing_errors(down, None, False, "Spare")
    assert "expected_online" in lifecycle.standing_errors(down, "Spare", True, "Spare")
    assert lifecycle.standing_errors(down, None, False, None) == {}
    assert lifecycle.standing_errors(removal, "Excess", False, "Production") == {}
    assert lifecycle.standing_errors(removal, "Production", False, "Production") == {}
    assert "disposition" in lifecycle.standing_errors(removal, "Spare", False, "Production")


@pytest.mark.parametrize(
    ("state", "current", "expected"),
    [
        ("Delivered", None, (None, False)),
        ("Assigned", None, ("Staging", False)),
        ("Assigned", "Excess", ("Excess", False)),
        ("Test", "Staging", ("Staging", True)),
        ("Test", "Spare", ("Staging", True)),
        ("Prod", "Staging", ("Production", True)),
        ("Prod", "Spare", ("Spare", True)),
        ("Down", "Production", ("Production", False)),
        ("Pending-Removal", "Spare", ("Spare", False)),
        ("Released", "Excess", (None, False)),
    ],
)
def test_standing_on_entry(db: Session, state: str, current: str | None, expected: tuple) -> None:
    assert lifecycle.entry_standing(lifecycle.rule_of(db, state), current) == expected


def test_what_the_caller_names_on_entry_is_taken_as_given(db: Session) -> None:
    prod = lifecycle.rule_of(db, "Prod")
    assert lifecycle.entry_standing(prod, "Staging", "Spare", False) == ("Spare", False)
    assert lifecycle.entry_standing(prod, "Staging", "Spare", UNSET) == ("Spare", True)
    assert lifecycle.entry_standing(prod, "Staging", None, UNSET) == (None, False)


def test_moves(db: Session) -> None:
    def move(current: str | None, to: str, **more: object) -> bool:
        options = {"force": False, "role": Role.INVENTORY, "reason": None, **more}
        return lifecycle.check_move(db, current, to, **options)

    assert move("Delivered", "Assigned") is False
    assert move(None, "Prod") is False
    assert move("Pending-Removal", "Assigned") is False
    for current, to in (("Delivered", "Prod"), ("Archived", "Prod"), ("Prod", "Test")):
        with pytest.raises(Invalid):
            move(current, to)
        with pytest.raises(NotAllowed):
            move(current, to, force=True, reason="correction")
        with pytest.raises(Invalid):
            move(current, to, force=True, role=Role.ADMIN)
        assert move(current, to, force=True, role=Role.ADMIN, reason="correction") is True
    with pytest.raises(Invalid):
        move("Prod", "Prod", force=True, role=Role.ADMIN, reason="correction")


def test_spelling_of_states_and_dispositions() -> None:
    assert lifecycle.state_name(" pending-removal ") == "Pending-Removal"
    assert lifecycle.disposition_name("SPARE") == "Spare"
    for bad in ("", "Pending Removal", None, 3):
        with pytest.raises(Invalid):
            lifecycle.state_name(bad)


def test_item_value_in_force_is_its_own_then_the_catalogs_then_nothing() -> None:
    entry = CatalogEntry(hid="entry", est_value=Decimal("18000.00"), support_weight=Decimal("1"))
    item = Item(hid="item", est_value=Decimal("21000.00"))
    effective = inheritance.of_item(item, entry)
    assert effective["est_value"] == inheritance.Effective(Decimal("21000.00"), "own", "item")
    assert effective["support_weight"] == inheritance.Effective(Decimal("1"), "catalog", "entry")
    assert effective["ldos"] == inheritance.NOTHING
    assert all(
        value == inheritance.NOTHING for value in inheritance.of_item(Item(hid="x"), None).values()
    )
    # Zero is a value of its own and does not inherit.
    free = inheritance.of_item(Item(hid="item", est_value=Decimal("0")), entry)
    assert free["est_value"].source == "own"


def test_pattern_limits() -> None:
    assert dialect.regex_search("^SITE2-", "site2-sw-core-01") is True
    assert dialect.regex_search("core$", "site2-sw-core-01") is False
    with pytest.raises(dialect.PatternError, match="at most 200"):
        dialect.compile_pattern("a" * 201)
    with pytest.raises(dialect.PatternError, match="cannot be compiled"):
        dialect.compile_pattern("(")
    with pytest.raises(TimeoutError):
        dialect.regex_search("(a|aa)+$", "a" * 5000 + "b")


def test_request_budget_is_shared_by_every_match() -> None:
    with dialect.regex_budget(0.2) as budget:
        assert dialect.regex_search("a", "a") is True
        assert 0 < budget.spent < 0.2
        budget.spent = 0.2
        with pytest.raises(TimeoutError):
            dialect.regex_search("a", "a")
        assert "too long" in budget.failure
    # Outside a budget only the limit of one match applies.
    assert dialect.regex_search("a", "a") is True


def test_one_match_never_runs_past_what_is_left_of_the_budget() -> None:
    with dialect.regex_budget(0.01) as budget, pytest.raises(TimeoutError):
        dialect.regex_search("(a|aa)+$", "a" * 5000 + "b")
    assert budget.spent < dialect.REGEX_MATCH_SECONDS
    assert "too long" in budget.failure


def test_a_moment_is_shown_in_the_applications_time_zone() -> None:
    from datetime import UTC, datetime

    from hirdir import clock

    winter = datetime(2026, 1, 31, 19, 5, 9, tzinfo=UTC)
    summer = datetime(2026, 7, 31, 18, 5, 9, tzinfo=UTC)
    assert clock.DEFAULT_ZONE == "America/New_York"
    assert clock.shown(winter) == "2026-01-31 14:05:09 EST"
    assert clock.shown(summer) == "2026-07-31 14:05:09 EDT"
    assert clock.shown(winter, "Europe/Berlin") == "2026-01-31 20:05:09 CET"


def test_a_stamp_in_a_file_name_is_read_back_whatever_zone_wrote_it() -> None:
    from datetime import UTC, datetime

    from hirdir import clock

    moment = datetime(2026, 11, 13, 2, 0, 0, tzinfo=UTC)
    assert clock.stamp(moment) == "20261112T210000-0500"
    assert clock.stamp(moment, "Europe/Berlin") == "20261113T030000+0100"
    for name in (
        "hirdir-20261112T210000-0500.db",
        "hirdir-20261113T030000+0100.db",
        "hirdir-20261113T020000Z.db",
    ):
        assert clock.of_stamp(name) == moment, name
    assert clock.of_stamp("hirdir-by-hand.db") is None
    # The hour that comes twice when the clocks go back gives two names, in order.
    first = datetime(2026, 11, 1, 5, 30, tzinfo=UTC)
    second = datetime(2026, 11, 1, 6, 30, tzinfo=UTC)
    assert clock.stamp(first) == "20261101T013000-0400"
    assert clock.stamp(second) == "20261101T013000-0500"
