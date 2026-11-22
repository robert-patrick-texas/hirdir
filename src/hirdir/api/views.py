"""Turning records into the shapes the API returns."""

from collections.abc import Sequence
from dataclasses import asdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from hirdir import clock
from hirdir.api import schemas
from hirdir.auth.roles import highest
from hirdir.db.models import AuditEvent, Contact, Operator, RoleGrant, User, UserGroup
from hirdir.domain import accounts, contacts, load, operators, profile
from hirdir.domain.people import Person
from hirdir.io.measures import Host


def person_ref(contact: Contact | None) -> schemas.PersonRef | None:
    """Return the contact a user is, as the user shows it."""
    if contact is None:
        return None
    return schemas.PersonRef(
        hid=contact.hid,
        name=contact.name,
        email=contact.email,
        phone=contact.phone,
        phone2=contact.phone2,
        record_status=contact.record_status,
    )


def operator_brief(operator: Operator) -> schemas.OperatorBrief:
    """Return an operator as a user and a contact name it (P-280)."""
    return schemas.OperatorBrief.model_validate(operator)


def user_out(db: Session, user: User) -> schemas.UserOut:
    """Return one user, as `users_out` returns each of a page."""
    return users_out(db, [user])[0]


def me_out(db: Session, user: User) -> schemas.MeOut:
    """Return the signed-in user as it reads itself, by `GET /auth/me`, by the routes
    under it and in the answer of signing in: with the contact it is and the operators
    it is behind, each with the version it is changed at (P-294), and with no notes,
    for anybody, an Admin too. The notes on an account are an Admin's, read by the
    routes of users alone (P-281). The record status of the user is left out: it is
    signed in, and so is not retired (P-296)."""
    base = user_out(db, user)
    contact = profile.contact_of(db, user)
    return schemas.MeOut(
        hid=base.hid,
        username=base.username,
        contact_hid=base.contact_hid,
        contact=schemas.OwnContact.model_validate(contact) if contact is not None else None,
        display_name=base.display_name,
        email=base.email,
        operators=[
            schemas.OwnOperator.model_validate(one) for one in profile.operators_of(db, user)
        ],
        notes=None,
        kind=base.kind,
        answerable_hid=base.answerable_hid,
        answerable=base.answerable,
        agents=base.agents,
        disabled=base.disabled,
        role=base.role,
        grants=base.grants,
        role_in_force=base.role_in_force,
        role_capped_by=base.role_capped_by,
        groups=base.groups,
        last_sign_in_at=base.last_sign_in_at,
        row_version=base.row_version,
        created_at=base.created_at,
        updated_at=base.updated_at,
    )


def account_ref(user: User, contact: Contact | None) -> schemas.AccountRef:
    """Return an account as another names it (P-316)."""
    return schemas.AccountRef.model_validate(
        {
            "hid": user.hid,
            "username": user.username,
            "name": accounts.name_of(user, contact),
            "record_status": user.record_status,
        }
    )


def users_out(db: Session, users: Sequence[User]) -> list[schemas.UserOut]:
    """Return users with the role and groups each holds right now and where each role
    comes from (P-307), the contact each is, whose name and email are the contact's, read
    now (P-172), the operators each works as (P-280), and the person an agent is
    answerable to and the agents of a person, with the role an agent is held to
    (P-316). Each of these is read once for them all, never for a row."""
    persons = accounts.answerable_of(db, users)
    agents = accounts.agents_of(db, users)
    people = accounts.contacts_of(db, [*users, *persons.values()])
    behind = accounts.operators_of(db, users)
    grants = accounts.grants_of(db, users)
    forces = accounts.in_force(db, users, grants)
    groups = accounts.groups_of_users(db, users)
    out = []
    for user in users:
        contact = people.get(user.contact_hid or "")
        role = highest(one.grant.role for one in grants[user.hid])
        force = forces[user.hid]
        person = persons.get(user.answerable_hid or "")
        # The record status is read as the model has it, and checked against the shape's
        # own list.
        out.append(
            schemas.UserOut.model_validate(
                {
                    "hid": user.hid,
                    "username": user.username,
                    "contact_hid": user.contact_hid,
                    "contact": person_ref(contact),
                    "display_name": contact.name if contact is not None else "",
                    "email": (contact.email or "") if contact is not None else "",
                    "operators": [operator_brief(one) for one in behind[user.hid]],
                    "notes": user.notes,
                    "kind": user.kind,
                    "answerable_hid": user.answerable_hid,
                    "answerable": account_ref(person, people.get(person.contact_hid or ""))
                    if person is not None
                    else None,
                    "agents": [account_ref(one, None) for one in agents[user.hid]],
                    "disabled": user.disabled,
                    "record_status": user.record_status,
                    "role": role.value if role else None,
                    "grants": [
                        {
                            "hid": one.grant.hid,
                            "role": one.grant.role,
                            "group": {"hid": one.group.hid, "name": one.group.name}
                            if one.group is not None
                            else None,
                        }
                        for one in grants[user.hid]
                    ],
                    "role_in_force": force.role.value if force.role else None,
                    "role_capped_by": force.capped_by,
                    "groups": [schemas.GroupRef(hid=g.hid, name=g.name) for g in groups[user.hid]],
                    "last_sign_in_at": user.last_sign_in_at,
                    "row_version": user.row_version,
                    "created_at": user.created_at,
                    "updated_at": user.updated_at,
                }
            )
        )
    return out


