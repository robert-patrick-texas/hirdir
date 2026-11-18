"""Groups of circuits: circuits that may land at different sites, looked at and costed
together, such as Internet access or a cloud on-ramp (P-152).

A circuit may be in any number of groups and is in one group once. A membership is a
way of looking at circuits and not a fact of their history, so one is removed outright,
the audit event of the removal holding what it was. A retired circuit stays listed in
its groups and is added to none; a retired group takes no new circuit.
"""

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hirdir import ids
from hirdir.db import dialect
from hirdir.db.models import Circuit, CircuitGroup, CircuitGroupMember, Owner
from hirdir.domain import audit, circuit_records, circuits, records, settings, tags
from hirdir.domain.audit import AuditContext, change
from hirdir.domain.errors import Conflict, Existing, Invalid, NotFound

RECORD_TYPE = "circuit_group"
MEMBER_TYPE = "circuit_group_member"
FIELDS = ("name", "description", "owner_hid", "notes", "record_status")
MEMBER_FIELDS = ("group_hid", "circuit_hid")


@dataclass(frozen=True)
class Summary:
    """What the circuits of a group add up to on a day, each circuit once."""

    circuits: int
    in_service: int
    monthly_cost: Decimal

    @property
    def annual_cost(self) -> Decimal:
        """Twelve times the monthly cost."""
        return self.monthly_cost * circuit_records.MONTHS


def get_group(db: Session, hid: str) -> CircuitGroup:
    """Return the circuit group with hid."""
    group = db.get(CircuitGroup, hid)
    if group is None:
        raise NotFound(f"there is no circuit group {hid}")
    return group


def find_group(db: Session, text: str) -> CircuitGroup | None:
    """Return the group a text names: by its HID or by its name."""
    text = text.strip()
    if ids.is_hid(text):
        found = db.get(CircuitGroup, text)
        if found is not None:
            return found
    return db.scalar(select(CircuitGroup).where(CircuitGroup.name_key == records.key(text)))


def the_one(db: Session, text: str, field: str) -> CircuitGroup:
    """Return the group a text names, or refuse a name that there is not."""
    found = find_group(db, text)
    if found is None:
        raise Invalid(
            "there is no such circuit group", {field: f"there is no circuit group {text}"}
        )
    return found


# --- reading -------------------------------------------------------------------------


def members_of(
    db: Session, group_hids: Collection[str]
) -> dict[str, list[tuple[CircuitGroupMember, Circuit]]]:
    """Return the circuits of each group, with their memberships, by the circuit's name."""
    found: dict[str, list[tuple[CircuitGroupMember, Circuit]]] = {hid: [] for hid in group_hids}
    wanted = sorted(set(group_hids))
    for start in range(0, len(wanted), 500):
        rows = db.execute(
            select(CircuitGroupMember, Circuit)
            .join(Circuit, Circuit.hid == CircuitGroupMember.circuit_hid)
            .where(CircuitGroupMember.group_hid.in_(wanted[start : start + 500]))
            .order_by(Circuit.name_key, Circuit.hid)
        )
        for member, circuit in rows:
            found[member.group_hid].append((member, circuit))
    return found


def groups_of(db: Session, circuit_hids: Collection[str]) -> dict[str, list[CircuitGroup]]:
    """Return the groups each circuit is in, by name: retired ones too, which say so."""
    found: dict[str, list[CircuitGroup]] = {hid: [] for hid in circuit_hids}
    wanted = sorted(set(circuit_hids))
    for start in range(0, len(wanted), 500):
        rows = db.execute(
            select(CircuitGroupMember.circuit_hid, CircuitGroup)
            .join(CircuitGroup, CircuitGroup.hid == CircuitGroupMember.group_hid)
            .where(CircuitGroupMember.circuit_hid.in_(wanted[start : start + 500]))
            .order_by(CircuitGroup.name_key, CircuitGroup.hid)
        )
        for circuit_hid, group in rows:
            found[circuit_hid].append(group)
    return found


