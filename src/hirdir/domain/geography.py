"""Geography: regions, the sites in them, and the locations within a site.

A path is the names from the top region down. It is worked out when it is read and
stored nowhere, so moving a site to another region changes the path of everything in
it and writes to nothing but the site.

What a place has in force, its contacts for each role, its shipping address and its
shipping instructions, is resolved here as well: from the place itself, the locations
above it, its site, then each region outward. Nothing is copied down.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, aliased

from hirdir import ids
from hirdir.db import dialect
from hirdir.db.models import (
    ADDRESS_FIELDS,
    DEGREE_PLACES,
    SHIP_FIELDS,
    Contact,
    ContactAssignment,
    DeviceGroup,
    Item,
    Location,
    Region,
    Site,
)
from hirdir.domain import choices, records, tags
from hirdir.domain.audit import AuditContext
from hirdir.domain.errors import Conflict, Invalid, NotFound

REGION, SITE, LOCATION = "region", "site", "location"
Level = Literal["region", "site", "location"]
LEVELS: tuple[Level, ...] = ("region", "site", "location")
MODELS: dict[str, Any] = {REGION: Region, SITE: Site, LOCATION: Location}
SEPARATOR = ">"
JOINED = " > "
# How deep locations nest within a site: a building, a floor, a room, a rack, and room
# to spare.
MAX_LOCATION_DEPTH = 8
KIND_LIST = "location_kind"
ROLE_LIST = "contact_role"
SHIPPING = (*SHIP_FIELDS, "ship_instructions")
REGION_FIELDS = ("code", "name", "parent_region_hid", *SHIPPING, "notes", "record_status")
SITE_FIELDS = (
    "code",
    "name",
    "region_hid",
    *ADDRESS_FIELDS,
    *SHIPPING,
    "latitude",
    "longitude",
    "notes",
    "record_status",
)
LOCATION_FIELDS = (
    "code",
    "name",
    "site_hid",
    "parent_location_hid",
    "kind",
    *ADDRESS_FIELDS,
    *SHIPPING,
    "latitude",
    "longitude",
    "notes",
    "record_status",
)
# The states in which an item has left the team's hands, and is in no place any more.
OUT_OF_HANDS = ("Released", "Archived")
DEGREES = {"latitude": Decimal(90), "longitude": Decimal(180)}


@dataclass(frozen=True)
class Place:
    """A region, a site or a location."""

    level: Level
    record: Any

    @property
    def hid(self) -> str:
        """The HID of the record."""
        return self.record.hid


# --- reading -------------------------------------------------------------------------


def get_region(db: Session, hid: str) -> Region:
    """Return the region with hid."""
    region = db.get(Region, hid)
    if region is None:
        raise NotFound(f"there is no region {hid}")
    return region


def get_site(db: Session, hid: str) -> Site:
    """Return the site with hid."""
    site = db.get(Site, hid)
    if site is None:
        raise NotFound(f"there is no site {hid}")
    return site


def get_location(db: Session, hid: str) -> Location:
    """Return the location with hid."""
    location = db.get(Location, hid)
    if location is None:
        raise NotFound(f"there is no location {hid}")
    return location


def get_place(db: Session, level: str, hid: str) -> Place:
    """Return the place of one level with hid."""
    getters = {REGION: get_region, SITE: get_site, LOCATION: get_location}
    for known in LEVELS:
        if known == level:
            return Place(known, getters[known](db, hid))
    raise NotFound(f"there is no {level} {hid}")


class Atlas:
    """The places one answer needs, each read once, and the paths that follow from them.

    Regions are few and are read together. Sites and locations are read as they are
    asked for, a level at a time, so a page of a thousand locations costs a handful of
    statements and not a thousand.
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self._regions: dict[str, Region] | None = None
        self._sites: dict[str, Site] = {}
        self._locations: dict[str, Location] = {}

    @property
    def regions(self) -> dict[str, Region]:
        """Every region, by its HID."""
        if self._regions is None:
            self._regions = {region.hid: region for region in self.db.scalars(select(Region))}
        return self._regions

    def _read(self, model: Any, held: dict[str, Any], hids: Iterable[str | None]) -> None:
        missing = sorted({hid for hid in hids if hid and hid not in held})
        for start in range(0, len(missing), 500):
            piece = missing[start : start + 500]
            held.update(
                (record.hid, record)
                for record in self.db.scalars(select(model).where(model.hid.in_(piece)))
            )

    def take(self, records_: Iterable[Any]) -> None:
        """Hold records that the caller has read already."""
        for record in records_:
            if isinstance(record, Site):
                self._sites[record.hid] = record
            elif isinstance(record, Location):
                self._locations[record.hid] = record

    def read_sites(self, hids: Iterable[str | None]) -> None:
        """Read the sites that are not held yet."""
        self._read(Site, self._sites, hids)

    def read_locations(self, hids: Iterable[str | None]) -> None:
        """Read the locations that are not held yet, with the ones above them and their sites."""
        wanted = list(hids)
        for _ in range(MAX_LOCATION_DEPTH + 1):
            self._read(Location, self._locations, wanted)
            wanted = [
                location.parent_location_hid
                for location in self._locations.values()
                if location.parent_location_hid
                and location.parent_location_hid not in self._locations
            ]
            if not wanted:
                break
        self.read_sites(location.site_hid for location in self._locations.values())

    def site(self, hid: str) -> Site | None:
        """Return a site."""
        self.read_sites([hid])
        return self._sites.get(hid)

    def location(self, hid: str) -> Location | None:
        """Return a location."""
        if hid not in self._locations:
            self.read_locations([hid])
        return self._locations.get(hid)

    def region_line(self, hid: str | None) -> list[Region]:
        """Return a region and the regions above it, the top one first."""
        line: list[Region] = []
        seen: set[str] = set()
        while hid and hid not in seen and hid in self.regions:
            seen.add(hid)
            line.append(self.regions[hid])
            hid = self.regions[hid].parent_region_hid
        return line[::-1]

    def location_line(self, hid: str | None) -> list[Location]:
        """Return a location and the locations above it, the top one first."""
        line: list[Location] = []
        seen: set[str] = set()
        while hid and hid not in seen:
            location = self.location(hid)
            if location is None:
                break
            seen.add(hid)
            line.append(location)
            hid = location.parent_location_hid
        return line[::-1]

    def region_path(self, hid: str | None) -> str:
        """Return the path of a region."""
        return JOINED.join(region.name for region in self.region_line(hid))

    def site_path(self, hid: str | None) -> str:
        """Return the path of a site."""
        site = self.site(hid) if hid else None
        if site is None:
            return ""
        return JOINED.join(part for part in (self.region_path(site.region_hid), site.name) if part)

    def location_path(self, hid: str | None) -> str:
        """Return the path of a location."""
        line = self.location_line(hid)
        if not line:
            return ""
        return JOINED.join([self.site_path(line[0].site_hid), *(one.name for one in line)])

    def path(self, place: Place) -> str:
        """Return the path of a place."""
        if place.level == REGION:
            return self.region_path(place.hid)
        if place.level == SITE:
            self.take([place.record])
            return self.site_path(place.hid)
        self.take([place.record])
        return self.location_path(place.hid)

    def chain(self, place: Place) -> list[Place]:
        """Return a place and what it is in, the nearest first: the locations above a
        location, its site, then each region outward."""
        found: list[Place] = []
        region_hid: str | None
        if place.level == LOCATION:
            self.take([place.record])
            line = self.location_line(place.hid)
            found += [Place("location", one) for one in reversed(line)]
            site = self.site(place.record.site_hid)
        else:
            site = place.record if place.level == SITE else None
        if site is not None:
            found.append(Place("site", site))
            region_hid = site.region_hid
        else:
            region_hid = place.hid
        found += [Place("region", region) for region in reversed(self.region_line(region_hid))]
        return found