def person_out(db: Session, person: Person) -> schemas.Person:
    """Return the person a record belongs to, as the chain of the three shows it: the
    user, the contact and the operators, the retired among them, with how much names
    the contact and each operator (P-297)."""
    user, contact = person.user, person.contact
    roles = accounts.roles_of(db, [*([user] if user is not None else []), *person.agents])
    role = roles[user.hid] if user is not None else None
    named = contacts.uses(db, [contact.hid])[contact.hid] if contact is not None else 0
    given = operators.uses(db, [one.hid for one in person.operators])
    return schemas.Person.model_validate(
        {
            "user": None
            if user is None
            else {
                "hid": user.hid,
                "username": user.username,
                "record_status": user.record_status,
                "disabled": user.disabled,
                "role": role.value if role else None,
            },
            "contact": None
            if contact is None
            else {
                "hid": contact.hid,
                "name": contact.name,
                "email": contact.email,
                "record_status": contact.record_status,
                "uses": named,
            },
            "operators": [
                {
                    "hid": one.hid,
                    "label": one.label,
                    "colour": one.colour,
                    "record_status": one.record_status,
                    "uses": given[one.hid],
                }
                for one in person.operators
            ],
            "agents": [
                {
                    "hid": one.hid,
                    "username": one.username,
                    "record_status": one.record_status,
                    "disabled": one.disabled,
                    "role": held.value if (held := roles[one.hid]) else None,
                }
                for one in person.agents
            ],
        }
    )


def _group_fields(group: UserGroup, member_count: int, roles: list[str]) -> dict:
    return {
        "hid": group.hid,
        "name": group.name,
        "description": group.description,
        "member_count": member_count,
        "roles": roles,
        "row_version": group.row_version,
        "created_at": group.created_at,
        "updated_at": group.updated_at,
    }


def group_out(db: Session, group: UserGroup) -> schemas.GroupOut:
    """Return one group, as `groups_out` returns each."""
    return groups_out(db, [group])[0]


def groups_out(db: Session, groups: Sequence[UserGroup]) -> list[schemas.GroupOut]:
    """Return groups with the size of each and the roles granted to it, each read once
    for them all."""
    sizes, roles = accounts.sizes_of(db, groups), accounts.roles_of_groups(db, groups)
    return [
        schemas.GroupOut(**_group_fields(group, sizes[group.hid], roles[group.hid]))
        for group in groups
    ]


def group_detail(db: Session, group: UserGroup) -> schemas.GroupDetail:
    """Return group with its members."""
    members = accounts.members_of(db, group)
    return schemas.GroupDetail(
        **_group_fields(group, len(members), accounts.roles_of_groups(db, [group])[group.hid]),
        members=users_out(db, members),
    )


def grant_out(db: Session, grant: RoleGrant) -> schemas.GrantOut:
    """Return grant with the name of the user or group it is made to."""
    if grant.user_hid:
        user = db.get(User, grant.user_hid)
        name = user.username if user else ""
    else:
        group = db.get(UserGroup, grant.group_hid)
        name = group.name if group else ""
    return schemas.GrantOut(
        hid=grant.hid,
        role=grant.role,
        user_hid=grant.user_hid,
        group_hid=grant.group_hid,
        target_name=name,
        created_at=grant.created_at,
    )


def audit_out(db: Session, event: AuditEvent) -> schemas.AuditEventOut:
    """Return one event, as `audit_events_out` returns each."""
    return audit_events_out(db, [event])[0]


