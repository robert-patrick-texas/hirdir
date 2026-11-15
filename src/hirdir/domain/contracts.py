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

A renewal that is entered before its period begins is kept as the next term. The term
in force is worked out when a record is read: the present one until the day the next
begins, and the next from then on. No clock writes anything. The next term is written
into the record's own fields by the first change that is made after it has begun.

What is in force is worked out here for a page of records and, as SQL, for the
database to filter, sort and count by. A test holds the two together.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace
from typing import Any, Literal
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, and_, case, func, literal, or_, select
from sqlalchemy.orm import Session, object_session

from hirdir import clock, ids
from hirdir.db import dialect
from hirdir.db.models import Agreement, AuditEvent, Contract, ContractCoverage, Item, Vendor
from hirdir.domain import audit, records, settings, tags
from hirdir.domain.audit import AuditContext, change
from hirdir.domain.errors import Conflict, Invalid, NotFound
from hirdir.domain.inheritance import NOTHING, Effective

RECORD_TYPE = "contract"
AGREEMENT_TYPE = "agreement"
COVERAGE_TYPE = "contract_coverage"
STATUSES = ("active", "renewal_pending", "expired", "pending", "cancelled")
ACTIVE = STATUSES[0]
# The term has ended and the renewal is in procurement: the vendor still gives support,
# by escalation, and the contract covers past the end of its period.
RENEWAL_PENDING = STATUSES[1]
EXPIRED = STATUSES[2]
COVERING = (ACTIVE, RENEWAL_PENDING)
# What a person said of a term that has ended, and a term that begins puts an end to:
# the contract is active from that day, as it is after a renewal that is in force at
# once. `pending` and `cancelled` are of the contract and not of a term, and stay.
ENDED_BY_A_TERM = (RENEWAL_PENDING, EXPIRED)
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
# What a term is: what a renewal gives anew.
TERM = ("number", "starts_on", "ends_on", "annual_cost", "purchase_reference")
NEXT = tuple(f"next_{name}" for name in TERM)
_SHARED = (
    "reseller_hid",
    "starts_on",
    "ends_on",
    "status",
    *TEXTS[:-1],
    "support_url",
    "notes",
    "annual_cost",
    *NEXT,
    "record_status",
)
_DATES = ("starts_on", "ends_on", "next_starts_on", "next_ends_on")
AGREEMENT_FIELDS = ("name", "number", "vendor_hid", *_SHARED)
FIELDS = ("number", "vendor_hid", "agreement_hid", *_SHARED)
COVERAGE_FIELDS = ("contract_hid", "item_hid", "starts_on", "ends_on", "left_service")
# An item has left service when it is retired or in one of these states (D-142).
OUT_OF_SERVICE = ("Pending-Removal", "Released", "Archived")
MAX_AT_ONCE = 1000
MAX_NAMED = 20


def today(db: Session) -> date:
    """Return today's date in the application's time zone."""
    return clock.today(settings.time_zone(db))


# --- the term in force ---------------------------------------------------------------


def next_started(record: Any, day: date) -> bool:
    """Say whether the next term of an agreement or a contract has begun."""
    return record.next_starts_on is not None and record.next_starts_on <= day


def _next_term(record: Any) -> dict[str, Any]:
    """Return the next term whole: what it gives anew, and the rest as it stands."""
    return {
        "number": record.next_number or record.number,
        "starts_on": record.next_starts_on,
        "ends_on": record.next_ends_on,
        "annual_cost": record.annual_cost
        if record.next_annual_cost is None
        else record.next_annual_cost,
        "purchase_reference": record.next_purchase_reference or record.purchase_reference,
    }


def term(record: Any, day: date) -> dict[str, Any]:
    """Return the term of an agreement or a contract that is in force on a day."""
    if next_started(record, day):
        return _next_term(record)
    return {name: getattr(record, name) for name in TERM}


def last_term(record: Any) -> dict[str, Any]:
    """Return the last term that is known: the next one, where there is one."""
    if record.next_starts_on is not None:
        return _next_term(record)
    return {name: getattr(record, name) for name in TERM}


def pending_term(record: Any, day: date) -> dict[str, Any] | None:
    """Return the term that is still to begin, or None where there is none."""
    if record.next_starts_on is None or next_started(record, day):
        return None
    return {name: getattr(record, f"next_{name}") for name in TERM}


def status_of(record: Any, day: date) -> str:
    """Return the status in force: a renewal that was pending is no longer, and a
    contract that had expired is active again, once the term to come has begun."""
    if record.status in ENDED_BY_A_TERM and next_started(record, day):
        return ACTIVE
    return record.status


def last_status(record: Any) -> str:
    """Return the status in the last term that is known: that of the next one, where
    there is one."""
    if record.status in ENDED_BY_A_TERM and record.next_starts_on is not None:
        return ACTIVE
    return record.status


