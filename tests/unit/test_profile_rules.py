"""The rules of a person's own profile, each by itself, on a database with no server:
whose records a person changes, which fields of them, and what is asked of an access
code (P-294, P-295)."""

from datetime import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from hirdir import clock
from hirdir.auth import codes, tokens
from hirdir.auth.throttle import Throttle
from hirdir.db.models import AuditEvent, User
from hirdir.domain import accounts, audit, contacts, operators, profile, settings
from hirdir.domain.accounts import Principal
from hirdir.domain.audit import AuditContext
from hirdir.domain.errors import Conflict, Invalid, NotAllowed, NotFound, SignInDelayed

CODE = "kim-lee-code-01"
NEW_CODE = "kim-lee-code-02"
KEY = b"a key of the tests, and of nothing else"


def _person(db: Session, username: str = "klee", name: str | None = "Kim Lee") -> User:
    """Make a person who is a contact, where a name is given, and behind an operator."""
    made = accounts.onboard(
        db,
        audit.SYSTEM,
        username=username,
        access_code=CODE,
        contact={"name": name} if name else None,
        operator={} if name else None,
    )
    db.commit()
    return made.user


def _as(user: User, kind: str = "session") -> tuple[Principal, AuditContext]:
    return Principal(user=user, role=None, kind=kind), AuditContext(actor_hid=user.hid, via="api")


def _change(
    db: Session,
    user: User,
    throttle: Throttle,
    current: str,
    new: str = NEW_CODE,
    kind: str = "session",
) -> tuple[str, datetime]:
    principal, context = _as(user, kind)
    return profile.change_access_code(
        db,
        principal,
        context,
        current=current,
        new=new,
        address="192.0.2.10",
        throttle=throttle,
        signing_key=KEY,
        session_hours=8,
    )


def _actions(db: Session) -> list[tuple[str, str | None, str | None]]:
    """Return the events that are stored, oldest first, read by another session."""
    with Session(db.get_bind()) as other:
        return [
            (event.action, event.actor_hid, event.record_hid)
            for event in other.scalars(select(AuditEvent).order_by(AuditEvent.hid))
            if event.action.startswith(("access_code", "set_access_code"))
        ]


# --- whose records, and which fields ----------------------------------------------------


def test_a_service_account_has_no_profile_whatever_its_token_or_its_role(db: Session) -> None:
    kim = _person(db)
    robot, _ = accounts.create_user(db, audit.SYSTEM, username="probe", is_service_account=True)
    for user, kind in ((kim, "service"), (robot, "service"), (robot, "session")):
        principal, context = _as(user, kind)
        with pytest.raises(NotAllowed, match="a service account has no profile"):
            profile.update_contact(db, principal, context, 1, {"name": "Kim A. Lee"})
        with pytest.raises(NotAllowed):
            profile.update_operator(db, principal, context, "any", 1, {"label": "KL"})
        with pytest.raises(NotAllowed):
            _change(db, user, Throttle(5), CODE, kind=kind)
    assert codes.verify(kim.access_code_hash, CODE)


@pytest.mark.parametrize("field", ["notes", "tags", "record_status", "contact_hid", "name_key"])
def test_a_profile_changes_five_fields_of_a_contact_and_no_other(db: Session, field: str) -> None:
    kim = _person(db)
    contact = profile.contact_of(db, kim)
    assert contact is not None
    with pytest.raises(Invalid) as refused:
        profile.update_contact(
            db, *_as(kim), contact.row_version, {"name": "Kim A. Lee", field: "draft"}
        )
    assert refused.value.fields == {field: "not changed on a profile"}
    db.rollback()
    assert contacts.get_contact(db, contact.hid).name == "Kim Lee"


@pytest.mark.parametrize("field", ["contact_hid", "description", "record_status", "label_key"])
def test_a_profile_changes_two_fields_of_an_operator_and_no_other(db: Session, field: str) -> None:
    kim = _person(db)
    (operator,) = profile.operators_of(db, kim)
    with pytest.raises(Invalid) as refused:
        profile.update_operator(
            db, *_as(kim), operator.hid, operator.row_version, {"label": "KL", field: None}
        )
    assert refused.value.fields == {field: "not changed on a profile"}
    db.rollback()
    assert operators.get_operator(db, operator.hid).label == "klee"


def test_a_person_changes_their_own_contact_and_none_where_they_have_none(db: Session) -> None:
    kim, bare = _person(db), _person(db, "sokafor", name=None)
    contact = profile.contact_of(db, kim)
    assert contact is not None
    changed = profile.update_contact(
        db, *_as(kim), contact.row_version, {"organization": "Example Networks"}
    )
    assert (changed.hid, changed.organization) == (contact.hid, "Example Networks")

    assert profile.contact_of(db, bare) is None
    with pytest.raises(Conflict, match="no contact: an Admin gives an account its contact"):
        profile.update_contact(db, *_as(bare), 1, {"name": "Sam Okafor"})

    contacts.retire_contact(db, audit.SYSTEM, contact.hid, changed.row_version)
    with pytest.raises(Conflict, match="is retired"):
        profile.update_contact(db, *_as(kim), contact.row_version, {"name": "Kim A. Lee"})
    # Nobody is behind the labels of a retired contact: the person has none to change.
    assert profile.operators_of(db, kim) == []


