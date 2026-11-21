"""A person retired together, by the rules themselves (P-296 to P-298): the domain is
given the role of whoever asks, and holds every refusal with no router before it."""

from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hirdir.auth.roles import Role
from hirdir.db.models import AuditEvent, Contact, Operator, User
from hirdir.domain import accounts, audit, contacts, operators, people
from hirdir.domain.errors import Conflict, Invalid, NotAllowed, StaleVersion
from hirdir.io import fields

CONTEXT = audit.AuditContext(actor_hid=None, via="api", request_id="r-people")


class Made:
    """Kim Lee, a user who is a contact behind the operator KL, and an Admin beside."""

    def __init__(self, db: Session) -> None:
        ada, _ = accounts.create_user(db, CONTEXT, username="ada", access_code="ada-code-0001")
        accounts.grant_role(db, CONTEXT, role="admin", user_hid=ada.hid)
        self.user, _ = accounts.create_user(
            db,
            CONTEXT,
            username="klee",
            access_code="kim-lee-code-01",
            contact={"name": "Kim Lee", "email": "kim.lee@example.com"},
        )
        accounts.grant_role(db, CONTEXT, role="viewer", user_hid=self.user.hid)
        self.contact = contacts.get_contact(db, self.user.contact_hid or "")
        self.label = operators.create_operator(
            db, CONTEXT, {"label": "KL", "contact_hid": self.contact.hid}
        )
        db.commit()


@pytest.fixture
def made(db: Session) -> Made:
    return Made(db)


def _events(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(AuditEvent)) or 0


def _statuses(db: Session, made: Made) -> tuple[str, str, str]:
    db.expire_all()
    return (
        db.get_one(User, made.user.hid).record_status,
        db.get_one(Contact, made.contact.hid).record_status,
        db.get_one(Operator, made.label.hid).record_status,
    )


def test_the_role_of_whoever_asks_is_checked_from_the_plan(db: Session, made: Made) -> None:
    everything = {"user": "retire", "operators": [{"hid": made.label.hid, "action": "retire"}]}
    kept = {"user": "keep", "contact": "keep"}
    cases: list[tuple[Role | None, str, str, dict[str, Any]]] = [
        # A request that retires a user is an Admin's.
        (Role.INVENTORY, people.CONTACT, made.contact.hid, everything),
        (Role.INVENTORY, people.USER, made.user.hid, {"contact": "keep"}),
        (None, people.USER, made.user.hid, {"contact": "keep"}),
        # One that retires a contact or an operator is the Inventory role's at the least.
        (Role.VIEWER, people.OPERATOR, made.label.hid, kept),
        (None, people.OPERATOR, made.label.hid, kept),
    ]
    before = _events(db)
    for role, kind, hid, linked in cases:
        with pytest.raises(NotAllowed):
            people.retire(db, CONTEXT, role, kind, hid, None, linked)
        db.rollback()
    assert _statuses(db, made) == ("active", "active", "active")
    assert _events(db) == before
    # The Inventory role retires the label and keeps the rest.
    people.retire(db, CONTEXT, Role.INVENTORY, people.OPERATOR, made.label.hid, None, kept)
    db.commit()
    assert _statuses(db, made) == ("active", "active", "retired")
    # And only an Admin brings the user back.
    people.retire(db, CONTEXT, Role.ADMIN, people.USER, made.user.hid, None, {"contact": "keep"})
    db.commit()
    for role in (Role.INVENTORY, Role.VIEWER, None):
        with pytest.raises(NotAllowed):
            people.bring_back(db, CONTEXT, role, made.user.hid, None)
    back = people.bring_back(db, CONTEXT, Role.ADMIN, made.user.hid, None)
    assert back.access_code
    assert back.user.record_status == "active"


def test_a_plan_is_judged_whole_before_anything_of_it_is_written(db: Session, made: Made) -> None:
    """Each refusal is raised with nothing changed in the session: no rollback undoes it."""
    hid = made.contact.hid
    label = {"hid": made.label.hid, "action": "open"}
    refusals: list[tuple[type[Exception], int | None, dict[str, Any] | None]] = [
        (Conflict, None, None),
        (Conflict, None, {"user": "retire"}),
        (Invalid, None, {"user": "keep", "operators": [label]}),
        (Invalid, None, {"user": "retire", "operators": [{**label, "action": "keep"}]}),
        (Invalid, None, {"user": "retire", "contact": "retire", "operators": [label]}),
        (StaleVersion, 99, {"user": "retire", "operators": [label]}),
    ]
    for error, version, linked in refusals:
        with pytest.raises(error):
            people.retire(db, CONTEXT, Role.ADMIN, people.CONTACT, hid, version, linked)
        assert not db.dirty
        assert not db.new
    people.retire(
        db, CONTEXT, Role.ADMIN, people.CONTACT, hid, 1, {"user": "retire", "operators": [label]}
    )
    db.commit()
    assert _statuses(db, made) == ("retired", "retired", "active")
    assert db.get_one(Operator, made.label.hid).contact_hid is None


def test_what_is_linked_to_a_record_is_what_is_not_retired_beside_it(
    db: Session, made: Made
) -> None:
    def linked(kind: str, hid: str) -> list[tuple[str, str]]:
        return [(one.record_type, one.label) for one in people.linked_to(db, kind, hid)]

    assert linked(people.CONTACT, made.contact.hid) == [("operator", "KL"), ("user", "klee")]
    assert linked(people.USER, made.user.hid) == [("operator", "KL"), ("contact", "Kim Lee")]
    assert linked(people.OPERATOR, made.label.hid) == [("user", "klee"), ("contact", "Kim Lee")]
    people.retire(
        db,
        CONTEXT,
        Role.ADMIN,
        people.USER,
        made.user.hid,
        None,
        {"contact": "keep", "operators": [{"hid": made.label.hid, "action": "keep"}]},
    )
    db.commit()
    assert linked(people.CONTACT, made.contact.hid) == [("operator", "KL")]


def test_a_retired_account_is_no_user_of_its_contact_and_is_its_account_still(
    db: Session, made: Made
) -> None:
    hid = made.contact.hid
    is_user = select(func.count()).select_from(Contact).where(fields.is_user(Contact.hid))
    assert list(contacts.users_of(db, [hid])) == [hid]
    assert operators.scope(made.contact, contacts.users_of(db, [hid])) == "internal"
    assert db.scalar(is_user) == 1
    accounts.retire_user(db, CONTEXT, made.user.hid, None)
    db.commit()
    assert contacts.users_of(db, [hid]) == {}
    assert contacts.accounts_of(db, [hid])[hid].username == "klee"
    assert operators.scope(made.contact, contacts.users_of(db, [hid])) == "external"
    # The database says the same as the page.
    assert db.scalar(is_user) == 0


def test_a_retired_admin_is_no_admin_to_keep(db: Session, made: Made) -> None:
    """The last Admin is one who is not retired: a retired account counts for nothing,
    whatever was left granted to it."""
    ada = accounts.find_user(db, "ada")
    assert ada is not None
    assert accounts._admin_count(db) == 1
    accounts.grant_role(db, CONTEXT, role="admin", user_hid=made.user.hid)
    db.commit()
    assert accounts._admin_count(db) == 2
    made.user.record_status = "retired"
    db.commit()
    assert accounts._admin_count(db) == 1
    with pytest.raises(Conflict, match="no Admin"):
        accounts.retire_user(db, CONTEXT, ada.hid, None)