def _parts(text: str) -> list[str]:
    return [part.strip() for part in text.split(SEPARATOR)]


def find_place(db: Session, text: str, within: Place | None = None) -> Place | None:
    """Return the region, site or location that text names: by its HID, or by its path.

    With `within`, a path that is not found from the top is tried from that place down,
    as a location is named from its site.
    """
    text = text.strip()
    if ids.is_hid(text):
        for level in LEVELS:
            record = db.get(MODELS[level], text)
            if record is not None:
                return Place(level, record)
    parts = _parts(text)
    if not text or not all(parts):
        return None
    found = _walk(db, parts, None)
    if found is None and within is not None:
        found = _walk(db, parts, within)
    return found


def find_within(db: Session, within: Place | None, name: str) -> Place | None:
    """Return what is directly in a place under a name: a region or a site of a region,
    a location of a site or of a location. With no place, a region at the top."""
    return _walk(db, [name.strip()], within)


def _walk(db: Session, parts: list[str], start: Place | None) -> Place | None:
    """Follow the names of a path down from the top, or from a place."""
    at = start
    for name in parts:
        wanted = records.key(name)
        if at is None:
            region = db.scalar(
                select(Region).where(Region.parent_region_hid.is_(None), Region.name_key == wanted)
            )
            at = Place("region", region) if region is not None else None
        elif at.level == REGION:
            region = db.scalar(
                select(Region).where(Region.parent_region_hid == at.hid, Region.name_key == wanted)
            )
            site = (
                None
                if region is not None
                else db.scalar(
                    select(Site).where(Site.region_hid == at.hid, Site.name_key == wanted)
                )
            )
            at = (
                Place("region", region)
                if region is not None
                else (Place("site", site) if site is not None else None)
            )
        else:
            site_hid = at.hid if at.level == SITE else at.record.site_hid
            parent = None if at.level == SITE else at.hid
            location = db.scalar(
                select(Location).where(
                    Location.site_hid == site_hid,
                    Location.parent_location_hid.is_(None)
                    if parent is None
                    else Location.parent_location_hid == parent,
                    Location.name_key == wanted,
                )
            )
            at = Place("location", location) if location is not None else None
        if at is None:
            return None
    return at


