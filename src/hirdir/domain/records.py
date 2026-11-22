"""What every editable record shares: clean text, stale-edit refusal and audited changes."""

from collections.abc import Callable, Generator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from hirdir import clock, ids
from hirdir.db.models import AuditEvent
from hirdir.domain import audit
from hirdir.domain.audit import AuditContext, change
from hirdir.domain.errors import Invalid, StaleVersion

RECORD_STATUSES = ("draft", "active", "retired")
RETIRED = "retired"
# Whether the record being made is one a row of a file makes retired (P-311): it is made
# so, in its one create event, and the links it keeps to records that are retired too
# are taken, as a retired record keeps its links in the app.
_MAKING_RETIRED: ContextVar[bool] = ContextVar("making_retired", default=False)


@contextmanager
def making_retired() -> Generator[None]:
    """Within it, the record a row of a file makes is made retired, as the row says."""
    token = _MAKING_RETIRED.set(True)
    try:
        yield
    finally:
        _MAKING_RETIRED.reset(token)


def is_making_retired() -> bool:
    """Say whether the record being made is one a file makes retired (P-311)."""
    return _MAKING_RETIRED.get()


def made_retired_by_a_file(db: Session, record_type: str, record: Any) -> bool:
    """Say whether a retired record was made retired by a row of a file, and is so still:
    its first event is its creation from a file, which says `retired`, and no event after
    changes its status. What stands on a retired record is taken from a file for such a
    one alone, and not for one retired in the app (P-311)."""
    if getattr(record, "record_status", None) != RETIRED:
        return False
    events = db.scalars(
        select(AuditEvent)
        .where(AuditEvent.record_type == record_type, AuditEvent.record_hid == record.hid)
        .order_by(AuditEvent.at, AuditEvent.hid)
    )
    first = True
    for event in events:
        statuses = [one for one in event.changes or [] if one.get("field") == "record_status"]
        if first:
            made = event.action == "create" and event.via == "import"
            if not made or not any(one.get("new") == RETIRED for one in statuses):
                return False
            first = False
        elif statuses or event.action == "retire":
            return False
    return not first


def refuses_retired(found: Any) -> bool:
    """Say whether a new link to `found` is refused for its being retired: it is, but
    from a record that a file makes retired, which may keep it (P-311)."""
    return getattr(found, "record_status", None) == RETIRED and not is_making_retired()


# What puts the rows of a statement in the order that was asked for, before the order
# the statement has of its own. `hirdir.io.tables` makes one from a `sort`.
type AnySelect = Select[*tuple[Any, ...]]
type Arrange = Callable[[AnySelect], AnySelect]
MONEY_FIELDS = ("est_value", "annual_support_cost")


def key(text: str) -> str:
    """Return text as it is compared: without case or surrounding space."""
    return text.strip().casefold()


def clean(value: Any) -> Any:
    """Return a text value without surrounding space, and a blank one as None.

    Text with a NUL character in it is refused: no database keeps it faithfully.
    """
    if isinstance(value, str):
        if "\x00" in value:
            raise Invalid("text must not hold a NUL character")
        return value.strip() or None
    return value


def decimal_text(name: str, value: Decimal) -> str:
    """Write a decimal as every interface shows it: money with two places, the rest plain."""
    if name in MONEY_FIELDS:
        return f"{value:.2f}"
    return format(value.normalize(), "f")


def jsonable(value: Any, name: str = "") -> Any:
    """Return the value of the field called name in the form it takes in an audit event."""
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return decimal_text(name, value)
    return value


def touch(record: Any, context: AuditContext, expected_version: int | None) -> None:
    """Refuse a stale edit, then mark record as changed by the caller."""
    if expected_version is not None and record.row_version != expected_version:
        raise StaleVersion(
            f"this record is at version {record.row_version}, "
            f"and the change was made against version {expected_version}"
        )
    record.row_version += 1
    record.updated_at = clock.now()
    record.updated_by = context.actor_hid


def _stored_only(name: str) -> bool:
    """Say whether a column is bookkeeping for comparing, and not a field of the record."""
    return name.endswith("_key")


def differences(record: Any, values: dict[str, Any]) -> list[dict[str, Any]]:
    """Return a change for each of values that differs from what record holds."""
    return [
        change(name, jsonable(getattr(record, name), name), jsonable(new, name))
        for name, new in values.items()
        if getattr(record, name) != new and not _stored_only(name)
    ]


def created(
    db: Session,
    context: AuditContext,
    record_type: str,
    record: Any,
    fields: tuple[str, ...],
    *,
    names: Mapping[str, str] | None = None,
    then: Callable[[], list[dict[str, Any]]] | None = None,
) -> None:
    """Add record, and audit its creation with every field that was given a value.

    `names` gives the documented name of a field whose attribute is called something
    else. `then` runs once the record has its HID, for what is stored beside the record
    and belongs in the same event, such as its tags; it returns the changes it made.
    """
    record.created_by = context.actor_hid
    record.updated_by = context.actor_hid
    # A row of a file that names its record by an HID no record has makes it so (P-311).
    given = None if record.hid else ids.take_given(record_type)
    if given is not None:
        record.hid = given
    db.add(record)
    db.flush()
    changes = [
        change((names or {}).get(name, name), None, jsonable(getattr(record, name), name))
        for name in fields
        if getattr(record, name) not in (None, [], "")
    ]
    if then is not None:
        changes += then()
    audit.record(db, context, "create", record_type, record.hid, changes)


