"""The timing fixture and the timing of the item filters: scripts/seed_fixture.py and
scripts/time_filters.py."""

import importlib.util
import sys
from collections import Counter
from pathlib import Path
from types import ModuleType

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from hirdir.app import create_app
from hirdir.config import Config
from hirdir.db.engine import make_engine, make_sessions
from hirdir.db.models import (
    CatalogEntry,
    ContractCoverage,
    DeviceGroup,
    DeviceGroupMember,
    Item,
)
from hirdir.io import filters
from hirdir.io.fields import ITEMS

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


seed_fixture = _load("seed_fixture")
time_filters = _load("time_filters")


def test_the_dice_choose_the_same_for_the_same_key() -> None:
    one, again, other = (
        seed_fixture.Dice("a"),
        seed_fixture.Dice("a"),
        seed_fixture.Dice("b"),
    )
    shares = [one.share("key", number) for number in range(200)]
    assert shares == [again.share("key", number) for number in range(200)]
    assert shares != [other.share("key", number) for number in range(200)]
    assert all(0 <= share < 1 for share in shares)
    assert {one.between(1, 3, "n", number) for number in range(200)} == {1, 2, 3}
    picked = Counter(one.weighted((("rare", 1.0), ("common", 9.0)), "w", n) for n in range(2000))
    assert 100 < picked["rare"] < 300


def test_shares_are_split_into_whole_numbers_that_add_up() -> None:
    counts = seed_fixture.apportion(7, (("a", 1.0), ("b", 1.0), ("c", 1.0)))
    assert sum(counts.values()) == 7
    assert sorted(counts.values()) == [2, 2, 3]


def test_the_shape_at_full_size_is_the_target_of_the_requirements() -> None:
    kinds = seed_fixture.Shape(50_000).kinds
    assert sum(kinds.values()) == 50_000
    major = sum(count for use, count in kinds.items() if use not in ("phone", "minor"))
    assert (major, kinds["phone"], kinds["minor"]) == (15_000, 22_000, 13_000)


def test_the_percentile_is_by_the_nearest_rank() -> None:
    assert time_filters.percentile(list(range(1, 21)), 0.95) == 19
    assert time_filters.percentile([7.0], 0.95) == 7.0
    assert time_filters.percentile([3.0, 1.0, 2.0], 0.5) == 2.0
    with pytest.raises(ValueError, match="no samples"):
        time_filters.percentile([], 0.95)


def test_every_request_timed_is_one_the_item_list_takes() -> None:
    for case in time_filters.cases("CN-000001"):
        if not case.path.endswith("/items"):
            continue
        filters.parse(case.params.get("filter", ""))
        assert filters.parse_sort([case.params["sort"]], ITEMS.fields)
        assert case.params["limit"] == time_filters.PAGE


def test_a_folder_that_is_not_a_fixture_is_left_alone(tmp_path: Path) -> None:
    (tmp_path / "hirdir.db").write_text("not a fixture", encoding="utf-8")
    with pytest.raises(SystemExit, match="not a fixture"):
        seed_fixture.prepare(tmp_path)
    assert (tmp_path / "hirdir.db").read_text(encoding="utf-8") == "not a fixture"


@pytest.fixture(scope="module")
def small(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict]:
    """A small fixture of the same shape, made once for the tests below."""
    folder = tmp_path_factory.mktemp("fixture")
    return folder, seed_fixture.build(folder, 400, "test")


def test_a_small_fixture_has_every_kind_of_thing(small: tuple[Path, dict]) -> None:
    folder, facts = small
    counts = facts["counts"]
    assert counts["items"] == 400
    assert counts["major items that are not phones"] == 120
    assert counts["phones"] == 176
    for name in (
        "items in Pending-Removal",
        "items in Released",
        "items in Archived",
        "retired items",
        "stacks",
        "contracts pending renewal",
        "contracts with a next term",
        "coverages ended on leaving service",
    ):
        assert counts[name] > 0, name
    engine = make_engine(Config(state_dir=folder).database_url)
    with make_sessions(engine)() as db:
        # What the rules hold: an item is known once by its model and serial number,
        # a member of a stack is a major item, and every coverage is of an item.
        keys = db.execute(select(Item.catalog_entry_hid, Item.serial_key)).all()
        assert len(keys) == len(set(keys))
        minor_in_stacks = db.scalar(
            select(func.count())
            .select_from(DeviceGroupMember)
            .join(DeviceGroup, DeviceGroup.hid == DeviceGroupMember.group_hid)
            .join(Item, Item.hid == DeviceGroupMember.item_hid)
            .where(DeviceGroup.type == "stack", Item.parent_item_hid.is_not(None))
        )
        assert minor_in_stacks == 0
        orphans = db.scalar(
            select(func.count())
            .select_from(ContractCoverage)
            .outerjoin(Item, Item.hid == ContractCoverage.item_hid)
            .where(Item.hid.is_(None))
        )
        assert orphans == 0
        assert (
            db.scalar(select(func.count()).select_from(CatalogEntry)) == counts["catalog entries"]
        )
    engine.dispose()


def test_every_request_is_answered_on_the_fixture(small: tuple[Path, dict]) -> None:
    folder, facts = small
    app = create_app(Config(state_dir=folder))
    said: list[str] = []
    with TestClient(app) as client:
        results = time_filters.run(
            client,
            facts,
            runs=1,
            warm_up=0,
            only=None,
            engine=None,
            explain_to=None,
            say=said.append,
        )
    app.state.engine.dispose()
    assert len(results) == len(time_filters.cases("x"))
    for timed in results:
        assert len(timed.runs) == 1
        assert timed.total is not None
    report = results[-1].total
    assert report["out_of_service"] > 0
    assert len(time_filters.table(results).splitlines()) == len(results) + 1
    assert said[0].startswith("contract.number is CN-")
