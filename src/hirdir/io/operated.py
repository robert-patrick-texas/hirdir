"""What an operator is on, and how (P-177).

An operator is given to places, to device groups and to items as their own, and every
item beneath a place or in a group that has no operator nearer to it has it from there.
This answers, for one operator, each place and group it is given to, how many items have
it from that record, what beneath it has it too, and what beneath it is another's; and how
many items have it as their own or from the item they are in. Every count comes with the
filter of the item list that lists those items, and is counted by that filter, so that a
link from a count leads to exactly what it counts.
"""

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from hirdir.db.models import DeviceGroup, Location, Operator, Region, Site
from hirdir.domain import descent, geography, operators
from hirdir.io import fields, listing

# The most places or groups listed beneath one box; the rest are counted.
MOST_BENEATH = 20


@dataclass
class Count:
    """How many items of the view, and the filter of the item list that lists them."""

    count: int
    filter: dict[str, Any]


@dataclass
class Beneath:
    """The records beneath a box that have the operator from it."""

    count: int
    shown: list[dict[str, Any]] = field(default_factory=list)

    @property
    def more(self) -> int:
        return self.count - len(self.shown)


@dataclass
class PlaceBox:
    hid: str
    level: str
    path: str
    items: Count
    beneath: Beneath
    exceptions: Count


@dataclass
class GroupBox:
    hid: str
    name: str
    type: str
    items: Count
    beneath: Beneath
    exceptions: Count


@dataclass
class Operated:
    operator_hid: str
    places: list[PlaceBox]
    groups: list[GroupBox]
    own: Count
    from_item: Count
    totals: Count


def _condition(name: str, op: str, value: Any) -> dict[str, Any]:
    return {"field": name, "op": op, "value": value}


def _all(*conditions: dict[str, Any]) -> dict[str, Any]:
    return {"and": list(conditions)}


def operated(
    db: Session, operator: Operator, *, include_drafts: bool = False, include_archived: bool = False
) -> Operated:
    """Return what an operator is on, and how, for a view of the items."""

    def counted(filter_: dict[str, Any]) -> Count:
        found = listing.count(
            db,
            fields.ITEMS,
            filter_=filter_,
            include_archived=include_archived,
            include_drafts=include_drafts,
        )
        return Count(found, filter_)

    hid = operator.hid
    mine = _condition("effective.operator_hid", "eq", hid)
    others = _condition("effective.operator_hid", "ne", hid)
    source = "effective.operator_hid.source"
    holder = "effective.operator_hid.source_hid"
    gone = operators.released(db)
    atlas = geography.Atlas(db)

    places: list[PlaceBox] = []
    for level, model in (
        (geography.REGION, Region),
        (geography.SITE, Site),
        (geography.LOCATION, Location),
    ):
        given = db.scalars(
            select(model).where(model.operator_hid == hid, model.record_status != "retired")
        )
        for place in given:
            spot = geography.Place(level, place)
            beneath = _places_beneath(db, atlas, spot, gone)
            places.append(
                PlaceBox(
                    hid=place.hid,
                    level=level,
                    path=atlas.path(spot),
                    items=counted(_all(mine, _condition(holder, "eq", place.hid))),
                    beneath=beneath,
                    exceptions=counted(_all(_condition("location", "within", place.hid), others)),
                )
            )
    places.sort(key=lambda box: (box.path.casefold(), box.hid))

    groups: list[GroupBox] = []
    given_groups = list(
        db.scalars(
            select(DeviceGroup).where(
                DeviceGroup.operator_hid == hid, DeviceGroup.record_status != "retired"
            )
        )
    )
    every_group = list(
        db.scalars(select(DeviceGroup).where(DeviceGroup.record_status != "retired"))
    )
    in_force = descent.of_groups(db, every_group, "operator_hid", gone)
    for group in sorted(given_groups, key=lambda one: (one.name_key, one.hid)):
        nested = sorted(
            (
                one
                for one in every_group
                if one.hid != group.hid
                and in_force[one.hid].value == hid
                and in_force[one.hid].source_hid == group.hid
            ),
            key=lambda one: (one.name_key, one.hid),
        )
        groups.append(
            GroupBox(
                hid=group.hid,
                name=group.name,
                type=group.type,
                items=counted(_all(mine, _condition(holder, "eq", group.hid))),
                beneath=Beneath(
                    len(nested),
                    [
                        {"hid": one.hid, "name": one.name, "type": one.type}
                        for one in nested[:MOST_BENEATH]
                    ],
                ),
                exceptions=counted(_all(_condition("group", "within", group.hid), others)),
            )
        )

    return Operated(
        operator_hid=hid,
        places=places,
        groups=groups,
        own=counted(_all(mine, _condition(source, "eq", "own"))),
        from_item=counted(_all(mine, _condition(source, "eq", "parent_item"))),
        totals=counted(mine),
    )


def _places_beneath(
    db: Session, atlas: geography.Atlas, place: geography.Place, gone: set[str]
) -> Beneath:
    """Return the places beneath a place that have the operator from it: those of no
    operator of their own, nor one nearer to them that is not retired."""
    found: list[dict[str, Any]] = []
    for below in _beneath(db, place):
        chain = atlas.chain(below)
        holder = next(
            (
                one
                for one in chain
                if one.record.operator_hid is not None and one.record.operator_hid not in gone
            ),
            None,
        )
        if holder is not None and holder.hid == place.hid:
            found.append({"hid": below.hid, "level": below.level, "path": atlas.path(below)})
    found.sort(key=lambda one: (one["path"].casefold(), one["hid"]))
    return Beneath(len(found), found[:MOST_BENEATH])


def _beneath(db: Session, place: geography.Place) -> list[geography.Place]:
    """Return every place beneath a place that is not retired: the regions, the sites
    and the locations within it."""
    regions: list[str] = []
    sites: list[Site] = []
    locations: list[Location] = []
    live = Location.record_status != "retired"
    if place.level == geography.REGION:
        regions = list(db.scalars(geography.regions_beneath(place.hid)))
        sites = list(
            db.scalars(
                select(Site).where(Site.region_hid.in_(regions), Site.record_status != "retired")
            )
        )
        site_hids = [one.hid for one in sites]
        locations = list(db.scalars(select(Location).where(Location.site_hid.in_(site_hids), live)))
    elif place.level == geography.SITE:
        locations = list(db.scalars(select(Location).where(Location.site_hid == place.hid, live)))
    else:
        inside = list(db.scalars(geography.locations_beneath(place.hid)))
        locations = list(
            db.scalars(
                select(Location).where(Location.hid.in_(inside), Location.hid != place.hid, live)
            )
        )
    held = [
        geography.Place(geography.REGION, one)
        for one in db.scalars(
            select(Region).where(
                Region.hid.in_(regions), Region.hid != place.hid, Region.record_status != "retired"
            )
        )
    ]
    held += [geography.Place(geography.SITE, one) for one in sites]
    held += [geography.Place(geography.LOCATION, one) for one in locations]
    return held
