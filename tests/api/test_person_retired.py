"""A person retired together (P-291, P-297, P-298): what is linked to a user, a contact
and an operator, what a retirement says of each, what is refused and changes nothing,
who may, and who brings back. Through the API."""

import threading
from typing import Any

import pytest
from fastapi.testclient import TestClient

from hirdir.domain import accounts, operators
from tests.api.inventory import API, Maker, errors
from tests.api.test_files import Files
from tests.api.test_hardening import _together
from tests.api.test_retired import CODE, bring_back, events, person


class Kim:
    """Kim Lee: a user who is a contact behind two operators, KL and LM, and Sam Okafor,
    a contact to hand a label over to."""

    def __init__(self, desk: Maker, role: str | None = "viewer") -> None:
        self.desk = desk
        more = {"role": role} if role else {}
        self.user = person(desk, **more)
        self.contact_hid: str = self.user["contact_hid"]
        self.kl = desk.post("/operators", {"label": "KL", "contact_hid": self.contact_hid})
        self.lm = desk.post("/operators", {"label": "LM", "contact_hid": self.contact_hid})
        self.sam = desk.contact("Sam Okafor")

    @property
    def contact(self) -> dict:
        return self.desk.get(f"/contacts/{self.contact_hid}")

    def now(self, kind: str, record: dict) -> dict:
        return self.desk.get(f"/{kind}/{record['hid']}")

    def retire(
        self, kind: str, record: dict, expect: int = 200, by: Maker | None = None, **linked: Any
    ) -> dict:
        body: dict[str, Any] = {"row_version": self.now(kind, record)["row_version"]}
        if linked:
            body["linked"] = linked
        return (by or self.desk).post(f"/{kind}/{record['hid']}/retire", body, expect)

    def statuses(self) -> dict[str, str]:
        linked = self.desk.get(f"/contacts/{self.contact_hid}/linked")
        found = {one["label"]: one["record_status"] for one in linked["operators"]}
        found["contact"] = linked["contact"]["record_status"]
        if linked["user"] is not None:
            found["user"] = linked["user"]["record_status"]
        return found

    def every(self, action: str = "retire") -> list[dict[str, str]]:
        return [{"hid": one["hid"], "action": action} for one in (self.kl, self.lm)]


ALL_ACTIVE = {"KL": "active", "LM": "active", "contact": "active", "user": "active"}


@pytest.fixture
def desk(client: TestClient, admin: dict) -> Maker:
    return Maker(client, admin)


@pytest.fixture
def kim(desk: Maker) -> Kim:
    return Kim(desk)


# --- what is linked --------------------------------------------------------------------


def test_each_of_the_three_answers_the_person_it_belongs_to(
    kim: Kim, desk: Maker, client: TestClient, viewer: dict
) -> None:
    site = desk.region("Example Region")
    desk.assign(kim.contact, "technical", region_hid=site["hid"])
    desk.patch(f"/regions/{site['hid']}", {"row_version": 1, "operator_hid": kim.kl["hid"]})
    kim.retire("operators", kim.lm, **_keep(kim, "lm"))
    expected = {
        "user": {
            "hid": kim.user["hid"],
            "username": "klee",
            "record_status": "active",
            "disabled": False,
            "role": "viewer",
        },
        "contact": {
            "hid": kim.contact_hid,
            "name": "Kim Lee",
            "email": "kim.lee@example.com",
            "record_status": "active",
            # The place it is assigned to and the two operators it stands behind.
            "uses": 3,
        },
        "operators": [
            {
                "hid": kim.kl["hid"],
                "label": "KL",
                "colour": None,
                "record_status": "active",
                "uses": 1,
            },
            {
                "hid": kim.lm["hid"],
                "label": "LM",
                "colour": None,
                "record_status": "retired",
                "uses": 0,
            },
        ],
    }
    paths = (
        f"/users/{kim.user['hid']}/linked",
        f"/contacts/{kim.contact_hid}/linked",
        f"/operators/{kim.kl['hid']}/linked",
        f"/operators/{kim.lm['hid']}/linked",
    )
    for path in paths:
        assert desk.get(path) == expected
        # Every role reads it.
        assert client.get(API + path, headers=viewer).json() == expected
    # A user with no contact is itself alone, and so is an operator with none.
    bare = desk.post("/users", {"username": "sokafor"})["user"]
    alone = desk.get(f"/users/{bare['hid']}/linked")
    assert (alone["user"]["username"], alone["contact"], alone["operators"]) == (
        "sokafor",
        None,
        [],
    )
    label = desk.post("/operators", {"label": "OPEN"})
    alone = desk.get(f"/operators/{label['hid']}/linked")
    assert (alone["user"], alone["contact"]) == (None, None)
    assert [one["label"] for one in alone["operators"]] == ["OPEN"]
    # A contact that is nobody's user and behind no label.
    alone = desk.get(f"/contacts/{kim.sam['hid']}/linked")
    assert (alone["user"], alone["operators"]) == (None, [])
    assert alone["contact"]["name"] == "Sam Okafor"
    for path in ("/users/none/linked", "/contacts/none/linked", "/operators/none/linked"):
        desk.get(path, 404)
    assert client.get(API + paths[0]).status_code == 401