def test_a_person_changes_the_operators_they_are_behind_and_no_other(db: Session) -> None:
    kim, sam = _person(db), _person(db, "sokafor", "Sam Okafor")
    (mine,) = profile.operators_of(db, kim)
    (theirs,) = profile.operators_of(db, sam)
    open_label = operators.create_operator(db, audit.SYSTEM, {"label": "open-label"})
    old = operators.create_operator(
        db, audit.SYSTEM, {"label": "kl-old", "contact_hid": kim.contact_hid}
    )
    operators.retire_operator(db, audit.SYSTEM, old.hid, old.row_version)
    assert [one.label for one in profile.operators_of(db, kim)] == ["klee"]

    for other in (theirs, open_label, old):
        with pytest.raises(NotFound, match="that you are behind"):
            profile.update_operator(db, *_as(kim), other.hid, other.row_version, {"label": "taken"})
    changed = profile.update_operator(db, *_as(kim), mine.hid, mine.row_version, {"label": "KL"})
    assert (changed.label, changed.contact_hid) == ("KL", kim.contact_hid)
    assert operators.get_operator(db, theirs.hid).label == "sokafor"


# --- the access code --------------------------------------------------------------------


def test_a_changed_code_ends_the_sessions_there_were_and_starts_the_one_returned(
    db: Session,
) -> None:
    kim = _person(db)
    before, _ = tokens.issue_session(KEY, kim.hid, clock.now_ms(), 8)
    assert accounts.authenticate(db, KEY, before).user.hid == kim.hid

    token, expires_at = _change(db, kim, Throttle(5), CODE)
    db.commit()
    assert isinstance(expires_at, datetime)
    assert codes.verify(kim.access_code_hash, NEW_CODE)
    assert not codes.verify(kim.access_code_hash, CODE)
    assert accounts.authenticate(db, KEY, token).user.hid == kim.hid
    with pytest.raises(accounts.NotSignedIn):
        accounts.authenticate(db, KEY, before)
    assert _actions(db) == [("set_access_code", kim.hid, kim.hid)]


def test_a_wrong_current_code_is_counted_under_the_keys_of_a_sign_in_and_kept(
    db: Session,
) -> None:
    kim = _person(db)
    throttle = Throttle(2)
    for _ in range(2):
        with pytest.raises(Invalid) as refused:
            _change(db, kim, throttle, "not-the-code-i-have")
        assert list(refused.value.fields) == ["current_access_code"]
        # The caller rolls back what a refused request did: the refusal is stored already.
        db.rollback()
    # The count is the one of signing in: by the username, and by the address.
    assert throttle.retry_after("user:klee") > 0
    assert throttle.retry_after("addr:192.0.2.10") > 0
    assert throttle.retry_after("user:sokafor", "addr:192.0.2.11") == 0

    with pytest.raises(SignInDelayed) as delayed:
        _change(db, kim, throttle, CODE)
    assert delayed.value.retry_after > 0
    db.rollback()
    assert codes.verify(kim.access_code_hash, CODE)
    assert _actions(db) == [
        ("access_code_refused", kim.hid, kim.hid),
        ("access_code_refused", kim.hid, kim.hid),
        ("access_code_delayed", kim.hid, kim.hid),
    ]


def test_the_right_current_code_clears_the_count_though_the_new_one_is_refused(
    db: Session,
) -> None:
    kim = _person(db)
    throttle = Throttle(2)
    with pytest.raises(Invalid):
        _change(db, kim, throttle, "not-the-code-i-have")
    db.rollback()
    with pytest.raises(Invalid) as short:
        _change(db, kim, throttle, CODE, new="eleven-char")
    assert short.value.fields == {"access_code": "at least 12 characters (access_code_min_length)"}
    db.rollback()
    # One more wrong one is the first again, and not the second.
    with pytest.raises(Invalid):
        _change(db, kim, throttle, "not-the-code-i-have")
    db.rollback()
    assert throttle.retry_after("user:klee", "addr:192.0.2.10") == 0
    assert codes.verify(kim.access_code_hash, CODE)


def test_a_typed_code_is_held_to_the_setting_and_a_made_one_is_not(db: Session) -> None:
    with pytest.raises(Invalid, match="too short: at least 12 characters"):
        accounts.create_user(db, audit.SYSTEM, username="klee", access_code="eleven-char")
    settings.set_setting(db, audit.SYSTEM, settings.CODE_LENGTH_SETTING, 0, 1)
    with pytest.raises(Invalid, match="the access code is not acceptable"):
        accounts.create_user(db, audit.SYSTEM, username="klee", access_code="")
    kim, code = accounts.create_user(db, audit.SYSTEM, username="klee", access_code="x")
    assert code == "x"

    row = settings.get_setting(db, settings.CODE_LENGTH_SETTING)
    settings.set_setting(db, audit.SYSTEM, settings.CODE_LENGTH_SETTING, row.row_version, 64)
    with pytest.raises(Invalid) as short:
        accounts.set_access_code(db, audit.SYSTEM, kim.hid, "x" * 63)
    assert short.value.fields == {"access_code": "at least 64 characters (access_code_min_length)"}
    assert str(short.value) == "the access code is too short: at least 64 characters"
    made = accounts.set_access_code(db, audit.SYSTEM, kim.hid)
    assert len(made) == 14
    _, made = accounts.create_user(db, audit.SYSTEM, username="sokafor")
    assert made is not None
    assert len(made) == 14
