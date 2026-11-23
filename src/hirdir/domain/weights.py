"""Support weights in force: of a major item, a site, a circuit, a region and a location
(P-139, P-141, P-155).

The rule of each kind is here and nowhere else, in the two forms the code reads it in:
for one record, with where its weight came from, and as SQL, for the lists and the
counts, which work it out in the database.

The weight in force of a major item is its own, its model's, or else the setting
`default_item_weight`; of a site its own, or else `default_site_weight`; of a circuit
its own, or else `default_circuit_weight`; of a region and of a location its own alone,
and no place passes its weight down. Where a minimum of its kind is set, a weight in
force below it is raised to it, and says the weight it was raised from. A weight of
zero is a weight, and is raised; nothing, a blank with no default, is not. A minor item
has its weight as before, and neither a default nor a minimum, since it carries none.

Which defaults and minimums are used is said by `Figures`: the settings in force, or
those a Try of the capacity report gives in their place.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields, replace
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import (
    BigInteger,
    ColumnElement,
    and_,
    case,
    false,
    func,
    literal_column,
    type_coerce,
)
from sqlalchemy.orm import Session

from hirdir.db import dialect
from hirdir.db.models import WEIGHT_PLACES, CatalogEntry, Circuit, Item, Scaled, Site
from hirdir.domain import held, inheritance, records, settings
from hirdir.domain.inheritance import Effective

Kind = Literal["item", "site", "circuit"]
KINDS: tuple[Kind, ...] = ("item", "site", "circuit")
# A weight is kept in hundredths: the steps its SQL is worked out in.
STEPS = 10**WEIGHT_PLACES


def default_key(kind: Kind) -> str:
    """Return the setting of the default weight of a kind."""
    return f"default_{kind}_weight"


def minimum_key(kind: Kind) -> str:
    """Return the setting of the minimum weight of a kind."""
    return f"minimum_{kind}_weight"


# The six settings of P-155, a default and a minimum of each kind.
WEIGHT_SETTINGS = tuple(key for kind in KINDS for key in (default_key(kind), minimum_key(kind)))


@dataclass(frozen=True)
class Figures:
    """The figures a support weight and the capacity balance are worked out with.

    The default and the minimum weight of each kind, blank where none is set; the
    global stack discount, which a model that sets its own overrides; and the support
    weight one resource unit carries. Each is the setting of the same name.
    """

    default_item_weight: Decimal | None = None
    minimum_item_weight: Decimal | None = None
    default_site_weight: Decimal | None = None
    minimum_site_weight: Decimal | None = None
    default_circuit_weight: Decimal | None = None
    minimum_circuit_weight: Decimal | None = None
    stack_discount_pct: Decimal = Decimal(settings.SPECS["stack_discount_pct"].default)
    weight_per_resource_unit: Decimal = Decimal(settings.SPECS["weight_per_resource_unit"].default)

    def default(self, kind: Kind) -> Decimal | None:
        """Return the default weight of a kind."""
        return getattr(self, default_key(kind))

    def minimum(self, kind: Kind) -> Decimal | None:
        """Return the minimum weight of a kind."""
        return getattr(self, minimum_key(kind))

    def with_values(self, values: Mapping[str, Decimal | None]) -> Figures:
        """Return these figures with some of them given others."""
        return replace(self, **values)


# The settings that make the figures, in their order.
KEYS = tuple(one.name for one in fields(Figures))


def _decimal(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def in_force(db: Session) -> Figures:
    """Return the figures as the settings have them: worked out once while a file of
    items is worked (P-324)."""
    return held.kept(db, "weights", lambda: _figures(db))


def _figures(db: Session) -> Figures:
    weights = {key: _decimal(settings.value(db, key)) for key in WEIGHT_SETTINGS}
    return Figures(
        **weights,
        stack_discount_pct=Decimal(str(settings.value(db, "stack_discount_pct"))),
        weight_per_resource_unit=Decimal(str(settings.value(db, "weight_per_resource_unit"))),
    )


# --- one record ----------------------------------------------------------------------


@dataclass(frozen=True)
class Weighed(Effective):
    """A support weight in force, where it came from, and what it was before it was
    raised to the minimum of its kind: blank where it was not raised."""

    raised_from: Decimal | None = None

    @property
    def defaulted(self) -> bool:
        """Say whether the weight is the default of its kind."""
        return self.source == "setting"

    @property
    def raised(self) -> bool:
        """Say whether the weight was raised to the minimum of its kind."""
        return self.raised_from is not None


def resolved(found: Effective, kind: Kind | None, figures: Figures) -> Weighed:
    """Return a weight in force: the one found, or else the default of its kind, raised
    to the minimum of its kind where it is below it. A kind of None has neither."""
    if kind is None:
        return Weighed(found.value, found.source, found.source_hid)
    if found.value is None:
        default = figures.default(kind)
        found = inheritance.NOTHING if default is None else Effective(default, "setting", None)
    minimum = figures.minimum(kind)
    if found.value is not None and minimum is not None and found.value < minimum:
        return Weighed(minimum, found.source, found.source_hid, raised_from=found.value)
    return Weighed(found.value, found.source, found.source_hid)


def _own(record: Any) -> Effective:
    own = record.support_weight
    return inheritance.NOTHING if own is None else Effective(own, "own", record.hid)


def of_item(
    item: Item, entry: CatalogEntry | None, figures: Figures, found: Effective | None = None
) -> Weighed:
    """Return the support weight in force of one unit of an item.

    Its own, or its model's; for a major item then the default, raised to the minimum.
    A minor item has its own or its model's alone. `found` is what
    `hirdir.domain.inheritance.of_item` found already, where the caller has it.
    """
    if found is None:
        found = inheritance.of_item(item, entry)["support_weight"]
    return resolved(found, "item" if item.parent_item_hid is None else None, figures)


def of_site(site: Site, figures: Figures) -> Weighed:
    """Return the support weight in force of a site: its own, or the default, raised to
    the minimum."""
    return resolved(_own(site), "site", figures)


def of_circuit(circuit: Circuit, figures: Figures) -> Weighed:
    """Return the support weight in force of a circuit: its own, or the default, raised
    to the minimum."""
    return resolved(_own(circuit), "circuit", figures)


def of_place(record: Any) -> Weighed:
    """Return the support weight of a region or a location: its own alone."""
    return resolved(_own(record), None, Figures())


def effective_entry(found: Weighed) -> dict[str, Any]:
    """Return a weight in force as a record answers it in `effective`: `value`,
    `source`, `source_hid` and `raised_from`, each decimal as text."""

    def text(value: Decimal | None) -> str | None:
        return None if value is None else records.decimal_text("support_weight", value)

    return {
        "value": text(found.value),
        "source": found.source,
        "source_hid": found.source_hid,
        "raised_from": text(found.raised_from),
    }


def circuit_effective(circuit: Circuit, figures: Figures) -> dict[str, Any]:
    """Return `effective.support_weight` of a circuit, as its record answers it."""
    return effective_entry(of_circuit(circuit, figures))


# --- as SQL --------------------------------------------------------------------------


def _hundredths(column: Any) -> ColumnElement[Any]:
    """Return a kept weight as the whole number of hundredths it is stored as."""
    return type_coerce(column, BigInteger)


def _steps(value: Decimal | None) -> ColumnElement[Any] | None:
    """Return a weight as hundredths written into the statement, so that it is the same
    expression wherever it stands, in what is selected and in what is grouped by."""
    if value is None:
        return None
    return literal_column(str(int(value * STEPS)), BigInteger)


@dataclass(frozen=True)
class InForce:
    """A support weight in force as SQL, in hundredths, and whether it is the default
    of its kind and whether it was raised to the minimum."""

    value: ColumnElement[Any]
    defaulted: ColumnElement[bool]
    raised: ColumnElement[bool]


def _in_force(
    chain: Sequence[ColumnElement[Any]],
    default: ColumnElement[Any] | None,
    minimum: ColumnElement[Any] | None,
) -> InForce:
    """Return the first of a chain of weights that is given, or else the default,
    raised to the minimum where it is below it, each in hundredths."""
    given = [*chain, default] if default is not None else list(chain)
    # A coalesce of one is the one itself: SQLite takes no coalesce of fewer than two.
    found = func.coalesce(*given) if len(given) > 1 else given[0]
    defaulted: ColumnElement[bool] = (
        false() if default is None else and_(*(one.is_(None) for one in chain))
    )
    if minimum is None:
        return InForce(found, defaulted, false())
    below = found < minimum
    return InForce(case((below, minimum), else_=found), defaulted, below)


def _floor(
    kind: Kind, figures: Figures | None
) -> tuple[ColumnElement[Any] | None, ColumnElement[Any] | None]:
    """Return the default and the minimum of a kind as the statement is to read them:
    the figures given, or the settings, read by the statement itself."""
    if figures is None:
        return (
            dialect.setting_in_hundredths(default_key(kind)),
            dialect.setting_in_hundredths(minimum_key(kind)),
        )
    return _steps(figures.default(kind)), _steps(figures.minimum(kind))


def item_in_force(figures: Figures | None = None) -> InForce:
    """Return, as SQL, the weight in force of one unit of a major item: its own, its
    model's, then the default, raised to the minimum. It reads `Item` and the
    `CatalogEntry` of its model, outer joined."""
    default, minimum = _floor("item", figures)
    chain = (_hundredths(Item.support_weight), _hundredths(CatalogEntry.support_weight))
    return _in_force(chain, default, minimum)


def site_in_force(figures: Figures | None = None, site: Any = Site) -> InForce:
    """Return, as SQL, the weight in force of a site: its own, then the default, raised
    to the minimum."""
    default, minimum = _floor("site", figures)
    return _in_force((_hundredths(site.support_weight),), default, minimum)


def circuit_in_force(figures: Figures | None = None, circuit: Any = Circuit) -> InForce:
    """Return, as SQL, the weight in force of a circuit: its own, then the default,
    raised to the minimum."""
    default, minimum = _floor("circuit", figures)
    return _in_force((_hundredths(circuit.support_weight),), default, minimum)


def place_in_force(column: Any) -> InForce:
    """Return, as SQL, the weight of a region or a location: its own alone."""
    return _in_force((_hundredths(column),), None, None)


def _as_weight(steps: ColumnElement[Any]) -> ColumnElement[Any]:
    """Return hundredths as a weight, for a list to filter and sort by."""
    return type_coerce(steps, Scaled(WEIGHT_PLACES))


def item_weight_column() -> ColumnElement[Any]:
    """Return `effective.support_weight` of an item as a list reads it: for a major
    item the weight in force with the settings' default and minimum, for a minor item
    its own or its model's."""
    major = item_in_force().value
    minor = func.coalesce(
        _hundredths(Item.support_weight), _hundredths(CatalogEntry.support_weight)
    )
    return _as_weight(case((Item.parent_item_hid.is_(None), major), else_=minor))


def site_weight_column(site: Any = Site) -> ColumnElement[Any]:
    """Return `effective.support_weight` of a site as a list reads it."""
    return _as_weight(site_in_force(site=site).value)


def circuit_weight_column(circuit: Any = Circuit) -> ColumnElement[Any]:
    """Return `effective.support_weight` of a circuit as a list reads it."""
    return _as_weight(circuit_in_force(circuit=circuit).value)