def version(record: Any, day: date) -> int:
    """Return the version of an agreement or a contract as it is read on a day.

    A next term that has begun and is not written down yet counts as the change it
    will be: so what was read before that day is stale after it, and an edit that was
    meant for the old term is refused and not made to the new one.
    """
    return record.row_version + (1 if next_started(record, day) else 0)


def _as_would_be(record: Any | None, values: dict[str, Any]) -> Any:
    """Return the terms of a record as a change would leave them."""
    return SimpleNamespace(
        **{
            name: values.get(name, getattr(record, name) if record is not None else None)
            for name in (*TERM, *NEXT)
        }
    )


def _inverted(contract: Any, agreement: Any | None, day: date) -> bool:
    """Say whether a contract has, today or on a day to come, a period in force that
    ends before it starts: its own dates, or its agreement's where its own are blank,
    by the terms of the two that are in force together on that day."""
    turns = {
        one.next_starts_on
        for one in (contract, agreement)
        if one is not None and one.next_starts_on is not None and one.next_starts_on > day
    }
    for on in sorted({day, *turns}):
        its = _period(term(contract, on), term(agreement, on) if agreement is not None else None)
        if its.starts_on is not None and its.ends_on is not None and its.ends_on < its.starts_on:
            return True
    return False


def _fold(db: Session, context: AuditContext, record: Any, record_type: str) -> bool:
    """Write a next term that has begun into the record's own fields. Say whether one was.

    Nothing reads differently for it: the term in force was the next one already. It
    is done before any other change, so that a change is made to what is in force.
    """
    day = today(db)
    if not next_started(record, day):
        return False
    values: dict[str, Any] = {**_next_term(record), **dict.fromkeys(NEXT)}
    if record_type == RECORD_TYPE:
        values["number_key"] = records.key(values["number"])
    values["status"] = status_of(record, day)
    records.apply(db, context, record_type, record, None, values, action="renew")
    return True


def _shared(db: Session, fields: dict[str, Any], record: Any | None) -> dict[str, Any]:
    """Return the checked values of what an agreement and a contract both hold."""
    values: dict[str, Any] = {}
    if "reseller_hid" in fields:
        values["reseller_hid"] = records.linked(
            db, Vendor, "reseller_hid", fields["reseller_hid"], record, "vendor"
        )
    for name in ("starts_on", "ends_on", "next_starts_on", "next_ends_on"):
        if name in fields:
            values[name] = records.checked_day(name, fields[name])
    if "status" in fields:
        values["status"] = records.checked_choice(fields["status"] or ACTIVE, STATUSES, "status")
    for name in (*TEXTS, "next_number", "next_purchase_reference"):
        if name in fields:
            values[name] = records.clean(fields[name])
    if "support_url" in fields:
        values["support_url"] = records.checked_url("support_url", fields["support_url"])
    for name in ("annual_cost", "next_annual_cost"):
        if name in fields:
            values[name] = records.checked_amount(name, fields[name])
    if "record_status" in fields:
        values["record_status"] = records.checked_status(fields["record_status"])

    def final(name: str) -> Any:
        return values.get(name, getattr(record, name) if record is not None else None)

    if final("next_starts_on") is None and any(final(name) is not None for name in NEXT):
        raise Invalid(
            "a next term begins on a day",
            {"next_starts_on": "the first day of the next term, or none of the next term"},
        )
    return values


def _checked_renewal(fields: dict[str, Any], allowed: tuple[str, ...]) -> None:
    unknown = sorted(set(fields) - set(allowed) - {"withdraw"})
    if unknown:
        raise Invalid(
            "a renewal does not change this",
            dict.fromkeys(unknown, f"a renewal sets {', '.join(allowed)}"),
        )


def _renewal(
    db: Session, record: Any, fields: dict[str, Any], values: dict[str, Any]
) -> dict[str, Any]:
    """Return what a renewal writes: the new term at once, or as the next term where
    its period begins after today, so that the present term runs on until then."""
    if fields.get("withdraw"):
        if set(fields) - {"withdraw"}:
            raise Invalid(
                "a next term is withdrawn by itself", {"withdraw": "send nothing else with it"}
            )
        if record.next_starts_on is None:
            raise Invalid("there is no next term", {"withdraw": "no renewal is waiting to begin"})
        return dict.fromkeys(NEXT)
    starts_on = values.get("starts_on")
    if starts_on is None or starts_on <= today(db):
        if all(
            values.get(name, getattr(record, name)) == getattr(record, name) for name in TERM[:3]
        ):
            raise Invalid(
                "a renewal has a new number or a new period",
                {"ends_on": "give the new number, the new period, or both"},
            )
        # In force at once, and whatever was waiting to begin is superseded by it.
        return {**values, **dict.fromkeys(NEXT)}
    if "ends_on" not in fields:
        raise Invalid(
            "a term that is still to begin says when it ends",
            {"ends_on": "the last day of the new period, or null for none"},
        )
    records.checked_span(starts_on, values.get("ends_on"))
    later = {name: value for name, value in values.items() if name not in (*TERM, "number_key")}
    # The status is what a person says of the present term: it is left as it is.
    if "status" not in fields:
        later.pop("status", None)
    return {
        **later,
        "next_number": values.get("number"),
        "next_starts_on": starts_on,
        "next_ends_on": values.get("ends_on"),
        "next_annual_cost": values.get("annual_cost"),
        "next_purchase_reference": values.get("purchase_reference"),
    }


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