def the_place(db: Session, text: str, field_: str, level: str | None = None) -> Place:
    """Return the place text names, refusing one that is not there or is of another level."""
    place = find_place(db, text)
    what = level or "region, site or location"
    if place is None or (level is not None and place.level != level):
        raise Invalid(f"there is no such {what}", {field_: f"there is no {what} {text}"})
    return place


def regions_beneath(hid: str) -> Select[Any]:
    """Return the statement that yields the HID of a region and of every region within it."""
    inner: Any = aliased(Region)
    start = select(Region.hid.label("hid")).where(Region.hid == hid).cte(recursive=True)
    beneath = start.union_all(select(inner.hid).where(inner.parent_region_hid == start.c.hid))
    return select(beneath.c.hid)


def locations_beneath(hid: str) -> Select[Any]:
    """Return the statement that yields the HID of a location and of every location within it."""
    inner: Any = aliased(Location)
    start = select(Location.hid.label("hid")).where(Location.hid == hid).cte(recursive=True)
    beneath = start.union_all(select(inner.hid).where(inner.parent_location_hid == start.c.hid))
    return select(beneath.c.hid)


def region_ancestry() -> Any:
    """Return, as a table, each region paired with itself and with every region above it."""
    parent: Any = aliased(Region)
    start = select(Region.hid.label("hid"), Region.hid.label("above")).cte(recursive=True)
    return start.union_all(
        select(start.c.hid, parent.parent_region_hid)
        .select_from(start)
        .join(parent, parent.hid == start.c.above)
        .where(parent.parent_region_hid.is_not(None))
    )


# --- checking ------------------------------------------------------------------------


def _name(fields: dict[str, Any], values: dict[str, Any]) -> None:
    if "name" not in fields:
        return
    name = records.clean(fields["name"])
    if name is None or SEPARATOR in name:
        raise Invalid(
            "the name is not acceptable",
            {"name": f"must not be blank or hold '{SEPARATOR}', which separates a path"},
        )
    values["name"] = name
    values["name_key"] = records.key(name)


