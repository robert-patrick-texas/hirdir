"""Several items or device groups retired at once, and an Admin's deletion of those that
were a mistake (P-227, P-228, P-236).

Retiring stays the way a record ends. Several are retired by one request each as its own
page retires one, with an audit event each. Deleting removes a record that should never
have been, and only one that nothing else depends on.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import delete, inspect, or_, select
from sqlalchemy.orm import Session

from hirdir.db import dialect
from hirdir.db.models import (
    Address,
    Circuit,
    CircuitDevice,
    Contract,
    ContractCoverage,
    DeviceGroup,
    DeviceGroupMember,
    Item,
    ItemReplacement,
    PurchaseLine,
    PurchaseRequest,
    ReferenceAttachment,
    ReferenceFile,
    Registration,
    TagLink,
)
from hirdir.domain import (
    addresses,
    audit,
    circuit_records,
    contracts,
    deleted,
    groups,
    items,
    purchases,
    records,
    references,
    replacements,
    systems,
    tags,
)
from hirdir.domain.audit import AuditContext, change
from hirdir.domain.errors import DomainError, Existing, Invalid

# How many records one request retires or deletes, at most.
MOST_AT_ONCE = 1000
ITEM = items.RECORD_TYPE
DEVICE_GROUP = groups.RECORD_TYPE
KINDS = (ITEM, DEVICE_GROUP)
# Records are read this many to a statement.
PIECE = 500


@dataclass(frozen=True)
class Kind:
    """What retiring and deleting need to know of one kind of record."""

    record_type: str
    model: Any
    label: Callable[[Any], str]
    # Retire one, telling the list what went with it because it ran on it (P-247).
    retire: Callable[[Session, AuditContext, str, int, list[tuple[Item, str]]], Any]


def _group_label(group: DeviceGroup) -> str:
    return group.name


def _retire_item(
    db: Session, context: AuditContext, hid: str, row_version: int, went: list[tuple[Item, str]]
) -> Any:
    return items.retire_item(db, context, hid, row_version, went)


def _retire_group(
    db: Session, context: AuditContext, hid: str, row_version: int, _: list[tuple[Item, str]]
) -> Any:
    return groups.retire_group(db, context, hid, row_version)


def kind_of(record_type: str) -> Kind:
    """Return the kind of record that is retired or deleted several at a time."""
    if record_type == ITEM:
        return Kind(ITEM, Item, items.shown_name, _retire_item)
    if record_type == DEVICE_GROUP:
        return Kind(DEVICE_GROUP, DeviceGroup, _group_label, _retire_group)
    raise Invalid("this kind of record is not retired or deleted so", {"kind": "item or group"})


def unique(hids: Sequence[str], field_: str = "hids") -> list[str]:
    """Return the HIDs named, each once, in the order first named, refusing too many."""
    named = list(dict.fromkeys(hids))
    if not named:
        raise Invalid("nothing is named", {field_: "name one record at least"})
    if len(named) > MOST_AT_ONCE:
        raise Invalid("too many at once", {field_: f"at most {MOST_AT_ONCE:,} to a request"})
    return named


def read(db: Session, model: Any, hids: Sequence[str]) -> dict[str, Any]:
    """Return the records of a kind that the HIDs name, by HID."""
    found: dict[str, Any] = {}
    for piece in _pieces(hids):
        found.update(
            (one.hid, one) for one in db.scalars(select(model).where(model.hid.in_(piece)))
        )
    return found


def _pieces(hids: Sequence[str]) -> list[list[str]]:
    return [list(hids[start : start + PIECE]) for start in range(0, len(hids), PIECE)]


def said(error: DomainError) -> str:
    """Return what a refusal says, with what it says of each field."""
    fields = getattr(error, "fields", None) or {}
    parts = [f"{name}: {text}" if name else text for name, text in fields.items()]
    return "; ".join([str(error), *parts]) if parts else str(error)


# --- several retired at once (P-228) --------------------------------------------------


@dataclass
class Retired:
    """What a request that retires several did, or with a dry run would do, with each
    record it named; and in `hosted`, by its HID, label and host, each item that went
    with one named because it runs on it (P-247)."""

    dry_run: bool = False
    retired: list[tuple[str, str]] = field(default_factory=list)
    already: list[tuple[str, str]] = field(default_factory=list)
    refused: list[tuple[str, str, str, list[Existing]]] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    hosted: list[tuple[str, str, str]] = field(default_factory=list)


def retire_many(
    db: Session,
    context: AuditContext,
    record_type: str,
    hids: Sequence[str],
    *,
    dry_run: bool = False,
) -> Retired:
    """Retire each record named, as its own page retires it, with an audit event each.

    One that is retired already is counted so and not refused. One that the rules refuse
    is named with why, and leaves the others as they went. No version is asked for: what
    a person ticked is what is retired, as it is when the request is worked.

    With `dry_run` the work is done in a savepoint that is then undone, so that the answer
    is what the request would do, by the same rules, and nothing is kept.
    """
    kind = kind_of(record_type)
    named = unique(hids)
    # The memberships and the coverage that retiring ends are read with no other change
    # under way, as one retire reads them.
    dialect.hold_other_writers(db)
    if not dry_run:
        return _retire_each(db, context, kind, named, Retired())
    trying = db.begin_nested()
    try:
        return _retire_each(db, context, kind, named, Retired(dry_run=True))
    finally:
        trying.rollback()


def _retire_each(
    db: Session, context: AuditContext, kind: Kind, named: list[str], done: Retired
) -> Retired:
    """Retire each record named, in the order named, and say what became of each.

    What runs on an item goes with it (P-247). One named that went with another named
    before it is counted as retired by this request, and only once.
    """
    found = read(db, kind.model, named)
    went_with: dict[str, tuple[str, str, str]] = {}
    for hid in named:
        record = found.get(hid)
        if record is None:
            done.missing.append(hid)
            continue
        label = kind.label(record)
        if record.record_status == "retired":
            if hid in went_with:
                done.retired.append((hid, label))
            else:
                done.already.append((hid, label))
            continue
        savepoint = db.begin_nested()
        went: list[tuple[Item, str]] = []
        try:
            kind.retire(db, context, hid, record.row_version, went)
        except DomainError as error:
            savepoint.rollback()
            done.refused.append((hid, label, said(error), getattr(error, "depends_on", [])))
        else:
            savepoint.commit()
            done.retired.append((hid, label))
            for one, host_hid in went:
                went_with.setdefault(one.hid, (one.hid, items.shown_name(one), host_hid))
    asked = set(named)
    done.hosted = [one for hid, one in went_with.items() if hid not in asked]
    return done


# --- deleting what was a mistake (P-227, P-236) ---------------------------------------


@dataclass
class Deletion:
    """What a request that deletes several did, or with a dry run would do, with each."""

    dry_run: bool
    deleted: list[tuple[str, str]] = field(default_factory=list)
    refused: list[tuple[str, str, list[Existing]]] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


@dataclass
class _Ties:
    """What depends on each record that is to be deleted.

    `outside` is what is not of the request, each of which refuses the deletion, and
    `inside` the records of the request beneath it, which must go before it does.
    """

    outside: dict[str, list[Existing]]
    inside: dict[str, list[str]]


def _circuit_label(circuit: Circuit) -> str:
    return circuit.enterprise_circuit_id or circuit.name


def _circuits(db: Session, column: Any, piece: list[str], ties: _Ties) -> None:
    """Add the circuits connected to each record, which refuse its deletion."""
    connected = db.execute(
        select(column, Circuit)
        .join(Circuit, Circuit.hid == CircuitDevice.circuit_hid)
        .where(column.in_(piece))
        .order_by(Circuit.hid)
    )
    for hid, circuit in connected:
        tie = Existing(circuit_records.RECORD_TYPE, circuit.hid, _circuit_label(circuit))
        ties.outside[hid].append(tie)


def _replacements(db: Session, piece: list[str], ties: _Ties) -> None:
    """Add the replacements each item was part of, which refuse its deletion."""
    swapped = list(
        db.scalars(
            select(ItemReplacement)
            .where(
                or_(
                    ItemReplacement.old_item_hid.in_(piece),
                    ItemReplacement.new_item_hid.in_(piece),
                )
            )
            .order_by(ItemReplacement.hid)
        )
    )
    both = {one.old_item_hid for one in swapped} | {one.new_item_hid for one in swapped}
    named = read(db, Item, sorted(both))
    for replacement in swapped:
        old, new = named[replacement.old_item_hid], named[replacement.new_item_hid]
        label = f"{items.shown_name(old)} replaced by {items.shown_name(new)}"
        tie = Existing(replacements.RECORD_TYPE, replacement.hid, label)
        for hid in (replacement.old_item_hid, replacement.new_item_hid):
            if hid in ties.outside:
                ties.outside[hid].append(tie)


def _item_ties(db: Session, found: dict[str, Item]) -> _Ties:
    """Return what depends on each item: what is installed in it, what covers it or has,
    the line it arrived on, a replacement, a circuit and a reference."""
    ties = _Ties({hid: [] for hid in found}, {hid: [] for hid in found})
    for piece in _pieces(list(found)):
        for child in db.scalars(
            select(Item).where(Item.parent_item_hid.in_(piece)).order_by(Item.hid)
        ):
            parent = child.parent_item_hid or ""
            if child.hid in found:
                ties.inside[parent].append(child.hid)
            else:
                ties.outside[parent].append(items.existing_item(child))
        covered = db.execute(
            select(ContractCoverage.item_hid, Contract)
            .join(Contract, Contract.hid == ContractCoverage.contract_hid)
            .where(ContractCoverage.item_hid.in_(piece))
            .order_by(Contract.number, Contract.hid)
        )
        for hid, contract in covered:
            tie = Existing(contracts.RECORD_TYPE, contract.hid, contract.number)
            ties.outside[hid].append(tie)
        _replacements(db, piece, ties)
        _circuits(db, CircuitDevice.item_hid, piece, ties)
        attached = db.execute(
            select(ReferenceAttachment.item_hid, ReferenceFile)
            .join(ReferenceFile, ReferenceFile.hid == ReferenceAttachment.reference_file_hid)
            .where(ReferenceAttachment.item_hid.in_(piece))
            .order_by(ReferenceFile.title, ReferenceFile.hid)
        )
        for hid, reference in attached:
            tie = Existing(references.RECORD, reference.hid, reference.title)
            ties.outside[hid or ""].append(tie)
    lines = read(db, PurchaseLine, sorted({one.purchase_line_hid or "" for one in found.values()}))
    asked = read(db, PurchaseRequest, sorted({line.request_hid for line in lines.values()}))
    for item in found.values():
        line = lines.get(item.purchase_line_hid or "")
        if line is not None:
            label = purchases.line_name(asked[line.request_hid], line)
            ties.outside[item.hid].append(Existing(purchases.LINE_TYPE, line.hid, label))
    return ties


def _group_ties(db: Session, found: dict[str, DeviceGroup]) -> _Ties:
    """Return what depends on each device group: a group nested in it and a circuit."""
    ties = _Ties({hid: [] for hid in found}, {hid: [] for hid in found})
    for piece in _pieces(list(found)):
        for child in db.scalars(
            select(DeviceGroup)
            .where(DeviceGroup.parent_group_hid.in_(piece))
            .order_by(DeviceGroup.name_key, DeviceGroup.hid)
        ):
            parent = child.parent_group_hid or ""
            if child.hid in found:
                ties.inside[parent].append(child.hid)
            else:
                ties.outside[parent].append(Existing(DEVICE_GROUP, child.hid, child.name))
        _circuits(db, CircuitDevice.group_hid, piece, ties)
    return ties


def _judged(kind: Kind, found: dict[str, Any], ties: _Ties) -> dict[str, list[Existing]]:
    """Return each record that is refused, with what depends on it.

    A record is refused for anything outside the request that depends on it, and for a
    record of the request beneath it that is refused in its turn: a switch whose power
    supply is covered by a contract stays, and names the supply.
    """
    refused = {
        hid: list(dict.fromkeys(outside)) for hid, outside in ties.outside.items() if outside
    }
    changed = True
    while changed:
        changed = False
        for hid in found:
            if hid in refused:
                continue
            kept = [child for child in ties.inside[hid] if child in refused]
            if kept:
                refused[hid] = [
                    Existing(kind.record_type, one, kind.label(found[one])) for one in kept
                ]
                changed = True
    return refused


def _deepest_first(found: dict[str, Any], above: Callable[[Any], str | None]) -> list[Any]:
    """Return the records to delete, each after every one of them that is beneath it."""

    def depth(record: Any) -> int:
        count, seen, at = 0, {record.hid}, above(record)
        while at is not None and at in found and at not in seen:
            seen.add(at)
            count += 1
            at = above(found[at])
        return count

    return sorted(found.values(), key=lambda record: -depth(record))


def _as_it_was(record: Any) -> list[dict[str, Any]]:
    """Return every field of a record as an entry of its deletion's event."""
    return [
        change(attr.key, records.jsonable(getattr(record, attr.key), attr.key), None)
        for attr in inspect(type(record)).column_attrs
        if attr.key != "hid" and not attr.key.endswith("_key")
    ]


