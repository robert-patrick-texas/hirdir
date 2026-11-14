"""Support agreements, contracts, and the coverage of items under contracts.

An agreement with a vendor, such as an enterprise agreement, groups contracts. A
contract in one has from it what it leaves blank: whom to ask, where support is
reached, the support level, the reseller and the period. A contract may also stand by
itself, and be put into an agreement later.

A contract covers on a day when it is active in both senses, its record status and
the status a person gave it, and the day is within its period. A coverage is one item
under one contract for a range of days, each end of which is the contract's where the
coverage names none. Nothing is copied down: giving an agreement or a contract another
end date moves the end of everything beneath that has none of its own, and writes to
none of it.

What is in force is worked out when it is read, here for a page of records and, as
SQL, for the database to filter, sort and count by. A test holds the two together.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import ColumnElement, and_, case, func, or_, select
from sqlalchemy.orm import Session, object_session

from hirdir import clock, ids
from hirdir.db import dialect
from hirdir.db.models import Agreement, AuditEvent, Contract, ContractCoverage, Item, Vendor
from hirdir.domain import records, settings, tags
from hirdir.domain.audit import AuditContext
from hirdir.domain.errors import Conflict, Invalid, NotFound
from hirdir.domain.inheritance import NOTHING, Effective

RECORD_TYPE = "contract"
AGREEMENT_TYPE = "agreement"
COVERAGE_TYPE = "contract_coverage"
STATUSES = ("active", "expired", "pending", "cancelled")
ACTIVE = STATUSES[0]
TEXTS = ("support_level", "purchase_reference", "account_manager", "support_contact", "notes")
# What a contract in an agreement has from it, where the contract's own is blank.
INHERITED = (
    "reseller_hid",
    "starts_on",
    "ends_on",
    "support_level",
    "account_manager",
    "support_contact",
    "support_url",
)
_SHARED = (
    "reseller_hid",
    "starts_on",
    "ends_on",
    "status",
    *TEXTS[:-1],
    "support_url",
    "notes",
    "annual_cost",
    "record_status",
)
AGREEMENT_FIELDS = ("name", "number", "vendor_hid", *_SHARED)
FIELDS = ("number", "vendor_hid", "agreement_hid", *_SHARED)
COVERAGE_FIELDS = ("contract_hid", "item_hid", "starts_on", "ends_on")
MAX_AT_ONCE = 10_000


def today(db: Session) -> date:
    """Return today's date in the application's time zone."""
    return clock.today(settings.time_zone(db))


def _shared(db: Session, fields: dict[str, Any], record: Any | None) -> dict[str, Any]:
    """Return the checked values of what an agreement and a contract both hold."""
    values: dict[str, Any] = {}
    if "reseller_hid" in fields:
        values["reseller_hid"] = records.linked(
            db, Vendor, "reseller_hid", fields["reseller_hid"], record, "vendor"
        )
    for name in ("starts_on", "ends_on"):
        if name in fields:
            values[name] = records.checked_day(name, fields[name])
    if "status" in fields:
        values["status"] = records.checked_choice(fields["status"] or ACTIVE, STATUSES, "status")
    for name in TEXTS:
        if name in fields:
            values[name] = records.clean(fields[name])
    if "support_url" in fields:
        values["support_url"] = records.checked_url("support_url", fields["support_url"])
    if "annual_cost" in fields:
        values["annual_cost"] = records.checked_amount("annual_cost", fields["annual_cost"])
    if "record_status" in fields:
        values["record_status"] = records.checked_status(fields["record_status"])
    return values


# --- agreements ----------------------------------------------------------------------


def get_agreement(db: Session, hid: str) -> Agreement:
    """Return the agreement with hid."""
    agreement = db.get(Agreement, hid)
    if agreement is None:
        raise NotFound(f"there is no agreement {hid}")
    return agreement


def find_agreement(db: Session, text: str) -> Agreement | None:
    """Return the agreement that text names: by its HID or by its name."""
    text = text.strip()
    if ids.is_hid(text):
        found = db.get(Agreement, text)
        if found is not None:
            return found
    return db.scalar(select(Agreement).where(Agreement.name_key == records.key(text)))


def the_agreement(db: Session, text: str, field: str) -> Agreement:
    """Return the agreement text names, or refuse a name that there is not."""
    found = find_agreement(db, text)
    if found is None:
        raise Invalid("there is no such agreement", {field: f"there is no agreement {text}"})
    return found


def contracts_in(db: Session, agreement_hids: Sequence[str]) -> dict[str, int]:
    """Return how many contracts that are not retired each agreement groups."""
    counts = dict.fromkeys(agreement_hids, 0)
    if agreement_hids:
        counted = db.execute(
            select(Contract.agreement_hid, func.count())
            .where(Contract.agreement_hid.in_(agreement_hids), Contract.record_status != "retired")
            .group_by(Contract.agreement_hid)
        )
        for hid, count in counted:
            if hid is not None:
                counts[hid] = count
    return counts


def _checked_agreement(
    db: Session, fields: dict[str, Any], agreement: Agreement | None
) -> dict[str, Any]:
    values = _shared(db, fields, agreement)
    if "name" in fields:
        name = records.clean(fields["name"])
        if name is None or ";" in name:
            raise Invalid(
                "the name is not acceptable", {"name": "not blank, and with no semicolon"}
            )
        taken = db.scalar(select(Agreement).where(Agreement.name_key == records.key(name)))
        if taken is not None and (agreement is None or taken.hid != agreement.hid):
            raise Conflict(
                f"there is already an agreement {taken.name}",
                {"name": "another agreement has this name"},
            )
        values["name"] = name
        values["name_key"] = records.key(name)
    if "number" in fields:
        values["number"] = records.clean(fields["number"])
    if "vendor_hid" in fields:
        hid = fields["vendor_hid"] or None
        if hid is None or db.get(Vendor, hid) is None:
            raise Invalid(
                "an agreement is with a vendor", {"vendor_hid": f"there is no vendor {hid or ''}"}
            )
        if agreement is not None and hid != agreement.vendor_hid:
            held = db.scalar(
                select(func.count())
                .select_from(Contract)
                .where(Contract.agreement_hid == agreement.hid)
            )
            if held:
                raise Invalid(
                    "the agreement has contracts",
                    {"vendor_hid": "the contracts in an agreement are with its vendor"},
                )
        values["vendor_hid"] = hid

    def final(name: str) -> Any:
        return values.get(name, getattr(agreement, name) if agreement is not None else None)

    records.checked_span(final("starts_on"), final("ends_on"))
    return values


def create_agreement(db: Session, context: AuditContext, fields: dict[str, Any]) -> Agreement:
    """Create a support agreement. Contracts are put into it afterwards."""
    labels = fields.pop("tags", None) or []
    given = {"name": None, "vendor_hid": None, **fields}
    agreement = Agreement(**_checked_agreement(db, given, None))
    records.created(
        db,
        context,
        AGREEMENT_TYPE,
        agreement,
        AGREEMENT_FIELDS,
        then=lambda: tags.set_labels(db, AGREEMENT_TYPE, agreement.hid, labels),
    )
    return agreement


def update_agreement(
    db: Session, context: AuditContext, hid: str, row_version: int, fields: dict[str, Any]
) -> Agreement:
    """Change an agreement. Every contract in it that says nothing of its own has the
    change at once, and so has every item under those contracts: none is written to."""
    dialect.hold_other_writers(db)
    agreement = get_agreement(db, hid)
    has_tags = "tags" in fields
    labels = fields.pop("tags", None) or []
    values = _checked_agreement(db, fields, agreement)
    tag_change = tags.set_labels(db, AGREEMENT_TYPE, hid, labels) if has_tags else []
    records.apply(db, context, AGREEMENT_TYPE, agreement, row_version, values, tag_change)
    return agreement


def retire_agreement(db: Session, context: AuditContext, hid: str, row_version: int) -> Agreement:
    """Retire an agreement, once no contract that is not retired is in it."""
    dialect.hold_other_writers(db)
    agreement = get_agreement(db, hid)
    held = contracts_in(db, [agreement.hid])[agreement.hid]
    if held and agreement.record_status != "retired":
        raise Conflict(
            f"{held} contracts that are not retired are in this agreement",
            {"record_status": "take the contracts out of it, or retire them, first"},
        )
    records.apply(
        db,
        context,
        AGREEMENT_TYPE,
        agreement,
        row_version,
        {"record_status": "retired"},
        action="retire",
    )
    return agreement


def agreement_of(contract: Contract) -> Agreement | None:
    """Return the agreement a contract is grouped into, as the contract names it now."""
    db = object_session(contract)
    if contract.agreement_hid is None or db is None:
        return None
    return db.get(Agreement, contract.agreement_hid)


def effective(contract: Contract) -> dict[str, Effective]:
    """Return what a contract has in force for each field it may have from its
    agreement: its own, or the agreement's where its own is blank."""
    agreement = agreement_of(contract)
    found: dict[str, Effective] = {}
    for name in INHERITED:
        own = getattr(contract, name)
        if own is not None:
            found[name] = Effective(own, "own", contract.hid)
        elif agreement is not None and getattr(agreement, name) is not None:
            found[name] = Effective(getattr(agreement, name), "agreement", agreement.hid)
        else:
            found[name] = NOTHING
    return found


