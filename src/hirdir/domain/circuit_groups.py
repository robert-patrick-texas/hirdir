"""Groups of circuits: circuits that may land at different sites, looked at and costed
together, such as Internet access or a cloud on-ramp (P-152).

A group has a kind (P-319, P-320): a `network`, a carrier's network or the internet,
which the Z side of a circuit may name as the network it reaches, with its carrier, a
vendor; or a `collection`, circuits put together for the enterprise's own purpose.

A circuit may be in any number of groups and is in one group once. A membership is a
way of looking at circuits and not a fact of their history, so one is removed outright,
the audit event of the removal holding what it was. A retired circuit stays listed in
its groups and is added to none; a retired group takes no new circuit. A network's
circuits are those added to it and those whose Z side names it, each once: the second
are read when the group is read, and are not stored as memberships.
"""

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, select, union
from sqlalchemy.orm import Session

from hirdir import ids
from hirdir.db import dialect
from hirdir.db.models import Circuit, CircuitGroup, CircuitGroupMember, Owner, Vendor
from hirdir.domain import audit, circuit_records, circuits, records, settings, tags
from hirdir.domain.audit import AuditContext, change
from hirdir.domain.errors import Conflict, Existing, Invalid, NotFound

RECORD_TYPE = "circuit_group"
MEMBER_TYPE = "circuit_group_member"
FIELDS = ("name", "kind", "carrier_hid", "description", "owner_hid", "notes", "record_status")
MEMBER_FIELDS = ("group_hid", "circuit_hid")
KINDS = circuits.GROUP_KINDS
# How many circuits a refusal names by name, beside how many there are.
NAMED_AT_MOST = 5


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


@dataclass(frozen=True)
class Listed:
    """A circuit of a group: its membership, where it was added by hand, and whether its
    Z side names the group (P-320). Each circuit is listed once."""

    member: CircuitGroupMember | None
    circuit: Circuit
    z_side: bool


@dataclass(frozen=True)
class GroupOf:
    """A group a circuit is in, and whether its Z side names it."""

    group: CircuitGroup
    z_side: bool


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


def _pairs(group_hids: Sequence[str]) -> Any:
    """Return, as SQL, each group and each of its circuits once: those added to it and
    those whose Z side names it (P-320)."""
    return union(
        select(
            CircuitGroupMember.group_hid.label("group_hid"),
            CircuitGroupMember.circuit_hid.label("circuit_hid"),
        ).where(CircuitGroupMember.group_hid.in_(group_hids)),
        select(Circuit.z_group_hid, Circuit.hid).where(Circuit.z_group_hid.in_(group_hids)),
    ).subquery("of_group")


def _of_group(group_hids: Sequence[str]) -> Any:
    """Return the circuits of some groups, each once for each group, with the
    membership where it was added by hand."""
    pairs = _pairs(group_hids)
    return (
        select(pairs.c.group_hid, Circuit, CircuitGroupMember)
        .select_from(pairs)
        .join(Circuit, Circuit.hid == pairs.c.circuit_hid)
        .outerjoin(
            CircuitGroupMember,
            and_(
                CircuitGroupMember.group_hid == pairs.c.group_hid,
                CircuitGroupMember.circuit_hid == pairs.c.circuit_hid,
            ),
        )
    )


def members_of(db: Session, group_hids: Collection[str]) -> dict[str, list[Listed]]:
    """Return the circuits of each group by the circuit's name, each once: those added
    to it, with their memberships, and those whose Z side names it (P-320)."""
    found: dict[str, list[Listed]] = {hid: [] for hid in group_hids}
    wanted = sorted(set(group_hids))
    for start in range(0, len(wanted), 500):
        rows = db.execute(
            _of_group(wanted[start : start + 500]).order_by(Circuit.name_key, Circuit.hid)
        )
        for group_hid, circuit, member in rows:
            found[group_hid].append(Listed(member, circuit, circuit.z_group_hid == group_hid))
    return found


