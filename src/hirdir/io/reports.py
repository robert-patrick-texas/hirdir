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
    DeviceGroup,
    DeviceGroupMember,
    Item,
    Network,
    Owner,
    Tag,
    TagLink,
    Vendor,
)
from hirdir.domain import choices, geography, groups, health, records, settings
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
SHARED = ("vendor", "kind", "type", "function", "owner", "operator", "site", "region")
SUMMARY_BY = (*SHARED, "lifecycle_state", "disposition", "condition", "health", "tag")
MANAGEMENT_BY = (*SHARED, "tag")
ONE_NODE = groups.MANAGED_AS[0]
AND_ITS_OWN = groups.MANAGED_AS[2]


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
class Row(Measures):
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
class MoneyRow(Money):
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

    def source(self, query: Any) -> Any:
        """Return a statement over the view, with what the measures read joined in."""
        return (
            ITEMS.joined(query.select_from(Item))
            .outerjoin(self.stack, self.stack.c.item_hid == Item.hid)
            .outerjoin(self.cluster, self.cluster.c.item_hid == Item.hid)
            .where(*self.where)
        )


def _terms(db: Session, filter_: Any, include_archived: bool, include_drafts: bool) -> _Terms:
    where = (
        filters.to_sql(filters.parse(filter_), ITEMS.fields, settings.time_zone(db), db),
        *default_view(ITEMS, include_archived, include_drafts),
    )
    count_states = list(settings.value(db, "count_states"))
    weight_states = list(settings.value(db, "weight_states"))
    count_kinds = list(settings.value(db, "count_kinds"))
    discount = int(Decimal(str(settings.value(db, "stack_discount_pct"))) * 100)
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
            case(
                (
                    weighed,
                    func.coalesce(_whole(Item.support_weight), _whole(CatalogEntry.support_weight)),
                )
            ),
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
    involved = _involved(db, terms, key, join) if operators else None
    rows = [
        Row(
            key=row[0],
            label=called.get(row[1], row[1]),
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
    rows = [
        MoneyRow(
            key=row[0],
            label=called.get(row[1], row[1]),
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