def _keep(kim: Kim, target: str) -> dict[str, Any]:
    """Say of everything linked to one operator of Kim that it is kept."""
    other = kim.kl if target == "lm" else kim.lm
    return {
        "user": "keep",
        "contact": "keep",
        "operators": [{"hid": other["hid"], "action": "keep"}],
    }


# --- a retirement says what becomes of each linked record ------------------------------


def test_a_retirement_that_says_nothing_of_the_linked_records_names_them_and_changes_nothing(
    kim: Kim, desk: Maker
) -> None:
    before = desk.get("/audit-events", limit=1)["total"]
    refused = kim.retire("contacts", kim.contact, 409)
    assert set(errors(refused)) == {"linked.user", "linked.operators"}
    assert "klee" in errors(refused)["linked.user"]
    assert "KL, LM" in errors(refused)["linked.operators"]
    assert refused["depends_on"] == [
        {"hid": kim.kl["hid"], "record_type": "operator", "label": "KL"},
        {"hid": kim.lm["hid"], "record_type": "operator", "label": "LM"},
        {"hid": kim.user["hid"], "record_type": "user", "label": "klee"},
    ]
    # The user's route and an operator's name what each leaves unsaid, the contact too.
    refused = kim.retire("users", kim.user, 409)
    assert set(errors(refused)) == {"linked.contact", "linked.operators"}
    assert [one["record_type"] for one in refused["depends_on"]] == [
        "operator",
        "operator",
        "contact",
    ]
    refused = kim.retire("operators", kim.kl, 409, user="keep")
    assert set(errors(refused)) == {"linked.contact", "linked.operators"}
    assert [one["label"] for one in refused["depends_on"]] == ["LM", "Kim Lee"]
    # Part of it said is not all of it said.
    refused = kim.retire(
        "contacts", kim.contact, 409, user="retire", operators=[kim.every("open")[0]]
    )
    assert refused["depends_on"] == [
        {"hid": kim.lm["hid"], "record_type": "operator", "label": "LM"}
    ]
    assert kim.statuses() == ALL_ACTIVE
    assert desk.get("/audit-events", limit=1)["total"] == before


