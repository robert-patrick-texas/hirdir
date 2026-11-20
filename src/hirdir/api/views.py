"""Turning records into the shapes the API returns."""

from dataclasses import asdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from hirdir import clock
from hirdir.api import schemas
from hirdir.db.models import AuditEvent, Contact, Operator, RoleGrant, User, UserGroup
from hirdir.domain import accounts, load
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


def user_out(
    db: Session,
    user: User,
    contact: Contact | None = None,
    operators: list[Operator] | None = None,
) -> schemas.UserOut:
    """Return user with the role and groups they hold right now, the contact it is, whose
    name and email are the contact's, read now (P-172), and the operators it works as
    (P-280). A page of users passes the contacts and the operators it read for them all."""
    role = accounts.effective_role(db, user)
    if contact is None or contact.hid != user.contact_hid:
        contact = accounts.contact_of(db, user)
    if operators is None:
        operators = accounts.operators_of(db, [user])[user.hid]
    return schemas.UserOut(
        hid=user.hid,
        username=user.username,
        contact_hid=user.contact_hid,
        contact=person_ref(contact),
        display_name=contact.name if contact is not None else "",
        email=(contact.email or "") if contact is not None else "",
        operators=[operator_brief(one) for one in operators],
        notes=user.notes,
        is_service_account=user.is_service_account,
        disabled=user.disabled,
        role=role.value if role else None,
        groups=[schemas.GroupRef(hid=g.hid, name=g.name) for g in accounts.groups_of(db, user)],
        last_sign_in_at=user.last_sign_in_at,
        row_version=user.row_version,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


def _group_fields(db: Session, group: UserGroup, member_count: int) -> dict:
    roles = db.scalars(select(RoleGrant.role).where(RoleGrant.group_hid == group.hid))
    return {
        "hid": group.hid,
        "name": group.name,
        "description": group.description,
        "member_count": member_count,
        "roles": sorted(roles),
        "row_version": group.row_version,
        "created_at": group.created_at,
        "updated_at": group.updated_at,
    }


def group_out(db: Session, group: UserGroup) -> schemas.GroupOut:
    """Return group with its size and the roles granted to it."""
    return schemas.GroupOut(**_group_fields(db, group, len(group.memberships)))


def group_detail(db: Session, group: UserGroup) -> schemas.GroupDetail:
    """Return group with its members."""
    members = accounts.members_of(db, group)
    return schemas.GroupDetail(
        **_group_fields(db, group, len(members)),
        members=users_out(db, members),
    )


def users_out(db: Session, users: list[User]) -> list[schemas.UserOut]:
    """Return a page of users, their contacts and their operators read once for them all."""
    people = accounts.contacts_of(db, users)
    behind = accounts.operators_of(db, users)
    return [
        user_out(db, user, people.get(user.contact_hid or ""), behind[user.hid]) for user in users
    ]


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
    """Return event with the username of whoever caused it."""
    actor = db.get(User, event.actor_hid) if event.actor_hid else None
    return schemas.AuditEventOut(
        hid=event.hid,
        at=event.at,
        actor_hid=event.actor_hid,
        actor_name=actor.username if actor else None,
        via=event.via,
        request_id=event.request_id,
        action=event.action,
        record_type=event.record_type,
        record_hid=event.record_hid,
        changes=event.changes,
    )


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
            kind=load.SERVICE if who.kind == load.SERVICE else load.PERSON,
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
