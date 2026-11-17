"""Reports: counting a view of the items, and the addresses that are held twice.

The measures are defined under "Counting and weight" on the data model page. They are
worked out by the database, in one statement for each answer, over the view that a
filter and the default view choose, so a summary always agrees with the list it is of.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    ColumnElement,
    String,
    and_,
    case,
    distinct,
    func,
    literal_column,
    or_,
    select,
    type_coerce,
)
from sqlalchemy.exc import DBAPIError, OperationalError, StatementError
from sqlalchemy.orm import Session, aliased

from hirdir.db import dialect
from hirdir.db.models import (
    Address,
    CatalogEntry,
    Contract,
    ContractCoverage,
    DeviceGroup,
    DeviceGroupMember,
    Item,
    Location,
    Network,
    Owner,
    Region,
    Site,
    Tag,
    TagLink,
    Vendor,
)
from hirdir.domain import (
    choices,
    contracts,
    geography,
    groups,
    health,
    records,
    settings,
    weights,
)
from hirdir.domain.errors import Invalid
from hirdir.io import fields, filters
from hirdir.io.fields import ITEMS, default_view

# An item with no catalog entry has no kind of its own, and is counted as hardware. The
# word is written into the statement, so that it is the same expression wherever it
# stands, in what is selected and in what is grouped by.
KIND: Any = func.coalesce(CatalogEntry.kind, literal_column("'hardware'"))
HUNDREDTH = Decimal("0.01")
# A weight is kept in hundredths and a discount in hundredths of a percent: the sum of
# weight x quantity x (100% - discount) is exact in units of this size.
WEIGHT_STEPS = Decimal(100 * 100 * 100)
MONEY_STEPS = Decimal(100)
SHARED = (
    "vendor",
    "kind",
    "type",
    "function",
    "owner",
    "operator",
    "site",
    "region",
    "contract",
    "group",
    "model",
)
SUMMARY_BY = (*SHARED, "lifecycle_state", "disposition", "condition", "health", "tag")
MANAGEMENT_BY = (*SHARED, "tag")
ONE_NODE = groups.MANAGED_AS[0]
AND_ITS_OWN = groups.MANAGED_AS[2]
# What a row of a model is called: its vendor and its PID, `Cisco C9300-48P`. The space
# is written into the statement, so that the label is grouped by as it is selected.
MODEL_LABEL: Any = Vendor.name + literal_column("' '", String) + CatalogEntry.pid


@dataclass(frozen=True)
class HealthCount:
    """The components of each health."""

    good: int = 0
    degraded: int = 0
    failed: int = 0
    unknown: int = 0


@dataclass(frozen=True)
class Counted:
    """The items and the components that share one value: a kind, or a condition."""

    key: str | None
    label: str | None
    items: int
    component_count: int


@dataclass(frozen=True)
class Measures:
    """What the summary counts of a set of items. It holds no money."""

    items: int = 0
    component_count: int = 0
    managed_node_count: int = 0
    support_weight: Decimal = Decimal(0)
    by_health: HealthCount = HealthCount()


@dataclass(frozen=True)
class Totals(Measures):
    """The measures of the whole view, and its items by condition and by kind."""

    by_condition: tuple[Counted, ...] = ()
    by_kind: tuple[Counted, ...] = ()


@dataclass(frozen=True)
class Involved:
    """An operator in force among the items of one row, and how much of the row it has."""

    hid: str | None
    items: int
    component_count: int
    support_weight: Decimal


@dataclass(frozen=True)
class Described:
    """What a row of a report by group or by model says of the record it is of (P-178,
    P-180). The rows of anything else, and the blank row, say none of it."""

    # A group's type, or a model's.
    type: str | None = None
    member_count: int | None = None
    nested_groups: int | None = None
    vendor: str | None = None
    pid: str | None = None
    model_name: str | None = None
    kind: str | None = None
    # By operator: how its items have it, which add up to its items, and how many groups
    # and places are given it as their own (P-178).
    own: int | None = None
    from_item: int | None = None
    from_group: int | None = None
    from_place: int | None = None
    groups_given: int | None = None
    places_given: int | None = None


@dataclass(frozen=True)
class Row(Measures, Described):
    """The measures of the items that share one value."""

    key: str | None = None
    label: str | None = None
    # Who looks after the items of the row, the one with the most first, nobody last.
    operators: tuple[Involved, ...] | None = None


@dataclass(frozen=True)
class Summary:
    """A summary of a view of the items, for the people who run the network."""

    by: str | None
    totals: Totals
    rows: list[Row] = field(default_factory=list)


@dataclass(frozen=True)
class Money:
    """What the management report counts of a set of items."""

    items: int = 0
    component_count: int = 0
    est_value: Decimal = Decimal(0)
    annual_support_cost: Decimal = Decimal(0)


@dataclass(frozen=True)
class MoneyRow(Money, Described):
    """The value and the cost of the items that share one value."""

    key: str | None = None
    label: str | None = None


@dataclass(frozen=True)
class Management:
    """The value and the cost of a view of the items, for the people who pay for it."""

    by: str | None
    totals: Money
    rows: list[MoneyRow] = field(default_factory=list)


def _whole(column: Any) -> ColumnElement[Any]:
    """Return a kept decimal as the whole number of steps it is stored as."""
    return type_coerce(column, BigInteger)


def _current(kind: str, statuses: tuple[str, ...]) -> Any:
    """Return, for each item, the group of a type that it is a current member of, with
    how many current members that group has and how it says it is managed."""
    sizes = (
        select(DeviceGroupMember.group_hid.label("group_hid"), func.count().label("size"))
        .where(DeviceGroupMember.left_on.is_(None))
        .group_by(DeviceGroupMember.group_hid)
        .subquery(f"{kind}_sizes")
    )
    return (
        select(
            DeviceGroupMember.item_hid.label("item_hid"),
            func.min(DeviceGroup.hid).label("group_hid"),
            func.min(sizes.c.size).label("size"),
            func.min(func.coalesce(DeviceGroup.managed_as, ONE_NODE)).label("managed_as"),
        )
        .join(DeviceGroup, DeviceGroup.hid == DeviceGroupMember.group_hid)
        .join(sizes, sizes.c.group_hid == DeviceGroup.hid)
        .where(
            DeviceGroupMember.left_on.is_(None),
            DeviceGroup.type == kind,
            DeviceGroup.record_status.in_(statuses),
        )
        .group_by(DeviceGroupMember.item_hid)
        .subquery(f"in_{kind}")
    )


@dataclass(frozen=True)
class _Terms:
    """The pieces every statement of a report is made of, for one view."""

    where: tuple[Any, ...]
    stack: Any
    cluster: Any
    component: ColumnElement[bool]
    counted_whatever_kind: ColumnElement[bool]
    items: ColumnElement[Any]
    components: ColumnElement[Any]
    nodes: ColumnElement[Any]
    health: tuple[ColumnElement[Any], ...]
    weight: tuple[ColumnElement[Any], ...]
    money: tuple[ColumnElement[Any], ...]
    # How many items that carry weight count at the default, and how many were raised
    # to the minimum (P-155).
    defaulted: ColumnElement[Any]
    raised: ColumnElement[Any]

    def source(self, query: Any) -> Any:
        """Return a statement over the view, with what the measures read joined in."""
        return (
            ITEMS.joined(query.select_from(Item))
            .outerjoin(self.stack, self.stack.c.item_hid == Item.hid)
            .outerjoin(self.cluster, self.cluster.c.item_hid == Item.hid)
            .where(*self.where)
        )


def _terms(
    db: Session,
    filter_: Any,
    include_archived: bool,
    include_drafts: bool,
    figures: weights.Figures | None = None,
) -> _Terms:
    """Return the pieces of the statements of a report over one view. `figures` are the
    defaults and minimums of support weight and the global stack discount, the settings
    in force unless a Try gives others."""
    figures = figures or weights.in_force(db)
    where = (
        filters.to_sql(filters.parse(filter_), ITEMS.fields, settings.time_zone(db), db),
        *default_view(ITEMS, include_archived, include_drafts),
    )
    count_states = list(settings.value(db, "count_states"))
    weight_states = list(settings.value(db, "weight_states"))
    count_kinds = list(settings.value(db, "count_kinds"))
    discount = int(figures.stack_discount_pct * 100)
    # A draft stack is not yet one device on the network. In a view that holds the
    # drafts it is, as a draft item is counted there.
    statuses = ("active", "draft") if include_drafts else ("active",)
    stack, cluster = _current("stack", statuses), _current("cluster", statuses)
    major = Item.parent_item_hid.is_(None)
    counted = and_(
        major, or_(Item.lifecycle_state.is_(None), Item.lifecycle_state.in_(count_states))
    )
    component = and_(counted, KIND.in_(count_kinds))
    # What an item is on the network. In a cluster that is managed as one, it is part
    # of the cluster's one node. Otherwise it counts through its stack, or by itself.
    node = case(
        (cluster.c.managed_as == ONE_NODE, cluster.c.group_hid),
        else_=func.coalesce(stack.c.group_hid, Item.hid),
    )
    # A cluster that answers as a node of its own, beside its members, is one more.
    its_own = case((and_(component, cluster.c.managed_as == AND_ITS_OWN), cluster.c.group_hid))
    weighed = and_(major, Item.lifecycle_state.in_(weight_states))
    # The weight of one unit in force: its own, its model's, the default, raised to the
    # minimum. It is then multiplied by the quantity, and the stack discount applied.
    unit = weights.item_in_force(figures)
    its_health = fields.HEALTH
    return _Terms(
        where=where,
        stack=stack,
        cluster=cluster,
        component=component,
        counted_whatever_kind=counted,
        items=func.count(distinct(Item.hid)),
        components=func.count(distinct(case((component, Item.hid)))),
        nodes=func.count(distinct(case((component, node)))) + func.count(distinct(its_own)),
        health=tuple(
            func.count(distinct(case((and_(component, its_health == value), Item.hid))))
            for value in health.HEALTHS
        ),
        # The amounts of one item, each as the whole number of steps it is stored as.
        # They are multiplied and summed outside the database, where no number is too
        # large: here the items that share them are only gathered, and their
        # quantities added.
        weight=(
            case((weighed, unit.value)),
            # One switch alone takes the full effort: the discount is for a stack of
            # two or more.
            case(
                (
                    stack.c.size >= 2,
                    10_000 - func.coalesce(_whole(CatalogEntry.stack_discount_pct), discount),
                ),
                else_=10_000,
            ),
        ),
        money=(
            func.coalesce(_whole(Item.est_value), _whole(CatalogEntry.est_value)),
            func.coalesce(
                _whole(Item.annual_support_cost), _whole(CatalogEntry.annual_support_cost)
            ),
        ),
        defaulted=func.count(distinct(case((and_(weighed, unit.defaulted), Item.hid)))),
        raised=func.count(distinct(case((and_(weighed, unit.raised), Item.hid)))),
    )


def _grouping(by: str) -> tuple[Any, Any, Any]:
    """Return what a report is grouped by: the key, its label, and a join it needs."""
    if by == "vendor":
        return Vendor.hid, Vendor.name, None
    if by == "kind":
        return KIND, KIND, None
    if by in ("type", "function"):
        column = getattr(CatalogEntry, by)
        return column, column, None
    if by == "owner":
        # The owner in force: a minor item is under the owner of the item it is in.
        return Owner.hid, Owner.label, None
    if by == "operator":
        # The operator in force: the blank row is what nobody is assigned to.
        return fields.ITEM_OPERATOR.hid, fields.ITEM_OPERATOR.label, None
    if by == "site":
        return fields.ITEM_SITE.hid, fields.ITEM_SITE.hid, None
    if by == "region":
        # Every region an item is within: its site's own, and each one above that. An
        # item is so in the row of each, as an item with several tags is.
        above = geography.region_ancestry()

        def within(query: Any) -> Any:
            return query.outerjoin(above, above.c.hid == fields.ITEM_SITE.region_hid)

        return above.c.above, above.c.above, within
    if by == "contract":
        # Every contract that covers an item today. An item is so in the row of each,
        # and what no contract covers is in the blank row.
        cover = aliased(ContractCoverage, name="report_coverage")
        contract = aliased(Contract, name="report_contract")
        provider = aliased(Vendor, name="report_contract_vendor")
        covering = (
            select(
                cover.item_hid.label("item_hid"),
                contract.hid.label("contract_hid"),
                (contracts.term_value(contract, "number") + " (" + provider.name + ")").label(
                    "label"
                ),
            )
            .join(contract, contract.hid == cover.contract_hid)
            .join(provider, provider.hid == contract.vendor_hid)
            .where(contracts.coverage_in_force(cover, contract))
            .distinct()
            .subquery("covering")
        )

        def covered(query: Any) -> Any:
            return query.outerjoin(covering, covering.c.item_hid == Item.hid)

        return covering.c.contract_hid, covering.c.label, covered
    if by == "group":
        # Every group an item is under, and the blank row the items under none.
        under = fields.UNDER_GROUPS
        named: Any = aliased(DeviceGroup, name="report_group")

        def grouped(query: Any) -> Any:
            return query.outerjoin(under, under.c.item_hid == Item.hid).outerjoin(
                named, named.hid == under.c.group_hid
            )

        return under.c.group_hid, named.name, grouped
    if by == "model":
        # A model is a vendor's product, whatever its type; the blank row is what has
        # no catalog entry (P-180).
        return CatalogEntry.hid, MODEL_LABEL, None
    if by in ("lifecycle_state", "disposition"):
        column = fields.standing(by)
        return column, column, None
    if by == "condition":
        return Item.condition, Item.condition, None
    if by == "health":
        return fields.HEALTH, fields.HEALTH, None
    link = aliased(TagLink, name="summary_tag_link")
    tag = aliased(Tag, name="summary_tag")

    def tagged(query: Any) -> Any:
        return query.outerjoin(
            link, and_(link.record_type == "item", link.record_hid == Item.hid)
        ).outerjoin(tag, tag.hid == link.tag_hid)

    return tag.hid, tag.label, tagged


# The lists of choices that say what people call the values a report may be by.
LABELLED = {"type": "catalog_type", "function": "catalog_function", "condition": "item_condition"}


def _labels(db: Session, by: str, keys: Sequence[Any] = ()) -> dict[str, str]:
    """Return what people call the values a report is by: as a list of choices labels
    them, or, for a site and a region, by its path."""
    if by in ("site", "region"):
        atlas = geography.Atlas(db)
        if by == "site":
            atlas.read_sites(keys)
            return {key: atlas.site_path(key) for key in keys if key}
        return {key: atlas.region_path(key) for key in keys if key}
    if by not in LABELLED:
        return {}
    return {choice.value: choice.label for choice in choices.list_choices(db, LABELLED[by])}


# How an item has its operator, as the columns of a row by operator count it (P-178).
SOURCE_COLUMNS = {
    "own": "own",
    "parent_item": "from_item",
    "device_group": "from_group",
    "location": "from_place",
    "site": "from_place",
    "region": "from_place",
}


def _by_operator(db: Session, terms: _Terms, hids: list[str]) -> dict[str, dict[str, Any]]:
    """Return, for each operator of a report by operator, how the items of its row have
    it, and how many groups and places are given it as their own (P-178)."""
    told: dict[str, dict[str, Any]] = {
        hid: {
            "own": 0,
            "from_item": 0,
            "from_group": 0,
            "from_place": 0,
            "groups_given": 0,
            "places_given": 0,
        }
        for hid in hids
    }
    counting = terms.source(
        select(fields.OPERATOR_IN_FORCE, fields.OPERATOR_SOURCE, func.count(Item.hid))
    ).group_by(fields.OPERATOR_IN_FORCE, fields.OPERATOR_SOURCE)
    for hid, source, count in _run(db, counting):
        column = SOURCE_COLUMNS.get(source)
        if hid in told and column is not None:
            told[hid][column] += count
    given = (
        (DeviceGroup, "groups_given"),
        (Region, "places_given"),
        (Site, "places_given"),
        (Location, "places_given"),
    )
    for model, column in given:
        counted = db.execute(
            select(model.operator_hid, func.count())
            .where(model.operator_hid.in_(hids), model.record_status != "retired")
            .group_by(model.operator_hid)
        )
        for hid, count in counted:
            if hid in told:
                told[hid][column] += count
    return told


def _described(
    db: Session, by: str, keys: Sequence[Any], terms: _Terms | None = None
) -> dict[str, dict[str, Any]]:
    """Return what the record of each row says of itself, by group, by model or by
    operator: a group's type, its current members and how many groups are nested in it;
    a model's vendor, PID, name, kind and type; how the items of an operator have it.
    A report by anything else describes nothing."""
    hids = sorted({key for key in keys if key})
    if not hids or by not in ("group", "model", "operator"):
        return {}
    if by == "operator":
        return {} if terms is None else _by_operator(db, terms, hids)
    if by == "model":
        found = db.execute(
            select(CatalogEntry, Vendor.name)
            .join(Vendor, Vendor.hid == CatalogEntry.vendor_hid)
            .where(CatalogEntry.hid.in_(hids))
        )
        return {
            entry.hid: {
                "vendor": vendor,
                "pid": entry.pid,
                "model_name": entry.model_name,
                "kind": entry.kind,
                "type": entry.type,
            }
            for entry, vendor in found
        }
    nested = fields.NESTED_GROUPS
    beneath = dict(
        db.execute(
            select(nested.c.top_hid, func.count())
            .where(nested.c.top_hid.in_(hids), nested.c.group_hid != nested.c.top_hid)
            .group_by(nested.c.top_hid)
        ).all()
    )
    members = groups.member_counts(db, hids)
    return {
        hid: {"type": kind, "member_count": members[hid], "nested_groups": beneath.get(hid, 0)}
        for hid, kind in db.execute(
            select(DeviceGroup.hid, DeviceGroup.type).where(DeviceGroup.hid.in_(hids))
        )
    }


def _run(db: Session, statement: Any) -> list[Any]:
    """Run one statement of a report, refusing a filter that cannot be run."""
    with dialect.regex_budget() as budget:
        try:
            return list(db.execute(statement).all())
        except OperationalError:
            if budget.failure:
                raise filters.refuse(budget.failure) from None
            raise
        except StatementError as error:
            if isinstance(error, DBAPIError):
                raise
            raise filters.refuse("a value in the filter cannot be compared") from None


def _checked_by(by: str | None, allowed: tuple[str, ...]) -> None:
    if by is not None and by not in allowed:
        raise Invalid("the grouping is not acceptable", {"by": f"one of {', '.join(allowed)}"})


def weight_steps(
    db: Session, include_drafts: bool = False, figures: weights.Figures | None = None
) -> int:
    """Return the support weight of the whole inventory, exactly, in the steps it is
    summed in: `WEIGHT_STEPS` of them to one."""
    terms = _terms(db, None, False, include_drafts, figures)
    return _sums(db, terms, terms.weight).get(None, [0, 0])[0]


def weight_steps_by_region(
    db: Session, include_drafts: bool = False, figures: weights.Figures | None = None
) -> dict[str | None, int]:
    """Return the support weight of the items at or beneath each region, by the
    location in force, in the steps `weight_steps` sums in, as the summary by `region`
    counts it: an item is in the row of each region above it. The items that are
    nowhere are under None. Only a region that holds an item of the view is named."""
    terms = _terms(db, None, False, include_drafts, figures)
    key, _, join = _grouping("region")
    return {region: sums[0] for region, sums in _sums(db, terms, terms.weight, key, join).items()}


def weight_counts(
    db: Session, include_drafts: bool = False, figures: weights.Figures | None = None
) -> tuple[int, int]:
    """Return how many items of the whole inventory that carry support weight count at
    the default of `default_item_weight`, and how many were raised to the minimum.

    Where neither is set no item can have been either, and the items are not read a
    second time for it: the capacity report reads them once, as before 0.8.0.
    """
    held = weights.in_force(db) if figures is None else figures
    if held.default("item") is None and held.minimum("item") is None:
        return 0, 0
    terms = _terms(db, None, False, include_drafts, figures)
    defaulted, raised = _run(db, terms.source(select(terms.defaulted, terms.raised)))[0]
    return int(defaulted or 0), int(raised or 0)


def _sums(
    db: Session, terms: _Terms, amounts: tuple[Any, ...], key: Any = None, join: Any = None
) -> dict[Any, list[int]]:
    """Return, for each value of a key, the exact sums of amounts times quantity.

    The amounts are multiplied together and by the quantity of the items that share
    them, here and not in the database, so the sums are exact however large they grow.
    `weight` is a weight and the share of it that counts; `money` is two amounts, each
    summed by itself.
    """
    paired = amounts is terms.weight
    head = () if key is None else (key,)
    statement = terms.source(select(*head, *amounts, func.sum(Item.quantity)))
    if join is not None:
        statement = join(statement)
    found: dict[Any, list[int]] = {}
    for row in _run(db, statement.group_by(*head, *amounts)):
        sums = found.setdefault(row[0] if head else None, [0, 0])
        first, second, quantity = (int(value or 0) for value in row[len(head) :])
        if paired:
            sums[0] += first * second * quantity
        else:
            sums[0] += first * quantity
            sums[1] += second * quantity
    return found


def _measures(counts: Any, sums: list[int]) -> dict[str, Any]:
    items, components, nodes, *healths = counts
    return {
        "items": items,
        "component_count": components,
        "managed_node_count": nodes,
        # Summed exactly, and rounded once.
        "support_weight": (Decimal(sums[0]) / WEIGHT_STEPS).quantize(
            HUNDREDTH, rounding=ROUND_HALF_UP
        ),
        "by_health": HealthCount(**dict(zip(health.HEALTHS, healths, strict=True))),
    }


def _money(counts: Any, sums: list[int]) -> dict[str, Any]:
    items, components = counts
    return {
        "items": items,
        "component_count": components,
        "est_value": Decimal(sums[0]) / MONEY_STEPS,
        "annual_support_cost": Decimal(sums[1]) / MONEY_STEPS,
    }


def _in_order(rows: list[Any]) -> list[Any]:
    """Return rows by what people read, the blank one last."""
    return sorted(
        rows, key=lambda row: (row.key is None, records.key(row.label or ""), row.key or "")
    )


def _counted(
    db: Session, terms: _Terms, key: Any, labels: dict[str, str], component: Any
) -> list[Counted]:
    """Return the items and the components of each value of a key.

    `component` says what a component is here: of the kinds the headline counts, or of
    whatever kind, where the kinds themselves are what is being told apart.
    """
    found = _run(
        db,
        terms.source(
            select(key, terms.items, func.count(distinct(case((component, Item.hid)))))
        ).group_by(key),
    )
    return [
        Counted(key=value, label=labels.get(value, value), items=items, component_count=components)
        for value, items, components in found
    ]


def summary(
    db: Session,
    *,
    filter_: Any = None,
    by: str | None = None,
    include_archived: bool = False,
    include_drafts: bool = False,
    operators: bool = False,
) -> Summary:
    """Count a view of the items, as a whole and by one of the things items share.

    Components, managed nodes, support weight and health: what the people who run the
    network ask. The money is in `management`. With `operators`, each row also says
    which operators are in force among its items, and how much each has.
    """
    _checked_by(by, SUMMARY_BY)
    terms = _terms(db, filter_, include_archived, include_drafts)
    counts = (terms.items, terms.components, terms.nodes, *terms.health)
    whole = _run(db, terms.source(select(*counts)))[0]
    order = {kind: place for place, kind in enumerate(settings.CATALOG_KINDS)}
    conditions = [choice.value for choice in choices.list_choices(db, "item_condition")]
    totals = Totals(
        **_measures(whole, _sums(db, terms, terms.weight).get(None, [0, 0])),
        by_condition=tuple(
            sorted(
                _counted(db, terms, Item.condition, _labels(db, "condition"), terms.component),
                key=lambda one: (
                    one.key is None,
                    conditions.index(one.key) if one.key in conditions else len(conditions),
                ),
            )
        ),
        by_kind=tuple(
            sorted(
                _counted(db, terms, KIND, {}, terms.counted_whatever_kind),
                key=lambda one: order.get(one.key, len(order)),
            )
        ),
    )
    if by is None:
        return Summary(None, totals)
    key, label, join = _grouping(by)
    counting = terms.source(select(key, label, *counts))
    if join is not None:
        counting = join(counting)
    sums = _sums(db, terms, terms.weight, key, join)
    found = _run(db, counting.group_by(key, label))
    called = _labels(db, by, [row[0] for row in found])
    told = _described(db, by, [row[0] for row in found], terms)
    involved = _involved(db, terms, key, join) if operators else None
    rows = [
        Row(
            key=row[0],
            label=called.get(row[1], row[1]),
            **told.get(row[0], {}),
            **_measures(row[2:], sums.get(row[0], [0, 0])),
            operators=None if involved is None else tuple(involved.get(row[0], ())),
        )
        for row in found
    ]
    return Summary(by, totals, _in_order(rows))


def _involved(db: Session, terms: _Terms, key: Any, join: Any) -> dict[Any, list[Involved]]:
    """Return, for each value of a key, the operators in force among its items, each
    with its items, its components and its support weight: the one with the most
    first, and what nobody is assigned to last."""
    operator = fields.ITEM_OPERATOR.hid
    counting = terms.source(select(key, operator, terms.items, terms.components))
    weighing = terms.source(select(key, operator, *terms.weight, func.sum(Item.quantity)))
    if join is not None:
        counting, weighing = join(counting), join(weighing)
    weights: dict[tuple[Any, Any], int] = {}
    for value, hid, weight, share, quantity in _run(
        db, weighing.group_by(key, operator, *terms.weight)
    ):
        weights[value, hid] = weights.get((value, hid), 0) + (
            int(weight or 0) * int(share or 0) * int(quantity or 0)
        )
    found: dict[Any, list[Involved]] = {}
    for value, hid, items, components in _run(db, counting.group_by(key, operator)):
        found.setdefault(value, []).append(
            Involved(
                hid=hid,
                items=items,
                component_count=components,
                support_weight=(Decimal(weights.get((value, hid), 0)) / WEIGHT_STEPS).quantize(
                    HUNDREDTH, rounding=ROUND_HALF_UP
                ),
            )
        )
    for listed in found.values():
        listed.sort(
            key=lambda one: (
                one.hid is None,
                -one.support_weight,
                -one.component_count,
                -one.items,
                one.hid or "",
            )
        )
    return found


def management(
    db: Session,
    *,
    filter_: Any = None,
    by: str | None = None,
    include_archived: bool = False,
    include_drafts: bool = False,
) -> Management:
    """Return the estimated value and the annual support cost of a view of the items.

    For the people who pay for the network: the whole inventory, and one row for each
    value of `by`, which is the site unless another is asked for. Neither condition nor
    health is in it.
    """
    _checked_by(by, MANAGEMENT_BY)
    by = by or "site"
    terms = _terms(db, filter_, include_archived, include_drafts)
    counts = (terms.items, terms.components)
    whole = _run(db, terms.source(select(*counts)))[0]
    totals = Money(**_money(whole, _sums(db, terms, terms.money).get(None, [0, 0])))
    key, label, join = _grouping(by)
    counting = terms.source(select(key, label, *counts))
    if join is not None:
        counting = join(counting)
    sums = _sums(db, terms, terms.money, key, join)
    found = _run(db, counting.group_by(key, label))
    called = _labels(db, by, [row[0] for row in found])
    told = _described(db, by, [row[0] for row in found], terms)
    rows = [
        MoneyRow(
            key=row[0],
            label=called.get(row[1], row[1]),
            **told.get(row[0], {}),
            **_money(row[2:], sums.get(row[0], [0, 0])),
        )
        for row in found
    ]
    return Management(by, totals, _in_order(rows))


def by_location(
    db: Session,
    *,
    filter_: Any = None,
    include_archived: bool = False,
    include_drafts: bool = False,
) -> dict[str | None, tuple[int, int]]:
    """Return the items and the components of a view at each location, by the location
    in force, and under no key those that are nowhere."""
    terms = _terms(db, filter_, include_archived, include_drafts)
    where = fields.LOCATION_IN_FORCE
    found = _run(db, terms.source(select(where, terms.items, terms.components)).group_by(where))
    return {hid: (items, components) for hid, items, components in found}


def by_planned_location(
    db: Session,
    *,
    filter_: Any = None,
    include_archived: bool = False,
    include_drafts: bool = False,
) -> dict[str, int]:
    """Return how many items of a view are planned for each location, and not there yet."""
    terms = _terms(db, filter_, include_archived, include_drafts)
    where = fields.PLANNED_IN_FORCE
    found = _run(
        db,
        terms.source(select(where, terms.items)).where(where.is_not(None)).group_by(where),
    )
    return dict(found)


# --- addresses held more than once ---------------------------------------------------


@dataclass(frozen=True)
class Holder:
    """An item or a group that holds an address."""

    address_hid: str
    item_hid: str | None
    group_hid: str | None
    name: str | None
    role: str
    is_primary: bool


@dataclass(frozen=True)
class Duplicate:
    """An address that is held more than once under one network."""

    address: str
    network_hid: str | None
    network: str | None
    count: int
    holders: list[Holder]


def _held(include_archived: bool, include_drafts: bool) -> Any:
    """Return the addresses whose item or group a list would show."""
    group_view: list[ColumnElement[bool]] = []
    if not include_drafts:
        group_view.append(DeviceGroup.record_status != "draft")
    if not include_archived:
        group_view.append(DeviceGroup.record_status != "retired")
    of_items = ITEMS.joined(select(Address.hid).join(Item, Item.hid == Address.item_hid)).where(
        *default_view(ITEMS, include_archived, include_drafts)
    )
    of_groups = (
        select(Address.hid)
        .join(DeviceGroup, DeviceGroup.hid == Address.group_hid)
        .where(*group_view)
    )
    return of_items.union_all(of_groups)


def duplicates(
    db: Session,
    *,
    include_archived: bool = False,
    include_drafts: bool = False,
    limit: int = 100,
    offset: int = 0,
    arrange: records.Arrange | None = None,
) -> tuple[list[Duplicate], int]:
    """Return a page of the addresses held more than once under one network, and their number.

    The unlabelled address space is one network of its own. An address whose item or
    group a list leaves out by default is not counted. `arrange` sorts them as was
    asked for, and the address and its network settle what that leaves tied.
    """
    held = _held(include_archived, include_drafts).subquery("held")
    network = func.coalesce(Address.network_hid, "")
    twice = (
        select(Address.address, network.label("network"), func.count().label("count"))
        .join(held, held.c.hid == Address.hid)
        .group_by(Address.address, network)
        .having(func.count() > 1)
    )
    total = db.scalar(select(func.count()).select_from(twice.subquery())) or 0
    if arrange is not None:
        twice = arrange(twice)
    paged = twice.order_by(Address.address, network).limit(limit).offset(offset)
    page = db.execute(paged).all()
    if not page:
        return [], total
    # Who holds each address of the page: the page is joined, however long it is.
    of_page = paged.subquery("page")
    rows = db.execute(
        select(Address, Network.label, func.coalesce(Item.name, Item.hostname), DeviceGroup.name)
        .join(held, held.c.hid == Address.hid)
        .join(
            of_page,
            and_(Address.address == of_page.c.address, network == of_page.c.network),
        )
        .outerjoin(Network, Network.hid == Address.network_hid)
        .outerjoin(Item, Item.hid == Address.item_hid)
        .outerjoin(DeviceGroup, DeviceGroup.hid == Address.group_hid)
        .order_by(Address.hid)
    ).all()
    holders: dict[tuple[str, str], list[Holder]] = {}
    labels: Mapping[str, str | None] = {
        address.network_hid or "": label for address, label, _, _ in rows
    }
    for address, _, item_name, group_name in rows:
        holders.setdefault((address.address, address.network_hid or ""), []).append(
            Holder(
                address_hid=address.hid,
                item_hid=address.item_hid,
                group_hid=address.group_hid,
                name=item_name if address.item_hid else group_name,
                role=address.role,
                is_primary=address.is_primary,
            )
        )
    return (
        [
            Duplicate(
                address=address,
                network_hid=under or None,
                network=labels.get(under),
                count=count,
                holders=holders.get((address, under), []),
            )
            for address, under, count in page
        ],
        total,
    )