def test_a_person_is_retired_in_one_change_each_record_audited_as_by_itself(
    kim: Kim, desk: Maker, client: TestClient, admin: dict
) -> None:
    group = desk.post("/user-groups", {"name": "Example East"})
    client.put(f"{API}/user-groups/{group['hid']}/members/{kim.user['hid']}", headers=admin)
    session = client.post(f"{API}/auth/sign-in", json={"username": "klee", "access_code": CODE})
    token = {"Authorization": f"Bearer {session.json()['token']}"}
    response = client.post(
        f"{API}/contacts/{kim.contact_hid}/retire",
        json={
            "row_version": kim.contact["row_version"],
            "linked": {
                "user": "retire",
                "operators": [
                    {"hid": kim.kl["hid"], "action": "hand_over", "contact_hid": kim.sam["hid"]},
                    {"hid": kim.lm["hid"], "action": "retire"},
                ],
            },
        },
        headers=admin,
    )
    assert response.status_code == 200, response.text
    assert response.json()["record_status"] == "retired"
    assert kim.statuses() == {"LM": "retired", "contact": "retired", "user": "retired"}
    handed = desk.get(f"/operators/{kim.kl['hid']}")
    assert (handed["contact_hid"], handed["record_status"]) == (kim.sam["hid"], "active")
    assert client.get(f"{API}/auth/me", headers=token).status_code == 401
    # One request: the operators, then the user and what it held, then the contact.
    request = response.headers["x-request-id"]
    assert events(desk, request_id=request) == [
        ("update", "operator", kim.kl["hid"]),
        ("retire", "operator", kim.lm["hid"]),
        ("remove_member", "user_group", group["hid"]),
        ("revoke_role", "user", kim.user["hid"]),
        ("retire", "user", kim.user["hid"]),
        ("update", "contact", kim.contact_hid),
        ("retire", "contact", kim.contact_hid),
    ]
    by_record = {
        one["record_hid"]: one
        for one in desk.audit(request_id=request)
        if one["action"] != "update" or one["record_type"] != "contact"
    }
    assert by_record[kim.kl["hid"]]["changes"] == [
        {"field": "contact_hid", "old": kim.contact_hid, "new": kim.sam["hid"]}
    ]
    assert by_record[kim.contact_hid]["changes"] == [
        {"field": "record_status", "old": "active", "new": "retired"}
    ]


def test_each_linked_record_is_a_choice_and_what_is_kept_stays(kim: Kim, desk: Maker) -> None:
    """Somebody who moves to another department: the account goes, and they are still
    whom to call, behind one label still, another left open."""
    retired = kim.retire(
        "users",
        kim.user,
        contact="keep",
        operators=[
            {"hid": kim.kl["hid"], "action": "keep"},
            {"hid": kim.lm["hid"], "action": "open"},
        ],
    )
    assert retired["record_status"] == "retired"
    # LM is the contact's no longer: it is open.
    assert kim.statuses() == {"KL": "active", "contact": "active", "user": "retired"}
    assert desk.get(f"/operators/{kim.kl['hid']}")["contact_hid"] == kim.contact_hid
    opened = desk.get(f"/operators/{kim.lm['hid']}")
    assert (opened["contact_hid"], opened["is_open"], opened["record_status"]) == (
        None,
        True,
        "active",
    )
    assert kim.contact["record_status"] == "active"
    # What is left linked: the retired account is said no more, the label still is.
    refused = kim.retire("contacts", kim.contact, 409)
    assert set(errors(refused)) == {"linked.operators"}
    done = kim.retire("contacts", kim.contact, operators=[{"hid": kim.kl["hid"], "action": "open"}])
    assert done["record_status"] == "retired"


def test_somebody_who_looks_after_equipment_no_longer_has_a_label_alone_retired(
    kim: Kim, desk: Maker, client: TestClient, inventory: dict
) -> None:
    """The Inventory role retires a label and keeps the rest, as before."""
    ivy = Maker(client, inventory)
    retired = kim.retire("operators", kim.lm, by=ivy, **_keep(kim, "lm"))
    assert retired["record_status"] == "retired"
    assert kim.statuses() == {**ALL_ACTIVE, "LM": "retired"}
    assert events(desk, record_type="operator", action="retire") == [
        ("retire", "operator", kim.lm["hid"])
    ]


def test_a_contact_is_not_retired_while_its_account_or_a_label_stands_on_it(
    kim: Kim, desk: Maker
) -> None:
    refused = kim.retire("contacts", kim.contact, 422, user="keep", operators=kim.every("open"))
    assert set(errors(refused)) == {"linked.user"}
    refused = kim.retire(
        "contacts",
        kim.contact,
        422,
        user="retire",
        operators=[
            {"hid": kim.kl["hid"], "action": "keep"},
            {"hid": kim.lm["hid"], "action": "retire"},
        ],
    )
    assert set(errors(refused)) == {"linked.operators"}
    assert "KL" in errors(refused)["linked.operators"]
    # By the user's route and by an operator's, with the contact as `retire`, the same.
    refused = kim.retire("users", kim.user, 422, contact="retire", operators=kim.every("keep"))
    assert set(errors(refused)) == {"linked.operators"}
    refused = kim.retire(
        "operators",
        kim.kl,
        422,
        user="keep",
        contact="retire",
        operators=[{"hid": kim.lm["hid"], "action": "keep"}],
    )
    assert set(errors(refused)) == {"linked.user", "linked.operators"}
    assert kim.statuses() == ALL_ACTIVE
    # And by each of those routes it is retired with the rest.
    kim.retire("operators", kim.kl, user="retire", contact="retire", operators=[kim.every()[1]])
    assert kim.statuses() == {
        "KL": "retired",
        "LM": "retired",
        "contact": "retired",
        "user": "retired",
    }