def groups_of(db: Session, circuit_hids: Collection[str]) -> dict[str, list[CircuitGroup]]:
    """Return the groups each circuit was added to, by name: retired ones too, which say
    so. The network a Z side names is not among them unless the circuit was added to it
    too: this is the list a file holds and loads back (P-320)."""
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


def every_group_of(db: Session, found: Sequence[Circuit]) -> dict[str, list[GroupOf]]:
    """Return every group each circuit is in, by name, each once: those it was added to,
    and the network its Z side names, marked so (P-320)."""
    added = groups_of(db, [circuit.hid for circuit in found])
    networks = {
        group.hid: group
        for group in db.scalars(
            select(CircuitGroup).where(
                CircuitGroup.hid.in_({c.z_group_hid for c in found if c.z_group_hid})
            )
        )
    }
    result: dict[str, list[GroupOf]] = {}
    for circuit in found:
        named = networks.get(circuit.z_group_hid or "")
        listed = [GroupOf(group, group.hid == circuit.z_group_hid) for group in added[circuit.hid]]
        if named is not None and all(one.group.hid != named.hid for one in listed):
            listed.append(GroupOf(named, True))
            listed.sort(key=lambda one: (one.group.name_key, one.group.hid))
        result[circuit.hid] = listed
    return result


def summaries(db: Session, group_hids: Collection[str], day: date) -> dict[str, Summary]:
    """Return what the circuits of each group add up to on a day: how many there are,
    how many of them are in service, and what those in service cost a month, each
    circuit once."""
    members = members_of(db, group_hids)
    held = {one.circuit.hid for listed in members.values() for one in listed}
    lines = circuit_records.lines_of(db, held)
    found = {}
    for hid, listed in members.items():
        serving = [one.circuit for one in listed if circuits.in_service_on(one.circuit, day)]
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


def list_members(db: Session, group_hid: str, limit: int, offset: int) -> tuple[list[Listed], int]:
    """Return a page of the circuits of a group, by name, each once, and how many it
    has: those added to it and those whose Z side names it (P-320)."""
    get_group(db, group_hid)
    query = _of_group([group_hid])
    total = db.scalar(select(func.count()).select_from(_pairs([group_hid]))) or 0
    rows = db.execute(query.order_by(Circuit.name_key, Circuit.hid).limit(limit).offset(offset))
    return [
        Listed(member, circuit, circuit.z_group_hid == group_hid) for _, circuit, member in rows
    ], total


def naming_on_z_side(db: Session, group_hid: str, *, retired_too: bool) -> list[Circuit]:
    """Return the circuits whose Z side names a group, by name: those that are not
    retired, or every one of them."""
    query = select(Circuit).where(Circuit.z_group_hid == group_hid)
    if not retired_too:
        query = query.where(Circuit.record_status != "retired")
    return list(db.scalars(query.order_by(Circuit.name_key, Circuit.hid)))


def _counted(count: int) -> str:
    return f"{count} {'circuit' if count == 1 else 'circuits'}"


def _named(found: Sequence[Circuit]) -> str:
    """Return the names of the first of some circuits, and how many more there are."""
    shown = [circuit.enterprise_circuit_id or circuit.name for circuit in found[:NAMED_AT_MOST]]
    more = len(found) - NAMED_AT_MOST
    return ", ".join(shown) + (f" and {more} more" if more > 0 else "")


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
    if "kind" in fields:
        values["kind"] = records.checked_choice(fields["kind"], KINDS, "kind")
    if "carrier_hid" in fields:
        values["carrier_hid"] = records.linked(
            db, Vendor, "carrier_hid", fields["carrier_hid"], group, "vendor"
        )
    for name in ("description", "notes"):
        if name in fields:
            values[name] = records.clean(fields[name])
    if "owner_hid" in fields:
        # A retired owner keeps what refers to it (P-311).
        values["owner_hid"] = records.linked(
            db, Owner, "owner_hid", fields["owner_hid"], group, "owner", kept=True
        )
    if "record_status" in fields:
        values["record_status"] = records.checked_status(fields["record_status"])
        if group is not None and values["record_status"] == "retired":
            # A row of a file that retires a network is held to what retiring it is.
            dialect.hold_other_writers(db)
            _refuse_if_reached(db, group)

    def final(name: str) -> Any:
        return values.get(name, getattr(group, name) if group is not None else None)

    if final("kind") == circuits.COLLECTION and final("carrier_hid") is not None:
        raise Invalid(
            "a collection has no carrier",
            {"carrier_hid": "only a network names its carrier; a collection has none"},
        )
    made_collection = (
        group is not None
        and group.kind != circuits.COLLECTION
        and values.get("kind") == circuits.COLLECTION
    )
    if made_collection and group is not None:
        # Checked against the circuits, which name no collection: nobody may be naming
        # this group on a Z side meanwhile.
        dialect.hold_other_writers(db)
        naming = naming_on_z_side(db, group.hid, retired_too=True)
        if naming:
            raise Invalid(
                f"{group.name} is the network the Z side of {_counted(len(naming))} "
                f"reaches, {_named(naming)}, and stays a network while any names it",
                {
                    "kind": f"{_counted(len(naming))}, retired or not, "
                    f"{'names' if len(naming) == 1 else 'name'} it on the Z side; give "
                    f"{'it' if len(naming) == 1 else 'them'} another network, or none, first"
                },
            )
    return values