def apply(
    db: Session,
    context: AuditContext,
    record_type: str,
    record: Any,
    row_version: int | None,
    values: dict[str, Any],
    extra_changes: list[dict[str, Any]] | None = None,
    action: str = "update",
) -> bool:
    """Write values to record and audit what changed. Say whether anything did.

    A request that changes nothing leaves the record and its version alone, and is
    still refused when it was made against a stale copy.
    """
    changes = differences(record, values) + (extra_changes or [])
    if not changes:
        if row_version is not None and record.row_version != row_version:
            touch(record, context, row_version)
        return False
    touch(record, context, row_version)
    for name, new in values.items():
        setattr(record, name, new)
    db.flush()
    audit.record(db, context, action, record_type, record.hid, changes)
    return True


def checked_status(value: Any, allowed: tuple[str, ...] = ("draft", "active")) -> str:
    """Return a record status that a change may set, or refuse it. A record that a
    file makes retired takes `retired` (P-311)."""
    status = key(str(value or ""))
    if status == RETIRED and is_making_retired():
        return status
    if status not in allowed:
        raise Invalid(
            "the record status is not acceptable",
            {"record_status": f"one of {', '.join(allowed)}; use the retire route to retire"},
        )
    return status


def checked_day(name: str, value: Any) -> date | None:
    """Return a day a change gives, or refuse what is not a date."""
    if value is not None and (not isinstance(value, date) or isinstance(value, datetime)):
        raise Invalid(f"{name} is not acceptable", {name: "a date, as YYYY-MM-DD"})
    return value


def checked_span(start: date | None, end: date | None, field: str = "ends_on") -> None:
    """Refuse a range of days that ends before it starts. A blank is open."""
    if start is not None and end is not None and end < start:
        raise Invalid(
            "the dates are not acceptable", {field: "must not be before the day it starts"}
        )


def checked_choice(value: Any, allowed: tuple[str, ...], field: str) -> str:
    """Return one of a fixed list of values as the list spells it, or refuse it."""
    wanted = key(value) if isinstance(value, str) else ""
    if wanted not in allowed:
        raise Invalid(f"{field} is not acceptable", {field: f"one of {', '.join(allowed)}"})
    return wanted


def checked_amount(name: str, value: Any) -> Decimal | None:
    """Return an amount a change gives: a number that is not negative, or nothing."""
    if value is None:
        return None
    if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
        raise Invalid(f"{name} is not acceptable", {name: "a number that is not negative"})
    return value


def linked(
    db: Session, model: Any, field: str, value: Any, record: Any | None, what: str
) -> str | None:
    """Return the HID of a record that a change refers to in `field`.

    A reference that is left as it is, is not looked at again. A new one is to a
    record that exists and is not retired, but from a record a file makes retired.
    """
    hid = value or None
    if hid is None or (record is not None and getattr(record, field) == hid):
        return hid
    found = db.get(model, hid) if isinstance(hid, str) else None
    if found is None:
        raise Invalid(f"there is no such {what}", {field: f"there is no {what} {hid}"})
    if refuses_retired(found):
        raise Invalid(f"the {what} is retired", {field: f"this {what} is retired"})
    return hid


MAX_URL = 2000


def checked_url(name: str, value: Any) -> str | None:
    """Return an address on the web that a change gives, or refuse what is not one."""
    url = clean(value)
    if url is not None and (
        not isinstance(url, str)
        or len(url) > MAX_URL
        or not url.lower().startswith(("https://", "http://"))
        or any(character.isspace() for character in url)
    ):
        raise Invalid(
            f"{name} is not acceptable",
            {name: "an address that begins with https:// or http://, with no space"},
        )
    return url


# --- links ---------------------------------------------------------------------------

MAX_LINKS = 20
MAX_LINK_TEXT = 200
LINKS = "links"
# What a file writes a link with, `text <url>`, and so what neither the text nor the
# address of a link holds.
LINK_MARKS = ("<", ">")


def checked_links(value: Any, name: str = LINKS) -> list[dict[str, str]]:
    """Return the links a change gives a record, in their order, or refuse them.

    Each is an `url`, which begins with https:// or http://, holds no space, neither `<`
    nor `>`, and is at most 2,000 characters, and a `text` to show for it, of at most
    200 characters and without `<` or `>`, which may be blank. A record has 20 at most.
    A refusal names the link. Nothing is a list of none.
    """
    if value is None:
        return []
    if not isinstance(value, list):
        raise Invalid(f"{name} is not acceptable", {name: "a list of links, each url and text"})
    if len(value) > MAX_LINKS:
        raise Invalid(f"{name} is not acceptable", {name: f"at most {MAX_LINKS} links"})
    links = []
    for number, link in enumerate(value, start=1):
        if not isinstance(link, Mapping):
            raise Invalid(f"link {number} is not acceptable", {name: f"link {number}: url, text"})
        try:
            url = checked_url(name, link.get("url"))
        except Invalid:
            url = None
        if url is None or any(mark in url for mark in LINK_MARKS):
            raise Invalid(
                f"link {number} is not acceptable",
                {
                    name: f"link {number}: an address that begins with https:// or http://, "
                    f"with no space, < or >, of at most {MAX_URL:,} characters"
                },
            )
        text = clean(link.get("text"))
        if text is not None and (
            not isinstance(text, str)
            or len(text) > MAX_LINK_TEXT
            or any(mark in text for mark in LINK_MARKS)
        ):
            raise Invalid(
                f"link {number} is not acceptable",
                {name: f"link {number}: a text of at most {MAX_LINK_TEXT} characters, no < or >"},
            )
        links.append({"url": url, "text": text or ""})
    return links