def summaries(db: Session, group_hids: Collection[str], day: date) -> dict[str, Summary]:
    """Return what the circuits of each group add up to on a day: how many there are,
    how many of them are in service, and what those in service cost a month."""
    members = members_of(db, group_hids)
    held = {circuit.hid for listed in members.values() for _, circuit in listed}
    lines = circuit_records.lines_of(db, held)
    found = {}
    for hid, listed in members.items():
        serving = [circuit for _, circuit in listed if circuits.in_service_on(circuit, day)]
        found[hid] = Summary(
            circuits=len(listed),
            in_service=len(serving),
            monthly_cost=sum(
                (circuit_records.monthly_cost(lines[circuit.hid], day) for circuit in serving),
                Decimal("0.00"),
            ),
        )
    return found


def get_member(db: Session, group_hid: str, member_hid: str) -> CircuitGroupMember:
    """Return one membership of one group."""
    get_group(db, group_hid)
    member = db.get(CircuitGroupMember, member_hid)
    if member is None or member.group_hid != group_hid:
        raise NotFound(f"there is no member {member_hid} of this circuit group")
    return member


def list_members(
    db: Session, group_hid: str, limit: int, offset: int
) -> tuple[list[tuple[CircuitGroupMember, Circuit]], int]:
    """Return a page of the circuits of a group, by name, and how many it has."""
    get_group(db, group_hid)
    query = (
        select(CircuitGroupMember, Circuit)
        .join(Circuit, Circuit.hid == CircuitGroupMember.circuit_hid)
        .where(CircuitGroupMember.group_hid == group_hid)
    )
    total = (
        db.scalar(
            select(func.count())
            .select_from(CircuitGroupMember)
            .where(CircuitGroupMember.group_hid == group_hid)
        )
        or 0
    )
    rows = db.execute(query.order_by(Circuit.name_key, Circuit.hid).limit(limit).offset(offset))
    return [(member, circuit) for member, circuit in rows], total


# --- changing a group ----------------------------------------------------------------


def _checked(db: Session, fields: dict[str, Any], group: CircuitGroup | None) -> dict[str, Any]:
    values: dict[str, Any] = {}
    if "name" in fields:
        name = records.clean(fields["name"])
        if name is None or ";" in name:
            raise Invalid(
                "the name is not acceptable",
                {"name": "not blank, and with no semicolon, which separates groups in a file"},
            )
        # Checked against the names of the other groups.
        dialect.hold_other_writers(db)
        taken = db.scalar(select(CircuitGroup).where(CircuitGroup.name_key == records.key(name)))
        if taken is not None and (group is None or taken.hid != group.hid):
            raise Conflict(
                f"there is already a circuit group {taken.name}",
                {"name": "another circuit group has this name"},
                Existing(RECORD_TYPE, taken.hid, taken.name),
            )
        values["name"], values["name_key"] = name, records.key(name)
    for name in ("description", "notes"):
        if name in fields:
            values[name] = records.clean(fields[name])
    if "owner_hid" in fields:
        values["owner_hid"] = records.linked(
            db, Owner, "owner_hid", fields["owner_hid"], group, "owner"
        )
    if "record_status" in fields:
        values["record_status"] = records.checked_status(fields["record_status"])
    return values


def create_group(db: Session, context: AuditContext, fields: dict[str, Any]) -> CircuitGroup:
    """Create a circuit group."""
    labels = fields.pop("tags", None) or []
    group = CircuitGroup(**_checked(db, {"name": None, **fields}, None))
    records.created(
        db,
        context,
        RECORD_TYPE,
        group,
        FIELDS,
        then=lambda: tags.set_labels(db, RECORD_TYPE, group.hid, labels),
    )
    return group


def update_group(
    db: Session, context: AuditContext, hid: str, row_version: int, fields: dict[str, Any]
) -> CircuitGroup:
    """Change a circuit group."""
    group = get_group(db, hid)
    has_tags = "tags" in fields
    labels = fields.pop("tags", None) or []
    values = _checked(db, fields, group)
    tag_change = tags.set_labels(db, RECORD_TYPE, hid, labels) if has_tags else []
    records.apply(db, context, RECORD_TYPE, group, row_version, values, tag_change)
    return group


