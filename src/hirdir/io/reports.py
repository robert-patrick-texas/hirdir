"""Reports: counting a view of the items, and the addresses that are held twice.

The measures are defined under "Counting and weight" on the data model page. They are
worked out by the database, in one statement for each answer, over the view that a
filter and the default view choose, so a summary always agrees with the list it is of.
"""

from collections.abc import Mapping
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
from hirdir.domain import records, settings
from hirdir.domain.errors import Invalid
from hirdir.io import fields, filters
from hirdir.io.fields import ITEMS, default_view

HARDWARE = "hardware"
HUNDREDTH = Decimal("0.01")
# A weight is kept in hundredths and a discount in hundredths of a percent: the sum of
# weight x quantity x (100% - discount) is exact in units of this size.
WEIGHT_STEPS = Decimal(100 * 100 * 100)
MONEY_STEPS = Decimal(100)
BY = ("vendor", "kind", "type", "function", "owner", "lifecycle_state", "disposition", "tag")


@dataclass(frozen=True)
class Measures:
    """The counts and sums of a set of items."""

    items: int = 0
    component_count: int = 0
    managed_node_count: int = 0
    support_weight: Decimal = Decimal(0)
    est_value: Decimal = Decimal(0)
    annual_support_cost: Decimal = Decimal(0)


@dataclass(frozen=True)
class KindCount:
    """The items and the components of one kind."""

    kind: str
    items: int
    component_count: int


@dataclass(frozen=True)
class Totals(Measures):
    """The measures of the whole view, and its items by kind."""

    by_kind: tuple[KindCount, ...] = ()


@dataclass(frozen=True)
class Row(Measures):
    """The measures of the items that share one value."""

    key: str | None = None
    label: str | None = None


@dataclass(frozen=True)
class Summary:
    """A summary of a view of the items."""

    by: str | None
    totals: Totals
    rows: list[Row] = field(default_factory=list)


def _whole(column: Any) -> ColumnElement[Any]:
    """Return a kept decimal as the whole number of steps it is stored as."""
    return type_coerce(column, BigInteger)


def _current_group(kind: str) -> Any:
    """Return, for each item, the active group of a type that it is a current member of."""
    return (
        select(
            DeviceGroupMember.item_hid.label("item_hid"),
            func.min(DeviceGroup.hid).label("group_hid"),
        )
        .join(DeviceGroup, DeviceGroup.hid == DeviceGroupMember.group_hid)
        .where(
            DeviceGroupMember.left_on.is_(None),
            DeviceGroup.type == kind,
            DeviceGroup.record_status == "active",
        )
        .group_by(DeviceGroupMember.item_hid)
        .subquery(f"in_{kind}")
    )


@dataclass(frozen=True)
class _Terms:
    """The pieces every summary statement is made of, for one view."""

    where: tuple[Any, ...]
    stack: Any
    cluster: Any
    kind: ColumnElement[Any]
    component: ColumnElement[bool]
    counted_whatever_kind: ColumnElement[bool]
    measures: tuple[ColumnElement[Any], ...]

    def source(self, query: Any) -> Any:
        """Return a statement over the view, with what the measures read joined in."""
        return (
            ITEMS.joined(query.select_from(Item))
            .outerjoin(self.stack, self.stack.c.item_hid == Item.hid)
            .outerjoin(self.cluster, self.cluster.c.item_hid == Item.hid)
            .where(*self.where)
        )


def _terms(db: Session, where: tuple[Any, ...]) -> _Terms:
    count_states = list(settings.value(db, "count_states"))
    weight_states = list(settings.value(db, "weight_states"))
    count_kinds = list(settings.value(db, "count_kinds"))
    discount = int(Decimal(str(settings.value(db, "stack_discount_pct"))) * 100)
    stack, cluster = _current_group("stack"), _current_group("cluster")
    major = Item.parent_item_hid.is_(None)
    # An item with no catalog entry has no kind of its own, and is counted as hardware.
    kind = func.coalesce(CatalogEntry.kind, HARDWARE)
    counted = and_(
        major, or_(Item.lifecycle_state.is_(None), Item.lifecycle_state.in_(count_states))
    )
    component = and_(counted, kind.in_(count_kinds))
    # A cluster comes before a stack: an item in both is part of the cluster's one node.
    node = func.coalesce(cluster.c.group_hid, stack.c.group_hid, Item.hid)
    weight = func.coalesce(_whole(Item.support_weight), _whole(CatalogEntry.support_weight))
    share = case(
        (
            stack.c.group_hid.is_not(None),
            10_000 - func.coalesce(_whole(CatalogEntry.stack_discount_pct), discount),
        ),
        else_=10_000,
    )
    weighed = and_(major, Item.lifecycle_state.in_(weight_states))
    value = func.coalesce(_whole(Item.est_value), _whole(CatalogEntry.est_value))
    cost = func.coalesce(_whole(Item.annual_support_cost), _whole(CatalogEntry.annual_support_cost))
    measures = (
        func.count(distinct(Item.hid)),
        func.count(distinct(case((component, Item.hid)))),
        func.count(distinct(case((component, node)))),
        func.coalesce(func.sum(case((weighed, weight * Item.quantity * share), else_=0)), 0),
        func.coalesce(func.sum(value * Item.quantity), 0),
        func.coalesce(func.sum(cost * Item.quantity), 0),
    )
    return _Terms(where, stack, cluster, kind, component, counted, measures)