# --- contracts -----------------------------------------------------------------------


def get_contract(db: Session, hid: str) -> Contract:
    """Return the contract with hid."""
    contract = db.get(Contract, hid)
    if contract is None:
        raise NotFound(f"there is no contract {hid}")
    return contract


def named(db: Session, number: str, vendor_hid: str | None = None) -> list[Contract]:
    """Return the contracts with a number: one to a vendor that uses it."""
    query = select(Contract).where(Contract.number_key == records.key(number))
    if vendor_hid is not None:
        query = query.where(Contract.vendor_hid == vendor_hid)
    return list(db.scalars(query.order_by(Contract.hid).limit(50)))


def the_one(db: Session, text: str, field: str, vendor_hid: str | None = None) -> Contract:
    """Return the one contract that text names: by its HID, or by its number.

    Two vendors may use one number. Then the vendor says which, and without it the
    number alone names none.
    """
    text = text.strip()
    if ids.is_hid(text):
        found = db.get(Contract, text)
        if found is not None:
            return found
    found_ = named(db, text, vendor_hid)
    if not found_:
        raise Invalid("there is no such contract", {field: f"there is no contract {text}"})
    if len(found_) > 1:
        raise Invalid(
            f"more than one contract has the number {text}",
            {field: "more than one vendor uses this number; name the vendor, or give the HID"},
        )
    return found_[0]


