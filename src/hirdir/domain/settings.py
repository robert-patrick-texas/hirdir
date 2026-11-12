"""Settings: the installation-wide values that people change in the course of work.

Each setting has a default written here. The database keeps a row only for a setting
that has been given a value, so a default that a later release changes is not held back
by a copy made at install time.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from hirdir.db.models import Setting
from hirdir.domain import lifecycle, records
from hirdir.domain.audit import AuditContext
from hirdir.domain.errors import Invalid, NotFound

CATALOG_KINDS = ("hardware", "virtual_machine", "software", "service")


def _refuse(key: str, expected: str) -> Invalid:
    return Invalid(f"the value of {key} is not acceptable", {"value": expected})


def _number(key: str, low: Decimal, high: Decimal | None, above_low: bool = False) -> Callable:
    expected = f"a number from {low} to {high}" if high is not None else f"a number above {low}"

    def check(value: Any) -> Any:
        if isinstance(value, bool) or not isinstance(value, int | float | str):
            raise _refuse(key, expected)
        try:
            number = Decimal(str(value).strip())
        except InvalidOperation:
            raise _refuse(key, expected) from None
        too_low = number <= low if above_low else number < low
        if not number.is_finite() or too_low or (high is not None and number > high):
            raise _refuse(key, expected)
        number = number.quantize(Decimal("0.01"))
        return int(number) if number == number.to_integral_value() else float(number)

    return check


def _month(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 12:
        raise _refuse("fiscal_year_start_month", "a month number from 1 to 12")
    return value


def _currency(value: Any) -> str:
    code = value.strip().upper() if isinstance(value, str) else ""
    if len(code) != 3 or not code.isascii() or not code.isalpha():
        raise _refuse("currency", "a three-letter currency code, such as USD")
    return code


def _subset(key: str, allowed: tuple[str, ...]) -> Callable:
    expected = f"a list of one or more of {', '.join(allowed)}"

    def check(value: Any) -> list[str]:
        if not isinstance(value, list) or not value:
            raise _refuse(key, expected)
        by_key = {records.key(name): name for name in allowed}
        chosen = set()
        for entry in value:
            name = by_key.get(records.key(entry)) if isinstance(entry, str) else None
            if name is None:
                raise _refuse(key, expected)
            chosen.add(name)
        return [name for name in allowed if name in chosen]

    return check


@dataclass(frozen=True)
class Spec:
    """One setting: its default, what it means, and what values it takes."""

    default: Any
    meaning: str
    check: Callable[[Any], Any]


SPECS: dict[str, Spec] = {
    "stack_discount_pct": Spec(
        50,
        "applied to stack members whose model sets none",
        _number("stack_discount_pct", Decimal(0), Decimal(100)),
    ),
    "currency": Spec("USD", "label only", _currency),
    "fiscal_year_start_month": Spec(1, "for reports grouped by fiscal year", _month),
    "count_states": Spec(
        ["Assigned", "Test", "Prod", "Down", "Pending-Removal"],
        "states that count toward the component count",
        _subset("count_states", lifecycle.STATES),
    ),
    "weight_states": Spec(
        ["Test", "Prod", "Down"],
        "states that carry support weight",
        _subset("weight_states", lifecycle.STATES),
    ),
    "count_kinds": Spec(
        ["hardware", "virtual_machine"],
        "kinds in the headline component count",
        _subset("count_kinds", CATALOG_KINDS),
    ),
    "weight_per_resource_unit": Spec(
        300,
        "how much support weight one resource unit carries",
        _number("weight_per_resource_unit", Decimal(0), None, above_low=True),
    ),
}


@dataclass(frozen=True)
class SettingValue:
    """A setting as it stands: its value in force and whether that is the default."""

    key: str
    value: Any
    default: Any
    is_default: bool
    meaning: str
    row_version: int
    updated_at: datetime | None
    updated_by: str | None


def _spec(key: str) -> Spec:
    spec = SPECS.get(key)
    if spec is None:
        raise NotFound(f"there is no setting {key}")
    return spec


def _view(key: str, row: Setting | None) -> SettingValue:
    spec = SPECS[key]
    own = row.value if row is not None else None
    return SettingValue(
        key=key,
        value=spec.default if own is None else own,
        default=spec.default,
        is_default=own is None,
        meaning=spec.meaning,
        row_version=row.row_version if row is not None else 0,
        updated_at=row.updated_at if row is not None else None,
        updated_by=row.updated_by if row is not None else None,
    )


def list_settings(db: Session) -> list[SettingValue]:
    """Return every setting with the value in force."""
    rows = {row.key: row for row in db.scalars(select(Setting))}
    return [_view(key, rows.get(key)) for key in SPECS]


def get_setting(db: Session, key: str) -> SettingValue:
    """Return one setting with the value in force."""
    _spec(key)
    return _view(key, db.scalar(select(Setting).where(Setting.key == key)))


def value(db: Session, key: str) -> Any:
    """Return the value in force of the setting key."""
    return get_setting(db, key).value


def set_setting(
    db: Session, context: AuditContext, key: str, row_version: int, new: Any
) -> SettingValue:
    """Give a setting a value. None returns it to its default.

    A setting that has never been given a value is at version 0.
    """
    spec = _spec(key)
    checked = None if new is None else spec.check(new)
    if checked == spec.default:
        checked = None
    row = db.scalar(select(Setting).where(Setting.key == key))
    if row is None:
        if row_version != 0:
            raise Invalid(
                "the version is not acceptable",
                {"row_version": "0 for a setting that has never been changed"},
            )
        if checked is None:
            return _view(key, None)
        row = Setting(key=key, value=None, row_version=0)
        row.created_by = context.actor_hid
        db.add(row)
        db.flush()
    records.apply(db, context, "setting", row, row_version, {"value": checked})
    return _view(key, row)
