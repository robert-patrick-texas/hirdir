"""A change that may take the last role from an account takes the writer's place before
it reads the roles it compares (P-299).

Of two such changes at the same moment, an own grant and a group's revoked together,
each would otherwise read the other's grant still there under PostgreSQL's read
committed, and neither would end the sessions. SQLite has one writer whatever is done,
so what is held here is the order: the place is taken before the first read of a role,
and before the count of Admins that the same change keeps.
"""

from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy.orm import Session

from hirdir.db import dialect
from hirdir.domain import accounts, audit


def _person(db: Session) -> tuple[Any, Any, Any]:
    """A person with a role of their own and one through a group."""
    user, _ = accounts.create_user(db, audit.SYSTEM, username="klee", access_code="kim-lee-code-01")
    own = accounts.grant_role(db, audit.SYSTEM, role="viewer", user_hid=user.hid)
    group = accounts.create_group(db, audit.SYSTEM, name="Example Stores")
    accounts.grant_role(db, audit.SYSTEM, role="viewer", group_hid=group.hid)
    accounts.add_member(db, audit.SYSTEM, group.hid, user.hid)
    db.commit()
    return user, own, group


@pytest.mark.parametrize(
    "change",
    [
        lambda db, user, own, group: accounts.revoke_grant(db, audit.SYSTEM, own.hid),
        lambda db, user, own, group: accounts.remove_member(db, audit.SYSTEM, group.hid, user.hid),
        lambda db, user, own, group: accounts.delete_group(db, audit.SYSTEM, group.hid),
    ],
    ids=["revoke_grant", "remove_member", "delete_group"],
)
def test_the_writers_place_is_taken_before_the_roles_are_read(
    db: Session, monkeypatch: pytest.MonkeyPatch, change: Callable[..., None]
) -> None:
    user, own, group = _person(db)
    said: list[str] = []
    held, read, count = dialect.hold_other_writers, accounts.roles_of, accounts._admin_count

    def hold(session: Any) -> None:
        said.append("hold")
        held(session)

    def roles(session: Session, users: Any) -> Any:
        said.append("read")
        return read(session, users)

    monkeypatch.setattr(dialect, "hold_other_writers", hold)

    def admins(session: Session) -> int:
        said.append("count")
        return count(session)

    monkeypatch.setattr(accounts, "roles_of", roles)
    monkeypatch.setattr(accounts, "_admin_count", admins)
    change(db, user, own, group)
    assert {"read", "count"} <= set(said)
    # The place first, then the roles and the count of Admins, each read in it.
    assert said[0] == "hold"