def _checked(db: Session, fields: dict[str, Any], contract: Contract | None) -> dict[str, Any]:
    values = _shared(db, fields, contract)
    if "agreement_hid" in fields:
        values["agreement_hid"] = records.linked(
            db, Agreement, "agreement_hid", fields["agreement_hid"], contract, "agreement"
        )

    def final(name: str) -> Any:
        return values.get(name, getattr(contract, name) if contract is not None else None)

    within = get_agreement(db, final("agreement_hid")) if final("agreement_hid") else None
    if "vendor_hid" in fields or contract is None:
        # Left out, the vendor of a contract in an agreement is the agreement's.
        hid = fields.get("vendor_hid") or (within.vendor_hid if within is not None else None)
        if hid is None or db.get(Vendor, hid) is None:
            raise Invalid(
                "a contract is with a vendor", {"vendor_hid": f"there is no vendor {hid or ''}"}
            )
        values["vendor_hid"] = hid
    if "number" in fields:
        number = records.clean(fields["number"])
        if number is None or ";" in number:
            raise Invalid(
                "the number is not acceptable", {"number": "not blank, and with no semicolon"}
            )
        values["number"] = number
        values["number_key"] = records.key(number)
    if within is not None and within.vendor_hid != final("vendor_hid"):
        raise Invalid(
            "the agreement is with another vendor",
            {"agreement_hid": "a contract is grouped into an agreement with its own vendor"},
        )
    # The period in force: the contract's own, or the agreement's where that is blank.
    records.checked_span(
        final("starts_on") or (within.starts_on if within is not None else None),
        final("ends_on") or (within.ends_on if within is not None else None),
    )
    if "number_key" in values or "vendor_hid" in values:
        taken = db.scalar(
            select(Contract).where(
                Contract.vendor_hid == final("vendor_hid"),
                Contract.number_key == final("number_key"),
            )
        )
        if taken is not None and (contract is None or taken.hid != contract.hid):
            raise Conflict(
                f"this vendor already has a contract {taken.number}",
                {"number": "another contract of this vendor has this number"},
            )
    return values