def _measures(row: Any) -> dict[str, Any]:
    items, components, nodes, weight, value, cost = row
    return {
        "items": items,
        "component_count": components,
        "managed_node_count": nodes,
        # Summed exactly, and rounded once.
        "support_weight": (Decimal(int(weight)) / WEIGHT_STEPS).quantize(
            HUNDREDTH, rounding=ROUND_HALF_UP
        ),
        "est_value": Decimal(int(value)) / MONEY_STEPS,
        "annual_support_cost": Decimal(int(cost)) / MONEY_STEPS,
    }


def _grouping(by: str) -> tuple[Any, Any, Any]:
    """Return what a summary is grouped by: the key, its label, and a join it needs."""
    if by == "vendor":
        return Vendor.hid, Vendor.name, None
    if by == "kind":
        kind = func.coalesce(CatalogEntry.kind, HARDWARE)
        return kind, kind, None
    if by in ("type", "function"):
        column = getattr(CatalogEntry, by)
        return column, column, None
    if by == "owner":
        # The owner in force: a minor item is under the owner of the item it is in.
        return Owner.hid, Owner.label, None
    if by in ("lifecycle_state", "disposition"):
        column = fields.standing(by)
        return column, column, None
    link = aliased(TagLink, name="summary_tag_link")
    tag = aliased(Tag, name="summary_tag")

    def tagged(query: Any) -> Any:
        return query.outerjoin(
            link, and_(link.record_type == "item", link.record_hid == Item.hid)
        ).outerjoin(tag, tag.hid == link.tag_hid)

    return tag.hid, tag.label, tagged


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


def summary(
    db: Session,
    *,
    filter_: Any = None,
    by: str | None = None,
    include_archived: bool = False,
    include_drafts: bool = False,
) -> Summary:
    """Count a view of the items, as a whole and by one of the things items share."""
    if by is not None and by not in BY:
        raise Invalid("the grouping is not acceptable", {"by": f"one of {', '.join(BY)}"})
    where = (
        filters.to_sql(filters.parse(filter_), ITEMS.fields),
        *default_view(ITEMS, include_archived, include_drafts),
    )
    terms = _terms(db, where)
    whole = _run(db, terms.source(select(*terms.measures)))[0]
    kinds = _run(
        db,
        terms.source(
            select(
                terms.kind,
                func.count(distinct(Item.hid)),
                func.count(distinct(case((terms.counted_whatever_kind, Item.hid)))),
            )
        ).group_by(terms.kind),
    )
    order = {kind: place for place, kind in enumerate(settings.CATALOG_KINDS)}
    totals = Totals(
        **_measures(whole),
        by_kind=tuple(
            KindCount(kind=kind, items=items, component_count=components)
            for kind, items, components in sorted(
                kinds, key=lambda row: order.get(row[0], len(order))
            )
        ),
    )
    if by is None:
        return Summary(None, totals)
    key, label, join = _grouping(by)
    statement = terms.source(select(key, label, *terms.measures))
    if join is not None:
        statement = join(statement)
    found = _run(db, statement.group_by(key, label))
    rows = [Row(key=row[0], label=row[1], **_measures(row[2:])) for row in found]
    # By what people read, the blank one last.
    rows.sort(key=lambda row: (row.key is None, records.key(row.label or ""), row.key or ""))
    return Summary(by, totals, rows)


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
) -> tuple[list[Duplicate], int]:
    """Return a page of the addresses held more than once under one network, and their number.

    The unlabelled address space is one network of its own. An address whose item or
    group a list leaves out by default is not counted.
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
    page = db.execute(twice.order_by(Address.address, network).limit(limit).offset(offset)).all()
    if not page:
        return [], total
    wanted = or_(
        *(and_(Address.address == address, network == under) for address, under, _ in page)
    )
    rows = db.execute(
        select(Address, Network.label, func.coalesce(Item.name, Item.hostname), DeviceGroup.name)
        .join(held, held.c.hid == Address.hid)
        .outerjoin(Network, Network.hid == Address.network_hid)
        .outerjoin(Item, Item.hid == Address.item_hid)
        .outerjoin(DeviceGroup, DeviceGroup.hid == Address.group_hid)
        .where(wanted)
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
