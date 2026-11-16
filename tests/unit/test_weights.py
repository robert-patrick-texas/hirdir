"""The support weight in force of each kind (P-141, P-155): a default and a minimum, as
the rule for one record says and as the SQL of the lists and the counts says, which
must agree."""

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from hirdir.db import dialect
from hirdir.db.models import CatalogEntry, Circuit, Item, Location, Region, Setting, Site, Vendor
from hirdir.domain import inheritance, weights

D = Decimal
# The worked examples of the data model page: an object with no weight of its own,
# under a default and a minimum, and what it counts at.
CASES = [
    (D(2), D(1), D(2)),
    (D(1), D(2), D(2)),
    (None, D(1), D(0)),
    (D(0), D(1), D(1)),
]


def figures(kind: str, default: Decimal | None, minimum: Decimal | None) -> weights.Figures:
    return weights.Figures().with_values(
        {f"default_{kind}_weight": default, f"minimum_{kind}_weight": minimum}
    )


@pytest.mark.parametrize("kind", weights.KINDS)
@pytest.mark.parametrize(("default", "minimum", "counts_at"), CASES)
def test_an_object_with_no_weight_counts_as_the_data_model_says(
    kind: weights.Kind, default: Decimal | None, minimum: Decimal, counts_at: Decimal
) -> None:
    found = weights.resolved(inheritance.NOTHING, kind, figures(kind, default, minimum))
    # Nothing at all, a blank with no default, counts as nothing: it is not raised.
    assert (found.value or D(0)) == counts_at
    assert found.defaulted == (default is not None)
    assert found.raised == (default is not None and default < minimum)
    if found.raised:
        assert found.raised_from == default


@pytest.mark.parametrize("kind", weights.KINDS)
def test_a_weight_of_its_own_is_raised_and_one_above_the_minimum_is_not(
    kind: weights.Kind,
) -> None:
    rule = figures(kind, D(5), D(1))
    zero = weights.resolved(inheritance.Effective(D(0), "own", "x"), kind, rule)
    assert (zero.value, zero.source, zero.source_hid, zero.raised_from) == (D(1), "own", "x", D(0))
    high = weights.resolved(inheritance.Effective(D(3), "own", "x"), kind, rule)
    assert (high.value, high.source, high.raised_from) == (D(3), "own", None)


def test_no_kind_has_neither_a_default_nor_a_minimum() -> None:
    rule = weights.Figures(default_item_weight=D(2), minimum_item_weight=D(3))
    assert weights.resolved(inheritance.NOTHING, None, rule).value is None
    own = weights.resolved(inheritance.Effective(D("0.5"), "own", "x"), None, rule)
    assert (own.value, own.raised_from) == (D("0.5"), None)


def test_a_weight_in_force_is_answered_as_a_record_answers_it() -> None:
    found = weights.Weighed(D(1), "own", "0193", raised_from=D("0.50"))
    assert weights.effective_entry(found) == {
        "value": "1",
        "source": "own",
        "source_hid": "0193",
        "raised_from": "0.5",
    }
    blank = weights.effective_entry(weights.Weighed(None, "none", None))
    assert blank == {"value": None, "source": "none", "source_hid": None, "raised_from": None}


# --- the SQL agrees with the rule ----------------------------------------------------


@pytest.fixture
def places(db: Session) -> dict[str, str]:
    region = Region(name="Americas", name_key="americas")
    db.add(region)
    db.flush()
    site = Site(name="Site-2", name_key="site-2", region_hid=region.hid)
    db.add(site)
    db.flush()
    location = Location(name="Building 1", name_key="building 1", site_hid=site.hid)
    vendor = Vendor(name="Example Telecom", name_key="example telecom")
    db.add_all([location, vendor])
    db.flush()
    return {"region": region.hid, "site": site.hid, "location": location.hid, "vendor": vendor.hid}


OWN = [None, D(0), D("0.5"), D(3)]
FLOORS = [(None, None), (D(2), None), (None, D(1)), (D(1), D(2)), (D(0), D(1)), (D(2), D(1))]


@pytest.mark.parametrize("own", OWN)
@pytest.mark.parametrize(("default", "minimum"), FLOORS)
def test_the_sql_of_a_site_and_a_circuit_agrees_with_the_rule(
    db: Session,
    places: dict[str, str],
    own: Decimal | None,
    default: Decimal | None,
    minimum: Decimal | None,
) -> None:
    site = db.get(Site, places["site"])
    assert site is not None
    site.support_weight = own
    circuit = Circuit(
        name="Site-2 internet",
        name_key="site-2 internet",
        a_location_hid=places["location"],
        support_weight=own,
    )
    db.add(circuit)
    db.flush()
    site_rule, circuit_rule = (
        figures("site", default, minimum),
        figures("circuit", default, minimum),
    )
    for kind, expected, sql, table in (
        ("site", weights.of_site(site, site_rule), weights.site_in_force(site_rule), Site),
        (
            "circuit",
            weights.of_circuit(circuit, circuit_rule),
            weights.circuit_in_force(circuit_rule),
            Circuit,
        ),
    ):
        value, defaulted, raised = db.execute(
            select(sql.value, sql.defaulted, sql.raised).select_from(table)
        ).one()
        assert (None if value is None else D(value) / 100) == expected.value, kind
        assert bool(defaulted) == expected.defaulted, kind
        assert bool(raised) == expected.raised, kind


@pytest.mark.parametrize("own", OWN)
@pytest.mark.parametrize("model", [None, D("0.5"), D(4)])
@pytest.mark.parametrize(("default", "minimum"), FLOORS)
def test_the_sql_of_a_major_item_agrees_with_the_rule(
    db: Session,
    places: dict[str, str],
    own: Decimal | None,
    model: Decimal | None,
    default: Decimal | None,
    minimum: Decimal | None,
) -> None:
    entry = CatalogEntry(
        vendor_hid=places["vendor"], pid="C9300-48P", pid_key="c9300-48p", support_weight=model
    )
    db.add(entry)
    db.flush()
    item = Item(catalog_entry_hid=entry.hid, support_weight=own, quantity=1)
    db.add(item)
    db.flush()
    rule = figures("item", default, minimum)
    expected = weights.of_item(item, entry, rule)
    sql = weights.item_in_force(rule)
    value, defaulted, raised = db.execute(
        select(sql.value, sql.defaulted, sql.raised)
        .select_from(Item)
        .outerjoin(CatalogEntry, CatalogEntry.hid == Item.catalog_entry_hid)
    ).one()
    assert (None if value is None else D(value) / 100) == expected.value
    assert bool(defaulted) == expected.defaulted
    assert bool(raised) == expected.raised


def test_a_list_reads_the_default_and_the_minimum_from_the_settings(
    db: Session, places: dict[str, str]
) -> None:
    def read(key: str) -> int | None:
        return db.scalar(select(dialect.setting_in_hundredths(key)))

    assert read("default_site_weight") is None
    db.add_all(
        [
            Setting(key="default_site_weight", value=2),
            Setting(key="minimum_site_weight", value=0.29),
            Setting(key="default_item_weight", value=None),
        ]
    )
    db.flush()
    assert (read("default_site_weight"), read("minimum_site_weight")) == (200, 29)
    assert read("default_item_weight") is None
    column = weights.site_weight_column()
    assert db.scalar(select(column).select_from(Site)) == D(2)
    site = db.get(Site, places["site"])
    assert site is not None
    site.support_weight = D("0.1")
    db.flush()
    assert db.scalar(select(column).select_from(Site)) == D("0.29")
