"""The renewal alert after sign-in (P-117, P-128).

A person with the Inventory or the Admin role is shown how many contracts have lapsed,
have a renewal pending, of which overdue, and end within the warning period, each
count leading to its list on the worklist. It is shown once: a person who has seen it
is not shown it again until a contract is on one of those three lists that was not on
it when they last saw it. What each person has seen is kept on the server, as a change
of their own, and nothing is written to any contract.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from hirdir import clock
from hirdir.auth.roles import Role
from hirdir.db.models import RenewalAlertView
from hirdir.domain import audit
from hirdir.domain.audit import AuditContext, change
from hirdir.domain.errors import Conflict
from hirdir.io import kept, planning

# The roles the alert is shown to.
SHOWN_TO = (Role.INVENTORY, Role.ADMIN)


@dataclass(frozen=True)
class Summary:
    """The day's lists of the alert: the contracts on each, and how many are overdue."""

    as_of: date
    within_days: int
    overdue_after: int
    lists: dict[str, list[str]]
    overdue: int
    version: str


@dataclass(frozen=True)
class Alert:
    """The alert as one person is to be shown it."""

    summary: Summary
    show: bool
    new: dict[str, int]


def _worked_out(db: Session) -> Summary:
    found = planning.renewals(db)
    lists = {name: list(found.on_lists[name]) for name in planning.ALERTED}
    version = hashlib.sha256(
        json.dumps([found.as_of.isoformat(), lists], sort_keys=True).encode()
    ).hexdigest()[:32]
    return Summary(
        found.as_of,
        found.within_days,
        found.overdue_after,
        lists,
        found.totals["overdue"],
        version,
    )


def summary(db: Session) -> Summary:
    """Return the day's lists of the alert, kept until a change or the day makes them
    stale (P-133)."""
    return kept.answer(db, "renewal_alert", kept.asked(), lambda: _worked_out(db))


def _seen(db: Session, user_hid: str) -> RenewalAlertView | None:
    return db.scalar(select(RenewalAlertView).where(RenewalAlertView.user_hid == user_hid))


def alert(db: Session, user_hid: str, role: Role | None) -> Alert:
    """Return the alert for one person: the counts, and whether to show it, which is so
    for the Inventory and the Admin role when a contract is on a list that it was not
    on when they last saw it."""
    found = summary(db)
    view = _seen(db, user_hid)
    new = {
        name: len(set(hids) - set(getattr(view, name) if view is not None else []))
        for name, hids in found.lists.items()
    }
    return Alert(found, role in SHOWN_TO and any(new.values()), new)


def seen(db: Session, context: AuditContext, user_hid: str, version: str) -> RenewalAlertView:
    """Keep that a person has seen the alert as it was answered: the contracts on each
    of its lists. A version that is no longer the one in force is refused, so that what
    is kept is what they saw."""
    found = summary(db)
    if version != found.version:
        raise Conflict(
            "the alert has changed since it was read",
            {"version": "read the alert again: a contract has come onto or left a list"},
        )
    view = _seen(db, user_hid)
    values = {"as_of": found.as_of, "seen_at": clock.now(), **found.lists}
    if view is None:
        view = RenewalAlertView(user_hid=user_hid, **values)
        view.created_by = context.actor_hid
        view.updated_by = context.actor_hid
        db.add(view)
        db.flush()
    else:
        for name, value in values.items():
            setattr(view, name, value)
        view.updated_by = context.actor_hid
        view.row_version += 1
    audit.record(
        db,
        context,
        "alert_seen",
        "user",
        user_hid,
        [change(name, None, len(hids)) for name, hids in found.lists.items()],
    )
    return view
