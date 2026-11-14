"""Operators: the labels that stand for who of the team looks after what.

An item, a device group and a place are given a label and never a person, so the
person behind a label is changed in one place. An item has its own operator, or that
of the item above it, or that of a group it is a member of, or that of the place it is
at. A label that is retired is passed over at every level. Nothing is copied down: the
operator in force is worked out when it is read, here for a page of records, and in
`hirdir.io.fields` for the database to filter, sort and count by. A test holds the two
together.
"""

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import ColumnElement, case, func, select
from sqlalchemy.orm import Session, aliased

from hirdir import ids
from hirdir.db.models import Contact, DeviceGroup, Item, Location, Operator, Region, Site
from hirdir.domain import descent, geography, records, tags
from hirdir.domain.audit import AuditContext
from hirdir.domain.errors import Conflict, Invalid, NotFound
from hirdir.domain.inheritance import NOTHING, Effective

RECORD_TYPE = "operator"
FIELDS = ("label", "description", "colour", "contact_hid", "record_status")
MAX_LABEL = 40
GROUP_ORDER = descent.GROUP_ORDER
SOURCE_GROUP = descent.SOURCE_GROUP
# What may be given an operator, for counting what a label is on.
HOLDERS: tuple[Any, ...] = (Item, DeviceGroup, Region, Site, Location)


# --- the labels ----------------------------------------------------------------------


def get_operator(db: Session, hid: str) -> Operator:
    """Return the operator with hid."""
    operator = db.get(Operator, hid)
    if operator is None:
        raise NotFound(f"there is no operator {hid}")
    return operator


def find_operator(db: Session, text: str) -> Operator | None:
    """Return the operator that text names: by its HID or by its label."""
    text = text.strip()
    if ids.is_hid(text):
        found = db.get(Operator, text)
        if found is not None:
            return found
    return db.scalar(select(Operator).where(Operator.label_key == records.key(text)))


def the_one(db: Session, text: str, field: str) -> Operator:
    """Return the operator text names, or refuse a label that there is not."""
    found = find_operator(db, text)
    if found is None:
        raise Invalid("there is no such operator", {field: f"there is no operator {text}"})
    return found


def is_open(operator: Operator, contact: Contact | None) -> bool:
    """Say whether nobody is behind a label: it has no contact, or one that is retired."""
    return contact is None or contact.record_status == "retired"


def _checked(db: Session, fields: dict[str, Any], operator: Operator | None) -> dict[str, Any]:
    values: dict[str, Any] = {}
    if "label" in fields:
        label = records.clean(fields["label"])
        if label is None or ";" in label or len(label) > MAX_LABEL:
            raise Invalid(
                "the label is not acceptable",
                {"label": f"at most {MAX_LABEL} characters, not blank, with no semicolon"},
            )
        taken = db.scalar(select(Operator).where(Operator.label_key == records.key(label)))
        if taken is not None and (operator is None or taken.hid != operator.hid):
            raise Conflict(
                f"there is already an operator {taken.label}",
                {"label": "another operator has this label"},
            )
        values["label"] = label
        values["label_key"] = records.key(label)
    if "description" in fields:
        values["description"] = records.clean(fields["description"])
    if "colour" in fields:
        colour = records.clean(fields["colour"])
        if colour is not None:
            colour = colour.lower()
            if not tags.COLOUR.fullmatch(colour):
                raise Invalid("the colour is not acceptable", {"colour": "in the form #1f6feb"})
        values["colour"] = colour
    if "contact_hid" in fields:
        hid = fields["contact_hid"] or None
        if hid is not None and (operator is None or operator.contact_hid != hid):
            contact = db.get(Contact, hid)
            if contact is None:
                raise Invalid(
                    "there is no such contact", {"contact_hid": f"there is no contact {hid}"}
                )
            if contact.record_status == "retired":
                raise Invalid("the contact is retired", {"contact_hid": "this contact is retired"})
        values["contact_hid"] = hid
    if "record_status" in fields:
        values["record_status"] = records.checked_status(fields["record_status"])
    return values


def create_operator(db: Session, context: AuditContext, fields: dict[str, Any]) -> Operator:
    """Create an operator: a label, with or without somebody behind it yet."""
    operator = Operator(**_checked(db, {"label": None, **fields}, None))
    records.created(db, context, RECORD_TYPE, operator, FIELDS)
    return operator


def update_operator(
    db: Session, context: AuditContext, hid: str, row_version: int, fields: dict[str, Any]
) -> Operator:
    """Change an operator. Given another contact, everything the label is on is that
    person's at once; given none, it is an open assignment. Nothing else is written to."""
    operator = get_operator(db, hid)
    records.apply(db, context, RECORD_TYPE, operator, row_version, _checked(db, fields, operator))
    return operator