def _whole(record: Any, names: tuple[str, ...]) -> dict[str, Any]:
    """Return a part that goes with a record, as the record's event lists it."""
    return {"hid": record.hid} | {
        name: records.jsonable(getattr(record, name), name) for name in names
    }


# The entry of each part's own event that names the record it went with.
WENT_WITH = "deleted_with"


@dataclass(frozen=True)
class _Part:
    """One kind of record that belongs to an item or a group alone, and goes with it."""

    name: str
    record_type: str
    model: Any
    fields: tuple[str, ...]


PARTS = (
    _Part("addresses", addresses.RECORD_TYPE, Address, addresses.FIELDS),
    _Part("memberships", groups.MEMBER_TYPE, DeviceGroupMember, groups.MEMBER_FIELDS),
    _Part("registrations", systems.REGISTRATION_TYPE, Registration, systems.REGISTRATION_FIELDS),
)


def _delete_one(
    db: Session, context: AuditContext, record_type: str, record: Any, holder: str, why: str
) -> None:
    """Delete a record with what belongs to it alone, in one audit event that holds every
    field of it, what went with it and why; each part that goes has an event of its own,
    which holds what it was and names the record it went with."""
    hid = record.hid
    labels = tags.labels_of(db, record_type, [hid])[hid]
    went = [
        (
            part,
            list(
                db.scalars(
                    select(part.model)
                    .where(getattr(part.model, holder) == hid)
                    .order_by(part.model.hid)
                )
            ),
        )
        for part in PARTS
    ]
    audit.record(
        db,
        context,
        deleted.ACTION,
        record_type,
        hid,
        [
            *_as_it_was(record),
            change("tags", labels, None),
            *(
                change(part.name, [_whole(one, part.fields) for one in found], None)
                for part, found in went
            ),
            change(deleted.REASON, None, why),
        ],
    )
    for part, found in went:
        for one in found:
            entries = [
                change(name, records.jsonable(getattr(one, name), name), None)
                for name in part.fields
                if getattr(one, name) not in (None, False)
            ]
            audit.record(
                db,
                context,
                deleted.ACTION,
                part.record_type,
                one.hid,
                [*entries, change(WENT_WITH, None, hid)],
            )
            db.delete(one)
    db.execute(delete(TagLink).where(TagLink.record_type == record_type, TagLink.record_hid == hid))
    db.flush()
    db.delete(record)
    db.flush()


