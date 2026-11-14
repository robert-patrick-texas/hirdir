"""Choices: the editable lists that some fields take their values from."""

import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hirdir.db.models import CatalogEntry, Choice, Item, ItemReplacement
from hirdir.domain import audit, records
from hirdir.domain.audit import AuditContext, change
from hirdir.domain.errors import Conflict, Invalid, NotFound

LISTS = (
    "catalog_type",
    "catalog_function",
    "state_reason",
    "item_condition",
    "contact_role",
    "location_kind",
    "replacement_reason",
    "capacity_category",
)
VALUE = re.compile(r"[a-z0-9][a-z0-9_-]{0,39}")
FIELDS = ("list_name", "value", "label", "sort", "active")

# Where the values of each list are stored, so that one in use is never removed.
USES = {
    "catalog_type": ((CatalogEntry, CatalogEntry.type),),
    "catalog_function": ((CatalogEntry, CatalogEntry.function),),
    "state_reason": ((Item, Item.state_reason),),
    "item_condition": ((Item, Item.condition),),
    "replacement_reason": ((ItemReplacement, ItemReplacement.reason),),
}


def _checked_list(list_name: str) -> str:
    name = records.key(list_name)
    if name not in LISTS:
        raise Invalid("there is no such list", {"list": f"one of {', '.join(LISTS)}"})
    return name


def list_choices(db: Session, list_name: str = "") -> list[Choice]:
    """Return the choices of one list, or of every list, in their order."""
    query = select(Choice).order_by(Choice.list_name, Choice.sort, Choice.value_key)
    if list_name:
        query = query.where(Choice.list_name == _checked_list(list_name))
    return list(db.scalars(query))


def get_choice(db: Session, hid: str) -> Choice:
    """Return the choice with hid."""
    choice = db.get(Choice, hid)
    if choice is None:
        raise NotFound(f"there is no choice {hid}")
    return choice


def checked(db: Session, list_name: str, value: str, field: str) -> str:
    """Return value as the list spells it, or refuse a value the list does not offer."""
    choice = db.scalar(
        select(Choice).where(Choice.list_name == list_name, Choice.value_key == records.key(value))
    )
    if choice is None or not choice.active:
        offered = [c.value for c in list_choices(db, list_name) if c.active]
        raise Invalid(
            f"{value} is not a choice of {list_name}", {field: f"one of {', '.join(offered)}"}
        )
    return choice.value


def uses(db: Session, choice: Choice) -> int:
    """Return how many records hold this choice."""
    total = 0
    for model, column in USES.get(choice.list_name, ()):
        total += (
            db.scalar(select(func.count()).select_from(model).where(column == choice.value)) or 0
        )
    return total


def create_choice(
    db: Session,
    context: AuditContext,
    *,
    list_name: str,
    value: str,
    label: str = "",
    sort: int = 0,
    active: bool = True,
) -> Choice:
    """Add a value to a list."""
    list_name = _checked_list(list_name)
    value = records.key(value)
    if not VALUE.fullmatch(value):
        raise Invalid(
            "the value is not acceptable",
            {"value": "1 to 40 lower-case letters, digits, hyphens or underscores"},
        )
    taken = db.scalar(
        select(Choice).where(Choice.list_name == list_name, Choice.value_key == value)
    )
    if taken is not None:
        raise Conflict(
            f"{list_name} already has the value {value}",
            {"value": "the list already has this value"},
        )
    choice = Choice(
        list_name=list_name,
        value=value,
        value_key=value,
        label=label.strip() or value,
        sort=sort,
        active=active,
    )
    records.created(db, context, "choice", choice, FIELDS, names={"list_name": "list"})
    return choice


def update_choice(
    db: Session, context: AuditContext, hid: str, row_version: int, fields: dict[str, Any]
) -> Choice:
    """Change the label, the place in the order, or whether a choice is offered."""
    choice = get_choice(db, hid)
    values: dict[str, Any] = {}
    if "label" in fields:
        label = records.clean(fields["label"])
        if label is None:
            raise Invalid("the label is not acceptable", {"label": "must not be blank"})
        values["label"] = label
    for name in ("sort", "active"):
        if name in fields:
            if fields[name] is None:
                raise Invalid(f"{name} is not acceptable", {name: "must not be blank"})
            values[name] = fields[name]
    records.apply(db, context, "choice", choice, row_version, values)
    return choice


def delete_choice(db: Session, context: AuditContext, hid: str) -> None:
    """Remove a choice that no record holds. One in use can only be made inactive."""
    choice = get_choice(db, hid)
    count = uses(db, choice)
    if count:
        raise Conflict(
            f"{choice.value} is in use on {count} records; make it inactive instead of removing it"
        )
    audit.record(
        db,
        context,
        "delete",
        "choice",
        choice.hid,
        [change("list", choice.list_name, None), change("value", choice.value, None)],
    )
    db.delete(choice)
