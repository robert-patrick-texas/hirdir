"""Bulk edit: one change to many items, previewed and applied as an import is.

A bulk edit is turned into the rows of a file that nobody had to write: one row for
each item chosen, naming it by its HID and holding the change. From there it is an
import, with the same preview, the same rules and the same refusal of a stale copy.
"""

from collections.abc import Sequence
from typing import Any

from sqlalchemy.orm import Session

from hirdir.auth.roles import Role
from hirdir.db.models import ImportJob, Item
from hirdir.domain import records, settings, tags
from hirdir.domain.audit import AuditContext
from hirdir.domain.errors import Invalid
from hirdir.io import columns as cells
from hirdir.io import exports, files, filters, imports
from hirdir.io.columns import BLANK, Unreadable
from hirdir.io.entities import ENTITIES
from hirdir.io.fields import ITEMS, default_view
from hirdir.io.files import Row

PIECE = 500
ITEM = ENTITIES["items"]


def _change(set_: dict[str, Any], one_item: bool) -> dict[str, Any]:
    """Return the fields a bulk edit sets, as plain values, refusing what it may not set.

    The fields that tell one item from another are set on one item at a time: only a
    change that names a single item by its HID may hold them.
    """
    values: dict[str, Any] = {}
    wrong: dict[str, str] = {}
    for name, given in set_.items():
        column = ITEM.column(name)
        if column is None or not column.settable or column.name == "tags":
            wrong[f"set.{name}"] = (
                "use add_tags and remove_tags" if name == "tags" else "not a field that can be set"
            )
        elif column.name in ITEM.not_in_bulk and not one_item:
            wrong[f"set.{name}"] = "tells one item from another, and is set on one item at a time"
        else:
            try:
                value = cells.from_json(column, given)
            except Unreadable as error:
                wrong[f"set.{name}"] = str(error)
                continue
            if value is BLANK:
                wrong[f"set.{name}"] = "give a value, or null to clear the field"
            else:
                values[column.name] = value
    if wrong:
        raise Invalid("the change is not acceptable", wrong)
    return values


def _labels(db: Session, given: Sequence[str], name: str) -> dict[str, str]:
    """Return the tags named, by key, refusing a label that is not a tag."""
    known = {records.key(tag.label): tag.label for tag, _ in tags.list_tags(db)}
    unknown = [label for label in given if records.key(label) not in known]
    if unknown:
        raise Invalid("a tag is not known", {name: f"there is no tag {', '.join(unknown)}"})
    return {records.key(label): known[records.key(label)] for label in given}


def preview(
    db: Session,
    context: AuditContext,
    role: Role | None,
    *,
    filter_: Any = None,
    hids: Sequence[str] | None = None,
    all_rows: bool = False,
    include_archived: bool = False,
    include_drafts: bool = False,
    set_: dict[str, Any] | None = None,
    add_tags: Sequence[str] = (),
    remove_tags: Sequence[str] = (),
) -> ImportJob:
    """Work out what a bulk edit would do to each item it names, and store that."""
    change = _change(set_ or {}, one_item=hids is not None and len(set(hids)) == 1)
    adding = _labels(db, add_tags, "add_tags")
    removing = _labels(db, remove_tags, "remove_tags")
    if set(adding) & set(removing):
        raise Invalid(
            "a tag is both added and removed", {"remove_tags": "also among the tags to add"}
        )
    if not change and not adding and not removing:
        raise Invalid("there is nothing to change", {"set": "name at least one field or tag"})
    condition = filters.parse(filter_)
    if condition is None and hids is None and not all_rows:
        raise Invalid(
            "the rows are not named",
            {"filter": "give a filter or a list of HIDs, or all_rows to change every item"},
        )
    if hids is not None and not hids:
        raise Invalid("the rows are not named", {"hids": "name at least one item"})
    if hids is not None and len(hids) > exports.MAX_HIDS:
        raise Invalid(
            "too many records are named",
            {"hids": f"at most {exports.MAX_HIDS:,}; a filter chooses any number"},
        )
    order = filters.order_by(
        filters.parse_sort(list(ITEMS.default_sort), ITEMS.fields), ITEMS.fields
    )
    where = [filters.to_sql(condition, ITEMS.fields, settings.time_zone(db), db)]
    if hids is None:
        # Rows named one by one are changed whatever their status. A filter leaves out
        # what a list leaves out.
        where += default_view(ITEMS, include_archived, include_drafts)
    else:
        where.append(Item.hid.in_(list(hids)))
    found = exports.chosen(db, ITEMS, where, [*order, Item.hid.asc()])
    if len(found) > files.MAX_ROWS:
        raise files.TooLarge(f"a bulk edit changes at most {files.MAX_ROWS:,} items at a time")
    if hids is not None and len(found) != len(set(hids)):
        raise Invalid(
            "an item is not known",
            {"hids": f"{len(set(hids)) - len(found)} of the HIDs are not items the filter keeps"},
        )
    rows = []
    for start in range(0, len(found), PIECE):
        piece = found[start : start + PIECE]
        current = tags.labels_of(db, "item", piece) if adding or removing else {}
        for hid in piece:
            values = {"hid": hid, **change}
            if adding or removing:
                kept = {records.key(label): label for label in current[hid]}
                kept.update(adding)
                values["tags"] = sorted(
                    (label for key, label in kept.items() if key not in removing),
                    key=records.key,
                )
            rows.append(Row(values=values))
    return imports.preview_rows(
        db, context, role, source="bulk", which=ITEM, mode="update", rows=rows
    )