def _code(fields: dict[str, Any], values: dict[str, Any]) -> None:
    if "code" in fields:
        code = records.clean(fields["code"])
        values["code"] = code
        values["code_key"] = records.key(code) if code else None


def _texts(fields: dict[str, Any], values: dict[str, Any], names: Sequence[str]) -> None:
    for name in names:
        if name in fields:
            values[name] = records.clean(fields[name])


def _coordinates(fields: dict[str, Any], values: dict[str, Any], record: Any | None) -> None:
    for name, limit in DEGREES.items():
        if name not in fields:
            continue
        given = fields[name]
        if given is None:
            values[name] = None
            continue
        try:
            degrees = Decimal(str(given))
            exact = degrees == degrees.quantize(Decimal(1).scaleb(-DEGREE_PLACES))
        except InvalidOperation:
            degrees, exact = Decimal(0), False
        if not exact or not degrees.is_finite() or abs(degrees) > limit:
            raise Invalid(
                f"the {name} is not acceptable",
                {name: f"decimal degrees between -{limit} and {limit}, with at most six places"},
            )
        values[name] = degrees

    def final(name: str) -> Any:
        return values.get(name, getattr(record, name) if record is not None else None)

    if (final("latitude") is None) != (final("longitude") is None):
        missing = "longitude" if final("longitude") is None else "latitude"
        raise Invalid(
            "a place on the map has a latitude and a longitude",
            {missing: "give both, or neither"},
        )


def _taken(what: str, name: str) -> Conflict:
    return Conflict(f"there is already a {what} {name} there", {"name": f"a {what} there has it"})


def _check_code(
    db: Session, model: Any, values: dict[str, Any], record: Any | None, *where: Any
) -> None:
    key = values.get("code_key")
    if not key:
        return
    twin = db.scalar(select(model).where(model.code_key == key, *where))
    if twin is not None and (record is None or twin.hid != record.hid):
        raise Conflict(
            f"the code {twin.code} is taken by {twin.name}", {"code": "another record has it"}
        )


def _sibling_regions(db: Session, parent_hid: str | None, key: str, but: str | None) -> None:
    twin = db.scalar(
        select(Region).where(
            Region.parent_region_hid.is_(None)
            if parent_hid is None
            else Region.parent_region_hid == parent_hid,
            Region.name_key == key,
            Region.hid != (but or ""),
        )
    )
    if twin is not None:
        raise _taken("region", twin.name)


def _sibling_sites(db: Session, region_hid: str | None, key: str, but: str | None) -> None:
    if region_hid is None:
        return
    twin = db.scalar(
        select(Site).where(
            Site.region_hid == region_hid, Site.name_key == key, Site.hid != (but or "")
        )
    )
    if twin is not None:
        raise _taken("site", twin.name)


def _linked(db: Session, model: Any, name: str, hid: Any, record: Any | None, what: str) -> Any:
    """Return the record a place is to be in, refusing a new link to a retired one."""
    found = db.get(model, hid) if hid else None
    if found is None:
        raise Invalid(f"there is no such {what}", {name: f"there is no {what} {hid}"})
    unchanged = record is not None and getattr(record, name) == hid
    if found.record_status == "retired" and not unchanged:
        raise Invalid(f"the {what} is retired", {name: f"this {what} is retired"})
    return found


def _status(fields: dict[str, Any], values: dict[str, Any]) -> None:
    if "record_status" in fields:
        values["record_status"] = records.checked_status(fields["record_status"])