def create_contract(db: Session, context: AuditContext, fields: dict[str, Any]) -> Contract:
    """Create a contract, by itself or in an agreement. It covers nothing until items
    are put under it."""
    labels = fields.pop("tags", None) or []
    contract = Contract(**_checked(db, {"number": None, **fields}, None))
    records.created(
        db,
        context,
        RECORD_TYPE,
        contract,
        FIELDS,
        then=lambda: tags.set_labels(db, RECORD_TYPE, contract.hid, labels),
    )
    return contract


def update_contract(
    db: Session, context: AuditContext, hid: str, row_version: int, fields: dict[str, Any]
) -> Contract:
    """Change a contract. Another date moves the end of every coverage that has none of
    its own, at once, and no coverage is written to. Given an agreement, it is in that
    agreement from then on, and has from it whatever it leaves blank."""
    contract = get_contract(db, hid)
    has_tags = "tags" in fields
    labels = fields.pop("tags", None) or []
    values = _checked(db, fields, contract)
    tag_change = tags.set_labels(db, RECORD_TYPE, hid, labels) if has_tags else []
    records.apply(db, context, RECORD_TYPE, contract, row_version, values, tag_change)
    return contract


# What a renewal may say: the term, and what usually changes with it.
RENEWED = (
    "number",
    "starts_on",
    "ends_on",
    "annual_cost",
    "purchase_reference",
    "reseller_hid",
    "support_level",
    "notes",
    "status",
)
TERM = ("number", "starts_on", "ends_on", "annual_cost", "purchase_reference")


def renew_contract(
    db: Session, context: AuditContext, hid: str, row_version: int, fields: dict[str, Any]
) -> Contract:
    """Renew a contract: give it its new number and its new period, in one change.

    Every item in scope has the new number and the new period at once, because each
    holds the link and nothing else: no item and no coverage is written to. The
    contract is active afterwards unless the renewal says another status.
    """
    contract = get_contract(db, hid)
    if contract.record_status == "retired":
        raise Invalid("the contract is retired", {"record_status": "bring it back first"})
    unknown = sorted(set(fields) - set(RENEWED))
    if unknown:
        raise Invalid(
            "a renewal does not change this",
            dict.fromkeys(unknown, f"a renewal sets {', '.join(RENEWED)}"),
        )
    values = _checked(db, {"status": ACTIVE, **fields}, contract)
    if all(
        values.get(name, getattr(contract, name)) == getattr(contract, name) for name in TERM[:3]
    ):
        raise Invalid(
            "a renewal has a new number or a new period",
            {"ends_on": "give the new number, the new period, or both"},
        )
    records.apply(db, context, RECORD_TYPE, contract, row_version, values, action="renew")
    return contract


@dataclass(frozen=True)
class Term:
    """A term a contract had before it was renewed, and when that was."""

    number: str
    starts_on: date | None
    ends_on: date | None
    annual_cost: Decimal | None
    purchase_reference: str | None
    renewed_at: datetime
    renewed_by: str | None


def _as_kept(name: str, value: Any) -> Any:
    """Return a value of a term as the record holds it, from what an audit event kept."""
    if value is None:
        return None
    try:
        if name == "annual_cost":
            return Decimal(str(value))
        if name in ("starts_on", "ends_on"):
            return date.fromisoformat(str(value))
    except ValueError, InvalidOperation:
        return None
    return value


def terms(db: Session, contract: Contract) -> list[Term]:
    """Return the terms a contract had before, the latest first.

    They are read from the audit trail and stored nowhere else: every change of the
    contract is undone in turn, from what it is now, and what it was just before each
    renewal is a term.
    """
    state = {name: getattr(contract, name) for name in TERM}
    found: list[Term] = []
    events = db.scalars(
        select(AuditEvent)
        .where(AuditEvent.record_type == RECORD_TYPE, AuditEvent.record_hid == contract.hid)
        .order_by(AuditEvent.at.desc(), AuditEvent.hid.desc())
    )
    for event in events:
        for one in event.changes:
            if one.get("field") in state:
                state[one["field"]] = _as_kept(one["field"], one.get("old"))
        if event.action == "renew" and state["number"]:
            found.append(Term(**state, renewed_at=event.at, renewed_by=event.actor_hid))
    return found


