"""The audit trail: every change and every sign-in, kept for good."""

from dataclasses import dataclass, replace
from typing import Any

from sqlalchemy.orm import Session

from hirdir.db.models import AuditEvent


@dataclass(frozen=True)
class AuditContext:
    """Who is acting, through which door, in which request.

    `cause`, where there is one, is what a change was made by beside the request that
    asked for it, as `(field, old, new)`: an item changed by joining a group (P-217). It
    is one more entry of the `changes` of every event made in this context.
    """

    actor_hid: str | None
    via: str
    request_id: str = ""
    cause: tuple[str, Any, Any] | None = None


SYSTEM = AuditContext(actor_hid=None, via="system")


def change(field: str, old: Any, new: Any) -> dict[str, Any]:
    """Return one entry of an event's `changes`."""
    return {"field": field, "old": old, "new": new}


def because(context: AuditContext, field: str, old: Any, new: Any) -> AuditContext:
    """Return the context of changes that are made by something, which each event says."""
    return replace(context, cause=(field, old, new))


def record(
    db: Session,
    context: AuditContext,
    action: str,
    record_type: str = "",
    record_hid: str | None = None,
    changes: list[dict[str, Any]] | None = None,
) -> AuditEvent:
    """Add one event to the trail. It is written with the caller's transaction."""
    entries = list(changes or [])
    if context.cause is not None:
        entries.append(change(*context.cause))
    event = AuditEvent(
        actor_hid=context.actor_hid,
        via=context.via,
        request_id=context.request_id,
        action=action,
        record_type=record_type,
        record_hid=record_hid,
        changes=entries,
    )
    db.add(event)
    return event