def _check_contracts_fit(db: Session, agreement: Agreement, as_changed: Any) -> None:
    """Refuse a change of the periods of an agreement that would leave a contract in it
    with a period that ends before it starts, today or once a term to come has begun,
    and name those contracts. One that is so already is not held against the change."""
    day = today(db)
    wrong = []
    grouped = db.scalars(
        select(Contract)
        .where(Contract.agreement_hid == agreement.hid, Contract.record_status != "retired")
        .order_by(Contract.number_key)
    )
    for contract in grouped:
        if _inverted(contract, as_changed, day) and not _inverted(contract, agreement, day):
            wrong.append(term(contract, day)["number"])
    if wrong:
        named_ = ", ".join(wrong[:MAX_NAMED]) + (" and more" if len(wrong) > MAX_NAMED else "")
        raise Invalid(
            "contracts in this agreement would end before they start",
            {"ends_on": f"put the dates of these contracts right first: {named_}"},
        )


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
                "an agreement is with a vendor",
                {"vendor_hid": f"there is no vendor {hid}" if hid else "must not be blank"},
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
    records.checked_span(final("next_starts_on"), final("next_ends_on"), "next_ends_on")
    if agreement is not None and any(
        name in values and values[name] != getattr(agreement, name) for name in _DATES
    ):
        _check_contracts_fit(db, agreement, _as_would_be(agreement, values))
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
    db: Session,
    context: AuditContext,
    hid: str,
    row_version: int,
    fields: dict[str, Any],
    as_stored: bool = False,
) -> Agreement:
    """Change an agreement. Every contract in it that says nothing of its own has the
    change at once, and so has every item under those contracts: none is written to.

    `as_stored` is for a file, which holds the record as it is stored, the next term
    beside the present one: nothing is then written down before the row is.
    """
    # Checked against the contracts in it, which nobody may be changing meanwhile.
    dialect.hold_other_writers(db)
    agreement = get_agreement(db, hid)
    if not as_stored:
        # The version the caller read counted it already: see `version`.
        _fold(db, context, agreement, AGREEMENT_TYPE)
    has_tags = "tags" in fields
    labels = fields.pop("tags", None) or []
    values = _checked_agreement(db, fields, agreement)
    tag_change = tags.set_labels(db, AGREEMENT_TYPE, hid, labels) if has_tags else []
    records.apply(db, context, AGREEMENT_TYPE, agreement, row_version, values, tag_change)
    return agreement