def in_scope(db: Session, contract_hids: Sequence[str]) -> dict[str, int]:
    """Return how many items are in scope of each contract: those with a coverage
    under it that has not been ended, and so follow it when it is renewed."""
    counts = dict.fromkeys(contract_hids, 0)
    if contract_hids:
        day = dialect.today()
        counted = db.execute(
            select(
                ContractCoverage.contract_hid, func.count(func.distinct(ContractCoverage.item_hid))
            )
            .where(
                ContractCoverage.contract_hid.in_(contract_hids),
                or_(ContractCoverage.ends_on.is_(None), ContractCoverage.ends_on >= day),
            )
            .group_by(ContractCoverage.contract_hid)
        )
        for hid, count in counted:
            counts[hid] = count
    return counts


def retire_contract(db: Session, context: AuditContext, hid: str, row_version: int) -> Contract:
    """Retire a contract. Its coverages stay on record, and cover nothing any more."""
    contract = get_contract(db, hid)
    records.apply(
        db,
        context,
        RECORD_TYPE,
        contract,
        row_version,
        {"record_status": "retired"},
        action="retire",
    )
    return contract


# --- what is in force ----------------------------------------------------------------


@dataclass(frozen=True)
class Span:
    """A range of days. A blank end is open."""

    starts_on: date | None
    ends_on: date | None

    def holds(self, day: date) -> bool:
        """Say whether a day is within the span."""
        return (self.starts_on is None or self.starts_on <= day) and (
            self.ends_on is None or day <= self.ends_on
        )

    def meets(self, other: Span) -> bool:
        """Say whether two spans share a day."""
        return (
            self.ends_on is None or other.starts_on is None or other.starts_on <= self.ends_on
        ) and (other.ends_on is None or self.starts_on is None or self.starts_on <= other.ends_on)


def _later(first: date | None, second: date | None) -> date | None:
    if first is None or second is None:
        return first or second
    return max(first, second)


def _sooner(first: date | None, second: date | None) -> date | None:
    if first is None or second is None:
        return first or second
    return min(first, second)


def period(contract: Contract) -> Span:
    """Return the period in force of a contract: its own dates, or those of the
    agreement it is in where its own are blank."""
    agreement = agreement_of(contract)
    starts_on, ends_on = contract.starts_on, contract.ends_on
    if agreement is not None:
        starts_on = agreement.starts_on if starts_on is None else starts_on
        ends_on = agreement.ends_on if ends_on is None else ends_on
    return Span(starts_on, ends_on)


def span_of(starts_on: date | None, ends_on: date | None, within: Span) -> Span:
    """Return the days in force of a coverage with dates of its own, within the period
    of its contract."""
    return Span(_later(starts_on, within.starts_on), _sooner(ends_on, within.ends_on))


def span(coverage: ContractCoverage, contract: Contract) -> Span:
    """Return the days in force of a coverage."""
    return span_of(coverage.starts_on, coverage.ends_on, period(contract))


def covers(contract: Contract, day: date) -> bool:
    """Say whether a contract covers on a day: active in both senses, and in date."""
    return (
        contract.record_status == "active"
        and contract.status == ACTIVE
        and period(contract).holds(day)
    )


def in_force(coverage: ContractCoverage, contract: Contract, day: date) -> bool:
    """Say whether a coverage is in force on a day."""
    return covers(contract, day) and span(coverage, contract).holds(day)


def covered_until(found: Sequence[tuple[ContractCoverage, Contract]], day: date) -> date | None:
    """Return the last day the cover of an item runs to: of its coverages that have
    not ended, under contracts that a person calls active. None when one of them names
    no end, and when there is none."""
    ends_: list[date] = []
    for coverage, contract in found:
        if contract.record_status != "active" or contract.status != ACTIVE:
            continue
        its = span(coverage, contract)
        if its.starts_on is not None and its.ends_on is not None and its.ends_on < its.starts_on:
            continue
        if its.ends_on is None:
            return None
        if its.ends_on >= day:
            ends_.append(its.ends_on)
    return max(ends_, default=None)