def retire_group(db: Session, context: AuditContext, hid: str, row_version: int) -> CircuitGroup:
    """Retire a circuit group. Its circuits stay listed in it, and it takes no new one."""
    group = get_group(db, hid)
    records.apply(
        db, context, RECORD_TYPE, group, row_version, {"record_status": "retired"}, action="retire"
    )
    return group


# --- members -------------------------------------------------------------------------


def _member_of(db: Session, group_hid: str, circuit_hid: str) -> CircuitGroupMember | None:
    return db.scalar(
        select(CircuitGroupMember).where(
            CircuitGroupMember.group_hid == group_hid,
            CircuitGroupMember.circuit_hid == circuit_hid,
        )
    )


def add_members(
    db: Session, context: AuditContext, group_hid: str, circuit_hids: Sequence[str]
) -> list[CircuitGroupMember]:
    """Put circuits into a group, all together, each once."""
    # Checked against the members of the group, so nobody may be changing them.
    dialect.hold_other_writers(db)
    group = get_group(db, group_hid)
    if group.record_status == "retired":
        raise Invalid(
            "the group is retired",
            {"circuit_hids": "a retired group takes no circuit; bring it back first"},
        )
    if not circuit_hids:
        raise Invalid("there is nothing to add", {"circuit_hids": "name at least one circuit"})
    if len(circuit_hids) > settings.MOST_ITEMS_PER_REQUEST:
        raise Invalid(
            "too many circuits at once",
            {"circuit_hids": f"at most {settings.MOST_ITEMS_PER_REQUEST:,} in one request"},
        )
    if len(set(circuit_hids)) != len(circuit_hids):
        raise Invalid("a circuit is named twice", {"circuit_hids": "name each circuit once"})
    made = []
    for hid in circuit_hids:
        circuit = db.get(Circuit, hid) if isinstance(hid, str) else None
        if circuit is None:
            raise Invalid(
                "there is no such circuit", {"circuit_hids": f"there is no circuit {hid}"}
            )
        if circuit.record_status == "retired":
            raise Invalid(
                f"{circuit.name} is retired",
                {"circuit_hids": f"{circuit.name} is retired, and is added to no group"},
            )
        if _member_of(db, group.hid, circuit.hid) is not None:
            raise Conflict(
                f"{circuit.name} is in {group.name} already",
                {"circuit_hids": f"{circuit.name} is in the group already, and is in it once"},
            )
        member = CircuitGroupMember(group_hid=group.hid, circuit_hid=circuit.hid)
        records.created(db, context, MEMBER_TYPE, member, MEMBER_FIELDS)
        made.append(member)
    return made


def remove_member(db: Session, context: AuditContext, group_hid: str, member_hid: str) -> None:
    """Take a circuit out of a group. The audit event of the removal holds what it was."""
    member = get_member(db, group_hid, member_hid)
    _remove(db, context, member)


def _remove(db: Session, context: AuditContext, member: CircuitGroupMember) -> None:
    audit.record(
        db,
        context,
        "delete",
        MEMBER_TYPE,
        member.hid,
        [change(name, getattr(member, name), None) for name in MEMBER_FIELDS],
    )
    db.delete(member)
    db.flush()


def set_groups(
    db: Session, context: AuditContext, circuit_hid: str, group_hids: Sequence[str]
) -> bool:
    """Make the groups a circuit is in exactly these, as a file names them whole: put it
    into the ones it is not in, and take it out of the others. Say whether anything
    changed."""
    dialect.hold_other_writers(db)
    wanted = list(dict.fromkeys(group_hids))
    held = {
        member.group_hid: member
        for member in db.scalars(
            select(CircuitGroupMember).where(CircuitGroupMember.circuit_hid == circuit_hid)
        )
    }
    changed = False
    for hid, member in held.items():
        if hid not in wanted:
            _remove(db, context, member)
            changed = True
    for hid in wanted:
        if hid not in held:
            add_members(db, context, hid, [circuit_hid])
            changed = True
    return changed