AGREEMENT_RENEWED = (
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
RENEWED = AGREEMENT_RENEWED


def renew_agreement(
    db: Session, context: AuditContext, hid: str, row_version: int, fields: dict[str, Any]
) -> Agreement:
    """Renew an agreement: its new period, in one change. The contracts that are
    co-termed with it follow, and so do the items under them. A period that begins
    after today is kept as the next term, and the present one runs on until then."""
    dialect.hold_other_writers(db)
    agreement = get_agreement(db, hid)
    if agreement.record_status == "retired":
        raise Invalid("the agreement is retired", {"record_status": "bring it back first"})
    _checked_renewal(fields, AGREEMENT_RENEWED)
    _fold(db, context, agreement, AGREEMENT_TYPE)
    given = {name: value for name, value in fields.items() if name != "withdraw"}
    checked = _shared(db, {"status": ACTIVE, **given}, agreement)
    if "number" in given:
        checked["number"] = records.clean(given["number"])
    values = _renewal(db, agreement, fields, checked)
    after = _as_would_be(agreement, values)
    records.checked_span(after.starts_on, after.ends_on)
    _check_contracts_fit(db, agreement, after)
    records.apply(db, context, AGREEMENT_TYPE, agreement, row_version, values, action="renew")
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


def agreement_gives(contract: Contract, day: date) -> dict[str, Any]:
    """Return what the agreement of a contract gives on a day for each field the
    contract may have from it, whether the contract overrides the field or not. Each is
    blank for a contract in no agreement."""
    agreement = agreement_of(contract)
    if agreement is None:
        return dict.fromkeys(INHERITED)
    return {
        **{name: getattr(agreement, name) for name in INHERITED},
        **{name: value for name, value in term(agreement, day).items() if name in INHERITED},
    }


def effective(contract: Contract, day: date, as_stored: bool = False) -> dict[str, Effective]:
    """Return what a contract has in force for each field it may have from its
    agreement: its own, or the agreement's where its own is blank. `as_stored` is for a
    file: its own are then those of the term the record holds, whichever is in force."""
    agreement = agreement_of(contract)
    own = {name: getattr(contract, name) for name in INHERITED}
    if not as_stored:
        own.update({name: value for name, value in term(contract, day).items() if name in own})
    above = agreement_gives(contract, day)
    found: dict[str, Effective] = {}
    for name in INHERITED:
        if own[name] is not None:
            found[name] = Effective(own[name], "own", contract.hid)
        elif agreement is not None and above[name] is not None:
            found[name] = Effective(above[name], "agreement", agreement.hid)
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


def _numbered(number: str) -> ColumnElement[bool]:
    """Return the test that a contract answers to a number: its own, or its next one."""
    return or_(
        Contract.number_key == records.key(number),
        dialect.folded(Contract.next_number) == dialect.folded(literal(number.strip())),
    )


def named(db: Session, number: str, vendor_hid: str | None = None) -> list[Contract]:
    """Return the contracts that answer to a number: one to a vendor that uses it. A
    contract answers to the number it has and to the number of its next term."""
    query = select(Contract).where(_numbered(number))
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


def _check_number(
    db: Session, vendor_hid: str, number: str | None, contract: Contract | None, field: str
) -> None:
    """Refuse a number that another contract of the vendor has, now or as its next."""
    if number is None:
        return
    # Compared as a number is everywhere, by its key, and not as the database folds
    # text: the two differ for some letters, and one rule must hold for both numbers.
    key = records.key(number)
    others = db.scalars(
        select(Contract).where(
            Contract.vendor_hid == vendor_hid,
            or_(Contract.number_key == key, Contract.next_number.is_not(None)),
        )
    )
    for taken in others:
        same = taken.number_key == key or (
            taken.next_number is not None and records.key(taken.next_number) == key
        )
        if same and (contract is None or taken.hid != contract.hid):
            raise Conflict(
                f"this vendor already has a contract {number}",
                {field: "another contract of this vendor has this number"},
            )


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
                "a contract is with a vendor",
                {"vendor_hid": f"there is no vendor {hid}" if hid else "must not be blank"},
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
    brought_back = (
        contract is not None
        and contract.record_status == "retired"
        and values.get("record_status", "retired") != "retired"
    )
    if brought_back and within is not None and within.record_status == "retired":
        raise Invalid(
            f"{within.name}, the agreement it is in, is retired",
            {"record_status": "bring the agreement back first, or take the contract out of it"},
        )
    next_number = values.get("next_number")
    if next_number is not None and ";" in next_number:
        raise Invalid("the number is not acceptable", {"next_number": "with no semicolon"})
    # Its own dates, and then the period in force, which is the agreement's where its
    # own is blank: today, and on each day a term of either is still to begin. Only a
    # change of its dates or of its agreement is held to it, so that a contract which
    # is wrong already can still be given a note, and be put right.
    records.checked_span(final("starts_on"), final("ends_on"))
    records.checked_span(final("next_starts_on"), final("next_ends_on"), "next_ends_on")
    moved = contract is None or any(
        name in values and values[name] != getattr(contract, name)
        for name in (*_DATES, "agreement_hid")
    )
    if moved and _inverted(_as_would_be(contract, values), within, today(db)):
        which = (
            "next_ends_on" if "next_ends_on" in values or "next_starts_on" in values else "ends_on"
        )
        raise Invalid(
            "the contract would end before it starts",
            {
                which: "with the dates it has from its agreement, now or once a term that "
                "is still to begin has begun, the period would end before it starts"
            },
        )
    if "number_key" in values or "vendor_hid" in values:
        _check_number(db, final("vendor_hid"), final("number"), contract, "number")
    if "next_number" in values or "vendor_hid" in values:
        _check_number(db, final("vendor_hid"), final("next_number"), contract, "next_number")
    return values


def create_contract(db: Session, context: AuditContext, fields: dict[str, Any]) -> Contract:
    """Create a contract, by itself or in an agreement. It covers nothing until items
    are put under it."""
    # Checked against its agreement and the other contracts of its vendor.
    dialect.hold_other_writers(db)
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
    db: Session,
    context: AuditContext,
    hid: str,
    row_version: int,
    fields: dict[str, Any],
    as_stored: bool = False,
) -> Contract:
    """Change a contract. Another date moves the end of every coverage that has none of
    its own, at once, and no coverage is written to. Given an agreement, it is in that
    agreement from then on, and has from it whatever it leaves blank. `as_stored` is
    for a file: see `update_agreement`."""
    dialect.hold_other_writers(db)
    contract = get_contract(db, hid)
    if not as_stored:
        _fold(db, context, contract, RECORD_TYPE)
    has_tags = "tags" in fields
    labels = fields.pop("tags", None) or []
    values = _checked(db, fields, contract)
    tag_change = tags.set_labels(db, RECORD_TYPE, hid, labels) if has_tags else []
    records.apply(db, context, RECORD_TYPE, contract, row_version, values, tag_change)
    return contract