def of_items(
    db: Session, item_hids: Sequence[str]
) -> dict[str, list[tuple[ContractCoverage, Contract]]]:
    """Return the coverages of each item with their contracts: by the number of the
    contract, then by the day each starts."""
    found: dict[str, list[tuple[ContractCoverage, Contract]]] = {hid: [] for hid in item_hids}
    if not item_hids:
        return found
    rows = db.execute(
        select(ContractCoverage, Contract)
        .join(Contract, Contract.hid == ContractCoverage.contract_hid)
        .where(ContractCoverage.item_hid.in_(item_hids))
        .order_by(Contract.number_key, ContractCoverage.starts_on, ContractCoverage.hid)
    )
    for coverage, contract in rows:
        found[coverage.item_hid].append((coverage, contract))
    return found


# --- the same, for the database ------------------------------------------------------


def _least(first: Any, second: Any) -> ColumnElement[Any]:
    return case(
        (first.is_(None), second),
        (second.is_(None), first),
        (first < second, first),
        else_=second,
    )


def _greatest(first: Any, second: Any) -> ColumnElement[Any]:
    return case(
        (first.is_(None), second),
        (second.is_(None), first),
        (first > second, first),
        else_=second,
    )


def in_force_of(contract: Any, name: str) -> ColumnElement[Any]:
    """Return what a contract has in force in one of the fields it may have from its
    agreement: its own, or the agreement's where its own is blank."""
    from_agreement = (
        select(getattr(Agreement, name))
        .where(Agreement.hid == contract.agreement_hid)
        .correlate(contract)
        .scalar_subquery()
    )
    own = getattr(contract, name)
    return func.coalesce(own, from_agreement, type_=own.type)


def starts(coverage: Any = ContractCoverage, contract: Any = Contract) -> ColumnElement[Any]:
    """Return the day a coverage starts in force: its own or the contract's, the later."""
    return _greatest(coverage.starts_on, in_force_of(contract, "starts_on"))


def ends(coverage: Any = ContractCoverage, contract: Any = Contract) -> ColumnElement[Any]:
    """Return the day a coverage ends in force: its own or the contract's, the sooner."""
    return _least(coverage.ends_on, in_force_of(contract, "ends_on"))


def contract_covers(contract: Any = Contract, day: Any = None) -> ColumnElement[bool]:
    """Return the test that a contract covers on a day, today unless another is given."""
    day = dialect.today() if day is None else day
    starts_on, ends_on = in_force_of(contract, "starts_on"), in_force_of(contract, "ends_on")
    return and_(
        contract.record_status == "active",
        contract.status == ACTIVE,
        or_(starts_on.is_(None), starts_on <= day),
        or_(ends_on.is_(None), ends_on >= day),
    )


def coverage_in_force(
    coverage: Any = ContractCoverage, contract: Any = Contract, day: Any = None
) -> ColumnElement[bool]:
    """Return the test that a coverage, joined to its contract, is in force on a day."""
    day = dialect.today() if day is None else day
    return and_(
        contract_covers(contract, day),
        or_(coverage.starts_on.is_(None), coverage.starts_on <= day),
        or_(coverage.ends_on.is_(None), coverage.ends_on >= day),
    )


def covered_items(db: Session, contract_hids: Sequence[str]) -> dict[str, int]:
    """Return how many items each contract covers today."""
    counts = dict.fromkeys(contract_hids, 0)
    if contract_hids:
        counted = db.execute(
            select(
                ContractCoverage.contract_hid, func.count(func.distinct(ContractCoverage.item_hid))
            )
            .join(Contract, Contract.hid == ContractCoverage.contract_hid)
            .where(ContractCoverage.contract_hid.in_(contract_hids), coverage_in_force())
            .group_by(ContractCoverage.contract_hid)
        )
        for hid, count in counted:
            counts[hid] = count
    return counts


# --- coverage ------------------------------------------------------------------------


def get_coverage(db: Session, contract_hid: str, coverage_hid: str) -> ContractCoverage:
    """Return one coverage of one contract."""
    coverage = db.get(ContractCoverage, coverage_hid)
    if coverage is None or coverage.contract_hid != contract_hid:
        raise NotFound(f"there is no coverage {coverage_hid} under this contract")
    return coverage


def _others(
    db: Session, contract_hid: str, item_hid: str, but: str | None
) -> list[ContractCoverage]:
    return [
        one
        for one in db.scalars(
            select(ContractCoverage).where(
                ContractCoverage.contract_hid == contract_hid,
                ContractCoverage.item_hid == item_hid,
            )
        )
        if one.hid != but
    ]