def test_what_is_said_of_a_record_that_is_not_linked_or_is_retired_already_is_refused(
    kim: Kim, desk: Maker
) -> None:
    other = desk.post("/operators", {"label": "OTHER"})
    gone = desk.contact("Example Gone")
    desk.post(f"/contacts/{gone['hid']}/retire", {"row_version": gone["row_version"]}, 200)
    both = kim.every()

    def refused(kind: str, record: dict, field: str, **linked: Any) -> str:
        problem = kim.retire(kind, record, 422, **linked)
        assert set(errors(problem)) == {field}, problem
        return errors(problem)[field]

    operators_ = "linked.operators"
    # The record the route is on is not said.
    refused("users", kim.user, "linked.user", user="retire", contact="keep", operators=both)
    refused(
        "contacts", kim.contact, "linked.contact", user="retire", contact="retire", operators=both
    )
    assert "KL" in refused(
        "operators", kim.kl, operators_, user="keep", contact="keep", operators=both
    )
    # An operator of nobody's, and one said twice.
    said = [*both, {"hid": other["hid"], "action": "retire"}]
    assert "not linked" in refused(
        "contacts", kim.contact, operators_, user="retire", operators=said
    )
    said = [*both, both[0]]
    assert "twice" in refused("contacts", kim.contact, operators_, user="retire", operators=said)
    # A label is handed over to a contact: one that is there, not retired, and another.
    for to, why in (
        (None, "names the contact"),
        (kim.contact_hid, "another contact"),
        (gone["hid"], "is retired"),
        ("no-such-contact", "there is no contact"),
    ):
        said = [{"hid": kim.kl["hid"], "action": "hand_over", "contact_hid": to}, both[1]]
        assert why in refused("contacts", kim.contact, operators_, user="retire", operators=said)
    said = [{"hid": kim.kl["hid"], "action": "open", "contact_hid": kim.sam["hid"]}, both[1]]
    assert "hand_over alone" in refused(
        "contacts", kim.contact, operators_, user="retire", operators=said
    )
    # A contact with no user, and a user with no contact, have none to say anything of.
    assert "no user" in refused("contacts", kim.sam, "linked.user", user="retire")
    bare = desk.post("/users", {"username": "sokafor"})["user"]
    assert "no contact" in refused("users", bare, "linked.contact", contact="keep")
    assert kim.statuses() == ALL_ACTIVE
    # What is retired already is not said again.
    kim.retire("operators", kim.lm, **_keep(kim, "lm"))
    assert "retired already" in refused(
        "contacts", kim.contact, operators_, user="retire", operators=both
    )
    kim.retire(
        "users", kim.user, contact="keep", operators=[{"hid": kim.kl["hid"], "action": "keep"}]
    )
    assert "retired already" in refused(
        "contacts", kim.contact, "linked.user", user="retire", operators=[both[0]]
    )
    kim.retire("contacts", kim.contact, operators=[both[0]])
    # A label brought back on a contact that is retired: of the contact nothing is said.
    now = kim.now("operators", kim.kl)
    desk.patch(
        f"/operators/{kim.kl['hid']}",
        {"row_version": now["row_version"], "record_status": "active"},
    )
    assert "retired already" in refused("operators", kim.kl, "linked.contact", contact="keep")
    assert kim.retire("operators", kim.kl)["record_status"] == "retired"


