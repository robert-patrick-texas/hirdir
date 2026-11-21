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
from typing import Any, Literal

from sqlalchemy import ColumnElement, case, func, literal, or_, select
from sqlalchemy.orm import Session, aliased

from hirdir import ids
from hirdir.auth.roles import Role
from hirdir.db import dialect
from hirdir.db.models import Contact, DeviceGroup, Item, Location, Operator, Region, Site, User
from hirdir.domain import descent, geography, records, tags
from hirdir.domain.audit import AuditContext
from hirdir.domain.errors import Conflict, Existing, Invalid, NotAllowed, NotFound
from hirdir.domain.inheritance import NOTHING, Effective

RECORD_TYPE = "operator"
# Internal where the contact behind a label is a user's, external, to hirdir, where it is
# not; and no scope where nobody is behind it (P-172).
type Scope = Literal["internal", "external"]
INTERNAL: Scope = "internal"
EXTERNAL: Scope = "external"
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


def behind(contact: Contact | None) -> bool:
    """Say whether somebody stands behind a label with this contact: one that is not
    retired. A retired contact is as no contact, on each of the three lists (P-280)."""
    return contact is not None and contact.record_status != "retired"


def is_open(operator: Operator, contact: Contact | None) -> bool:
    """Say whether nobody is behind a label: it has no contact, or one that is retired."""
    return not behind(contact)


def nobody_behind(contact: Any) -> ColumnElement[bool]:
    """Say, for the database, what `behind` says is not so: that the contact a column of
    `contact` is, joined as an outer join, is none, or is retired (P-172, P-280)."""
    return or_(contact.hid.is_(None), contact.record_status == "retired")


def scope(contact: Contact | None, users: Mapping[str, User]) -> Scope | None:
    """Say whether the person behind a label is a user, `internal`, or is not, `external`.

    `users` gives the user each contact is, by the contact's HID, as
    `hirdir.domain.contacts.users_of` returns it. A label with nobody behind it, no
    contact or one that is retired, has none: it is open.
    """
    if contact is None or contact.record_status == "retired":
        return None
    return INTERNAL if contact.hid in users else EXTERNAL


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
                Existing(RECORD_TYPE, taken.hid, taken.label),
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
            # A label does not stand on a retired contact. The writer's place is taken
            # before the contact is looked at, so that a retirement of it at the same
            # moment waits, and then finds this label (P-297).
            dialect.hold_other_writers(db)
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


def brought_back_by_an_admin(
    record: Any, values: dict[str, Any], role: Role | None, what: str
) -> None:
    """Refuse a change that brings a retired contact or operator back, its
    `record_status` changed from `retired`, to anybody but an Admin (P-298). To retire
    one is the Inventory role's, and every other kind of record is brought back as
    before."""
    if _brought_back(record, values) and role is not Role.ADMIN:
        raise NotAllowed(f"an Admin brings a retired {what} back: this needs the admin role")


def _brought_back(record: Any, values: dict[str, Any]) -> bool:
    """Say whether a change brings a retired record back: its `record_status` changed
    from `retired`, to `active` or to `draft`."""
    return record.record_status == "retired" and values.get("record_status", "retired") != "retired"


def not_onto_a_retired_contact(db: Session, operator: Operator, values: dict[str, Any]) -> None:
    """Refuse a change that brings a retired operator back onto a contact that is retired
    (P-298): a contact is not retired while a label stands on it, and a label is not put
    back on a retired contact either. The way on is said: the contact brought back
    first, or taken off the label, which the same change may do.

    The contact is the one the operator has once the change is made. The writer's place
    is taken before it is looked at, and it is read anew, so that a retirement of the
    contact at the same moment waits, and then finds this label, or this finds the
    contact retired.
    """
    hid = values.get("contact_hid", operator.contact_hid)
    if not _brought_back(operator, values) or hid is None:
        return
    dialect.hold_other_writers(db)
    contact = db.get(Contact, hid, populate_existing=True)
    if contact is not None and contact.record_status == "retired":
        raise Conflict(
            f"the contact of {operator.label}, {contact.name}, is retired: bring the contact "
            "back first, or take it off the label",
            {
                "record_status": "a label is not brought back onto a retired contact: bring "
                "the contact back first, or take the contact off the label"
            },
            Existing("contact", contact.hid, contact.name),
        )