def _check_span(
    db: Session,
    contract: Contract,
    item_hid: str,
    starts_on: date | None,
    ends_on: date | None,
    but: str | None,
    field: str,
) -> None:
    """Refuse days that end before they start, or that another coverage of the same
    item under the same contract already has.

    Two coverages are held apart by their own dates, a blank being open: so whatever
    period the contract or its agreement is given later, they never come to overlap.
    """
    in_force_ = span_of(starts_on, ends_on, period(contract))
    records.checked_span(in_force_.starts_on, in_force_.ends_on, field)
    own = Span(starts_on, ends_on)
    for other in _others(db, contract.hid, item_hid, but):
        if own.meets(Span(other.starts_on, other.ends_on)):
            raise Conflict(
                "this contract already covers the item in those days",
                {
                    field: "another coverage of this item under this contract has these "
                    "days; end that one on a day of its own first"
                },
            )


def _own(given: date | None, of_contract: date | None) -> date | None:
    """Return the date a coverage keeps as its own. One that is the contract's is kept
    as blank: the coverage then follows the contract, whatever its period becomes."""
    return None if given == of_contract else given


def add_coverage(
    db: Session, context: AuditContext, contract_hid: str, entries: Sequence[dict[str, Any]]
) -> list[ContractCoverage]:
    """Put items under a contract, several at a time. Each is checked, and either all
    of them are covered or none is."""
    # Checked against the other coverages of each item under this contract.
    dialect.hold_other_writers(db)
    contract = get_contract(db, contract_hid)
    if contract.record_status == "retired":
        raise Invalid("the contract is retired", {"contract_hid": "this contract is retired"})
    if not entries:
        raise Invalid("nothing to cover", {"items": "name one item or more"})
    if len(entries) > MAX_AT_ONCE:
        raise Invalid("too many at once", {"items": f"at most {MAX_AT_ONCE} items to a request"})
    its = period(contract)
    made: list[ContractCoverage] = []
    for place, entry in enumerate(entries):
        where = f"items.{place}."
        hid = entry.get("item_hid") or ""
        item = db.get(Item, hid) if isinstance(hid, str) else None
        if item is None:
            raise Invalid("there is no such item", {f"{where}item_hid": f"there is no item {hid}"})
        if item.record_status == "retired":
            raise Invalid("the item is retired", {f"{where}item_hid": "this item is retired"})
        starts_on = _own(
            records.checked_day(f"{where}starts_on", entry.get("starts_on")), its.starts_on
        )
        ends_on = _own(records.checked_day(f"{where}ends_on", entry.get("ends_on")), its.ends_on)
        _check_span(db, contract, item.hid, starts_on, ends_on, None, f"{where}ends_on")
        coverage = ContractCoverage(
            contract_hid=contract.hid, item_hid=item.hid, starts_on=starts_on, ends_on=ends_on
        )
        records.created(db, context, COVERAGE_TYPE, coverage, COVERAGE_FIELDS)
        made.append(coverage)
    return made


def update_coverage(
    db: Session,
    context: AuditContext,
    contract_hid: str,
    coverage_hid: str,
    row_version: int,
    fields: dict[str, Any],
) -> ContractCoverage:
    """Change the days of a coverage. It is ended by giving it `ends_on`."""
    dialect.hold_other_writers(db)
    coverage = get_coverage(db, contract_hid, coverage_hid)
    contract = get_contract(db, contract_hid)
    for name in ("contract_hid", "item_hid"):
        if name in fields and fields[name] != getattr(coverage, name):
            raise Invalid(
                "a coverage stays with its contract and its item",
                {name: "end this coverage and add the other"},
            )
    its = period(contract)
    values = {
        name: _own(records.checked_day(name, fields[name]), getattr(its, name))
        for name in ("starts_on", "ends_on")
        if name in fields
    }
    if any(values[name] != getattr(coverage, name) for name in values):
        _check_span(
            db,
            contract,
            coverage.item_hid,
            values.get("starts_on", coverage.starts_on),
            values.get("ends_on", coverage.ends_on),
            coverage.hid,
            "ends_on",
        )
    records.apply(db, context, COVERAGE_TYPE, coverage, row_version, values)
    return coverage
