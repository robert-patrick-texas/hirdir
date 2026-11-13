"""Tags: labels that may be put on most records."""

import re
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from hirdir.db.models import Tag, TagLink
from hirdir.domain import audit, records
from hirdir.domain.audit import AuditContext, change
from hirdir.domain.errors import Conflict, Invalid, NotFound

COLOUR = re.compile(r"#[0-9a-f]{6}")
FIELDS = ("label", "colour", "description")


def get_tag(db: Session, hid: str) -> Tag:
    """Return the tag with hid."""
    tag = db.get(Tag, hid)
    if tag is None:
        raise NotFound(f"there is no tag {hid}")
    return tag


def list_tags(db: Session) -> list[tuple[Tag, int]]:
    """Return every tag by label, each with the number of records that carry it."""
    counted = db.execute(select(TagLink.tag_hid, func.count()).group_by(TagLink.tag_hid))
    counts = dict(counted.all())
    tags = db.scalars(select(Tag).order_by(Tag.label_key))
    return [(tag, counts.get(tag.hid, 0)) for tag in tags]


def _checked(db: Session, fields: dict[str, Any], except_hid: str | None = None) -> dict[str, Any]:
    values: dict[str, Any] = {}
    if "label" in fields:
        label = records.clean(fields["label"])
        if label is None or ";" in label:
            raise Invalid(
                "the label is not acceptable",
                {"label": "must not be blank or hold a semicolon, which separates tags in a file"},
            )
        taken = db.scalar(select(Tag).where(Tag.label_key == records.key(label)))
        if taken is not None and taken.hid != except_hid:
            raise Conflict(
                f"there is already a tag {taken.label}", {"label": "another tag has this label"}
            )
        values["label"] = label
        values["label_key"] = records.key(label)
    if "colour" in fields:
        colour = records.clean(fields["colour"])
        if colour is not None:
            colour = colour.lower()
            if not COLOUR.fullmatch(colour):
                raise Invalid("the colour is not acceptable", {"colour": "in the form #1f6feb"})
        values["colour"] = colour
    if "description" in fields:
        values["description"] = records.clean(fields["description"])
    return values


def create_tag(db: Session, context: AuditContext, fields: dict[str, Any]) -> Tag:
    """Create a tag."""
    tag = Tag(**_checked(db, {"label": None, **fields}))
    records.created(db, context, "tag", tag, FIELDS)
    return tag


def update_tag(
    db: Session, context: AuditContext, hid: str, row_version: int, fields: dict[str, Any]
) -> Tag:
    """Change a tag. Renaming it renames it on every record that carries it."""
    tag = get_tag(db, hid)
    records.apply(db, context, "tag", tag, row_version, _checked(db, fields, tag.hid))
    return tag


def delete_tag(db: Session, context: AuditContext, hid: str) -> None:
    """Remove a tag that no record carries."""
    tag = get_tag(db, hid)
    count = db.scalar(select(func.count()).select_from(TagLink).where(TagLink.tag_hid == hid))
    if count:
        raise Conflict(f"{tag.label} is on {count} records; take it off them first")
    audit.record(db, context, "delete", "tag", tag.hid, [change("label", tag.label, None)])
    db.delete(tag)


def labels_of(db: Session, record_type: str, hids: list[str]) -> dict[str, list[str]]:
    """Return the tag labels of each of the records, sorted."""
    found: dict[str, list[str]] = {hid: [] for hid in hids}
    if not hids:
        return found
    rows = db.execute(
        select(TagLink.record_hid, Tag.label)
        .join(Tag, Tag.hid == TagLink.tag_hid)
        .where(TagLink.record_type == record_type, TagLink.record_hid.in_(hids))
        .order_by(Tag.label_key)
    )
    for record_hid, label in rows:
        found[record_hid].append(label)
    # Sorted here as well, so the order does not depend on the database's collation.
    return {hid: sorted(labels, key=records.key) for hid, labels in found.items()}


def set_labels(
    db: Session, record_type: str, record_hid: str, labels: list[str]
) -> list[dict[str, Any]]:
    """Make labels the tags of a record. Return the change, or nothing when there is none.

    A label that is not yet a tag is refused: tags are made before they are used.
    """
    wanted: dict[str, Tag] = {}
    unknown = []
    for label in labels:
        tag = db.scalar(select(Tag).where(Tag.label_key == records.key(label)))
        if tag is None:
            unknown.append(label)
        else:
            wanted[tag.hid] = tag
    if unknown:
        raise Invalid("a tag is not known", {"tags": f"there is no tag {', '.join(unknown)}"})
    old = sorted(labels_of(db, record_type, [record_hid])[record_hid], key=records.key)
    new = sorted((tag.label for tag in wanted.values()), key=records.key)
    if old == new:
        return []
    db.execute(
        delete(TagLink).where(TagLink.record_type == record_type, TagLink.record_hid == record_hid)
    )
    db.add_all(
        TagLink(tag_hid=hid, record_type=record_type, record_hid=record_hid) for hid in wanted
    )
    db.flush()
    return [change("tags", old, new)]
