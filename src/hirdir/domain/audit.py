"""The audit trail: every change and every sign-in, kept for good."""

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from hirdir.db.models import AuditEvent


@dataclass(frozen=True)
class AuditContext:
    """Who is acting, through which door, in which request."""

    actor_hid: str | None
    via: str
    request_id: str = ""


SYSTEM = AuditContext(actor_hid=None, via="system")


def change(field: str, old: Any, new: Any) -> dict[str, Any]:
    """Return one entry of an event's `changes`."""
    return {"field": field, "old": old, "new": new}


def record(
    db: Session,
    context: AuditContext,
    action: str,
    record_type: str = "",
    record_hid: str | None = None,
    changes: list[dict[str, Any]] | None = None,
) -> AuditEvent:
    """Add one event to the trail. It is written with the caller's transaction."""
    event = AuditEvent(
        actor_hid=context.actor_hid,
        via=context.via,
        request_id=context.request_id,
        action=action,
        record_type=record_type,
        record_hid=record_hid,
        changes=changes or [],
    )
    db.add(event)
    return event
