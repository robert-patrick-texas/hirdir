"""The capacity balance: the demand for resource units against the supply of them.

Demand is the support weight of the inventory, turned into resource units, and the
work that is not the infrastructure. Supply is the capacity lines. The balance is
worked out twice, without the drafts and with them, so that "what if we add this
service" is answered by entering it as a draft. Every number is worked out exactly and
rounded to two places once.

A line that multiplies adds `factor` less 1, times `share`, times the units of the
staff lines it applies to that are counted in the same view on the same day.
Multipliers each work on the base units of the staff lines and do not compound, so
their order does not matter.

The support weight that is the demand is that of the items, and beside them that of the
places and the circuits, each at its weight in force (P-155): a site at its own or the
default of its kind, raised to the minimum, a region and a location at their own, and a
circuit at its own or the default, raised, while it carries its weight.

The balance is of the whole operations team. Beside it, the demand of each region says
where the work is, and no supply is divided among regions. The balance is also kept
week by week, in the records of `hirdir.domain.capacity`, to show the trend.

A Try works the same balance out with other figures and other staff lines, and keeps
nothing: see `hirdir.io.tried`.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import case, func, select, union_all
from sqlalchemy.orm import Session, aliased

from hirdir import clock
from hirdir.db.models import CapacityLine, CapacityRecord, Circuit, Location, Region, Site
from hirdir.domain import capacity, choices, circuits, geography, records, settings, weights
from hirdir.domain.audit import AuditContext
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
class Target:
    """A staff line that a line which multiplies works on, and its units in the view."""

    hid: str
    name: str
    counted: bool
    units: Decimal


@dataclass(frozen=True)
class Multiplying:
    """A line that multiplies, the lines it works on, and what it adds to them."""

    hid: str
    name: str
    category: str
    factor: Decimal
    share: Decimal
    applies_to: list[Target]
    base_units: Decimal
    units: Decimal


@dataclass(frozen=True)
class RegionDemand:
    """The support weight at or beneath one region, and the demand that is; or, with
    no region, that of the items that are nowhere."""

    region_hid: str | None
    parent_region_hid: str | None
    path: str | None
    support_weight: Decimal
    infrastructure_demand: Decimal
    share_pct: Decimal | None


@dataclass(frozen=True)
class Counted:
    """How many items, sites and circuits: of those that count, the ones at a default of
    their kind, or the ones raised to a minimum (P-155)."""

    items: int = 0
    sites: int = 0
    circuits: int = 0


@dataclass(frozen=True)
class View:
    """The balance of one view: the active lines and items, or those with the drafts."""

    support_weight: Decimal
    # The parts of the support weight, which add up to it (P-155).
    items_weight: Decimal
    places_weight: Decimal
    circuits_weight: Decimal
    defaulted: Counted
    raised: Counted
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
    multiplying_lines: list[Multiplying]
    demand_by_region: list[RegionDemand]


@dataclass(frozen=True)
class Balance:
    """Demand against supply for the whole installation, with and without the drafts."""

    as_of: date
    weight_per_resource_unit: Decimal
    active: View
    with_drafts: View


@dataclass(frozen=True)
class StaffTried:
    """Staff lines as a Try has them (P-156): lines added, lines that are there with
    another quantity or units of one, and lines that are there left out. Each line tried
    is active and in date in both views. None of them is saved."""

    added: tuple[CapacityLine, ...] = ()
    changed: Mapping[str, CapacityLine] = field(default_factory=dict)
    left_out: frozenset[str] = frozenset()

    def applied(self, lines: list[CapacityLine]) -> list[CapacityLine]:
        """Return the lines of the balance as they are tried."""
        kept = [self.changed.get(line.hid, line) for line in lines if line.hid not in self.left_out]
        return [*kept, *self.added]


def line_tried(
    hid: str, name: str, quantity: Decimal, units_each: Decimal, annual_cost: Decimal | None = None
) -> CapacityLine:
    """Return a staff line that adds, as a Try has it: active and in date, and held by no
    session, so that nothing of it is ever stored."""
    return CapacityLine(
        hid=hid,
        side=capacity.SUPPLY,
        category=capacity.STAFF,
        name=name,
        effect=capacity.ADD,
        quantity=quantity,
        units_each=units_each,
        factor=None,
        share=None,
        annual_cost=annual_cost,
        starts_on=None,
        ends_on=None,
        record_status="active",
    )


# --- the places and the circuits beside the items (P-155) ---

# A place's and a circuit's weight are kept in hundredths, and the items' are summed in
# the finer steps of `reports.WEIGHT_STEPS`: this many of those to one hundredth.
TO_ITEM_STEPS = int(reports.WEIGHT_STEPS) // weights.STEPS


@dataclass(frozen=True)
class _Beside:
    """The support weight of the places and of the circuits of one view, in the steps
    the items are summed in, and at or beneath each region; and how many sites and
    circuits counted at a default, and were raised to a minimum."""

    places: int
    circuits: int
    by_region: dict[str, int]
    defaulted: tuple[int, int]
    raised: tuple[int, int]


def _beside(db: Session, include_drafts: bool, figures: weights.Figures, today: date) -> _Beside:
    """Return the support weight of the places and the circuits of one view.

    A region, a site and a location count while it is active, or a draft with the
    drafts, at its weight in force, in the region it is, or is in; a circuit while it
    carries its weight, in the region of the site it counts at (P-150). Each is then in
    the row of every region above that one, as an item is.
    """
    # A place counts by its own status, as an item does.
    statuses = ("active", "draft") if include_drafts else ("active",)
    region_weight = weights.place_in_force(Region.support_weight)
    site_weight = weights.site_in_force(figures)
    location_weight = weights.place_in_force(Location.support_weight)
    circuit_weight = weights.circuit_in_force(figures)
    carries = circuits.carries_weight_column(today, include_drafts)
    placed = union_all(
        select(Region.hid.label("region_hid"), region_weight.value.label("steps")).where(
            Region.record_status.in_(statuses)
        ),
        select(Site.region_hid.label("region_hid"), site_weight.value.label("steps")).where(
            Site.record_status.in_(statuses)
        ),
        select(Site.region_hid.label("region_hid"), location_weight.value.label("steps"))
        .select_from(Location)
        .join(Site, Site.hid == Location.site_hid)
        .where(Location.record_status.in_(statuses)),
    ).subquery("placed")
    cost_location: Any = aliased(Location, name="cost_location")
    cost_site: Any = aliased(Site, name="cost_site")
    carried = (
        select(cost_site.region_hid.label("region_hid"), circuit_weight.value.label("steps"))
        .select_from(Circuit)
        .join(cost_location, cost_location.hid == circuits.cost_location_column())
        .join(cost_site, cost_site.hid == cost_location.site_hid)
        .where(carries)
        .subquery("carried")
    )
    by_region: dict[str, int] = {}
    whole = []
    for found in (placed, carried):
        whole.append(int(db.scalar(select(func.sum(found.c.steps))) or 0) * TO_ITEM_STEPS)
        above = geography.region_ancestry()
        for hid, steps in db.execute(
            select(above.c.above, func.sum(found.c.steps))
            .join(above, above.c.hid == found.c.region_hid)
            .where(found.c.steps.is_not(None))
            .group_by(above.c.above)
        ):
            by_region[hid] = by_region.get(hid, 0) + int(steps or 0) * TO_ITEM_STEPS
    sites = db.execute(
        select(
            func.count(case((site_weight.defaulted, Site.hid))),
            func.count(case((site_weight.raised, Site.hid))),
        ).where(Site.record_status.in_(statuses))
    ).one()
    carrying = db.execute(
        select(
            func.count(case((circuit_weight.defaulted, Circuit.hid))),
            func.count(case((circuit_weight.raised, Circuit.hid))),
        ).where(carries)
    ).one()
    return _Beside(
        places=whole[0],
        circuits=whole[1],
        by_region=by_region,
        defaulted=(int(sites[0]), int(carrying[0])),
        raised=(int(sites[1]), int(carrying[1])),
    )


# --- end of the places and the circuits ---


def _gains(
    lines: list[CapacityLine], targets: dict[str, list[str]], names: dict[str, str]
) -> tuple[dict[str, Decimal], list[Multiplying]]:
    """Return the units of every supply line of a view, and the lines that multiply.

    A line that multiplies works on the lines it applies to that are counted in the
    view: staff lines that add, of the view's statuses and in date. One that is retired,
    out of date or a draft outside the view of drafts gives it nothing.
    """
    counted = {line.hid: line for line in lines}
    units = {line.hid: capacity.units(line) for line in lines if not capacity.multiplies(line)}
    multiplying = []
    for line in lines:
        if not capacity.multiplies(line):
            continue
        applies_to = []
        for hid in targets.get(line.hid, []):
            target = counted.get(hid)
            works = target is not None and capacity.can_be_multiplied(target)
            applies_to.append(
                Target(
                    hid=hid,
                    name=names.get(hid, hid),
                    counted=works,
                    units=_rounded(units[hid]) if works else Decimal("0.00"),
                )
            )
        base = sum((units[one.hid] for one in applies_to if one.counted), Decimal(0))
        factor = line.factor if line.factor is not None else Decimal(1)
        share = line.share if line.share is not None else Decimal(1)
        units[line.hid] = (factor - 1) * share * base
        multiplying.append(
            Multiplying(
                hid=line.hid,
                name=line.name,
                category=line.category,
                factor=factor,
                share=share,
                applies_to=sorted(applies_to, key=lambda one: records.key(one.name)),
                base_units=_rounded(base),
                units=_rounded(units[line.hid]),
            )
        )
    return units, sorted(multiplying, key=lambda one: records.key(one.name))


def _by_region(
    db: Session, steps: dict[str | None, int], whole: int, per_unit: Decimal
) -> list[RegionDemand]:
    """Return the demand at or beneath each region that holds an item of the view, by
    path, and that of the items that are nowhere, last."""
    atlas = geography.Atlas(db)
    rows = []
    for hid, weight_steps in steps.items():
        if hid is None:
            continue
        region = atlas.regions.get(hid)
        rows.append((atlas.region_path(hid), hid, region, weight_steps))
    rows.sort(key=lambda row: (records.key(row[0]), row[1]))

    def demand(hid: str | None, path: str | None, parent: str | None, part: int) -> RegionDemand:
        weight = Decimal(part) / reports.WEIGHT_STEPS
        return RegionDemand(
            region_hid=hid,
            parent_region_hid=parent,
            path=path,
            support_weight=_rounded(weight),
            infrastructure_demand=_rounded(weight / per_unit),
            share_pct=_rounded(Decimal(part) / whole * 100) if whole else None,
        )

    found = [
        demand(hid, path, region.parent_region_hid if region is not None else None, part)
        for path, hid, region, part in rows
    ]
    found.append(demand(None, None, None, steps.get(None, 0)))
    return found


def _view(
    db: Session,
    include_drafts: bool,
    figures: weights.Figures,
    today: date,
    lines: list[CapacityLine],
    categories: list[tuple[str, str]],
    targets: dict[str, list[str]],
    names: dict[str, str],
) -> View:
    per_unit = figures.weight_per_resource_unit
    with localcontext() as context:
        context.prec = PRECISION
        # An item is in the row of each region above it, and so in the row of one top
        # region, or else in the row of none: the whole is the sum of those rows, and
        # needs no pass over the items of its own.
        by_region = reports.weight_steps_by_region(db, include_drafts, figures)
        regions = geography.Atlas(db).regions
        items_steps = sum(
            steps
            for hid, steps in by_region.items()
            if hid is None or regions[hid].parent_region_hid is None
        )
        # The places and the circuits beside them, each in the row of every region
        # above it, so that the top rows and what is nowhere still add up to the whole.
        beside = _beside(db, include_drafts, figures, today)
        for hid, steps in beside.by_region.items():
            by_region[hid] = by_region.get(hid, 0) + steps
        weight_steps = items_steps + beside.places + beside.circuits
        items_defaulted, items_raised = reports.weight_counts(db, include_drafts, figures)
        weight = Decimal(weight_steps) / reports.WEIGHT_STEPS
        infrastructure = weight / per_unit
        other = sum(
            (capacity.units(line) for line in lines if line.side == capacity.DEMAND), Decimal(0)
        )
        supplying = [line for line in lines if line.side == capacity.SUPPLY]
        units, multiplying = _gains(supplying, targets, names)
        supply = sum((units[line.hid] for line in supplying), Decimal(0))
        own = sum(
            (units[line.hid] for line in supplying if line.category == capacity.STAFF),
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
                    units=_rounded(sum((units[line.hid] for line in its), Decimal(0))),
                    annual_cost=sum((line.annual_cost or Decimal(0) for line in its), Decimal(0)),
                )
            )
        return View(
            support_weight=_rounded(weight),
            items_weight=_rounded(Decimal(items_steps) / reports.WEIGHT_STEPS),
            places_weight=_rounded(Decimal(beside.places) / reports.WEIGHT_STEPS),
            circuits_weight=_rounded(Decimal(beside.circuits) / reports.WEIGHT_STEPS),
            defaulted=Counted(items_defaulted, *beside.defaulted),
            raised=Counted(items_raised, *beside.raised),
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
            multiplying_lines=multiplying,
            demand_by_region=_by_region(db, by_region, weight_steps, per_unit),
        )


def balance(
    db: Session,
    day: date | None = None,
    figures: weights.Figures | None = None,
    staff: StaffTried | None = None,
) -> Balance:
    """Return the capacity balance of the whole installation, as of a day: today unless
    said.

    `figures` are the defaults and minimums of support weight, the global stack discount
    and the weight one resource unit carries: the settings in force unless a Try gives
    others. `staff` is the staff lines a Try adds, changes and leaves out.
    """
    today = day or clock.today(settings.time_zone(db))
    figures = figures or weights.in_force(db)
    per_unit = figures.weight_per_resource_unit
    # Every category that supplies, in the order of its list, also one with no line.
    categories = [
        (choice.value, choice.label)
        for choice in choices.list_choices(db, capacity.CATEGORY_LIST)
        if choice.active and choice.value != capacity.OTHER_WORK
    ]
    held = list(
        db.scalars(select(CapacityLine).where(CapacityLine.record_status.in_(("active", "draft"))))
    )
    if staff is not None:
        held = staff.applied(held)
    lines = [line for line in held if capacity.in_date(line, today)]
    multiplying = [line.hid for line in lines if capacity.multiplies(line)]
    targets = capacity.targets_of(db, multiplying)
    # The names of the lines a multiplier applies to, those that do not count among them.
    wanted = {hid for hids in targets.values() for hid in hids}
    named = select(CapacityLine.hid, CapacityLine.name).where(CapacityLine.hid.in_(wanted))
    names: dict[str, str] = dict(db.execute(named).all())

    def view(statuses: tuple[str, ...], include_drafts: bool) -> View:
        return _view(
            db,
            include_drafts,
            figures,
            today,
            [line for line in lines if line.record_status in statuses],
            categories,
            targets,
            names,
        )

    return Balance(today, per_unit, view(("active",), False), view(("active", "draft"), True))


# --- the balance kept week by week ---------------------------------------------------


def _kept(found: View) -> dict[str, Any]:
    """Return what a record keeps of one view: the figures, as text, with the parts of
    the support weight and how many counted at a default and were raised (P-155)."""
    return {
        **{name: capacity.figure_text(getattr(found, name)) for name in capacity.KEPT},
        **{name: capacity.figure_text(getattr(found, name)) for name in capacity.WEIGHT_PARTS},
        **{
            name: {kind: getattr(getattr(found, name), kind) for kind in capacity.COUNTED_KINDS}
            for name in capacity.WEIGHT_COUNTS
        },
        "by_category": [
            {
                "category": one.category,
                "label": one.label,
                "lines": one.lines,
                "units": capacity.figure_text(one.units),
                "annual_cost": f"{one.annual_cost:.2f}",
            }
            for one in found.by_category
        ],
    }


def record(
    db: Session, context: AuditContext, moment: datetime | None = None, note: Any = None
) -> CapacityRecord:
    """Record the balance of the whole installation as it is at a moment, now unless
    said, as the record of the week that moment is in, in the application's time zone.

    A week that has a record already has it replaced: a line added on a Wednesday is in
    that week's figures once somebody records again.
    """
    moment = moment or clock.now()
    day = moment.astimezone(ZoneInfo(settings.time_zone(db))).date()
    found = balance(db, day)
    return capacity.keep_record(
        db,
        context,
        week_of=capacity.monday_of(day),
        recorded_at=moment,
        weight_per_resource_unit=found.weight_per_resource_unit,
        views={"active": _kept(found.active), "with_drafts": _kept(found.with_drafts)},
        note=note,
    )


def record_if_missing(db: Session, context: AuditContext, moment: datetime) -> bool:
    """Record the balance at a moment when its week has no record yet, as the server
    does by itself on a Monday just after midnight and when it starts. Say whether it
    did. A week that somebody has recorded already keeps what they recorded."""
    day = moment.astimezone(ZoneInfo(settings.time_zone(db))).date()
    if capacity.record_of_week(db, capacity.monday_of(day)) is not None:
        return False
    record(db, context, moment)
    return True


def list_records(
    db: Session, limit: int, offset: int, arrange: records.Arrange | None = None
) -> tuple[list[CapacityRecord], int]:
    """Return a page of the records of the balance, the oldest week first, and how many
    there are. `arrange` sorts them as was asked for; the week settles what that leaves
    tied."""
    query = select(CapacityRecord)
    total = db.scalar(select(func.count()).select_from(CapacityRecord)) or 0
    if arrange is not None:
        query = arrange(query)
    page = db.scalars(query.order_by(CapacityRecord.week_of).limit(limit).offset(offset))
    return list(page), total