def audit_events_out(db: Session, events: Sequence[AuditEvent]) -> list[schemas.AuditEventOut]:
    """Return events with the username and the kind of whoever caused each, and of an
    agent's, the username of the person it was answerable to (P-316): every account they
    name is read in one statement for them all."""
    hids = {hid for event in events for hid in (event.actor_hid, event.for_hid) if hid}
    known = (
        {user.hid: user for user in db.scalars(select(User).where(User.hid.in_(hids)))}
        if hids
        else {}
    )
    out = []
    for event in events:
        actor = known.get(event.actor_hid or "")
        person = known.get(event.for_hid or "")
        # The kind is read as the model has it, and checked against the shape's list.
        out.append(
            schemas.AuditEventOut.model_validate(
                {
                    "hid": event.hid,
                    "at": event.at,
                    "actor_hid": event.actor_hid,
                    "actor_name": actor.username if actor else None,
                    "actor_kind": actor.kind if actor else None,
                    "for_hid": event.for_hid,
                    "for_name": person.username if person else None,
                    "via": event.via,
                    "request_id": event.request_id,
                    "action": event.action,
                    "record_type": event.record_type,
                    "record_hid": event.record_hid,
                    "changes": event.changes,
                }
            )
        )
    return out


def _tenth(value: float | None) -> float | None:
    """Return a time or a share to a tenth, which is as much as either says."""
    return None if value is None else round(value, 1)


def _hundredth(value: float | None) -> float | None:
    return None if value is None else round(value, 2)


def _spread(spread: load.Spread) -> schemas.LoadSpread:
    return schemas.LoadSpread(
        low=_tenth(spread.low), average=_tenth(spread.average), high=_tenth(spread.high)
    )


def _slow(one: load.Slow) -> schemas.LoadSlow:
    who = one.who
    return schemas.LoadSlow(
        at=one.at,
        method=one.method,
        route=one.route,
        ms=round(one.ms, 1),
        status=one.status,
        request_id=one.request_id,
        who=schemas.LoadWho(
            kind=load.kind_of(who.kind),
            hid=who.hid,
            username=who.username,
        )
        if who is not None
        else schemas.LoadWho(kind=load.UNNAMED, hid=None, username=None),
    )


def load_out(picture: load.Picture, host: Host, worker: Any) -> schemas.Load:
    """Return the server's own measures as its meter gives them, with what the host
    says of itself and whether the background work is being done."""
    reading, points = picture.reading, picture.points
    said = asdict(host)
    return schemas.Load(
        health=reading.health,
        because=list(reading.because),
        refusing=reading.refusing,
        ceiling=schemas.LoadCeiling(
            response_ms=picture.ceiling.response_ms,
            cpu_percent=picture.ceiling.cpu_percent,
            over_seconds=picture.ceiling.over_seconds,
            fewest_requests=load.FEWEST_REQUESTS,
        ),
        measures=schemas.LoadMeasures(
            response_ms=_tenth(reading.response_ms),
            requests=reading.requests,
            reads_ms=_tenth(reading.reads_ms),
            reads=reading.reads,
            cpu_percent=round(reading.cpu_percent, 1),
        ),
        window_seconds=load.WINDOW_SECONDS,
        step_seconds=load.STEP_SECONDS,
        started_at=picture.started_at,
        at=clock.now(),
        totals=schemas.LoadTotals(
            requests=picture.requests,
            ok=picture.ok,
            not_accepted=picture.not_accepted,
            failed=picture.failed,
            busy=picture.busy,
            response_ms=schemas.LoadTimes(
                low=_tenth(picture.response_ms.low),
                average=_tenth(picture.response_ms.average),
                high=_tenth(picture.response_ms.high),
                p50=_tenth(picture.percentiles.p50),
                p95=_tenth(picture.percentiles.p95),
                p99=_tenth(picture.percentiles.p99),
            ),
            bands=schemas.LoadBands(
                bounds_ms=[round(bound, 1) for bound in picture.bounds_ms],
                counts=list(picture.bands),
            ),
            cpu_percent=_spread(picture.cpu_percent),
        ),
        in_flight=schemas.LoadInFlight(
            count=picture.in_flight, oldest_ms=_tenth(picture.oldest_ms)
        ),
        process=schemas.LoadProcess(memory_bytes=said.pop("process_memory_bytes")),
        host=schemas.LoadHost(**{**said, "load_1m": _hundredth(said["load_1m"])}),
        worker=worker,
        points=schemas.LoadPoints(
            at=points.at,
            requests=points.requests,
            average_ms=[_tenth(value) for value in points.average_ms],
            high_ms=[_tenth(value) for value in points.high_ms],
            p50_ms=[_tenth(value) for value in points.p50_ms],
            p95_ms=[_tenth(value) for value in points.p95_ms],
            cpu_percent=[_tenth(value) for value in points.cpu_percent],
            busy=points.busy,
        ),
        slowest=[_slow(one) for one in picture.slowest],
        slowest_long=[_slow(one) for one in picture.slowest_long],
        people=[
            schemas.LoadPerson(
                kind=one.kind,
                hid=one.hid,
                username=one.username,
                requests=one.requests,
                bands=list(one.bands),
                slowest_ms=_tenth(one.slowest_ms),
                busy=one.busy,
                failed=one.failed,
                last_at=one.last_at,
            )
            for one in picture.people
        ],
    )
