"""External systems, and the registrations of items and device groups with them.

An external system is another tool that knows what the inventory holds: a monitoring
system, an SDN controller, a cloud service. A registration says that one item or one
group is known there, and by what key. It is on the record it was made for: a stack
that is registered as one device is registered as the stack, and not as its members.
"""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from hirdir import ids
from hirdir.db import dialect
from hirdir.db.models import DeviceGroup, DeviceGroupMember, ExternalSystem, Item, Registration
from hirdir.domain import audit, health, records, settings
from hirdir.domain.audit import AuditContext, change
from hirdir.domain.errors import Conflict, Invalid, NotFound

RECORD_TYPE = "external_system"
REGISTRATION_TYPE = "registration"
KINDS = (
    "monitoring",
    "config_backup",
    "access_control",
    "sdn_controller",
    "cloud_service",
    "dns",
    "discovery",
    "other",
)
OTHER = KINDS[-1]
STATUSES = ("registered", "pending", "removed")
REGISTERED, REMOVED = STATUSES[0], STATUSES[2]
FIELDS = ("name", "kind", "url", "notes", "record_status")
REGISTRATION_FIELDS = (
    "system_hid",
    "item_hid",
    "group_hid",
    "external_id",
    "status",
    "confirmed_at",
)
HOLDERS = {"item_hid": (Item, "item"), "group_hid": (DeviceGroup, "device group")}
# The types of group that are one device on the network.
ONE_DEVICE = ("stack", "cluster")


# --- systems -------------------------------------------------------------------------


def get_system(db: Session, hid: str) -> ExternalSystem:
    """Return the external system with hid."""
    system = db.get(ExternalSystem, hid)
    if system is None:
        raise NotFound(f"there is no external system {hid}")
    return system


def find_system(db: Session, text: str) -> ExternalSystem | None:
    """Return the system that text names: by its HID or by its name."""
    text = text.strip()
    if ids.is_hid(text):
        found = db.get(ExternalSystem, text)
        if found is not None:
            return found
    return db.scalar(select(ExternalSystem).where(ExternalSystem.name_key == records.key(text)))


def the_one(db: Session, text: str, field: str) -> ExternalSystem:
    """Return the system text names, or refuse a name that there is not."""
    found = find_system(db, text)
    if found is None:
        raise Invalid(
            "there is no such external system", {field: f"there is no external system {text}"}
        )
    return found


def _checked(db: Session, fields: dict[str, Any], system: ExternalSystem | None) -> dict[str, Any]:
    values: dict[str, Any] = {}
    if "name" in fields:
        name = records.clean(fields["name"])
        if name is None or ";" in name:
            raise Invalid(
                "the name is not acceptable", {"name": "not blank, and with no semicolon"}
            )
        taken = db.scalar(
            select(ExternalSystem).where(ExternalSystem.name_key == records.key(name))
        )
        if taken is not None and (system is None or taken.hid != system.hid):
            raise Conflict(
                f"there is already an external system {taken.name}",
                {"name": "another external system has this name"},
            )
        values["name"] = name
        values["name_key"] = records.key(name)
    if "kind" in fields:
        values["kind"] = records.checked_choice(fields["kind"] or OTHER, KINDS, "kind")
    if "url" in fields:
        values["url"] = records.checked_url("url", fields["url"])
    if "notes" in fields:
        values["notes"] = records.clean(fields["notes"])
    if "record_status" in fields:
        values["record_status"] = records.checked_status(fields["record_status"])
    return values


def create_system(db: Session, context: AuditContext, fields: dict[str, Any]) -> ExternalSystem:
    """Create an external system."""
    system = ExternalSystem(**_checked(db, {"name": None, **fields}, None))
    records.created(db, context, RECORD_TYPE, system, FIELDS)
    return system


def update_system(
    db: Session, context: AuditContext, hid: str, row_version: int, fields: dict[str, Any]
) -> ExternalSystem:
    """Change an external system."""
    system = get_system(db, hid)
    records.apply(db, context, RECORD_TYPE, system, row_version, _checked(db, fields, system))
    return system


def retire_system(db: Session, context: AuditContext, hid: str, row_version: int) -> ExternalSystem:
    """Retire an external system. Its registrations stay on record."""
    system = get_system(db, hid)
    records.apply(
        db, context, RECORD_TYPE, system, row_version, {"record_status": "retired"}, action="retire"
    )
    return system


# --- registrations -------------------------------------------------------------------


def get_registration(db: Session, hid: str) -> Registration:
    """Return the registration with hid."""
    registration = db.get(Registration, hid)
    if registration is None:
        raise NotFound(f"there is no registration {hid}")
    return registration


def find_registration(
    db: Session, system_hid: str, field: str, holder_hid: str
) -> Registration | None:
    """Return the registration of one item or group with one system, if there is one."""
    return db.scalar(
        select(Registration).where(
            Registration.system_hid == system_hid, getattr(Registration, field) == holder_hid
        )
    )


def _checked_registration(
    db: Session, fields: dict[str, Any], registration: Registration | None
) -> dict[str, Any]:
    values: dict[str, Any] = {}
    if "external_id" in fields:
        values["external_id"] = records.clean(fields["external_id"])
    if "status" in fields:
        values["status"] = records.checked_choice(
            fields["status"] or REGISTERED, STATUSES, "status"
        )
    if "confirmed_at" in fields:
        at = fields["confirmed_at"]
        values["confirmed_at"] = (
            None if at is None else health.moment(at, "confirmed_at", settings.time_zone(db))
        )
    return values