def create_operator(db: Session, context: AuditContext, fields: dict[str, Any]) -> Operator:
    """Create an operator: a label, with or without somebody behind it yet."""
    operator = Operator(**_checked(db, {"label": None, **fields}, None))
    records.created(db, context, RECORD_TYPE, operator, FIELDS)
    return operator


def update_operator(
    db: Session,
    context: AuditContext,
    hid: str,
    row_version: int | None,
    fields: dict[str, Any],
    role: Role | None = None,
) -> Operator:
    """Change an operator. Given another contact, everything the label is on is that
    person's at once; given none, it is an open assignment. Nothing else is written to.

    `role` is the role of whoever asks: a retired operator is brought back, its
    `record_status` changed from `retired`, by an Admin alone, and not onto a contact
    that is retired (P-298).
    """
    operator = get_operator(db, hid)
    values = _checked(db, fields, operator)
    brought_back_by_an_admin(operator, values, role, RECORD_TYPE)
    not_onto_a_retired_contact(db, operator, values)
    records.apply(db, context, RECORD_TYPE, operator, row_version, values)
    return operator


def retire_operator(
    db: Session, context: AuditContext, hid: str, row_version: int | None
) -> Operator:
    """Release what a label is on: retired, it stands for nothing, and each thing it
    was on has the operator of the next level up, or none. This is the change of the
    operator alone: `hirdir.domain.people.retire` sees first to what is linked to it,
    and the routes go through it (P-297)."""
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
    a region outward; with `holder_hid` and `holder_level`, the place that holds it."""

    def held(own: Any, hid: Any, level: str, then_hid: Any, then_level: Any) -> tuple[Any, Any]:
        mine = own.is_not(None)
        return case((mine, hid), else_=then_hid), case((mine, literal(level)), else_=then_level)

    child_region: Any = aliased(Region)
    top_live = live(Region.operator_hid)
    regions = (
        select(
            Region.hid.label("region_hid"),
            top_live.label("operator_hid"),
            case((top_live.is_not(None), Region.hid)).label("holder_hid"),
            case((top_live.is_not(None), literal("region"))).label("holder_level"),
        )
        .where(Region.parent_region_hid.is_(None))
        .cte(recursive=True)
    )
    child_live = live(child_region.operator_hid)
    regions = regions.union_all(
        select(
            child_region.hid,
            func.coalesce(child_live, regions.c.operator_hid),
            *held(
                child_live, child_region.hid, "region", regions.c.holder_hid, regions.c.holder_level
            ),
        ).where(child_region.parent_region_hid == regions.c.region_hid)
    )
    site_live = live(Site.operator_hid)
    site_hid, site_level = held(
        site_live, Site.hid, "site", regions.c.holder_hid, regions.c.holder_level
    )
    location_live = live(Location.operator_hid)
    child: Any = aliased(Location)
    locations = (
        select(
            Location.hid.label("location_hid"),
            func.coalesce(location_live, site_live, regions.c.operator_hid).label("operator_hid"),
            case((location_live.is_not(None), Location.hid), else_=site_hid).label("holder_hid"),
            case((location_live.is_not(None), literal("location")), else_=site_level).label(
                "holder_level"
            ),
        )
        .select_from(Location)
        .join(Site, Site.hid == Location.site_hid)
        .outerjoin(regions, regions.c.region_hid == Site.region_hid)
        .where(Location.parent_location_hid.is_(None))
        .cte(recursive=True)
    )
    inner_live = live(child.operator_hid)
    return locations.union_all(
        select(
            child.hid,
            func.coalesce(inner_live, locations.c.operator_hid),
            *held(
                inner_live, child.hid, "location", locations.c.holder_hid, locations.c.holder_level
            ),
        ).where(child.parent_location_hid == locations.c.location_hid)
    )