def renew_contract(
    db: Session, context: AuditContext, hid: str, row_version: int, fields: dict[str, Any]
) -> Contract:
    """Renew a contract: give it its new number and its new period, in one change.

    Every item in scope has the new number and the new period, because each holds the
    link and nothing else: no item and no coverage is written to. A period that begins
    after today is kept as the next term: the present number and period stay in force
    until that day, so the items are covered throughout. The contract is active after
    a renewal that is in force at once, unless the renewal says another status.
    """
    dialect.hold_other_writers(db)
    contract = get_contract(db, hid)
    if contract.record_status == "retired":
        raise Invalid("the contract is retired", {"record_status": "bring it back first"})
    _checked_renewal(fields, RENEWED)
    _fold(db, context, contract, RECORD_TYPE)
    given = {name: value for name, value in fields.items() if name != "withdraw"}
    starts_on = given.get("starts_on")
    ahead = isinstance(starts_on, date) and starts_on > today(db)
    if ahead:
        # The number and the period are of the term to come: checked as that, below,
        # and not against the term that is still running.
        now = {name: value for name, value in given.items() if name not in TERM}
        checked = _checked(db, now, contract)
        later = _shared(
            db, {name: given[name] for name in TERM if name in given and name != "number"}, None
        )
        if "number" in given:
            number = records.clean(given["number"])
            if number is None or ";" in number:
                raise Invalid(
                    "the number is not acceptable", {"number": "not blank, with no semicolon"}
                )
            _check_number(db, contract.vendor_hid, number, contract, "number")
            later["number"] = number
        checked = {**checked, **later}
    elif fields.get("withdraw"):
        checked = {}
    else:
        # In force at once: whatever was waiting to begin is superseded by it.
        checked = _checked(db, {"status": ACTIVE, **given, **dict.fromkeys(NEXT)}, contract)
    values = _renewal(db, contract, fields, checked)
    if values.get("next_starts_on") is not None and _inverted(
        _as_would_be(contract, values), agreement_of(contract), today(db)
    ):
        raise Invalid(
            "the term to come would end before it starts",
            {
                "ends_on": "with the dates the contract has from its agreement, the new "
                "period would end before it starts"
            },
        )
    records.apply(db, context, RECORD_TYPE, contract, row_version, values, action="renew")
    return contract


TermSource = Literal["own", "agreement", "none"]


@dataclass(frozen=True)
class Term:
    """A term an agreement or a contract had before it was renewed, and when that was.

    For a contract, the dates are those it had in force: where it had none of its own,
    those of the agreement it was in, as the agreement stood on the last day of the
    term. Each says where it came from, and `agreement_hid` is that agreement."""

    number: str | None
    starts_on: date | None
    ends_on: date | None
    annual_cost: Decimal | None
    purchase_reference: str | None
    renewed_at: datetime
    renewed_by: str | None
    agreement_hid: str | None = None
    starts_on_source: TermSource = "own"
    ends_on_source: TermSource = "own"


def _as_kept(name: str, value: Any) -> Any:
    """Return a value of a term as the record holds it, from what an audit event kept."""
    if value is None:
        return None
    try:
        if name == "annual_cost":
            return Decimal(str(value))
        if name in _DATES:
            return date.fromisoformat(str(value))
    except ValueError, InvalidOperation:
        return None
    return value


def _changed(event: AuditEvent, field: str) -> dict[str, Any]:
    """Return what an audit event says of one field, or nothing where it says nothing."""
    return next((one for one in event.changes if one.get("field") == field), {})


def _events(db: Session, record_type: str, hid: str) -> list[AuditEvent]:
    """Return the audit events of a record, the latest first."""
    return list(
        db.scalars(
            select(AuditEvent)
            .where(AuditEvent.record_type == record_type, AuditEvent.record_hid == hid)
            .order_by(AuditEvent.at.desc(), AuditEvent.hid.desc())
        )
    )


def _undone(state: dict[str, Any], event: AuditEvent) -> None:
    """Undo one change in a record's state: each field it changed is as it was before."""
    for one in event.changes:
        if one.get("field") in state:
            state[one["field"]] = _as_kept(one["field"], one.get("old"))


def _agreement_as_it_stood(db: Session, hid: str, before: datetime | None) -> Any | None:
    """Return the terms of an agreement as they stood at a moment, from its audit trail:
    what it is now, with every change made after that moment undone. None where there
    is no such agreement. `before` None is now."""
    agreement = db.get(Agreement, hid)
    if agreement is None:
        return None
    state = {name: getattr(agreement, name) for name in (*TERM, *NEXT)}
    if before is not None:
        for event in _events(db, AGREEMENT_TYPE, hid):
            if event.at <= before:
                break
            _undone(state, event)
    return SimpleNamespace(**state)


