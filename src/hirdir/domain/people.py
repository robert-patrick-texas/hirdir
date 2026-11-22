"""A person: the user, the contact and the operators that are one person's (P-291).

A user names its contact and an operator names its contact, so the contact is what
joins them, and no field holds the link. An agent names the user answerable for it
(P-316), so the agents of a person are linked to its user. This module says what is
linked to a record, and holds the one function that carries out a retirement with what
it says of the linked records, and the one that brings a user back. The change of each
record is its own module's: `accounts`, `contacts` and `operators`.

A retirement is judged whole before anything of it is written: who asks, what is said
of what, and what is left unsaid. Then the operators are changed, then the agents, then
the user, then the contact, so that at no step a contact is retired under an account or
a label that stands on it, nor a person under an agent answerable to them. All of it is
in the transaction of the request, and a refusal at any step undoes the whole.
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
# And of an agent of the user retired: retired with it, or handed to another person.
AGENT_ACTIONS = (RETIRE, HAND_OVER)
BRING_BACK = "bring_back"
# What a refusal asks to be said of a linked record, in the words of the documentation
# and not in the values the API takes.
EACH = "retire it or keep it"
EACH_OPERATOR = "retire it, keep it, leave it open or hand it over"
EACH_AGENT = "retire it or hand it to another person"


@dataclass(frozen=True)
class Person:
    """The records of one person: the user whose contact it is, a retired one too, the
    contact, every operator of that contact, in the order of their labels, and every
    agent answerable to the user, by username (P-316)."""

    user: User | None
    contact: Contact | None
    operators: list[Operator]
    agents: list[User] = field(default_factory=list)


def _agents(db: Session, user: User | None) -> list[User]:
    """Return the agents answerable to a user, the retired among them, by username."""
    return accounts.agents_of(db, [user])[user.hid] if user is not None else []


def _around(db: Session, contact: Contact) -> Person:
    """Return the person a contact is."""
    user = db.scalar(select(User).where(User.contact_hid == contact.hid))
    return Person(
        user, contact, contacts.operators_of(db, [contact.hid])[contact.hid], _agents(db, user)
    )


def of_contact(db: Session, hid: str) -> Person:
    """Return the person a contact is: itself, its user and its operators."""
    return _around(db, contacts.get_contact(db, hid))


def of_user(db: Session, hid: str) -> Person:
    """Return the person a user is. A user with no contact is itself alone."""
    user = accounts.get_user(db, hid)
    if user.contact_hid is None:
        return Person(user, None, [], _agents(db, user))
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
    record, the operators first, then the user, then the contact, then the agents: all
    but the one `but` names by its kind and its HID."""
    found = [Existing(OPERATOR, one.hid, one.label) for one in person.operators if _standing(one)]
    if person.user is not None and _standing(person.user):
        found.append(Existing(USER, person.user.hid, person.user.username))
    if person.contact is not None and _standing(person.contact):
        found.append(Existing(CONTACT, person.contact.hid, person.contact.name))
    found += [Existing(USER, one.hid, one.username) for one in person.agents if _standing(one)]
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


@dataclass(frozen=True)
class _AgentStep:
    """What becomes of one agent of the user retired: the action, and whom it is handed
    over to (P-316)."""

    agent: User
    action: str
    user_hid: str | None = None


@dataclass
class _Plan:
    """A retirement, judged: what is done to each record of the person."""

    user: User | None = None
    contact: Contact | None = None
    steps: list[_Step] = field(default_factory=list)
    agents: list[_AgentStep] = field(default_factory=list)


def _said(linked: Mapping[str, Any] | None) -> tuple[str | None, str | None, list[dict[str, Any]]]:
    """Return what a request says of the user, of the contact and of the operators."""
    linked = linked or {}
    return linked.get("user"), linked.get("contact"), list(linked.get("operators") or [])