def _delete_item(db: Session, context: AuditContext, item: Item, why: str) -> None:
    """Delete an item. A stack that saw it as master sees none now, by a change of its own
    that says why."""
    seen_by = db.scalars(select(DeviceGroup).where(DeviceGroup.observed_master_hid == item.hid))
    for stack in seen_by:
        cleared = {"observed_master_hid": None, "master_observed_at": None}
        records.apply(
            db, context, DEVICE_GROUP, stack, None, cleared, [change(WENT_WITH, None, item.hid)]
        )
    _delete_one(db, context, ITEM, item, "item_hid", why)


def delete_many(
    db: Session,
    context: AuditContext,
    record_type: str,
    hids: Sequence[str],
    reason: str | None,
    *,
    dry_run: bool = False,
) -> Deletion:
    """Delete the records named that nothing else depends on, each judged by itself.

    What belongs to a record alone goes with it; a record that another depends on is
    refused, naming what. A record that only records of the same request depend on is
    deleted with them. With `dry_run` the answer is the same and nothing is changed.
    """
    kind = kind_of(record_type)
    named = unique(hids)
    why = records.clean(reason)
    if not dry_run and why is None:
        raise Invalid("a deletion says why", {"reason": "give the reason, which is kept with it"})
    if not dry_run:
        # What depends on a record is read, and the record deleted, with no other change
        # under way: a change that comes after it finds the record gone, and one that
        # came before it is seen.
        dialect.hold_other_writers(db)
    found = read(db, kind.model, named)
    ties = _item_ties(db, found) if record_type == ITEM else _group_ties(db, found)
    refused = _judged(kind, found, ties)
    done = Deletion(dry_run=dry_run)
    for hid in named:
        record = found.get(hid)
        if record is None:
            done.missing.append(hid)
        elif hid in refused:
            done.refused.append((hid, kind.label(record), refused[hid]))
        else:
            done.deleted.append((hid, kind.label(record)))
    if dry_run or why is None:
        return done
    going = {hid: found[hid] for hid, _ in done.deleted}
    if record_type == ITEM:
        for item in _deepest_first(going, lambda one: one.parent_item_hid):
            _delete_item(db, context, item, why)
    else:
        for group in _deepest_first(going, lambda one: one.parent_group_hid):
            _delete_one(db, context, DEVICE_GROUP, group, "group_hid", why)
    return done