def _with_dates_in_force(db: Session, found: Term, began: datetime, zone: str) -> Term:
    """Return a term of a contract with the dates it had in force (D-163): a date it had
    none of is that of its agreement's term which was in force when the contract's term
    began, as the agreement stood at that moment."""
    above: dict[str, Any] = {}
    if found.agreement_hid is not None and (found.starts_on is None or found.ends_on is None):
        stood = _agreement_as_it_stood(db, found.agreement_hid, began)
        if stood is not None:
            above = term(stood, began.astimezone(ZoneInfo(zone)).date())
    dated: dict[str, Any] = {}
    for name in ("starts_on", "ends_on"):  # each by itself, as a contract has them
        own = getattr(found, name)
        if own is not None:
            dated |= {name: own, f"{name}_source": "own"}
        elif above.get(name) is not None:
            dated |= {name: above[name], f"{name}_source": "agreement"}
        else:
            dated |= {name: None, f"{name}_source": "none"}
    return Term(**{**found.__dict__, **dated})


def terms(db: Session, record: Any, record_type: str = RECORD_TYPE) -> list[Term]:
    """Return the terms a contract or an agreement had before, the latest first.

    They are read from the audit trail and stored nowhere else: every change of the
    record is undone in turn, from what it is now, and what it was just before each
    renewal that gave it another number or period is a term. `renewed_at` and
    `renewed_by` are when the renewal that ended the term was entered, and by whom:
    for one that was entered early, that is not the day its term began, nor the change
    that happened to write it down. A term of a contract has the dates it had in
    force, its agreement's where it had none of its own (D-163).
    """
    of_contract = record_type == RECORD_TYPE
    kept = (*TERM, "agreement_hid") if of_contract else TERM
    state = {name: getattr(record, name) for name in kept}
    events = _events(db, record_type, record.hid)
    day = today(db)
    zone = settings.time_zone(db)

    def entered(began: date, before: int) -> tuple[datetime, str | None]:
        """Return when the term that began on a day was entered, and by whom."""
        for event in events[before:]:
            # The last change that said when a term was to begin is the one that
            # entered the term which then did.
            if _changed(event, "next_starts_on").get("new") is not None:
                return event.at, event.actor_hid
        return datetime.combine(began, time.min, tzinfo=UTC), None

    def made(values: dict[str, Any], at: datetime, by: str | None) -> Term:
        return Term(
            **{name: values[name] for name in TERM},
            renewed_at=at,
            renewed_by=by,
            agreement_hid=values.get("agreement_hid"),
        )

    def morning(of: date) -> datetime:
        """Return the moment a day begins in the application's time zone."""
        return datetime.combine(of, time.min, tzinfo=ZoneInfo(zone))

    # Each term, the latest first, with the moment the term after it took effect.
    found: list[tuple[Term, datetime]] = []
    if next_started(record, day) and record.next_starts_on is not None:
        # The next term has begun and is not written down yet: the one before it is
        # the one the record still holds, and it ended the day before the next began.
        at, by = entered(record.next_starts_on, 0)
        found.append((made(state, at, by), morning(record.next_starts_on)))
    for place, event in enumerate(events):
        after = dict(state)
        _undone(state, event)
        another = any(state[name] != after[name] for name in TERM[:3])
        # A contract always has a number, and an agreement may have none.
        if event.action == "renew" and another and (state["number"] or not of_contract):
            at, by, ended = event.at, event.actor_hid, event.at
            waited = _as_kept("starts_on", _changed(event, "next_starts_on").get("old"))
            if waited is not None and waited == after["starts_on"]:
                # A term that had waited was written down by this change, whatever
                # else the change was for: it took effect on the day it began.
                at, by = entered(waited, place + 1)
                ended = morning(waited)
            found.append((made(state, at, by), ended))
    if not of_contract or not found:
        return [one for one, _ in found]
    # A term began when the one before it ended, and the first when the record was made.
    made_at = events[-1].at if events else clock.now()
    began = [ended for _, ended in found[1:]] + [made_at]
    return [
        _with_dates_in_force(db, one, start, zone)
        for (one, _), start in zip(found, began, strict=True)
    ]


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


def _period(own: dict[str, Any], above: dict[str, Any] | None) -> Span:
    starts_on, ends_on = own["starts_on"], own["ends_on"]
    if above is not None:
        starts_on = above["starts_on"] if starts_on is None else starts_on
        ends_on = above["ends_on"] if ends_on is None else ends_on
    return Span(starts_on, ends_on)


def period(contract: Contract, day: date) -> Span:
    """Return the period of a contract that is in force on a day: the dates of its own
    term, or those of the agreement it is in where its own are blank."""
    agreement = agreement_of(contract)
    return _period(term(contract, day), term(agreement, day) if agreement is not None else None)


def last_period(contract: Contract) -> Span:
    """Return the last period of a contract that is known: that of its next term, and
    of its agreement's next term, where there is one."""
    agreement = agreement_of(contract)
    return _period(last_term(contract), last_term(agreement) if agreement is not None else None)


def span_of(starts_on: date | None, ends_on: date | None, within: Span) -> Span:
    """Return the days in force of a coverage with dates of its own, within the period
    of its contract."""
    return Span(_later(starts_on, within.starts_on), _sooner(ends_on, within.ends_on))