def _said_of_agents(linked: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Return what a request says of the agents of the user (P-316)."""
    return list((linked or {}).get("agents") or [])


def _judged_agents(
    db: Session, person: Person, plan: _Plan, said: list[dict[str, Any]]
) -> tuple[dict[str, str], set[str]]:
    """Judge what a retirement says of the agents of the user: return what is wrong with
    it, at `linked.agents`, and the HIDs of the agents said, and add each step to the plan.

    Agents are said where the user is retired by the request, and only then: an agent
    of a user that is kept stays answerable to it (P-316).
    """
    wrong: dict[str, str] = {}
    spoken: set[str] = set()
    agents = {one.hid: one for one in person.agents}
    retired_user = plan.user
    for entry in said:
        one = agents.get(entry.get("hid") or "")
        action, to = entry.get("action"), entry.get("user_hid") or None
        if retired_user is None:
            problem = "agents are said only where the user they are answerable to is retired"
        elif one is None:
            problem = _no_such_agent(db, entry.get("hid"))
        elif one.hid in spoken:
            problem = f"the agent {one.username} is said twice"
        elif not _standing(one):
            problem = f"the agent {one.username} is retired already"
        elif action not in AGENT_ACTIONS:
            problem = f"say what becomes of the agent {one.username}: {EACH_AGENT}"
        elif action == HAND_OVER and to is None:
            problem = f"the agent {one.username} is handed over to a person: say which"
        elif action != HAND_OVER and to is not None:
            problem = f"the agent {one.username}: a person is named only where it is handed over"
        elif action == HAND_OVER and to == retired_user.hid:
            problem = (
                f"the agent {one.username} is handed over to another person, not to the one retired"
            )
        else:
            problem = _not_to_person(db, one, to) if action == HAND_OVER else None
        if one is not None:
            spoken.add(one.hid)
        if problem is not None:
            wrong.setdefault("linked.agents", problem)
        elif one is not None:
            plan.agents.append(_AgentStep(one, str(action), to))
    return wrong, spoken


def _no_such_agent(db: Session, hid: Any) -> str:
    """Say of an agent that a plan names and the user has not, why it is refused: by its
    username where it is an account, and as it was sent where it is none."""
    known = db.get(User, hid) if isinstance(hid, str) and hid else None
    if known is None:
        return f"there is no agent {hid}"
    if not accounts.is_agent(known):
        return f"{known.username} is no agent"
    return f"the agent {known.username} is not answerable to this user"


def _not_to_person(db: Session, agent: User, hid: str | None) -> str | None:
    """Say why an agent is not handed over to a user, or nothing where it may be: to a
    person who is not retired (P-316)."""
    other = db.get(User, hid) if hid else None
    if other is None:
        return f"the agent {agent.username}: there is no user {hid}"
    if not accounts.is_person(other):
        return (
            f"the agent {agent.username}: {other.username} is "
            f"{accounts.KIND_WORDS[other.kind]}, and an agent is answerable to a person"
        )
    if other.record_status == RETIRED:
        return f"the agent {agent.username}: the account {other.username} is retired"
    return None


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
            wrong["linked.user"] = "this is the user being retired: nothing is said of it here"
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
            wrong["linked.contact"] = (
                "this is the contact being retired: nothing is said of it here"
            )
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
            problem = _no_such(db, entry.get("hid"), "is not linked to this record")
        elif (OPERATOR, one.hid) == target:
            problem = f"{one.label} is the operator being retired: nothing is said of it here"
        elif one.hid in spoken:
            problem = f"the operator {one.label} is said twice"
        elif not _standing(one):
            problem = f"the operator {one.label} is retired already"
        elif action not in OPERATOR_ACTIONS:
            problem = f"say what becomes of the operator {one.label}: {EACH_OPERATOR}"
        elif action == HAND_OVER and to is None:
            problem = f"the operator {one.label} is handed over to a contact: say which"
        elif action != HAND_OVER and to is not None:
            problem = f"the operator {one.label}: a contact is named only where it is handed over"
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
    wrong_of_agents, spoken_agents = _judged_agents(db, person, plan, _said_of_agents(linked))
    wrong.update(wrong_of_agents)
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
        which = f"the operator {labels}" if len(quiet) == 1 else f"each of the operators {labels}"
        unsaid["linked.operators"] = f"say what becomes of {which}: {EACH_OPERATOR}"
        left += [Existing(OPERATOR, one.hid, one.label) for one in quiet]
    if kind != USER and user is not None and _standing(user) and of_user_ is None:
        unsaid["linked.user"] = f"say what becomes of the user {user.username}: {EACH}"
        left.append(Existing(USER, user.hid, user.username))
    if kind != CONTACT and contact is not None and _standing(contact) and of_contact_ is None:
        unsaid["linked.contact"] = f"say what becomes of the contact {contact.name}: {EACH}"
        left.append(Existing(CONTACT, contact.hid, contact.name))
    # The agents of the user retired, each said: retired with it, or handed over (P-316).
    quiet_agents = [one for one in person.agents if _standing(one) and one.hid not in spoken_agents]
    if plan.user is not None and quiet_agents:
        names = ", ".join(one.username for one in quiet_agents)
        which = f"the agent {names}" if len(quiet_agents) == 1 else f"each of the agents {names}"
        unsaid["linked.agents"] = f"say what becomes of {which}: {EACH_AGENT}"
        left += [Existing(USER, one.hid, one.username) for one in quiet_agents]
    if left:
        agent_hids = {one.hid for one in person.agents}
        raise Conflict(
            "records are linked to this one, and it is not said what becomes of each: "
            + ", ".join(
                f"the {'agent' if one.hid in agent_hids else one.record_type} {one.label}"
                for one in left
            ),
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


def _no_such(db: Session, hid: Any, why: str) -> str:
    """Say of an operator that a plan names and the person has not, why it is refused: by
    its label where it is an operator, another's or nobody's, so that a person reads who
    is meant, and as it was sent where it is no operator at all."""
    known = db.get(Operator, hid) if isinstance(hid, str) and hid else None
    if known is None:
        return f"there is no operator {hid}"
    return f"the operator {known.label} {why}"


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
                    f"this {kind} is retired already: each record that is linked to it "
                    "is retired by itself"
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
    # The agents before the user, so that no agent is answerable to a retired person at
    # any step; each as its own route does it (P-316).
    for agent_step in plan.agents:
        if agent_step.action == RETIRE:
            accounts.retire_user(db, context, agent_step.agent.hid, None)
        else:
            accounts.update_user(
                db, context, agent_step.agent.hid, None, {"answerable_hid": agent_step.user_hid}
            )
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
    asker: Role | None,
    hid: str,
    row_version: int | None,
    linked: Mapping[str, Any] | None = None,
    *,
    role: str | None = None,
    answerable_hid: str | None = None,
) -> BroughtBack:
    """Bring a retired user back, with what `linked` says is brought back with it (P-298),
    and the role it is given, `role`, granted in the same change (P-299). `asker` is the
    role of whoever asks: it is an Admin's.

    A person is given a role, since an account with none does not sign in: none is a
    refusal at `role`, before anything else is judged. A service account and an agent
    may be brought back with none, and an agent is never Admin. An agent stays answerable
    to its person, or to `answerable_hid` where it is given: where its person is retired,
    another is named, or the request is a `409` that names the person (P-316).

    An account does not stand on a retired contact: the contact of the user, where it is
    retired, is brought back with it, or the request is refused with the contact named.
    The operators of that contact that are retired are brought back where they are
    said, and none need be. The contact first, then the operators, then the user: each
    is changed by its own module and audited as if it were done by itself.
    """
    if asker is not Role.ADMIN:
        raise NotAllowed("an Admin brings a retired user back: this needs the admin role")
    dialect.hold_other_writers(db)
    person = of_user(db, hid)
    user, contact = accounts.get_user(db, hid), person.contact
    if user.record_status != RETIRED:
        raise Conflict(f"the account {user.username} is not retired")
    granted = accounts.checked_role(role, user.kind, user.username)
    if granted is None and accounts.is_person(user):
        raise Invalid(accounts.NO_ROLE_BACK, {"role": "give the role the account is to hold"})
    if answerable_hid and not accounts.is_agent(user):
        raise Invalid(
            f"{user.username} is {accounts.KIND_WORDS[user.kind]}, answerable to nobody: an "
            "agent alone is answerable to a person",
            {"answerable_hid": "an agent alone is answerable to a person"},
        )
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
            problem = _no_such(db, entry.get("hid"), "is not of this user's contact")
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
                "linked.contact": "an account does not stand on a retired contact: bring "
                f"{contact.name} back with it, or take the contact off the user first"
            },
            Existing(CONTACT, contact.hid, contact.name),
        )
    if accounts.is_agent(user) and answerable_hid:
        # The person named is held to what a hand-over is, before anything is written,
        # the one the agent was answerable to too: a person who is not retired (P-316).
        accounts.checked_answerable(db, answerable_hid)
    if accounts.is_agent(user) and not answerable_hid:
        person = db.get(User, user.answerable_hid) if user.answerable_hid else None
        if person is None or not _standing(person):
            whom = person.username if person is not None else "nobody"
            raise Conflict(
                f"the agent {user.username} is answerable to {whom}, who is retired: name "
                "another person to bring it back",
                {"answerable_hid": "the person of this agent is retired: name another"},
                Existing(USER, person.hid, person.username) if person is not None else None,
            )
    if with_contact and contact is not None:
        contacts.update_contact(db, context, contact.hid, None, {"record_status": "active"}, asker)
    for one in back:
        operators.update_operator(db, context, one.hid, None, {"record_status": "active"}, asker)
    returned, code = accounts.bring_back_user(db, context, hid, row_version)
    if answerable_hid and answerable_hid != returned.answerable_hid:
        accounts.update_user(db, context, returned.hid, None, {"answerable_hid": answerable_hid})
    if granted is not None:
        accounts.grant_role(db, context, role=granted, user_hid=returned.hid)
    return BroughtBack(returned, code)
