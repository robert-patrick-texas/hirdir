"""The contacts of an agreement and of a contract: contact records named in a role.

An agreement and a contract may name any number of account managers and support
contacts, each a contact record, beside the free text of `account_manager` and
`support_contact`, which stays as it is and is inherited by itself. For each role by
itself, a contract that names nobody of its own has those its agreement names, and one
that names anybody has its own, all of them, in place of the agreement's.

That is worked out when a record is read, for a page of records at once. Nothing is
copied down: a contact record that is changed shows its change on every record that
names it, and on every contract that has it from its agreement.
"""

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from hirdir.db import dialect
from hirdir.db.models import Agreement, Contact, Contract, ContractContact
from hirdir.domain import audit, records
from hirdir.domain.audit import AuditContext, change
from hirdir.domain.errors import Conflict, Invalid, NotFound

RECORD_TYPE = "contract_contact"
ROLES = ("account_manager", "support_contact")
# The name of each role in the `effective` block of a record: the list in force.
IN_FORCE = {"account_manager": "account_managers", "support_contact": "support_contacts"}
AGREEMENT = "agreement_hid"
CONTRACT = "contract_hid"
HOLDERS: dict[str, Any] = {AGREEMENT: Agreement, CONTRACT: Contract}
FIELDS = (AGREEMENT, CONTRACT, "role", "contact_hid", "priority")
MAX_PRIORITY = 1000

# A naming, with the contact record it names as that record is now.
Named = tuple[ContractContact, Contact]
Source = Literal["own", "agreement", "none"]


@dataclass(frozen=True)
class InForce:
    """The contacts in force for one role, and the record they came from."""

    named: list[Named]
    source: Source
    source_hid: str | None


def holder(db: Session, field: str, hid: str) -> Any:
    """Return the agreement or the contract that a naming is of."""
    found = db.get(HOLDERS[field], hid)
    if found is None:
        raise NotFound(f"there is no {_what(field)} {hid}")
    return found


def _what(field: str) -> str:
    return "agreement" if field == AGREEMENT else "contract"


def get_link(db: Session, field: str, hid: str, link_hid: str) -> ContractContact:
    """Return one naming of one agreement or contract."""
    link = db.get(ContractContact, link_hid)
    if link is None or getattr(link, field) != hid:
        raise NotFound(f"there is no contact {link_hid} of this {_what(field)}")
    return link


def named_by(db: Session, field: str, hids: Collection[str]) -> dict[str, list[Named]]:
    """Return what each of the agreements or contracts names, with the contacts: by
    role, then by priority, then by name."""
    found: dict[str, list[Named]] = {hid: [] for hid in hids}
    wanted = sorted(set(hids))
    column = getattr(ContractContact, field)
    for start in range(0, len(wanted), 500):
        rows = db.execute(
            select(ContractContact, Contact)
            .join(Contact, Contact.hid == ContractContact.contact_hid)
            .where(column.in_(wanted[start : start + 500]))
            .order_by(
                ContractContact.role,
                ContractContact.priority,
                Contact.name_key,
                ContractContact.hid,
            )
        )
        for link, contact in rows:
            found[getattr(link, field)].append((link, contact))
    return found


def resolve(
    own: Sequence[Named], above: Sequence[Named], record_hid: str, agreement_hid: str | None
) -> dict[str, InForce]:
    """Return the contacts in force for each role: the record's own where it names any,
    else its agreement's, else none. Each role is worked out by itself."""
    found: dict[str, InForce] = {}
    for role in ROLES:
        mine = [one for one in own if one[0].role == role]
        theirs = [one for one in above if one[0].role == role]
        if mine:
            found[role] = InForce(mine, "own", record_hid)
        elif agreement_hid is not None and theirs:
            found[role] = InForce(theirs, "agreement", agreement_hid)
        else:
            found[role] = InForce([], "none", None)
    return found


def of_agreements(
    db: Session, hids: Sequence[str]
) -> tuple[dict[str, list[Named]], dict[str, dict[str, InForce]]]:
    """Return what each agreement names, and what it has in force: its own, or none."""
    own = named_by(db, AGREEMENT, hids)
    return own, {hid: resolve(own[hid], (), hid, None) for hid in hids}


def of_contracts(
    db: Session, found: Sequence[Contract]
) -> tuple[dict[str, list[Named]], dict[str, dict[str, InForce]]]:
    """Return what each contract names, and what it has in force for each role: its
    own, or those of the agreement it is grouped into as it names it now."""
    own = named_by(db, CONTRACT, [contract.hid for contract in found])
    above = named_by(
        db, AGREEMENT, {contract.agreement_hid for contract in found if contract.agreement_hid}
    )
    in_force = {
        contract.hid: resolve(
            own[contract.hid],
            above.get(contract.agreement_hid or "", []),
            contract.hid,
            contract.agreement_hid,
        )
        for contract in found
    }
    return own, in_force