def span(coverage: ContractCoverage, contract: Contract, day: date) -> Span:
    """Return the days in force of a coverage, in the period that is in force on a day."""
    return span_of(coverage.starts_on, coverage.ends_on, period(contract, day))


def covers(contract: Contract, day: date) -> bool:
    """Say whether a contract covers on a day: active in both senses and in date, or
    past its period with its renewal pending."""
    if contract.record_status != "active":
        return False
    status, its = status_of(contract, day), period(contract, day)
    if status == RENEWAL_PENDING:
        return its.starts_on is None or its.starts_on <= day
    return status == ACTIVE and its.holds(day)


def in_force(coverage: ContractCoverage, contract: Contract, day: date) -> bool:
    """Say whether a coverage is in force on a day."""
    return covers(contract, day) and Span(coverage.starts_on, coverage.ends_on).holds(day)


def out_of_service(record_status: str, state: str | None) -> bool:
    """Say whether an item is out of service: retired, or in a state it has left in."""
    return record_status == "retired" or state in OUT_OF_SERVICE


def still_counts(coverage: ContractCoverage, contract: Contract, day: date) -> bool:
    """Say whether a contract still counts the item of a coverage once it is out of
    service: the cover goes on past today, or it was ended because the item left, in
    a term of the contract that still runs. `left_while_running` is the same test as
    SQL."""
    if in_force(coverage, contract, day) and (coverage.ends_on is None or day < coverage.ends_on):
        return True
    starts_on = period(contract, day).starts_on
    return (
        coverage.left_service
        and covers(contract, day)
        and (starts_on is None or coverage.ends_on is None or coverage.ends_on >= starts_on)
    )


def lapsed(record: Any, ends_on: date | None, day: date) -> bool:
    """Say whether an agreement or a contract has lapsed: its period in force has
    ended, and it still says that it is active."""
    return (
        record.record_status != "retired"
        and status_of(record, day) == ACTIVE
        and ends_on is not None
        and ends_on < day
    )


def covered_until(found: Sequence[tuple[ContractCoverage, Contract]], day: date) -> date | None:
    """Return the last day the cover of an item runs to: of its coverages that have
    not ended, under contracts that cover or are to cover, to the end of the last term
    that is known. None when one of them names no end, and when there is none."""
    ends_: list[date] = []
    for coverage, contract in found:
        status = last_status(contract)
        if contract.record_status != "active" or status not in COVERING:
            continue
        if status == RENEWAL_PENDING:
            # Past its period, with no term to come: no day is known to end it.
            end = coverage.ends_on
        else:
            end = _sooner(coverage.ends_on, last_period(contract).ends_on)
        if end is None:
            return None
        if end >= day:
            ends_.append(end)
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


def _started(model: Any) -> ColumnElement[bool]:
    return and_(model.next_starts_on.is_not(None), model.next_starts_on <= dialect.today())


def term_value(model: Any, name: str) -> ColumnElement[Any]:
    """Return a field of the term of an agreement or a contract that is in force today."""
    own, coming = getattr(model, name), getattr(model, f"next_{name}")
    if name in ("starts_on", "ends_on"):
        return case((_started(model), coming), else_=own)
    return case((_started(model), func.coalesce(coming, own)), else_=own)


def status_value(model: Any) -> ColumnElement[Any]:
    """Return the status in force of an agreement or a contract."""
    begun = and_(model.status.in_(ENDED_BY_A_TERM), _started(model))
    return case((begun, ACTIVE), else_=model.status)


def last_status_value(model: Any) -> ColumnElement[Any]:
    """Return the status of an agreement or a contract in the last term that is known."""
    renewed = and_(model.status.in_(ENDED_BY_A_TERM), model.next_starts_on.is_not(None))
    return case((renewed, ACTIVE), else_=model.status)


def version_value(model: Any) -> ColumnElement[Any]:
    """Return the version of an agreement or a contract as it is read today."""
    return model.row_version + case((_started(model), 1), else_=0)


def _last_end(model: Any) -> ColumnElement[Any]:
    return case((model.next_starts_on.is_not(None), model.next_ends_on), else_=model.ends_on)


def _of_agreement(contract: Any, value: Any) -> ColumnElement[Any]:
    return (
        select(value)
        .where(Agreement.hid == contract.agreement_hid)
        .correlate(contract)
        .scalar_subquery()
    )


def in_force_of(contract: Any, name: str) -> ColumnElement[Any]:
    """Return what a contract has in force in one of the fields it may have from its
    agreement: its own, or the agreement's where its own is blank."""
    own = getattr(contract, name)
    if name in TERM:
        return func.coalesce(
            term_value(contract, name),
            _of_agreement(contract, term_value(Agreement, name)),
            type_=own.type,
        )
    return func.coalesce(own, _of_agreement(contract, getattr(Agreement, name)), type_=own.type)