def test_a_request_that_retires_a_user_is_an_admins(
    kim: Kim, desk: Maker, client: TestClient, inventory: dict, viewer: dict
) -> None:
    ivy = Maker(client, inventory)
    before = desk.get("/audit-events", limit=1)["total"]
    refused = kim.retire("contacts", kim.contact, 403, by=ivy, user="retire", operators=kim.every())
    assert "Admin" in refused["detail"]
    refused = kim.retire(
        "operators",
        kim.kl,
        403,
        by=ivy,
        user="retire",
        contact="retire",
        operators=[kim.every()[1]],
    )
    assert "Admin" in refused["detail"]
    # Keeping the user, the Inventory role cannot retire the contact: the one rule.
    kim.retire("contacts", kim.contact, 422, by=ivy, user="keep", operators=kim.every())
    # A View-only user retires nothing.
    kim.retire("operators", kim.kl, 403, by=Maker(client, viewer), **_keep(kim, "kl"))
    assert kim.statuses() == ALL_ACTIVE
    assert desk.get("/audit-events", limit=1)["total"] == before
    # A contact that is no user's, behind a label, is the Inventory role's to retire.
    label = ivy.post("/operators", {"label": "SO", "contact_hid": kim.sam["hid"]})
    kim.retire("contacts", kim.sam, 409, by=ivy)
    done = kim.retire(
        "contacts", kim.sam, by=ivy, operators=[{"hid": label["hid"], "action": "open"}]
    )
    assert done["record_status"] == "retired"
    assert desk.get(f"/operators/{label['hid']}")["contact_hid"] is None


def test_a_record_with_nothing_linked_is_retired_with_its_version_alone_as_before(
    kim: Kim, desk: Maker, client: TestClient, inventory: dict
) -> None:
    ivy = Maker(client, inventory)
    assert kim.retire("contacts", kim.sam, by=ivy)["record_status"] == "retired"
    label = desk.post("/operators", {"label": "OPEN"})
    assert kim.retire("operators", label, by=ivy)["record_status"] == "retired"
    bare = desk.post("/users", {"username": "sokafor"})["user"]
    assert kim.retire("users", bare)["record_status"] == "retired"
    # An empty `linked` is nothing said.
    late = desk.contact("Example Late")
    done = desk.post(
        f"/contacts/{late['hid']}/retire", {"row_version": late["row_version"], "linked": {}}, 200
    )
    assert done["record_status"] == "retired"
    # One that is retired already is left as it is, as before; and nothing is said of
    # what is linked to it by its route.
    again = kim.retire("contacts", kim.sam, by=ivy)
    assert (again["record_status"], again["row_version"]) == ("retired", 2)
    assert events(desk, record_hid=kim.sam["hid"], action="retire") == [
        ("retire", "contact", kim.sam["hid"])
    ]
    kim.retire("users", kim.user, contact="retire", operators=kim.every("open"))
    refused = kim.retire("contacts", kim.contact, 409, operators=kim.every())
    assert "retired already" in refused["detail"]
    # The contact of a retired account, with every label gone from it, has nothing linked
    # that is not retired.
    assert kim.statuses()["contact"] == "retired"


def test_a_plan_refused_at_its_last_step_changes_nothing_and_keeps_no_event(
    desk: Maker, client: TestClient, admin: dict
) -> None:
    """The only Admin is a contact behind a label: the operator is opened first, and the
    whole is undone when the account cannot be retired."""
    ada = desk.get("/auth/me")
    contact = desk.contact("Example Admin")
    desk.patch(
        f"/users/{ada['hid']}", {"row_version": ada["row_version"], "contact_hid": contact["hid"]}
    )
    label = desk.post("/operators", {"label": "EA", "contact_hid": contact["hid"]})
    before = desk.get("/audit-events", limit=1)["total"]
    refused = desk.post(
        f"/contacts/{contact['hid']}/retire",
        {
            "row_version": contact["row_version"],
            "linked": {"user": "retire", "operators": [{"hid": label["hid"], "action": "open"}]},
        },
        409,
    )
    assert "no Admin" in refused["detail"]
    now = desk.get(f"/operators/{label['hid']}")
    assert (now["contact_hid"], now["row_version"]) == (contact["hid"], label["row_version"])
    assert desk.get(f"/contacts/{contact['hid']}")["record_status"] == "active"
    assert desk.get("/auth/me")["record_status"] == "active"
    assert desk.get("/audit-events", limit=1)["total"] == before
    # A stale copy of the record the route is on, likewise.
    stale = desk.post(
        f"/operators/{label['hid']}/retire",
        {"row_version": label["row_version"] + 1, "linked": {"user": "keep", "contact": "keep"}},
        409,
    )
    assert stale["title"] == "Stale version"
    assert desk.get("/audit-events", limit=1)["total"] == before