def retire_operator(db: Session, context: AuditContext, hid: str, row_version: int) -> Operator:
    """Release what a label is on: retired, it stands for nothing, and each thing it
    was on has the operator of the next level up, or none."""
    operator = get_operator(db, hid)
    records.apply(
        db,
        context,
        RECORD_TYPE,
        operator,
        row_version,
        {"record_status": "retired"},
        action="retire",
    )
    return operator


def uses(db: Session, hids: Sequence[str]) -> dict[str, int]:
    """Return how many items, groups and places each operator is given to as their own."""
    counts = dict.fromkeys(hids, 0)
    if hids:
        for model in HOLDERS:
            counted = db.execute(
                select(model.operator_hid, func.count())
                .where(model.operator_hid.in_(hids))
                .group_by(model.operator_hid)
            )
            for hid, count in counted:
                if hid is not None:
                    counts[hid] += count
    return counts


# --- who looks after what ------------------------------------------------------------


def released(db: Session) -> set[str]:
    """Return the operators that are retired, and so stand for nothing."""
    return set(db.scalars(select(Operator.hid).where(Operator.record_status == "retired")))


def of_groups(
    db: Session, found: Sequence[DeviceGroup], gone: set[str] | None = None
) -> dict[str, Effective]:
    """Return the operator in force of each group: its own, or that of the nearest
    group it is nested in that has one."""
    return descent.of_groups(db, found, "operator_hid", released(db) if gone is None else gone)


def from_groups(
    db: Session, item_hids: Sequence[str], gone: set[str] | None = None
) -> dict[str, Effective]:
    """Return the operator each item has from the groups it is a current member of."""
    return descent.from_groups(
        db, item_hids, "operator_hid", released(db) if gone is None else gone
    )


def from_places(
    db: Session, location_hids: Sequence[str], gone: set[str] | None = None
) -> dict[str, Effective]:
    """Return the operator that what is at each location has from its place: that of
    the location, of the locations above it, of its site, or of a region outward."""
    gone = released(db) if gone is None else gone
    atlas = geography.Atlas(db)
    atlas.read_locations(location_hids)
    found: dict[str, Effective] = {}
    for hid in location_hids:
        location = atlas.location(hid)
        found[hid] = NOTHING
        if location is None:
            continue
        for one in atlas.chain(geography.Place("location", location)):
            operator = one.record.operator_hid
            if operator is not None and operator not in gone:
                found[hid] = Effective(operator, one.level, one.hid)
                break
    return found


def of_items(
    db: Session, found: Sequence[Item], lines: Mapping[str, Sequence[Item]]
) -> dict[str, Effective]:
    """Return the operator in force of each item, and where it came from.

    `lines` gives the items above each item, the nearest first. The item's own comes
    first, then that of the nearest item above it, then that of a group the item at
    the top of the line is a current member of, then that of the place the item is at.
    """
    gone = released(db)
    in_force = descent.of_items(db, found, lines, "operator_hid", gone)
    nobody = [item for item in found if in_force[item.hid].value is None]
    if not nobody:
        return in_force
    where = descent.of_items(db, nobody, lines, "location_hid")
    by_place = from_places(db, sorted({one.value for one in where.values() if one.value}), gone)
    for item in nobody:
        place = where[item.hid].value
        if place:
            in_force[item.hid] = by_place[place]
    return in_force


# --- the same, for the database ------------------------------------------------------


def live(column: Any) -> ColumnElement[Any]:
    """Return an operator that a record names, or nothing where that operator is retired."""
    gone = select(Operator.hid).where(Operator.record_status == "retired")
    return case((column.in_(gone), None), else_=column)


def group_reach() -> Any:
    """Return, as a table, each group that has an operator in force with that operator."""
    return descent.group_reach("operator_hid", live)


def location_reach() -> Any:
    """Return, as a table, each location with the operator that what is there has from
    its place: the location's own, or that of a location above it, of its site, or of
    a region outward."""
    child_region: Any = aliased(Region)
    regions = (
        select(Region.hid.label("region_hid"), live(Region.operator_hid).label("operator_hid"))
        .where(Region.parent_region_hid.is_(None))
        .cte(recursive=True)
    )
    regions = regions.union_all(
        select(
            child_region.hid,
            func.coalesce(live(child_region.operator_hid), regions.c.operator_hid),
        ).where(child_region.parent_region_hid == regions.c.region_hid)
    )
    child: Any = aliased(Location)
    locations = (
        select(
            Location.hid.label("location_hid"),
            func.coalesce(
                live(Location.operator_hid), live(Site.operator_hid), regions.c.operator_hid
            ).label("operator_hid"),
        )
        .select_from(Location)
        .join(Site, Site.hid == Location.site_hid)
        .outerjoin(regions, regions.c.region_hid == Site.region_hid)
        .where(Location.parent_location_hid.is_(None))
        .cte(recursive=True)
    )
    return locations.union_all(
        select(child.hid, func.coalesce(live(child.operator_hid), locations.c.operator_hid)).where(
            child.parent_location_hid == locations.c.location_hid
        )
    )
