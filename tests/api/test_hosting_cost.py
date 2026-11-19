"""The walk through what runs on a host costs nothing where nothing does (P-246)."""

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import event
from sqlalchemy.orm import Session

from hirdir.config import Config
from hirdir.db.engine import make_engine, make_sessions
from hirdir.domain import settings
from hirdir.domain.audit import AuditContext
from hirdir.io import fields, hosted, listing, reports
from tests.api.inventory import Maker
from tests.api.test_hosting import Lab


@contextmanager
def _statements(config: Config) -> Generator[tuple[list[str], Session]]:
    engine = make_engine(config.database_url)
    sent: list[str] = []

    def seen(_conn: object, _cursor: object, statement: str, *_more: object) -> None:
        sent.append(statement)

    event.listen(engine, "before_cursor_execute", seen)
    with make_sessions(engine)() as db:
        yield sent, db
    engine.dispose()


def _read(db: Session) -> None:
    listing.page(db, fields.ITEMS, limit=100, sort=["location.name"])
    listing.count(db, fields.ITEMS, filter_="effective.operator_hid:empty:false")
    reports.summary(db, filter_="", by="site", include_archived=False, include_drafts=False)


def test_a_list_of_an_inventory_where_nothing_runs_on_a_host_holds_no_step_of_it(
    make: Maker, config: Config
) -> None:
    lab = Lab(make)
    with _statements(config) as (sent, db):
        _read(db)
    assert sent
    assert not [one for one in sent if "through_hosts" in one]

    vm = lab.vm(host_item_hid=lab.esx["hid"])
    with _statements(config) as (sent, db):
        _read(db)
        # And it answers through the host where something does.
        found, _ = listing.page(db, fields.ITEMS, limit=100, filter_=f"hid:eq:{vm['hid']}")
    assert [one for one in sent if "through_hosts" in one]
    assert [item.hid for item in found] == [vm["hid"]]


def test_whether_anything_is_hosted_is_asked_of_the_indexes_and_never_walks_the_items(
    make: Maker, config: Config
) -> None:
    """The question every request asks first is one statement, and SQLite answers it
    from the two indexes of the host columns: asked as IS NOT NULL it read every item,
    twice, for each request."""
    Lab(make)
    with _statements(config) as (sent, db):
        _read(db)
        asked = [one for one in sent if hosted.MARK in one]
        assert len(asked) == 1, asked
        connection = db.connection()
        plan = " | ".join(
            str(row[-1])
            for row in connection.exec_driver_sql(
                f"EXPLAIN QUERY PLAN {asked[0]}", (1, "", "", 1, 0)
            )
        )
    assert "ix_items_host_item_hid" in plan, plan
    assert "ix_items_host_group_hid" in plan, plan
    assert "SCAN items" not in plan, plan


def test_the_settings_are_read_once_for_a_transaction_and_a_change_is_seen(
    make: Maker, config: Config
) -> None:
    Lab(make)
    context = AuditContext(actor_hid=None, via="api", request_id="r-settings")
    with _statements(config) as (sent, db):
        for key in ("time_zone", "count_kinds", "end_of_life_within_days", "time_zone"):
            settings.value(db, key)
        assert len([one for one in sent if "FROM settings" in one]) == 1, sent
        # A setting given a value in the same transaction reads as given, a new row too.
        settings.set_setting(db, context, "end_of_life_within_days", 0, 365)
        assert settings.value(db, "end_of_life_within_days") == 365
        now = settings.get_setting(db, "end_of_life_within_days")
        settings.set_setting(db, context, "end_of_life_within_days", now.row_version, 400)
        assert settings.value(db, "end_of_life_within_days") == 400
        db.rollback()
        # And what was not kept is not read from what was.
        assert settings.value(db, "end_of_life_within_days") == 730