# --- two requests at the same moment ---------------------------------------------------


def test_a_contact_is_not_retired_while_it_is_being_given_to_a_user(
    desk: Maker, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sam = desk.contact("Sam Okafor")
    user = desk.post("/users", {"username": "sokafor"})["user"]
    looked = threading.Event()
    real = accounts._checked_contact

    def checked(*args: Any) -> Any:
        found = real(*args)
        # The user's request has seen the contact in order. The other request is let go
        # now, and has a moment to retire the contact before the user is written.
        looked.set()
        threading.Event().wait(0.5)
        return found

    monkeypatch.setattr(accounts, "_checked_contact", checked)

    def give(caller: TestClient) -> Any:
        return caller.patch(
            f"{API}/users/{user['hid']}",
            json={"row_version": user["row_version"], "contact_hid": sam["hid"]},
            headers=desk.headers,
        )

    def retire(caller: TestClient) -> Any:
        looked.wait(5)
        return caller.post(
            f"{API}/contacts/{sam['hid']}/retire",
            json={"row_version": sam["row_version"]},
            headers=desk.headers,
        )

    # The user took its turn before it looked, so the retiring waits, and then finds it.
    assert _together(client, [give, retire]) == [200, 409]
    assert desk.get(f"/users/{user['hid']}")["contact_hid"] == sam["hid"]
    assert desk.get(f"/contacts/{sam['hid']}")["record_status"] == "active"


def test_a_contact_is_not_retired_while_it_is_being_put_behind_a_label(
    desk: Maker, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sam = desk.contact("Sam Okafor")
    label = desk.post("/operators", {"label": "SO"})
    looked = threading.Event()
    real = operators._checked

    def checked(*args: Any) -> Any:
        found = real(*args)
        looked.set()
        threading.Event().wait(0.5)
        return found

    monkeypatch.setattr(operators, "_checked", checked)

    def give(caller: TestClient) -> Any:
        return caller.patch(
            f"{API}/operators/{label['hid']}",
            json={"row_version": label["row_version"], "contact_hid": sam["hid"]},
            headers=desk.headers,
        )

    def retire(caller: TestClient) -> Any:
        looked.wait(5)
        return caller.post(
            f"{API}/contacts/{sam['hid']}/retire",
            json={"row_version": sam["row_version"]},
            headers=desk.headers,
        )

    assert _together(client, [give, retire]) == [200, 409]
    assert desk.get(f"/operators/{label['hid']}")["contact_hid"] == sam["hid"]
    assert desk.get(f"/contacts/{sam['hid']}")["record_status"] == "active"


def test_a_user_is_not_given_a_contact_that_is_being_retired(
    desk: Maker, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other way round: the retirement looks first, and the user waits and is told."""
    from hirdir.domain import people

    sam = desk.contact("Sam Okafor")
    user = desk.post("/users", {"username": "sokafor"})["user"]
    looked = threading.Event()
    real = people._judged

    def judged(*args: Any) -> Any:
        found = real(*args)
        looked.set()
        threading.Event().wait(0.5)
        return found

    monkeypatch.setattr(people, "_judged", judged)

    def retire(caller: TestClient) -> Any:
        return caller.post(
            f"{API}/contacts/{sam['hid']}/retire",
            json={"row_version": sam["row_version"]},
            headers=desk.headers,
        )

    def give(caller: TestClient) -> Any:
        looked.wait(5)
        return caller.patch(
            f"{API}/users/{user['hid']}",
            json={"row_version": user["row_version"], "contact_hid": sam["hid"]},
            headers=desk.headers,
        )

    assert _together(client, [retire, give]) == [200, 422]
    assert desk.get(f"/users/{user['hid']}")["contact_hid"] is None
    assert desk.get(f"/contacts/{sam['hid']}")["record_status"] == "retired"


# --- bringing back ---------------------------------------------------------------------


def test_a_retired_contact_or_operator_is_brought_back_by_an_admin_alone(
    kim: Kim, desk: Maker, client: TestClient, inventory: dict
) -> None:
    ivy = Maker(client, inventory)
    kim.retire("users", kim.user, contact="retire", operators=kim.every())
    for kind, hid in (("contacts", kim.contact_hid), ("operators", kim.kl["hid"])):
        path = f"/{kind}/{hid}"
        now = desk.get(path)
        for status in ("active", "draft"):
            refused = ivy.patch(
                path, {"row_version": now["row_version"], "record_status": status}, 403
            )
            assert "Admin" in refused["detail"]
        # Another change of a retired one is the Inventory role's, as before.
        field = "notes" if kind == "contacts" else "description"
        noted = ivy.patch(path, {"row_version": now["row_version"], field: "Left in 2026."})
        assert noted["record_status"] == "retired"
        back = desk.patch(path, {"row_version": noted["row_version"], "record_status": "active"})
        assert back["record_status"] == "active"
        # To retire one is the Inventory role's still, and to make a draft of one.
        draft = ivy.patch(path, {"row_version": back["row_version"], "record_status": "draft"})
        assert draft["record_status"] == "draft"


def test_an_inventory_user_still_brings_back_a_site_and_an_item(make: Maker) -> None:
    """Every other kind of record is brought back as before (P-298)."""
    places = make.layout()
    switch = make.item(hostname="site2-sw-access-01", location_hid=places["room"]["hid"])
    retired = make.post(
        f"/items/{switch['hid']}/retire", {"row_version": switch["row_version"]}, 200
    )
    back = make.patch(
        f"/items/{switch['hid']}",
        {"row_version": retired["row_version"], "record_status": "active"},
    )
    assert back["record_status"] == "active"
    region = make.region("Example Region")
    site = make.site("Example Site", region)
    retired = make.post(f"/sites/{site['hid']}/retire", {"row_version": site["row_version"]}, 200)
    back = make.patch(
        f"/sites/{site['hid']}", {"row_version": retired["row_version"], "record_status": "active"}
    )
    assert back["record_status"] == "active"
    owner = make.owner("Example Owners")
    retired = make.post(
        f"/owners/{owner['hid']}/retire", {"row_version": owner["row_version"]}, 200
    )
    back = make.patch(
        f"/owners/{owner['hid']}",
        {"row_version": retired["row_version"], "record_status": "active"},
    )
    assert back["record_status"] == "active"


def test_a_user_whose_contact_is_retired_is_brought_back_with_it(
    kim: Kim, desk: Maker, client: TestClient, admin: dict
) -> None:
    kim.retire("users", kim.user, contact="retire", operators=kim.every())
    refused = bring_back(desk, kim.user, 409)
    assert set(errors(refused)) == {"linked.contact"}
    assert refused["existing"] == {
        "hid": kim.contact_hid,
        "record_type": "contact",
        "label": "Kim Lee",
    }
    other = desk.post("/operators", {"label": "OTHER"})
    before = desk.get("/audit-events", limit=1)["total"]
    for linked, field in (
        (
            {"contact": "bring_back", "operators": [{"hid": other["hid"], "action": "bring_back"}]},
            "linked.operators",
        ),
        (
            {"contact": "bring_back", "operators": [kim.every("bring_back")[0]] * 2},
            "linked.operators",
        ),
    ):
        problem = bring_back(desk, kim.user, 422, **linked)
        assert set(errors(problem)) == {field}
    assert kim.statuses()["user"] == "retired"
    assert desk.get("/audit-events", limit=1)["total"] == before

    response = client.post(
        f"{API}/users/{kim.user['hid']}/bring-back",
        json={
            "row_version": desk.get(f"/users/{kim.user['hid']}")["row_version"],
            "linked": {
                "contact": "bring_back",
                "operators": [{"hid": kim.kl["hid"], "action": "bring_back"}],
            },
        },
        headers=admin,
    )
    assert response.status_code == 200, response.text
    assert response.json()["access_code"]
    assert kim.statuses() == {**ALL_ACTIVE, "LM": "retired"}
    # The label brought back is the contact's still.
    assert desk.get(f"/operators/{kim.kl['hid']}")["contact_hid"] == kim.contact_hid
    assert events(desk, request_id=response.headers["x-request-id"]) == [
        ("update", "contact", kim.contact_hid),
        ("update", "operator", kim.kl["hid"]),
        ("bring_back", "user", kim.user["hid"]),
        ("update", "contact", kim.contact_hid),
    ]
    # What is not retired is not brought back.
    kim.retire(
        "users", kim.user, contact="keep", operators=[{"hid": kim.kl["hid"], "action": "keep"}]
    )
    problem = bring_back(desk, kim.user, 422, contact="bring_back")
    assert set(errors(problem)) == {"linked.contact"}
    problem = bring_back(
        desk, kim.user, 422, operators=[{"hid": kim.kl["hid"], "action": "bring_back"}]
    )
    assert set(errors(problem)) == {"linked.operators"}


def test_a_user_whose_retired_contact_is_taken_off_is_brought_back_alone(
    kim: Kim, desk: Maker
) -> None:
    kim.retire("users", kim.user, contact="retire", operators=kim.every())
    now = desk.get(f"/users/{kim.user['hid']}")
    desk.patch(
        f"/users/{kim.user['hid']}", {"row_version": now["row_version"], "contact_hid": None}
    )
    back = bring_back(desk, kim.user)
    assert (back["user"]["record_status"], back["user"]["contact"]) == ("active", None)
    assert desk.get(f"/contacts/{kim.contact_hid}")["record_status"] == "retired"
    problem = desk.post(
        f"/users/{kim.user['hid']}/retire", {"row_version": back["user"]["row_version"]}, 200
    )
    assert problem["record_status"] == "retired"
    refused = bring_back(desk, kim.user, 422, contact="bring_back")
    assert "no contact" in errors(refused)["linked.contact"]


# --- a file ----------------------------------------------------------------------------


def test_no_row_of_a_file_retires_a_contact_or_an_operator(
    kim: Kim, client: TestClient, inventory: dict
) -> None:
    """An import does not retire, with something linked or with nothing: the rule of
    `linked` has nothing to hold in a file (P-297)."""
    files = Files(client, inventory)
    for table, text in (
        ("contacts", "name,email,record_status\nKim Lee,kim.lee@example.com,retired\n"),
        ("operators", "label,record_status\nKL,retired\n"),
        ("contacts", "name,email,record_status\nSam Okafor,sam.okafor@example.net,retired\n"),
    ):
        preview = files.preview(table, text)
        rejected = preview["rows"][0]
        assert rejected["outcome"] == "rejected"
        assert "a file does not retire" in " ".join(one["message"] for one in rejected["reasons"])
        files.apply(preview, expect=422)
    assert kim.statuses() == ALL_ACTIVE
    assert kim.desk.get(f"/contacts/{kim.sam['hid']}")["record_status"] == "active"


def test_a_row_of_a_file_brings_a_contact_or_an_operator_back_for_an_admin_alone(
    kim: Kim, desk: Maker, client: TestClient, admin: dict, inventory: dict
) -> None:
    kim.retire("users", kim.user, contact="retire", operators=kim.every())
    contacts_file = "name,email,record_status\nKim Lee,kim.lee@example.com,active\n"
    operators_file = "label,record_status\nKL,active\n"
    for table, text in (("contacts", contacts_file), ("operators", operators_file)):
        files = Files(client, inventory)
        rejected = files.preview(table, text)["rows"][0]
        assert rejected["outcome"] == "rejected"
        assert "Admin" in " ".join(one["message"] for one in rejected["reasons"])
    assert kim.statuses()["contact"] == "retired"
    for table, text in (("contacts", contacts_file), ("operators", operators_file)):
        files = Files(client, admin)
        preview = files.preview(table, text)
        assert preview["rows"][0]["outcome"] == "update"
        files.apply(preview)
    assert kim.statuses() == {
        "KL": "active",
        "LM": "retired",
        "contact": "active",
        "user": "retired",
    }
