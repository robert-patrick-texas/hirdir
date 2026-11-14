"""The capacity balance: the demand for resource units against the supply of them.

Demand is the support weight of the inventory, turned into resource units, and the
work that is not the infrastructure. Supply is the capacity lines. The balance is
worked out twice, without the drafts and with them, so that "what if we add this
service" is answered by entering it as a draft. Every number is worked out exactly and
rounded to two places once.
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from hirdir.db.models import CapacityLine
from hirdir.domain import capacity, choices, contracts, settings
from hirdir.io import reports

HUNDREDTH = Decimal("0.01")
PRECISION = 60


def _rounded(value: Decimal) -> Decimal:
    """Return a number to two places, half up. What rounds to nothing is nothing, and
    not a nothing below zero."""
    rounded = value.quantize(HUNDREDTH, rounding=ROUND_HALF_UP)
    return rounded if rounded else Decimal("0.00")


@dataclass(frozen=True)
class Category:
    """The supply of one category: how many lines, their units and what they cost."""

    category: str
    label: str
    lines: int
    units: Decimal
    annual_cost: Decimal


@dataclass(frozen=True)
class View:
    """The balance of one view: the active lines and items, or those with the drafts."""

    support_weight: Decimal
    infrastructure_demand: Decimal
    other_demand: Decimal
    demand: Decimal
    supply: Decimal
    balance: Decimal
    coverage_pct: Decimal | None
    own_units: Decimal
    outside_units: Decimal
    own_share_pct: Decimal | None
    annual_cost: Decimal
    by_category: list[Category]


@dataclass(frozen=True)
class Balance:
    """Demand against supply for the whole installation, with and without the drafts."""

    as_of: date
    weight_per_resource_unit: Decimal
    active: View
    with_drafts: View


def _view(
    weight_steps: int,
    per_unit: Decimal,
    lines: list[CapacityLine],
    categories: list[tuple[str, str]],
) -> View:
    with localcontext() as context:
        context.prec = PRECISION
        weight = Decimal(weight_steps) / reports.WEIGHT_STEPS
        infrastructure = weight / per_unit
        other = sum(
            (capacity.units(line) for line in lines if line.side == capacity.DEMAND), Decimal(0)
        )
        supplying = [line for line in lines if line.side == capacity.SUPPLY]
        supply = sum((capacity.units(line) for line in supplying), Decimal(0))
        own = sum(
            (capacity.units(line) for line in supplying if line.category == capacity.STAFF),
            Decimal(0),
        )
        demand = infrastructure + other
        known = dict(categories)
        named = [*known, *sorted({line.category for line in supplying} - set(known))]
        by_category = []
        for category in named:
            its = [line for line in supplying if line.category == category]
            by_category.append(
                Category(
                    category=category,
                    label=known.get(category, category),
                    lines=len(its),
                    units=_rounded(sum((capacity.units(line) for line in its), Decimal(0))),
                    annual_cost=sum((line.annual_cost or Decimal(0) for line in its), Decimal(0)),
                )
            )
        return View(
            support_weight=_rounded(weight),
            infrastructure_demand=_rounded(infrastructure),
            other_demand=_rounded(other),
            demand=_rounded(demand),
            supply=_rounded(supply),
            balance=_rounded(supply - demand),
            coverage_pct=_rounded(supply / demand * 100) if demand else None,
            own_units=_rounded(own),
            outside_units=_rounded(supply - own),
            own_share_pct=_rounded(own / supply * 100) if supply else None,
            annual_cost=sum((line.annual_cost or Decimal(0) for line in supplying), Decimal(0)),
            by_category=by_category,
        )


def balance(db: Session) -> Balance:
    """Return the capacity balance of the whole installation, as of today."""
    today = contracts.today(db)
    per_unit = Decimal(str(settings.value(db, "weight_per_resource_unit")))
    # Every category that supplies, in the order of its list, also one with no line.
    categories = [
        (choice.value, choice.label)
        for choice in choices.list_choices(db, capacity.CATEGORY_LIST)
        if choice.active and choice.value != capacity.OTHER_WORK
    ]
    lines = [
        line
        for line in db.scalars(
            select(CapacityLine).where(CapacityLine.record_status.in_(("active", "draft")))
        )
        if capacity.in_date(line, today)
    ]

    def view(statuses: tuple[str, ...], include_drafts: bool) -> Any:
        return _view(
            reports.weight_steps(db, include_drafts),
            per_unit,
            [line for line in lines if line.record_status in statuses],
            categories,
        )

    return Balance(today, per_unit, view(("active",), False), view(("active", "draft"), True))