def _checked_region(db: Session, fields: dict[str, Any], region: Region | None) -> dict[str, Any]:
    values: dict[str, Any] = {}
    # Checked against the regions and sites beside it, so nobody else may be changing them.
    dialect.hold_other_writers(db)
    _name(fields, values)
    _code(fields, values)
    _texts(fields, values, (*SHIPPING, "notes"))
    _status(fields, values)
    if "parent_region_hid" in fields:
        parent_hid = fields["parent_region_hid"] or None
        if parent_hid is not None:
            _linked(db, Region, "parent_region_hid", parent_hid, region, "region")
            if region is not None:
                above = {one.hid for one in Atlas(db).region_line(parent_hid)}
                if region.hid in above:
                    raise Invalid(
                        "a region is never within itself",
                        {"parent_region_hid": ("this is the region itself, or a region within it")},
                    )
        values["parent_region_hid"] = parent_hid
    parent = values.get(
        "parent_region_hid", region.parent_region_hid if region is not None else None
    )
    key = values.get("name_key", region.name_key if region is not None else None)
    own = region.hid if region is not None else None
    if key is not None and ("name_key" in values or "parent_region_hid" in values):
        _sibling_regions(db, parent, key, own)
        # A path names one record: a site there must not answer to the same name.
        _sibling_sites(db, parent, key, None)
    _check_code(db, Region, values, region)
    return values


def _checked_site(db: Session, fields: dict[str, Any], site: Site | None) -> dict[str, Any]:
    values: dict[str, Any] = {}
    dialect.hold_other_writers(db)
    _name(fields, values)
    _code(fields, values)
    _texts(fields, values, (*ADDRESS_FIELDS, *SHIPPING, "notes"))
    _coordinates(fields, values, site)
    _status(fields, values)
    if "region_hid" in fields:
        _linked(db, Region, "region_hid", fields["region_hid"], site, "region")
        values["region_hid"] = fields["region_hid"]
    region_hid = values.get("region_hid", site.region_hid if site is not None else None)
    key = values.get("name_key", site.name_key if site is not None else None)
    own = site.hid if site is not None else None
    if key is not None and ("name_key" in values or "region_hid" in values):
        _sibling_sites(db, region_hid, key, own)
        _sibling_regions(db, region_hid, key, None)
    _check_code(db, Site, values, site)
    return values


def _height(db: Session, hid: str) -> int:
    """Return how many levels of locations there are beneath a location."""
    height, level = 0, [hid]
    while level and height <= MAX_LOCATION_DEPTH:
        level = list(
            db.scalars(select(Location.hid).where(Location.parent_location_hid.in_(level)))
        )
        if level:
            height += 1
    return height


def _checked_location(
    db: Session, fields: dict[str, Any], location: Location | None
) -> dict[str, Any]:
    values: dict[str, Any] = {}
    dialect.hold_other_writers(db)
    _name(fields, values)
    _code(fields, values)
    _texts(fields, values, (*ADDRESS_FIELDS, *SHIPPING, "notes"))
    _coordinates(fields, values, location)
    _status(fields, values)
    if "kind" in fields:
        kind = records.clean(fields["kind"])
        values["kind"] = choices.checked(db, KIND_LIST, kind, "kind") if kind else None
    if "site_hid" in fields:
        if location is not None and fields["site_hid"] != location.site_hid:
            raise Invalid(
                "a location stays in its site",
                {"site_hid": "a location is not moved to another site; make it there"},
            )
        _linked(db, Site, "site_hid", fields["site_hid"], location, "site")
        values["site_hid"] = fields["site_hid"]
    site_hid = values.get("site_hid", location.site_hid if location is not None else None)
    if "parent_location_hid" in fields:
        parent_hid = fields["parent_location_hid"] or None
        if parent_hid is not None:
            name = "parent_location_hid"
            parent = _linked(db, Location, name, parent_hid, location, "location")
            if site_hid is None:
                # A new location that names what it is in is in that location's site.
                site_hid = values["site_hid"] = parent.site_hid
            if parent.site_hid != site_hid:
                raise Invalid(
                    "a location is within a location of the same site",
                    {name: "this location is in another site"},
                )
            above = Atlas(db).location_line(parent_hid)
            if location is not None and location.hid in {one.hid for one in above}:
                raise Invalid(
                    "a location is never within itself",
                    {name: "this is the location itself, or a location within it"},
                )
            beneath = _height(db, location.hid) if location is not None else 0
            if len(above) + 1 + beneath > MAX_LOCATION_DEPTH:
                raise Invalid(
                    "locations nest too deep",
                    {name: f"locations nest at most {MAX_LOCATION_DEPTH} deep within a site"},
                )
        values["parent_location_hid"] = parent_hid
    if site_hid is None:
        raise Invalid("a location is in a site", {"site_hid": "name the site it is in"})
    parent_hid = values.get(
        "parent_location_hid", location.parent_location_hid if location is not None else None
    )
    key = values.get("name_key", location.name_key if location is not None else None)
    if key is not None and ("name_key" in values or "parent_location_hid" in values):
        twin = db.scalar(
            select(Location).where(
                Location.site_hid == site_hid,
                Location.parent_location_hid.is_(None)
                if parent_hid is None
                else Location.parent_location_hid == parent_hid,
                Location.name_key == key,
                Location.hid != (location.hid if location is not None else ""),
            )
        )
        if twin is not None:
            raise _taken("location", twin.name)
    _check_code(db, Location, values, location, Location.site_hid == site_hid)
    return values