def last_end_of(contract: Any) -> ColumnElement[Any]:
    """Return the last day of the last period of a contract that is known."""
    return func.coalesce(
        _last_end(contract),
        _of_agreement(contract, _last_end(Agreement)),
        type_=contract.ends_on.type,
    )


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
    status = status_value(contract)
    begun = or_(starts_on.is_(None), starts_on <= day)
    return and_(
        contract.record_status == "active",
        or_(
            and_(status == RENEWAL_PENDING, begun),
            and_(status == ACTIVE, begun, or_(ends_on.is_(None), ends_on >= day)),
        ),
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


def lapsed_test(model: Any, ends_on: Any) -> ColumnElement[bool]:
    """Return the test that an agreement or a contract has lapsed, given the last day
    of its period in force."""
    return and_(
        model.record_status != "retired",
        status_value(model) == ACTIVE,
        ends_on.is_not(None),
        ends_on < dialect.today(),
    )


def left_while_running(coverage: Any, contract: Any) -> ColumnElement[bool]:
    """Return the test that a coverage was ended because its item left service, in a
    term of its contract that still runs: the vendor still counts the item."""
    starts_on = in_force_of(contract, "starts_on")
    return and_(
        coverage.left_service.is_(True),
        contract_covers(contract),
        or_(starts_on.is_(None), coverage.ends_on.is_(None), coverage.ends_on >= starts_on),
    )


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
    records.checked_span(starts_on, ends_on, field)
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
    its = period(contract, today(db))
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
            contract_hid=contract.hid,
            item_hid=item.hid,
            starts_on=starts_on,
            ends_on=ends_on,
            left_service=bool(entry.get("left_service")),
        )
        # What is not so is not said: a coverage that began as any other says nothing
        # of an item that left.
        told = COVERAGE_FIELDS if coverage.left_service else COVERAGE_FIELDS[:-1]
        records.created(db, context, COVERAGE_TYPE, coverage, told)
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
    """Change the days of a coverage. It is ended by giving it `ends_on`. Clearing
    `left_service` says that the vendor has been told the item has left."""
    dialect.hold_other_writers(db)
    coverage = get_coverage(db, contract_hid, coverage_hid)
    contract = get_contract(db, contract_hid)
    for name in ("contract_hid", "item_hid"):
        if name in fields and fields[name] != getattr(coverage, name):
            raise Invalid(
                "a coverage stays with its contract and its item",
                {name: "end this coverage and add the other"},
            )
    its = period(contract, today(db))
    values: dict[str, Any] = {
        name: _own(records.checked_day(name, fields[name]), getattr(its, name))
        for name in ("starts_on", "ends_on")
        if name in fields
    }
    moved = any(values[name] != getattr(coverage, name) for name in values)
    if "left_service" in fields:
        values["left_service"] = bool(fields["left_service"])
    # What says nothing new is not a change, and is not refused: a file of coverage
    # that is loaded back as it was exported holds those of retired contracts too.
    changes = any(values[name] != getattr(coverage, name) for name in values)
    if changes and contract.record_status == "retired":
        raise Invalid("the contract is retired", {"contract_hid": "bring the contract back first"})
    if moved:
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


def remove_coverage(
    db: Session, context: AuditContext, contract_hid: str, coverage_hid: str
) -> None:
    """Remove a coverage that was a mistake. The audit event of the removal holds what
    it was. A coverage that was true for a time is ended with a date instead."""
    dialect.hold_other_writers(db)
    _removed(db, context, get_coverage(db, contract_hid, coverage_hid))


def _removed(db: Session, context: AuditContext, coverage: ContractCoverage) -> None:
    audit.record(
        db,
        context,
        "delete",
        COVERAGE_TYPE,
        coverage.hid,
        [
            change(name, records.jsonable(getattr(coverage, name)), None)
            for name in COVERAGE_FIELDS
            if getattr(coverage, name) not in (None, False)
        ],
    )
    db.delete(coverage)
    db.flush()


def end_for_item(db: Session, context: AuditContext, item_hid: str) -> None:
    """End today every coverage of an item that has not ended, because the item has
    left service: it was retired, released or archived. Each is marked as ended so,
    since the vendor still counts the item until somebody says otherwise. A coverage
    that had not begun never was in force: it is removed, as one made by mistake is,
    and the audit event of the removal holds what it was."""
    day = today(db)
    standing = db.execute(
        select(ContractCoverage, Contract)
        .join(Contract, Contract.hid == ContractCoverage.contract_hid)
        .where(
            ContractCoverage.item_hid == item_hid,
            or_(ContractCoverage.ends_on.is_(None), ContractCoverage.ends_on > day),
        )
    ).all()
    for coverage, contract in standing:
        begins = span(coverage, contract, day).starts_on
        if begins is not None and begins > day:
            _removed(db, context, coverage)
        else:
            records.apply(
                db, context, COVERAGE_TYPE, coverage, None, {"ends_on": day, "left_service": True}
            )
