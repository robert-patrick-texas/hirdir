"""What the audit trail says of a record that is not there: that an Admin deleted it,
when, by whom and why (P-236)."""

from sqlalchemy import literal, select, union_all
from sqlalchemy.orm import Session

from hirdir import clock
from hirdir.db.models import AuditEvent, Base, User
from hirdir.domain import settings
from hirdir.domain.errors import Deleted, NotFound

ACTION = "delete"
# The entry of a deletion's event that holds the reason the Admin gave.
REASON = "reason"


def kinds_in_trail(db: Session) -> tuple[str, ...]:
    """Return every kind of record the audit trail names, read once from its index."""
    return tuple(kind for kind in db.scalars(select(AuditEvent.record_type).distinct()) if kind)


def holder_of(db: Session, hid: str, kinds: tuple[str, ...]) -> AuditEvent | None:
    """Return an event of the record of any kind that has or had `hid`, its deletion
    first where it was deleted or removed, or None where no record ever had it (P-311).
    Every record is audited as it is made, so the trail knows each HID that was given."""
    if not kinds:
        return None
    return db.scalars(
        select(AuditEvent)
        .where(AuditEvent.record_type.in_(kinds), AuditEvent.record_hid == hid)
        .order_by((AuditEvent.action == ACTION).desc(), AuditEvent.at.desc())
        .limit(1)
    ).first()


def table_holding(db: Session, hid: str) -> str | None:
    """Return the table that holds a record of `hid`, of every table whose records have an
    HID, or None (P-311). Each is looked at by its primary key, in one statement: some
    records are made with no event of the trail, as the choices that the migrations make."""
    tables = [
        table
        for table in sorted(Base.metadata.tables.values(), key=lambda one: one.name)
        if "hid" in table.c and table.c.hid.primary_key
    ]
    found = union_all(
        *(select(literal(table.name).label("name")).where(table.c.hid == hid) for table in tables)
    )
    return db.scalars(select(found.subquery().c.name).limit(1)).first()


def deletion(db: Session, record_type: str, hid: str) -> AuditEvent | None:
    """Return the event in which a record was deleted, or None where it never was."""
    return db.scalars(
        select(AuditEvent)
        .where(
            AuditEvent.record_type == record_type,
            AuditEvent.record_hid == hid,
            AuditEvent.action == ACTION,
        )
        .order_by(AuditEvent.at.desc(), AuditEvent.hid.desc())
        .limit(1)
    ).first()


def reason_of(event: AuditEvent) -> str | None:
    """Return the reason a deletion's event holds."""
    for entry in event.changes or []:
        if entry.get("field") == REASON:
            return entry.get("new")
    return None


def missing(db: Session, record_type: str, hid: str, what: str) -> NotFound:
    """Return the refusal of a record of a kind that an Admin deletes, which is not there.

    Where it was deleted, the refusal says so, with when and by whom, read from the
    audit trail; where it never was, it says there is none.
    """
    event = deletion(db, record_type, hid) if hid else None
    if event is None:
        return NotFound(f"there is no {what} {hid}")
    actor = db.get(User, event.actor_hid) if event.actor_hid else None
    name = actor.username if actor is not None else None
    reason = reason_of(event)
    # The reason is in `reason` alone, and not said again in the words: it may be long.
    said = (
        f"the {what} {hid} was deleted on {clock.shown(event.at, settings.time_zone(db))} "
        f"by {name or 'the system'}"
    )
    return Deleted(
        said,
        at=event.at,
        actor_hid=event.actor_hid,
        actor_name=name,
        reason=reason,
    )