CHECKS: dict[str, Any] = {
    REGION: (_checked_region, REGION_FIELDS),
    SITE: (_checked_site, SITE_FIELDS),
    LOCATION: (_checked_location, LOCATION_FIELDS),
}
REQUIRED: dict[str, tuple[str, ...]] = {
    REGION: ("name",),
    SITE: ("name", "region_hid"),
    LOCATION: ("name",),
}


# --- changing ------------------------------------------------------------------------


def create_place(db: Session, context: AuditContext, level: str, fields: dict[str, Any]) -> Any:
    """Create a region, a site or a location."""
    labels = fields.pop("tags", None) or []
    check, names = CHECKS[level]
    record = MODELS[level](**check(db, {**dict.fromkeys(REQUIRED[level]), **fields}, None))
    records.created(
        db,
        context,
        level,
        record,
        names,
        then=lambda: tags.set_labels(db, level, record.hid, labels),
    )
    return record


def update_place(
    db: Session,
    context: AuditContext,
    level: str,
    hid: str,
    row_version: int,
    fields: dict[str, Any],
) -> Any:
    """Change a region, a site or a location.

    Giving a site another region moves it, and giving a region another parent moves the
    region with everything in it: one change of one record, and one audit event. The
    paths and what is inherited follow by themselves, because neither is stored.
    """
    record = get_place(db, level, hid).record
    has_tags = "tags" in fields
    labels = fields.pop("tags", None) or []
    check, _ = CHECKS[level]
    values = check(db, fields, record)
    tag_change = tags.set_labels(db, level, hid, labels) if has_tags else []
    records.apply(db, context, level, record, row_version, values, tag_change)
    return record


def _count(db: Session, model: Any, *where: Any) -> int:
    return db.scalar(select(func.count()).select_from(model).where(*where)) or 0


def _within_it(db: Session, place: Place) -> list[str]:
    """Return what is in a place and is not retired, in words, for a refusal."""
    hid = place.hid
    found: list[tuple[int, str]] = []
    if place.level == REGION:
        found.append(
            (
                _count(db, Region, Region.parent_region_hid == hid, _live(Region)),
                "regions",
            )
        )
        found.append((_count(db, Site, Site.region_hid == hid, _live(Site)), "sites"))
    elif place.level == SITE:
        found.append((_count(db, Location, Location.site_hid == hid, _live(Location)), "locations"))
    else:
        found.append(
            (
                _count(db, Location, Location.parent_location_hid == hid, _live(Location)),
                "locations",
            )
        )
        in_hand = Item.lifecycle_state.is_(None) | Item.lifecycle_state.not_in(OUT_OF_HANDS)
        found.append((_count(db, Item, Item.location_hid == hid, _live(Item), in_hand), "items"))
        found.append(
            (
                _count(db, DeviceGroup, DeviceGroup.location_hid == hid, _live(DeviceGroup)),
                "device groups",
            )
        )
    return [f"{count} {what}" for count, what in found if count]


def _live(model: Any) -> Any:
    return model.record_status != "retired"