# --- naming and removing -------------------------------------------------------------


def _checked_role(value: Any) -> str:
    return records.checked_choice(value, ROLES, "role")


def _checked_priority(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_PRIORITY:
        raise Invalid(
            "the priority is not acceptable",
            {"priority": f"a whole number from 1, the first listed, to {MAX_PRIORITY}"},
        )
    return value


def _checked_contact(db: Session, value: Any) -> Contact:
    """Return the contact a naming is to name: one that is there and is not retired."""
    hid = value if isinstance(value, str) else ""
    contact = db.get(Contact, hid) if hid else None
    if contact is None:
        raise Invalid(
            "there is no such contact",
            {"contact_hid": f"there is no contact {hid}" if hid else "must not be blank"},
        )
    if contact.record_status == "retired":
        raise Invalid("the contact is retired", {"contact_hid": "this contact is retired"})
    return contact


def _beside(db: Session, field: str, hid: str, role: str, but: str | None) -> list[ContractContact]:
    """Return the other namings of one record in one role."""
    return list(
        db.scalars(
            select(ContractContact).where(
                getattr(ContractContact, field) == hid,
                ContractContact.role == role,
                ContractContact.hid != (but or ""),
            )
        )
    )


def _check_once(beside: list[ContractContact], contact_hid: str, field: str) -> None:
    if any(other.contact_hid == contact_hid for other in beside):
        raise Conflict(
            f"this contact is already named for this {_what(field)} in this role",
            {"contact_hid": "a contact is named once for one record and one role"},
        )


def add(
    db: Session, context: AuditContext, field: str, hid: str, fields: dict[str, Any]
) -> ContractContact:
    """Name a contact for an agreement or a contract in a role.

    Left out, its priority is one more than the highest there is for that record and
    role, so that it is listed last.
    """
    # Checked against the other namings of the record, so nobody may be changing them.
    dialect.hold_other_writers(db)
    record = holder(db, field, hid)
    if record.record_status == "retired":
        what = _what(field)
        raise Invalid(f"the {what} is retired", {field: f"this {what} is retired"})
    role = _checked_role(fields.get("role"))
    contact = _checked_contact(db, fields.get("contact_hid"))
    beside = _beside(db, field, hid, role, None)
    _check_once(beside, contact.hid, field)
    priority = (
        _checked_priority(fields["priority"])
        if fields.get("priority") is not None
        else 1 + max((other.priority for other in beside), default=0)
    )
    link = ContractContact(
        **{field: hid}, role=role, contact_hid=contact.hid, priority=min(priority, MAX_PRIORITY)
    )
    records.created(db, context, RECORD_TYPE, link, FIELDS)
    return link


def update(
    db: Session,
    context: AuditContext,
    field: str,
    hid: str,
    link_hid: str,
    row_version: int,
    fields: dict[str, Any],
) -> ContractContact:
    """Change the role, the priority or the contact of a naming. It stays with its
    record. A contact that is retired is not newly named, and stays where it is."""
    dialect.hold_other_writers(db)
    link = get_link(db, field, hid, link_hid)
    for name in HOLDERS:
        if name in fields and (fields[name] or None) != getattr(link, name):
            raise Invalid(
                f"a contact stays with its {_what(field)}",
                {name: "remove this contact and name it where it belongs"},
            )
    values: dict[str, Any] = {}
    if "role" in fields:
        values["role"] = _checked_role(fields["role"])
    if "contact_hid" in fields and fields["contact_hid"] != link.contact_hid:
        values["contact_hid"] = _checked_contact(db, fields["contact_hid"]).hid
    if fields.get("priority") is not None:
        values["priority"] = _checked_priority(fields["priority"])
    role = values.get("role", link.role)
    contact_hid = values.get("contact_hid", link.contact_hid)
    if role != link.role or contact_hid != link.contact_hid:
        _check_once(_beside(db, field, hid, role, link.hid), contact_hid, field)
    records.apply(db, context, RECORD_TYPE, link, row_version, values)
    return link


def remove(db: Session, context: AuditContext, field: str, hid: str, link_hid: str) -> None:
    """Remove a naming that was a mistake. The audit event of the removal holds what
    it was."""
    link = get_link(db, field, hid, link_hid)
    audit.record(
        db,
        context,
        "delete",
        RECORD_TYPE,
        link.hid,
        [
            change(name, getattr(link, name), None)
            for name in FIELDS
            if getattr(link, name) is not None
        ],
    )
    db.delete(link)
    db.flush()
