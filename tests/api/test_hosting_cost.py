"""The walk through what runs on a host costs nothing where nothing does (P-246)."""

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import event
from sqlalchemy.orm import Session

from hirdir.config import Config
from hirdir.db.engine import make_engine, make_sessions
from hirdir.io import fields, listing, reports
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