def create_group(db: Session, context: AuditContext, fields: dict[str, Any]) -> CircuitGroup:
    """Create a circuit group: a collection unless it is said to be a network."""
    labels = fields.pop("tags", None) or []
    given = {"name": None, **fields}
    if given.get("kind") is None:
        given["kind"] = circuits.COLLECTION
    group = CircuitGroup(**_checked(db, given, None))
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
    """Change a circuit group. A network that a Z side names stays a network."""
    group = get_group(db, hid)
    has_tags = "tags" in fields
    labels = fields.pop("tags", None) or []
    values = _checked(db, fields, group)
    tag_change = tags.set_labels(db, RECORD_TYPE, hid, labels) if has_tags else []
    records.apply(db, context, RECORD_TYPE, group, row_version, values, tag_change)
    return group


def _refuse_if_reached(db: Session, group: CircuitGroup) -> None:
    """Refuse to retire a network that a circuit that is not retired names on its Z
    side, saying how many and naming them (P-320). The caller holds the one writer's
    place, so that nobody names it meanwhile."""
    if group.record_status == "retired":
        return
    naming = naming_on_z_side(db, group.hid, retired_too=False)
    if naming:
        them = "it" if len(naming) == 1 else "them"
        raise Conflict(
            f"{group.name} is the network the Z side of {_counted(len(naming))} not "
            f"retired reaches, {_named(naming)}: give {them} another network, or "
            f"retire {them}, first",
            depends_on=[
                Existing(
                    circuit_records.RECORD_TYPE,
                    circuit.hid,
                    circuit.enterprise_circuit_id or circuit.name,
                )
                for circuit in naming
            ],
        )


def retire_group(db: Session, context: AuditContext, hid: str, row_version: int) -> CircuitGroup:
    """Retire a circuit group. Its circuits stay listed in it, and it takes no new one.

    A network that a circuit that is not retired names on its Z side is not retired:
    the refusal says how many, and names them (P-320).
    """
    dialect.hold_other_writers(db)
    group = get_group(db, hid)
    _refuse_if_reached(db, group)
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
    """Put circuits into a group, all together, each once. A circuit whose Z side names
    the group is added and kept, so that it stays when its Z side is changed (P-320)."""
    # Checked against the members of the group, so nobody may be changing them.
    dialect.hold_other_writers(db)
    group = get_group(db, group_hid)
    # A retired group keeps its circuits listed in it, and a file of them holds them (P-311).
    if records.refuses_retired(group, "circuit group", kept=True):
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
        if records.refuses_retired(circuit, "circuit", kept=True):
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
    """Take a circuit out of a group. The audit event of the removal holds what it was.
    A circuit whose Z side names the group stays listed by it."""
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
    """Make the groups a circuit was added to exactly these, as a file names them whole:
    put it into the ones it is not in, and take it out of the others. The network its Z
    side names is no membership, and is left alone. Say whether anything changed."""
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
