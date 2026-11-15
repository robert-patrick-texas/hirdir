"""The renewal alert after sign-in (P-117, P-128).

A person with the Inventory or the Admin role is shown how many contracts have lapsed,
have a renewal pending, of which overdue, and end within the warning period, and the
same of the agreements, each count leading to its list on the worklist. It is shown
once a day: a person who has dismissed it is not shown it again until the next day in
the application's time zone, whatever has changed meanwhile (the owner's answer of
2026-11-15). What each person has seen is kept on the server, as a change of their
own, and nothing is written to any contract.
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
from hirdir.io import kept, planning

# The roles the alert is shown to.
SHOWN_TO = (Role.INVENTORY, Role.ADMIN)


@dataclass(frozen=True)
class Summary:
    """The day's lists of the alert: the contracts and the agreements on each, and how
    many contracts are overdue."""

    as_of: date
    within_days: int
    overdue_after: int
    lists: dict[str, list[str]]
    agreements: dict[str, list[str]]
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
    agreements = {name: list(hids) for name, hids in found.agreement_lists.items()}
    version = hashlib.sha256(
        json.dumps([found.as_of.isoformat(), lists, agreements], sort_keys=True).encode()
    ).hexdigest()[:32]
    return Summary(
        found.as_of,
        found.within_days,
        found.overdue_after,
        lists,
        agreements,
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
    for the Inventory and the Admin role when any count is more than none and they have
    not dismissed it yet that day. `new` says how many of each list were not on it
    when they last dismissed it."""
    found = summary(db)
    view = _seen(db, user_hid)
    new = {
        name: len(set(hids) - set(getattr(view, name) if view is not None else []))
        for name, hids in found.lists.items()
    }
    anything = any(found.lists.values()) or any(found.agreements.values())
    dismissed_today = view is not None and view.as_of == found.as_of
    return Alert(found, role in SHOWN_TO and anything and not dismissed_today, new)


def seen(db: Session, context: AuditContext, user_hid: str) -> RenewalAlertView:
    """Keep that a person has seen the alert today, with the contracts on each of its
    lists then: it is not shown to them again until the next day."""
    found = summary(db)
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
