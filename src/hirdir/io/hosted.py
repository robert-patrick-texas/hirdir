"""Whether anything runs on a host, asked once for each session (P-246).

The walk of what an item has from above goes on through what it runs on. In SQL that
step is a table of its own, worked out for each statement that reads a value in force,
and it costs a statement its preparation even where nothing runs on anything. So a
session asks once, before its first query, whether any item names a host, an indexed
look; where none does, the step is written as nothing at all, and the statement is as
it was before 0.9.8. A session that names a host, by any change it flushes, has the step
from then on. Anything else that is not sure, as the first statement of a session
that is not read through the ORM, has the step.
"""

from contextvars import ContextVar
from typing import Any

from sqlalchemy import ColumnElement, event, literal, or_, select
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import ORMExecuteState, Session
from sqlalchemy.sql.visitors import InternalTraversal

from hirdir.db.models import Item

KEY = "hirdir.anything_hosted"
# What the question says of itself in a statement, so that it is told from the others.
MARK = "/* anything hosted */"
# Whether the statement being made may read through a host: true unless a session
# has found that nothing does.
NAMED: ContextVar[bool] = ContextVar("anything_hosted", default=True)


class IfHosted(ColumnElement[Any]):
    """A step of the walk that is written only where something runs on a host, and
    is nothing, NULL, where nothing does."""

    __visit_name__ = "if_hosted"
    inherit_cache = True

    def __init__(self, inner: ColumnElement[Any]) -> None:
        self.inner = inner
        self.type = inner.type

    def _gen_cache_key(self, anon_map: Any, bindparams: list[Any]) -> Any:
        # The statement with the step and the one without are two statements, each
        # cached as itself.
        if not NAMED.get():
            return (self.__class__, False)
        key = super()._gen_cache_key(anon_map, bindparams)
        return None if key is None else (key, True)


# What a traversal of a statement, and its key in the cache, goes into: the step.
IfHosted._traverse_internals = [("inner", InternalTraversal.dp_clauseelement)]


@compiles(IfHosted)
def _compiled(element: IfHosted, compiler: Any, **kw: Any) -> str:
    if not NAMED.get():
        return "NULL"
    return compiler.process(element.inner, **kw)


def anything_hosted(session: Session) -> bool:
    """Return whether any item names a host, asked once for the session."""
    known = session.info.get(KEY)
    if known is None:
        # A HID is never empty, so "greater than nothing" finds what is not null, and
        # unlike IS NOT NULL it is answered from the index of each column: where nothing
        # runs on anything, two looks into two empty indexes, and no walk of the items.
        found = session.connection().execute(
            select(literal(1))
            .prefix_with(MARK)
            .where(or_(Item.host_item_hid > "", Item.host_group_hid > ""))
            .limit(1)
        )
        known = found.first() is not None
        session.info[KEY] = known
    return known


@event.listens_for(Session, "do_orm_execute")
def _before_a_query(state: ORMExecuteState) -> None:
    if state.is_select:
        NAMED.set(anything_hosted(state.session))


@event.listens_for(Session, "after_flush")
def _after_a_flush(session: Session, _: Any) -> None:
    if session.info.get(KEY) is False and any(
        isinstance(one, Item) and (one.host_item_hid or one.host_group_hid)
        for one in (*session.new, *session.dirty)
    ):
        session.info[KEY] = True


@event.listens_for(Session, "after_commit")
@event.listens_for(Session, "after_rollback")
def _after_a_transaction(session: Session) -> None:
    # Somebody else may have named a host since: the next transaction asks again.
    session.info.pop(KEY, None)