def retire_place(db: Session, context: AuditContext, level: str, hid: str, row_version: int) -> Any:
    """Retire a region, a site or a location that nothing is in any more."""
    dialect.hold_other_writers(db)
    place = get_place(db, level, hid)
    record = place.record
    if record.record_status != "retired":
        if record.row_version != row_version:
            records.touch(record, context, row_version)
        inside = _within_it(db, place)
        if inside:
            raise Conflict(
                f"{record.name} still holds {', '.join(inside)} that are not retired; "
                "move or retire them first"
            )
    records.apply(
        db, context, level, record, row_version, {"record_status": "retired"}, action="retire"
    )
    return record


# --- what a place has in force ---------------------------------------------------------


@dataclass(frozen=True)
class RoleContacts:
    """The contacts of a place for one role, and the level they came from."""

    role: str
    label: str
    source: str
    source_hid: str | None
    source_path: str | None
    stopped: bool
    contacts: list[tuple[ContactAssignment, Contact]] = field(default_factory=list)


@dataclass(frozen=True)
class Inherited:
    """A value in force for a place, and the level it came from."""

    value: Any
    source: str
    source_hid: str | None
    source_path: str | None


@dataclass(frozen=True)
class InForce:
    """What a place has in force: its contacts by role, and where deliveries go."""

    level: str
    hid: str
    path: str
    contacts: list[RoleContacts]
    ship_address: Inherited
    ship_instructions: Inherited


NOWHERE = Inherited(None, "none", None, None)


def _source(place: Place, asked: Place) -> str:
    return "own" if place.hid == asked.hid else place.level


def effective(db: Session, place: Place) -> InForce:
    """Return what a place has in force, each thing with the level it came from.

    For a role, the first level that has any assignment supplies all of its contacts,
    and a level whose assignment says "none here, and do not look further up" supplies
    none and ends the search. The shipping address is taken whole from the nearest
    record that has any of it, and the shipping instructions likewise by themselves.
    """
    atlas = Atlas(db)
    chain = atlas.chain(place)
    paths = {one.hid: atlas.path(one) for one in chain}
    columns = {
        REGION: ContactAssignment.region_hid,
        SITE: ContactAssignment.site_hid,
        LOCATION: ContactAssignment.location_hid,
    }
    assigned: dict[tuple[str, str], list[tuple[ContactAssignment, Contact | None]]] = {}
    for level, column in columns.items():
        hids = [one.hid for one in chain if one.level == level]
        if not hids:
            continue
        rows = db.execute(
            select(ContactAssignment, Contact)
            .outerjoin(Contact, Contact.hid == ContactAssignment.contact_hid)
            .where(column.in_(hids))
            .order_by(ContactAssignment.priority, Contact.name_key, ContactAssignment.hid)
        )
        for assignment, contact in rows:
            assigned.setdefault((getattr(assignment, column.key), assignment.role), []).append(
                (assignment, contact)
            )
    roles = [(choice.value, choice.label) for choice in choices.list_choices(db, ROLE_LIST)]
    known = {value for value, _ in roles}
    roles += sorted({(role, role) for _, role in assigned if role not in known})
    by_role: list[RoleContacts] = []
    for role, label in roles:
        found = RoleContacts(role, label, "none", None, None, False)
        for one in chain:
            here = assigned.get((one.hid, role))
            if here:
                found = RoleContacts(
                    role,
                    label,
                    _source(one, place),
                    one.hid,
                    paths[one.hid],
                    stopped=any(assignment.stop_inheritance for assignment, _ in here),
                    contacts=[
                        (assignment, contact) for assignment, contact in here if contact is not None
                    ],
                )
                break
        by_role.append(found)

    def nearest(names: Sequence[str], whole: bool) -> Inherited:
        for one in chain:
            held = {name: getattr(one.record, name, None) for name in names}
            if any(value is not None for value in held.values()):
                value: Any = (
                    {name.removeprefix("ship_"): text for name, text in held.items()}
                    if whole
                    else held[names[0]]
                )
                return Inherited(value, _source(one, place), one.hid, paths[one.hid])
        return NOWHERE

    return InForce(
        level=place.level,
        hid=place.hid,
        path=paths[place.hid],
        contacts=by_role,
        ship_address=nearest(SHIP_FIELDS, whole=True),
        ship_instructions=nearest(("ship_instructions",), whole=False),
    )
