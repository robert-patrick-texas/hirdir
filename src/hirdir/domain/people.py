"""A person: the user, the contact and the operators that are one person's (P-291).

A user names its contact and an operator names its contact, so the contact is what
joins them, and no field holds the link. This module says what is linked to a record,
and holds the one function that carries out a retirement with what it says of the
linked records, and the one that brings a user back. The change of each record is its
own module's: `accounts`, `contacts` and `operators`.

A retirement is judged whole before anything of it is written: who asks, what is said
of what, and what is left unsaid. Then the operators are changed, then the user, then
the contact, so that at no step a contact is retired under an account or a label that
stands on it. All of it is in the transaction of the request, and a refusal at any
step undoes the whole.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from hirdir.auth.roles import Role
from hirdir.db import dialect
from hirdir.db.models import Contact, Operator, User
from hirdir.domain import accounts, contacts, operators
from hirdir.domain.audit import AuditContext
from hirdir.domain.errors import Conflict, Existing, Invalid, NotAllowed, StaleVersion

USER = "user"
CONTACT = contacts.RECORD_TYPE
OPERATOR = operators.RECORD_TYPE
RETIRED = "retired"
# What a retirement says of a linked user and of a linked contact.
RETIRE, KEEP = "retire", "keep"
# And of a linked operator, beside those two: the label left with nobody behind it, or
# given to another contact.
OPEN, HAND_OVER = "open", "hand_over"
OPERATOR_ACTIONS = (RETIRE, KEEP, OPEN, HAND_OVER)
BRING_BACK = "bring_back"


@dataclass(frozen=True)
class Person:
    """The records of one person: the user whose contact it is, a retired one too, the
    contact, and every operator of that contact, in the order of their labels."""

    user: User | None
    contact: Contact | None
    operators: list[Operator]


def _around(db: Session, contact: Contact) -> Person:
    """Return the person a contact is."""
    user = db.scalar(select(User).where(User.contact_hid == contact.hid))
    return Person(user, contact, contacts.operators_of(db, [contact.hid])[contact.hid])


def of_contact(db: Session, hid: str) -> Person:
    """Return the person a contact is: itself, its user and its operators."""
    return _around(db, contacts.get_contact(db, hid))


def of_user(db: Session, hid: str) -> Person:
    """Return the person a user is. A user with no contact is itself alone."""
    user = accounts.get_user(db, hid)
    if user.contact_hid is None:
        return Person(user, None, [])
    return _around(db, contacts.get_contact(db, user.contact_hid))


def of_operator(db: Session, hid: str) -> Person:
    """Return the person behind an operator. An operator with no contact is itself alone."""
    operator = operators.get_operator(db, hid)
    if operator.contact_hid is None:
        return Person(None, None, [operator])
    return _around(db, contacts.get_contact(db, operator.contact_hid))


# The person of a record of each of the three kinds.
OF = {USER: of_user, CONTACT: of_contact, OPERATOR: of_operator}


def _standing(record: Any | None) -> bool:
    """Say whether a record is there and is not retired."""
    return record is not None and record.record_status != RETIRED


def named(person: Person, but: tuple[str, str] | None = None) -> list[Existing]:
    """Return the records of a person that are not retired, each as a refusal names a
    record, the operators first, then the user, then the contact: all but the one `but`
    names by its kind and its HID."""
    found = [Existing(OPERATOR, one.hid, one.label) for one in person.operators if _standing(one)]
    if person.user is not None and _standing(person.user):
        found.append(Existing(USER, person.user.hid, person.user.username))
    if person.contact is not None and _standing(person.contact):
        found.append(Existing(CONTACT, person.contact.hid, person.contact.name))
    return [one for one in found if (one.record_type, one.hid) != but]


def linked_to(db: Session, kind: str, hid: str) -> list[Existing]:
    """Return the records linked to one that are not retired: what a retirement of it
    is to say something of (P-297)."""
    return named(OF[kind](db, hid), (kind, hid))


# --- a retirement ----------------------------------------------------------------------


@dataclass(frozen=True)
class _Step:
    """What becomes of one operator: the action, and whom it is handed over to."""

    operator: Operator
    action: str
    contact_hid: str | None = None


@dataclass
class _Plan:
    """A retirement, judged: what is done to each record of the person."""

    user: User | None = None
    contact: Contact | None = None
    steps: list[_Step] = field(default_factory=list)


def _said(linked: Mapping[str, Any] | None) -> tuple[str | None, str | None, list[dict[str, Any]]]:
    """Return what a request says of the user, of the contact and of the operators."""
    linked = linked or {}
    return linked.get("user"), linked.get("contact"), list(linked.get("operators") or [])


def _judged(
    db: Session,
    role: Role | None,
    kind: str,
    hid: str,
    person: Person,
    linked: Mapping[str, Any] | None,
) -> _Plan:
    """Return what a retirement does, or refuse it: nothing is written here.

    In this order: what is said of a record that is not linked, or is retired already,
    or is the record itself, a `422`; a user retired by somebody who is no Admin, a
    `403`; a linked record that is not retired and is not said, a `409` that names
    each; and a contact retired while its account or a label is kept on it, a `422`.
    """
    user, contact = person.user, person.contact
    of_user_, of_contact_, of_operators = _said(linked)
    wrong: dict[str, str] = {}
    plan = _Plan()
    target = (kind, hid)

    # The user.
    if kind == USER:
        plan.user = user
        if of_user_ is not None:
            wrong["linked.user"] = "the route is on this user: it is retired, and is not said"
    elif of_user_ is not None:
        if user is None:
            wrong["linked.user"] = "no user is linked to this record"
        elif not _standing(user):
            wrong["linked.user"] = f"the account {user.username} is retired already"
        elif of_user_ == RETIRE:
            plan.user = user

    # The contact.
    if kind == CONTACT:
        plan.contact = contact
        if of_contact_ is not None:
            wrong["linked.contact"] = "the route is on this contact: it is retired, and is not said"
    elif of_contact_ is not None:
        if contact is None:
            wrong["linked.contact"] = "no contact is linked to this record"
        elif not _standing(contact):
            wrong["linked.contact"] = f"the contact {contact.name} is retired already"
        elif of_contact_ == RETIRE:
            plan.contact = contact

    # The operators.
    behind = {one.hid: one for one in person.operators}
    spoken: set[str] = set()
    if kind == OPERATOR:
        plan.steps.append(_Step(behind[hid], RETIRE))
    for entry in of_operators:
        one = behind.get(entry.get("hid") or "")
        action, to = entry.get("action"), entry.get("contact_hid") or None
        if one is None:
            problem = f"the operator {entry.get('hid')} is not linked to this record"
        elif (OPERATOR, one.hid) == target:
            problem = f"the route is on the operator {one.label}: it is retired, and is not said"
        elif one.hid in spoken:
            problem = f"the operator {one.label} is said twice"
        elif not _standing(one):
            problem = f"the operator {one.label} is retired already"
        elif action not in OPERATOR_ACTIONS:
            problem = f"the operator {one.label}: retire, keep, open or hand_over"
        elif action == HAND_OVER and to is None:
            problem = f"the operator {one.label}: hand_over names the contact it goes to"
        elif action != HAND_OVER and to is not None:
            problem = f"the operator {one.label}: contact_hid goes with hand_over alone"
        elif action == HAND_OVER and contact is not None and to == contact.hid:
            problem = f"the operator {one.label} is handed over to another contact, not to its own"
        else:
            problem = _not_to(db, one, to) if action == HAND_OVER else None
        if one is not None:
            spoken.add(one.hid)
        if problem is not None:
            wrong.setdefault("linked.operators", problem)
        elif one is not None and action != KEEP:
            plan.steps.append(_Step(one, str(action), to))
    if wrong:
        raise Invalid("what is said of the linked records is not acceptable", wrong)

    # Who may: a request that retires a user is an Admin's.
    if plan.user is not None and role is not Role.ADMIN:
        raise NotAllowed("an Admin retires a user: this needs the admin role")

    # Every linked record that is not retired is said.
    unsaid: dict[str, str] = {}
    left: list[Existing] = []
    quiet = [
        one
        for one in person.operators
        if _standing(one) and one.hid not in spoken and (OPERATOR, one.hid) != target
    ]
    if quiet:
        labels = ", ".join(one.label for one in quiet)
        unsaid["linked.operators"] = (
            f"say what becomes of {labels}: retire, keep, open or hand_over"
        )
        left += [Existing(OPERATOR, one.hid, one.label) for one in quiet]
    if kind != USER and user is not None and _standing(user) and of_user_ is None:
        unsaid["linked.user"] = f"say what becomes of the user {user.username}: retire or keep"
        left.append(Existing(USER, user.hid, user.username))
    if kind != CONTACT and contact is not None and _standing(contact) and of_contact_ is None:
        unsaid["linked.contact"] = f"say what becomes of the contact {contact.name}: retire or keep"
        left.append(Existing(CONTACT, contact.hid, contact.name))
    if left:
        raise Conflict(
            "records are linked to this one, and the request does not say what becomes of "
            "each: " + ", ".join(f"{one.record_type} {one.label}" for one in left),
            unsaid,
            depends_on=left,
        )

    # A contact is not retired while its account or a label stands on it.
    if plan.contact is not None:
        kept: dict[str, str] = {}
        if user is not None and _standing(user) and plan.user is None:
            kept["linked.user"] = (
                f"the contact is retired, so the user {user.username} is retired with it: "
                "an account does not stand on a retired contact"
            )
        changed = {step.operator.hid for step in plan.steps}
        standing = [one for one in person.operators if _standing(one) and one.hid not in changed]
        if standing:
            labels = ", ".join(one.label for one in standing)
            kept["linked.operators"] = (
                f"the contact is retired, so {labels} is retired, opened or handed over: "
                "a label does not stand on a retired contact"
            )
        if kept:
            raise Invalid(
                "a contact is not retired while its account or a label stands on it", kept
            )
    return plan


def _fresh(record: Any, row_version: int | None) -> None:
    """Refuse a change made against a stale copy of the record a route is on."""
    if row_version is not None and record.row_version != row_version:
        raise StaleVersion(
            f"this record is at version {record.row_version}, "
            f"and the change was made against version {row_version}"
        )


def _not_to(db: Session, operator: Operator, hid: str | None) -> str | None:
    """Say why an operator is not handed over to a contact, or nothing where it may be."""
    contact = db.get(Contact, hid) if hid else None
    if contact is None:
        return f"the operator {operator.label}: there is no contact {hid}"
    if contact.record_status == RETIRED:
        return f"the operator {operator.label}: the contact {contact.name} is retired"
    return None


def retire(
    db: Session,
    context: AuditContext,
    role: Role | None,
    kind: str,
    hid: str,
    row_version: int | None,
    linked: Mapping[str, Any] | None = None,
) -> None:
    """Retire a user, a contact or an operator, and carry out what `linked` says of the
    records linked to it (P-297). `role` is the role of whoever asks.

    The writer's place is taken before anything is read, so that of two requests at the
    same moment, one that retires a contact and one that gives it to a user or puts it
    behind a label, the second sees what the first did. Each record is changed by its
    own module and audited as if it were done by itself; `row_version` is of the record
    the route is on. A contact or an operator that is retired already is left as it is,
    as before, where nothing is said of what is linked to it.
    """
    if kind != USER and (role is None or not role.allows(Role.INVENTORY)):
        raise NotAllowed("this needs the inventory role")
    dialect.hold_other_writers(db)
    person = OF[kind](db, hid)
    if kind == USER and not _standing(person.user):
        raise Conflict(f"the account {accounts.get_user(db, hid).username} is retired already")
    if kind != USER:
        own = person.contact if kind == CONTACT else operators.get_operator(db, hid)
        if own is not None and own.record_status == RETIRED:
            if any(_said(linked)):
                raise Conflict(
                    f"this {kind} is retired already: what is linked to it is retired "
                    "by its own route"
                )
            retire_one = contacts.retire_contact if kind == CONTACT else operators.retire_operator
            retire_one(db, context, hid, row_version)
            return
    plan = _judged(db, role, kind, hid, person, linked)
    # Before anything is written: the whole is refused, and not at its last step.
    _fresh(
        {USER: plan.user, CONTACT: plan.contact}.get(kind) or plan.steps[0].operator, row_version
    )

    def version(of: str, record: Any) -> int | None:
        return row_version if (of, record.hid) == (kind, hid) else None

    for step in plan.steps:
        one = step.operator
        if step.action == RETIRE:
            operators.retire_operator(db, context, one.hid, version(OPERATOR, one))
        else:
            operators.update_operator(db, context, one.hid, None, {"contact_hid": step.contact_hid})
    if plan.user is not None:
        accounts.retire_user(db, context, plan.user.hid, version(USER, plan.user))
    if plan.contact is not None:
        contacts.retire_contact(db, context, plan.contact.hid, version(CONTACT, plan.contact))


# --- bringing back ---------------------------------------------------------------------


@dataclass(frozen=True)
class BroughtBack:
    """A user brought back, with its new access code, shown this once."""

    user: User
    access_code: str | None


def bring_back(
    db: Session,
    context: AuditContext,
    role: Role | None,
    hid: str,
    row_version: int | None,
    linked: Mapping[str, Any] | None = None,
) -> BroughtBack:
    """Bring a retired user back, with what `linked` says is brought back with it (P-298).
    `role` is the role of whoever asks: it is an Admin's.

    An account does not stand on a retired contact: the contact of the user, where it is
    retired, is brought back with it, or the request is refused with the contact named.
    The operators of that contact that are retired are brought back where they are
    said, and none need be. The contact first, then the operators, then the user: each
    is changed by its own module and audited as if it were done by itself.
    """
    if role is not Role.ADMIN:
        raise NotAllowed("an Admin brings a retired user back: this needs the admin role")
    dialect.hold_other_writers(db)
    person = of_user(db, hid)
    user, contact = accounts.get_user(db, hid), person.contact
    if user.record_status != RETIRED:
        raise Conflict(f"the account {user.username} is not retired")
    linked = linked or {}
    wrong: dict[str, str] = {}
    with_contact = linked.get("contact") == BRING_BACK
    if with_contact and contact is None:
        wrong["linked.contact"] = "this user has no contact"
    elif with_contact and contact is not None and _standing(contact):
        wrong["linked.contact"] = f"the contact {contact.name} is not retired"
    behind = {one.hid: one for one in person.operators}
    back: list[Operator] = []
    for entry in linked.get("operators") or []:
        one = behind.get(entry.get("hid") or "")
        if one is None:
            problem = f"the operator {entry.get('hid')} is not of this user's contact"
        elif _standing(one):
            problem = f"the operator {one.label} is not retired"
        elif one in back:
            problem = f"the operator {one.label} is said twice"
        else:
            back.append(one)
            continue
        wrong.setdefault("linked.operators", problem)
    if wrong:
        raise Invalid("what is said of the linked records is not acceptable", wrong)
    _fresh(user, row_version)
    if contact is not None and not _standing(contact) and not with_contact:
        raise Conflict(
            f"the contact of this account, {contact.name}, is retired: bring it back "
            "with the account, or take it off the account first",
            {
                "linked.contact": "an account does not stand on a retired contact: "
                "bring_back, or take the contact off the user first"
            },
            Existing(CONTACT, contact.hid, contact.name),
        )
    if with_contact and contact is not None:
        contacts.update_contact(db, context, contact.hid, None, {"record_status": "active"}, role)
    for one in back:
        operators.update_operator(db, context, one.hid, None, {"record_status": "active"}, role)
    returned, code = accounts.bring_back_user(db, context, hid, row_version)
    return BroughtBack(returned, code)