def create_registration(db: Session, context: AuditContext, fields: dict[str, Any]) -> Registration:
    """Register one item or one device group with an external system."""
    # Checked against the registrations there are: one to a system and a record.
    dialect.hold_other_writers(db)
    system_hid = fields.get("system_hid") or ""
    system = db.get(ExternalSystem, system_hid) if isinstance(system_hid, str) else None
    if system is None:
        raise Invalid(
            "there is no such external system",
            {"system_hid": f"there is no external system {system_hid}"},
        )
    if system.record_status == "retired":
        raise Invalid("the system is retired", {"system_hid": "this external system is retired"})
    named = [name for name in HOLDERS if fields.get(name)]
    if len(named) != 1:
        raise Invalid(
            "a registration is of one item or one device group",
            dict.fromkeys(named or HOLDERS, "exactly one of item_hid and group_hid"),
        )
    field = named[0]
    model, what = HOLDERS[field]
    holder = db.get(model, fields[field]) if isinstance(fields[field], str) else None
    if holder is None:
        raise Invalid(f"there is no such {what}", {field: f"there is no {what} {fields[field]}"})
    if holder.record_status == "retired":
        raise Invalid(f"the {what} is retired", {field: f"this {what} is retired"})
    if find_registration(db, system.hid, field, holder.hid) is not None:
        raise Conflict(
            f"it is already registered with {system.name}",
            {field: "a record is registered with one system once; change that registration"},
        )
    registration = Registration(
        system_hid=system.hid,
        **{field: holder.hid},
        **_checked_registration(db, {"status": None, **fields}, None),
    )
    records.created(db, context, REGISTRATION_TYPE, registration, REGISTRATION_FIELDS)
    return registration


def update_registration(
    db: Session, context: AuditContext, hid: str, row_version: int, fields: dict[str, Any]
) -> Registration:
    """Change a registration: its key in the other system, its status, when it was
    confirmed. One that ends is given the status `removed`."""
    registration = get_registration(db, hid)
    for name in ("system_hid", *HOLDERS):
        if name in fields and (fields[name] or None) != getattr(registration, name):
            raise Invalid(
                "a registration stays with its system and its record",
                {name: "give this one the status removed, and register the other"},
            )
    begins_again = (
        registration.status == REMOVED
        and "status" in fields
        and records.key(str(fields["status"] or REGISTERED)) != REMOVED
    )
    if begins_again and get_system(db, registration.system_hid).record_status == "retired":
        # A retired system takes no new registration, and none that begins again.
        raise Invalid("the system is retired", {"status": "this external system is retired"})
    records.apply(
        db,
        context,
        REGISTRATION_TYPE,
        registration,
        row_version,
        _checked_registration(db, fields, registration),
    )
    return registration


def of_holders(
    db: Session, field: str, hids: Sequence[str]
) -> dict[str, list[tuple[Registration, ExternalSystem]]]:
    """Return the registrations of each item, or of each group, with their systems, by
    the name of the system."""
    found: dict[str, list[tuple[Registration, ExternalSystem]]] = {hid: [] for hid in hids}
    if not hids:
        return found
    column = getattr(Registration, field)
    rows = db.execute(
        select(Registration, ExternalSystem)
        .join(ExternalSystem, ExternalSystem.hid == Registration.system_hid)
        .where(column.in_(hids))
        .order_by(ExternalSystem.name_key, Registration.hid)
    )
    for registration, system in rows:
        found[getattr(registration, field)].append((registration, system))
    return found


def remove_registration(db: Session, context: AuditContext, hid: str) -> None:
    """Remove a registration that was a mistake. The audit event of the removal holds
    what it was. One that was true for a time is given the status `removed` instead."""
    registration = get_registration(db, hid)
    audit.record(
        db,
        context,
        "delete",
        REGISTRATION_TYPE,
        registration.hid,
        [
            change(name, records.jsonable(getattr(registration, name)), None)
            for name in REGISTRATION_FIELDS
            if getattr(registration, name) is not None
        ],
    )
    db.delete(registration)
    db.flush()


def of_groups_of_items(
    db: Session, item_hids: Sequence[str]
) -> dict[str, list[tuple[Registration, ExternalSystem, DeviceGroup]]]:
    """Return, for each item, what the stacks and the clusters it is a current member
    of are registered with: each is one device, and what knows it knows its members."""
    found: dict[str, list[tuple[Registration, ExternalSystem, DeviceGroup]]] = {
        hid: [] for hid in item_hids
    }
    if not item_hids:
        return found
    rows = db.execute(
        select(DeviceGroupMember.item_hid, Registration, ExternalSystem, DeviceGroup)
        .join(DeviceGroup, DeviceGroup.hid == DeviceGroupMember.group_hid)
        .join(Registration, Registration.group_hid == DeviceGroup.hid)
        .join(ExternalSystem, ExternalSystem.hid == Registration.system_hid)
        .where(
            DeviceGroupMember.item_hid.in_(item_hids),
            DeviceGroupMember.left_on.is_(None),
            DeviceGroup.record_status != "retired",
            DeviceGroup.type.in_(ONE_DEVICE),
        )
        .order_by(ExternalSystem.name_key, DeviceGroup.name_key, Registration.hid)
    )
    for item_hid, registration, system, group in rows:
        found[item_hid].append((registration, system, group))
    return found
