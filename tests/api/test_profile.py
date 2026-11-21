"""A person's own profile: the contact they are, the operators they are behind and their
access code, changed by routes of their own (P-289, P-294, P-295). Through the API."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.api.inventory import API, Maker, errors, left_retired
from tests.conftest import ADMIN_CODE, INVENTORY_CODE, VIEWER_CODE, sign_in

CODE = "kim-lee-code-01"
NEW_CODE = "kim-lee-code-02"
KIM = {
    "name": "Kim Lee",
    "email": "kim.lee@example.com",
    "phone": "+1 555 0100",
    "phone2": "+1 555 0101",
    "organization": "Example Networks",
}


def _person(
    client: TestClient,
    admin: dict,
    username: str = "klee",
    role: str | None = "viewer",
    contact: dict[str, Any] | None = None,
    operator: bool = True,
) -> tuple[dict[str, str], dict[str, Any]]:
    """Make a person who is a contact and behind an operator, sign them in, and return
    their headers with what `POST /users` answered."""
    body: dict[str, Any] = {
        "username": username,
        "access_code": CODE,
        "contact": KIM if contact is None else contact,
    }
    if role:
        body["role"] = role
    if operator:
        body["operator"] = {}
    made = Maker(client, admin).post("/users", body)
    return sign_in(client, username, CODE), made


def _me(client: TestClient, headers: dict) -> dict[str, Any]:
    response = client.get(f"{API}/auth/me", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _events(client: TestClient, admin: dict, **params: Any) -> list[dict[str, Any]]:
    return Maker(client, admin).audit(**params)


# --- what a person reads of their own -------------------------------------------------


def test_me_carries_the_contact_and_the_operators_with_their_versions(
    client: TestClient, admin: dict
) -> None:
    kim, made = _person(client, admin)
    me = _me(client, kim)
    contact = Maker(client, admin).get(f"/contacts/{made['user']['contact_hid']}")
    assert me["contact"] == {
        "hid": contact["hid"],
        **KIM,
        "record_status": "active",
        "row_version": contact["row_version"],
    }
    operator = made["operator"]
    assert me["operators"] == [
        {
            "hid": operator["hid"],
            "label": "klee",
            "colour": operator["colour"],
            "record_status": "active",
            "row_version": operator["row_version"],
        }
    ]
    # The rest is the user as before, and its notes are nobody's to read here.
    assert (me["username"], me["role"], me["display_name"], me["notes"]) == (
        "klee",
        "viewer",
        "Kim Lee",
        None,
    )


def test_signing_in_answers_the_same_as_me(client: TestClient, admin: dict) -> None:
    kim, _ = _person(client, admin)
    signed = client.post(f"{API}/auth/sign-in", json={"username": "klee", "access_code": CODE})
    assert signed.status_code == 200, signed.text
    user = signed.json()["user"]
    me = _me(client, kim)
    # Signing in again moved the time of the last sign-in, and nothing else.
    assert {**user, "last_sign_in_at": None, "updated_at": None, "row_version": 0} == {
        **me,
        "last_sign_in_at": None,
        "updated_at": None,
        "row_version": 0,
    }
    assert user["contact"]["row_version"] == me["contact"]["row_version"]
    assert user["operators"] == me["operators"]


def test_me_lists_the_operators_by_label_and_leaves_the_retired_out(
    client: TestClient, admin: dict
) -> None:
    kim, made = _person(client, admin)
    desk = Maker(client, admin)
    contact_hid = made["user"]["contact_hid"]
    for label in ("zz-late", "Aa-early", "mm-gone"):
        desk.post("/operators", {"label": label, "contact_hid": contact_hid})
    draft = desk.post(
        "/operators", {"label": "dd-draft", "contact_hid": contact_hid, "record_status": "draft"}
    )
    gone = next(
        one for one in desk.get("/operators", limit=100)["items"] if one["label"] == "mm-gone"
    )
    desk.release(gone)
    desk.post("/operators", {"label": "another"})

    me = _me(client, kim)
    assert [one["label"] for one in me["operators"]] == ["Aa-early", "dd-draft", "klee", "zz-late"]
    assert {one["hid"]: one["record_status"] for one in me["operators"]}[draft["hid"]] == "draft"


def test_an_account_with_no_contact_and_a_service_account_have_none(
    client: TestClient, admin: dict, viewer: dict
) -> None:
    me = _me(client, viewer)
    assert (me["contact"], me["contact_hid"], me["operators"]) == (None, None, [])

    desk = Maker(client, admin)
    probe = desk.post("/users", {"username": "probe", "is_service_account": True, "role": "viewer"})
    secret = desk.post(f"/users/{probe['user']['hid']}/service-tokens", {"name": "probe"})["secret"]
    me = _me(client, {"Authorization": f"Bearer {secret}"})
    assert (me["contact"], me["operators"], me["is_service_account"]) == (None, [], True)


def test_a_retired_contact_is_shown_retired_and_stands_behind_no_operator(
    client: TestClient, admin: dict, db: Session
) -> None:
    """A contact left retired under its account, as a release before 0.9.14 could leave
    one: from 0.9.14 a contact is not retired while its account stands on it (P-297)."""
    kim, made = _person(client, admin)
    left_retired(db, made["user"]["contact_hid"])
    me = _me(client, kim)
    assert me["contact"]["record_status"] == "retired"
    assert me["operators"] == []


# --- the contact ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("username", "code", "role"),
    [
        ("vic", VIEWER_CODE, "viewer"),
        ("ivy", INVENTORY_CODE, "inventory"),
        ("ada", ADMIN_CODE, "admin"),
    ],
)
def test_each_role_changes_its_own_contact_and_is_named_in_the_audit_trail(
    client: TestClient, admin: dict, username: str, code: str, role: str
) -> None:
    desk = Maker(client, admin)
    contact = desk.contact("Example Person", email="example.person@example.com")
    who = next(u for u in desk.get("/users", limit=100)["items"] if u["username"] == username)
    desk.patch(
        f"/users/{who['hid']}", {"row_version": who["row_version"], "contact_hid": contact["hid"]}
    )
    own = sign_in(client, username, code)
    before = _me(client, own)
    assert before["role"] == role

    response = client.patch(
        f"{API}/auth/me/contact",
        headers=own,
        json={"row_version": before["contact"]["row_version"], **KIM},
    )
    assert response.status_code == 200, response.text
    me = response.json()
    assert me == _me(client, own)
    assert me["contact"] == {
        "hid": contact["hid"],
        **KIM,
        "record_status": "active",
        "row_version": before["contact"]["row_version"] + 1,
    }
    assert (me["display_name"], me["email"]) == ("Kim Lee", "kim.lee@example.com")
    # The contact everybody reads is the one that changed.
    assert desk.get(f"/contacts/{contact['hid']}")["organization"] == "Example Networks"

    events = _events(
        client,
        admin,
        record_type="contact",
        record_hid=contact["hid"],
        action="update",
        actor_hid=who["hid"],
    )
    # The Admin who gave their own account its contact is named by that change too.
    assert len(events) == (2 if role == "admin" else 1)
    event = events[0]
    assert {entry["field"]: entry["new"] for entry in event["changes"]} == KIM
    assert event["actor_name"] == username


def test_a_field_left_out_stays_and_a_null_or_a_blank_clears(
    client: TestClient, admin: dict
) -> None:
    kim, _ = _person(client, admin)
    version = _me(client, kim)["contact"]["row_version"]
    response = client.patch(
        f"{API}/auth/me/contact",
        headers=kim,
        json={"row_version": version, "phone2": None, "organization": "  "},
    )
    assert response.status_code == 200, response.text
    contact = response.json()["contact"]
    assert contact == {
        **contact,
        "name": "Kim Lee",
        "email": "kim.lee@example.com",
        "phone": "+1 555 0100",
        "phone2": None,
        "organization": None,
    }
    # A name is never blank, and nothing is changed by a request that is refused.
    blank = client.patch(
        f"{API}/auth/me/contact",
        headers=kim,
        json={"row_version": contact["row_version"], "name": " ", "phone": "+1 555 0199"},
    )
    assert blank.status_code == 422
    assert "name" in errors(blank.json())
    assert _me(client, kim)["contact"] == contact


@pytest.mark.parametrize(
    "more",
    [
        {"notes": "mine"},
        {"tags": ["mine"]},
        {"record_status": "draft"},
        {"contact_hid": "x"},
        {"hid": "x"},
    ],
)
def test_nothing_else_of_a_contact_is_changed_on_a_profile(
    client: TestClient, admin: dict, more: dict[str, Any]
) -> None:
    kim, _ = _person(client, admin)
    before = _me(client, kim)
    response = client.patch(
        f"{API}/auth/me/contact",
        headers=kim,
        json={"row_version": before["contact"]["row_version"], "name": "Kim A. Lee", **more},
    )
    assert response.status_code == 422, response.text
    assert list(errors(response.json())) == list(more)
    assert _me(client, kim) == before


def test_an_account_with_no_contact_or_a_retired_one_is_told_so(
    client: TestClient, admin: dict, viewer: dict, db: Session
) -> None:
    none = client.patch(
        f"{API}/auth/me/contact", headers=viewer, json={"row_version": 1, "name": "Vic Example"}
    )
    assert none.status_code == 409
    assert "no contact" in none.json()["detail"]

    kim, made = _person(client, admin)
    desk = Maker(client, admin)
    # Left retired under its account, as a release before 0.9.14 could leave one (P-297).
    left_retired(db, made["user"]["contact_hid"])
    retired = desk.get(f"/contacts/{made['user']['contact_hid']}")
    contact = retired
    assert retired["record_status"] == "retired"
    refused = client.patch(
        f"{API}/auth/me/contact",
        headers=kim,
        json={"row_version": retired["row_version"], "name": "Kim A. Lee"},
    )
    assert refused.status_code == 409
    assert "retired" in refused.json()["detail"]
    assert desk.get(f"/contacts/{contact['hid']}")["name"] == "Kim Lee"


def test_the_rules_of_a_contact_hold_an_email_of_another_and_a_stale_version(
    client: TestClient, admin: dict
) -> None:
    kim, _ = _person(client, admin)
    other = Maker(client, admin).contact("Sam Okafor", email="sam.okafor@example.com")
    version = _me(client, kim)["contact"]["row_version"]

    taken = client.patch(
        f"{API}/auth/me/contact",
        headers=kim,
        json={"row_version": version, "email": "SAM.OKAFOR@example.com"},
    )
    assert taken.status_code == 409
    assert taken.json()["existing"] == {
        "hid": other["hid"],
        "record_type": "contact",
        "label": "Sam Okafor",
    }
    assert "email" in errors(taken.json())

    wrong = client.patch(
        f"{API}/auth/me/contact", headers=kim, json={"row_version": version, "email": "kim"}
    )
    assert wrong.status_code == 422
    assert "email" in errors(wrong.json())

    stale = client.patch(
        f"{API}/auth/me/contact", headers=kim, json={"row_version": version + 5, "name": "K. Lee"}
    )
    assert stale.status_code == 409
    assert stale.json()["title"] == "Stale version"
    assert _me(client, kim)["contact"]["name"] == "Kim Lee"


# --- the operators --------------------------------------------------------------------


@pytest.mark.parametrize("role", ["viewer", "inventory", "admin"])
def test_each_role_changes_the_label_and_the_colour_of_its_own_operator(
    client: TestClient, admin: dict, role: str
) -> None:
    kim, made = _person(client, admin, role=role)
    operator = made["operator"]
    response = client.patch(
        f"{API}/auth/me/operators/{operator['hid']}",
        headers=kim,
        json={"row_version": operator["row_version"], "label": "KL", "colour": "#1F6FEB"},
    )
    assert response.status_code == 200, response.text
    me = response.json()
    assert me == _me(client, kim)
    assert me["operators"] == [
        {
            "hid": operator["hid"],
            "label": "KL",
            "colour": "#1f6feb",
            "record_status": "active",
            "row_version": operator["row_version"] + 1,
        }
    ]
    read = Maker(client, admin).get(f"/operators/{operator['hid']}")
    assert (read["label"], read["colour"], read["contact_hid"]) == (
        "KL",
        "#1f6feb",
        made["user"]["contact_hid"],
    )
    (event,) = _events(
        client, admin, record_type="operator", record_hid=operator["hid"], action="update"
    )
    assert event["actor_hid"] == made["user"]["hid"]
    assert {entry["field"]: (entry["old"], entry["new"]) for entry in event["changes"]} == {
        "label": ("klee", "KL"),
        "colour": (operator["colour"], "#1f6feb"),
    }


def test_a_person_behind_several_labels_changes_each(client: TestClient, admin: dict) -> None:
    kim, made = _person(client, admin)
    desk = Maker(client, admin)
    second = desk.post(
        "/operators", {"label": "klee-night", "contact_hid": made["user"]["contact_hid"]}
    )
    for operator, label in ((made["operator"], "kl-day"), (second, "kl-night")):
        response = client.patch(
            f"{API}/auth/me/operators/{operator['hid']}",
            headers=kim,
            json={"row_version": operator["row_version"], "label": label},
        )
        assert response.status_code == 200, response.text
    assert [one["label"] for one in _me(client, kim)["operators"]] == ["kl-day", "kl-night"]


def test_an_operator_of_another_a_retired_one_and_one_there_is_not_are_not_found(
    client: TestClient, admin: dict
) -> None:
    kim, made = _person(client, admin)
    sam, sams = _person(
        client,
        admin,
        username="sokafor",
        contact={"name": "Sam Okafor", "email": "sam.okafor@example.com"},
    )
    desk = Maker(client, admin)
    open_label = desk.post("/operators", {"label": "open-label"})
    mine = desk.post("/operators", {"label": "kl-old", "contact_hid": made["user"]["contact_hid"]})
    retired = desk.release(mine)
    events = len(_events(client, admin, record_type="operator", limit=500))
    for operator in (
        sams["operator"],
        open_label,
        retired,
        {"hid": "no-such-hid", "row_version": 1},
    ):
        response = client.patch(
            f"{API}/auth/me/operators/{operator['hid']}",
            headers=kim,
            json={"row_version": operator["row_version"], "label": "taken-over"},
        )
        assert response.status_code == 404, response.text
    assert _me(client, sam)["operators"][0]["label"] == "sokafor"
    assert desk.get(f"/operators/{retired['hid']}")["label"] == "kl-old"
    assert len(_events(client, admin, record_type="operator", limit=500)) == events


@pytest.mark.parametrize(
    "more",
    [{"contact_hid": None}, {"description": "mine"}, {"record_status": "draft"}],
)
def test_nothing_else_of_an_operator_is_changed_on_a_profile(
    client: TestClient, admin: dict, more: dict[str, Any]
) -> None:
    kim, made = _person(client, admin)
    before = _me(client, kim)
    response = client.patch(
        f"{API}/auth/me/operators/{made['operator']['hid']}",
        headers=kim,
        json={"row_version": made["operator"]["row_version"], "label": "KL", **more},
    )
    assert response.status_code == 422, response.text
    assert list(errors(response.json())) == list(more)
    assert _me(client, kim) == before


def test_the_rules_of_an_operator_hold_a_label_of_another_a_colour_and_a_stale_version(
    client: TestClient, admin: dict
) -> None:
    kim, made = _person(client, admin)
    operator = made["operator"]
    other = Maker(client, admin).post("/operators", {"label": "Night-Desk"})
    url = f"{API}/auth/me/operators/{operator['hid']}"
    version = operator["row_version"]

    taken = client.patch(url, headers=kim, json={"row_version": version, "label": "night-desk"})
    assert taken.status_code == 409
    assert taken.json()["existing"] == {
        "hid": other["hid"],
        "record_type": "operator",
        "label": "Night-Desk",
    }
    for body, field in (
        ({"label": " "}, "label"),
        ({"label": "a;b"}, "label"),
        ({"colour": "blue"}, "colour"),
    ):
        refused = client.patch(url, headers=kim, json={"row_version": version, **body})
        assert refused.status_code == 422, refused.text
        assert field in errors(refused.json())
    stale = client.patch(url, headers=kim, json={"row_version": version + 3, "label": "KL"})
    assert stale.status_code == 409
    assert stale.json()["title"] == "Stale version"
    # A colour given as null is none.
    cleared = client.patch(url, headers=kim, json={"row_version": version, "colour": None})
    assert cleared.status_code == 200
    assert cleared.json()["operators"][0]["colour"] is None


# --- whose routes these are -----------------------------------------------------------


def _writes(operator_hid: str = "no-such-hid") -> list[tuple[str, str, dict[str, Any]]]:
    return [
        ("patch", "/auth/me/contact", {"row_version": 1, "name": "Kim Lee"}),
        ("patch", f"/auth/me/operators/{operator_hid}", {"row_version": 1, "label": "KL"}),
        ("post", "/auth/me/access-code", {"current_access_code": CODE, "access_code": NEW_CODE}),
    ]


def test_a_service_token_has_no_profile(client: TestClient, admin: dict) -> None:
    desk = Maker(client, admin)
    probe = desk.post("/users", {"username": "probe", "is_service_account": True, "role": "admin"})
    secret = desk.post(f"/users/{probe['user']['hid']}/service-tokens", {"name": "probe"})["secret"]
    token = {"Authorization": f"Bearer {secret}"}
    for method, path, body in _writes():
        response = client.request(method, API + path, headers=token, json=body)
        assert response.status_code == 403, (path, response.text)
        assert "service account" in response.json()["detail"]


def test_nobody_signed_in_is_refused(client: TestClient) -> None:
    for method, path, body in _writes():
        assert client.request(method, API + path, json=body).status_code == 401, path


def test_an_account_with_no_role_changes_what_is_its_own(client: TestClient, admin: dict) -> None:
    """An account that is brought back has a new code and no role (P-296): the person
    changes the code they were given, and their own details, before a role is theirs."""
    nobody, made = _person(client, admin, role=None)
    assert _me(client, nobody)["role"] is None
    # The inventory is closed to them, the list of contacts too.
    assert client.get(f"{API}/contacts", headers=nobody).status_code == 403

    contact = client.patch(
        f"{API}/auth/me/contact",
        headers=nobody,
        json={"row_version": _me(client, nobody)["contact"]["row_version"], "phone": "+1 555 0142"},
    )
    assert contact.status_code == 200, contact.text
    assert contact.json()["contact"]["phone"] == "+1 555 0142"
    operator = client.patch(
        f"{API}/auth/me/operators/{made['operator']['hid']}",
        headers=nobody,
        json={"row_version": made["operator"]["row_version"], "label": "KL"},
    )
    assert operator.status_code == 200, operator.text
    assert operator.json()["operators"][0]["label"] == "KL"

    changed = _change(client, nobody, CODE, NEW_CODE)
    assert changed.status_code == 200, changed.text
    assert changed.json()["user"]["role"] is None
    assert _signs_in(client, "klee", CODE) == 401
    assert _signs_in(client, "klee", NEW_CODE) == 200
    actors = {
        event["actor_hid"]
        for event in _events(client, admin, actor_hid=made["user"]["hid"], limit=100)
        if event["action"] in ("update", "set_access_code")
    }
    assert actors == {made["user"]["hid"]}
    assert len(_events(client, admin, actor_hid=made["user"]["hid"], action="update")) == 2


# --- the access code ------------------------------------------------------------------


def _change(client: TestClient, headers: dict, current: str, new: str) -> Any:
    return client.post(
        f"{API}/auth/me/access-code",
        headers=headers,
        json={"current_access_code": current, "access_code": new},
    )


def _signs_in(client: TestClient, username: str, code: str) -> int:
    response = client.post(f"{API}/auth/sign-in", json={"username": username, "access_code": code})
    return response.status_code


@pytest.mark.parametrize("role", ["viewer", "inventory", "admin"])
def test_a_person_changes_their_code_and_keeps_the_session_in_hand(
    client: TestClient, admin: dict, role: str
) -> None:
    kim, made = _person(client, admin, role=role)
    elsewhere = sign_in(client, "klee", CODE)

    response = _change(client, kim, CODE, NEW_CODE)
    assert response.status_code == 200, response.text
    session = response.json()
    assert set(session) == {"token", "expires_at", "user"}
    in_hand = {"Authorization": f"Bearer {session['token']}"}
    assert session["user"] == _me(client, in_hand)
    assert session["user"]["username"] == "klee"

    # Every other session has ended, the token that was sent among them.
    assert client.get(f"{API}/auth/me", headers=elsewhere).status_code == 401
    assert client.get(f"{API}/auth/me", headers=kim).status_code == 401
    # The old code signs in no longer, and the new one does.
    assert _signs_in(client, "klee", CODE) == 401
    assert _signs_in(client, "klee", NEW_CODE) == 200
    # Signing in again ended nothing: the session in hand is alive.
    assert client.get(f"{API}/auth/me", headers=in_hand).status_code == 200

    (event,) = _events(client, admin, action="set_access_code", record_hid=made["user"]["hid"])
    assert (event["actor_hid"], event["record_type"]) == (made["user"]["hid"], "user")
    assert NEW_CODE not in str(event)
    assert CODE not in str(event)


def test_a_wrong_current_code_is_refused_counted_and_written_down(
    client: TestClient, admin: dict
) -> None:
    kim, made = _person(client, admin)
    response = _change(client, kim, "not-the-code-i-have", NEW_CODE)
    assert response.status_code == 422, response.text
    assert list(errors(response.json())) == ["current_access_code"]

    # Nothing is changed: the session stands, and the code is the one it was.
    assert client.get(f"{API}/auth/me", headers=kim).status_code == 200
    assert _signs_in(client, "klee", NEW_CODE) == 401
    # The refusal is kept, by the person, though the request was refused.
    (event,) = _events(client, admin, action="access_code_refused")
    assert (event["actor_hid"], event["record_type"], event["record_hid"]) == (
        made["user"]["hid"],
        "user",
        made["user"]["hid"],
    )
    assert "not-the-code-i-have" not in str(event)
    assert _events(client, admin, action="set_access_code", record_hid=made["user"]["hid"]) == []


@pytest.mark.parametrize(
    ("new", "says"),
    [
        ("eleven-char", "at least 12 characters"),
        ("", "must not be empty"),
        (" a-code-with-a-space", "space"),
        ("a-code-with-a-space ", "space"),
    ],
)
def test_a_new_code_that_is_too_short_or_blank_changes_nothing(
    client: TestClient, admin: dict, new: str, says: str
) -> None:
    kim, made = _person(client, admin)
    response = _change(client, kim, CODE, new)
    assert response.status_code == 422, response.text
    problem = errors(response.json())
    assert list(problem) == ["access_code"]
    assert says in problem["access_code"]
    assert client.get(f"{API}/auth/me", headers=kim).status_code == 200
    assert _signs_in(client, "klee", CODE) == 200
    assert _events(client, admin, action="set_access_code", record_hid=made["user"]["hid"]) == []
    assert _events(client, admin, action="access_code_refused") == []


def test_the_current_code_is_looked_at_first(client: TestClient, admin: dict) -> None:
    kim, _ = _person(client, admin)
    response = _change(client, kim, "not-the-code-i-have", "short")
    assert response.status_code == 422
    assert list(errors(response.json())) == ["current_access_code"]
    assert len(_events(client, admin, action="access_code_refused")) == 1


def test_the_sixth_wrong_code_is_delayed_as_a_sign_in_is_and_sign_in_with_it(
    client: TestClient, admin: dict
) -> None:
    kim, made = _person(client, admin)
    statuses = [_change(client, kim, f"wrong-code-{n}", NEW_CODE) for n in range(6)]
    assert [r.status_code for r in statuses] == [422, 422, 422, 422, 422, 429]
    assert int(statuses[5].headers["retry-after"]) >= 1
    # The right code is delayed too while the wait lasts, here and at sign-in.
    assert _change(client, kim, CODE, NEW_CODE).status_code == 429
    assert _signs_in(client, "klee", CODE) == 429
    # Nothing was changed, and the session was not ended.
    assert client.get(f"{API}/auth/me", headers=kim).status_code == 200

    refused = _events(client, admin, action="access_code_refused")
    delayed = _events(client, admin, action="access_code_delayed")
    assert (len(refused), len(delayed)) == (5, 2)
    assert {event["actor_hid"] for event in refused + delayed} == {made["user"]["hid"]}
    assert {event["record_hid"] for event in refused + delayed} == {made["user"]["hid"]}


def test_failed_sign_ins_delay_a_change_of_the_code(client: TestClient, admin: dict) -> None:
    kim, _ = _person(client, admin)
    assert [_signs_in(client, "KLEE", f"wrong-code-{n}") for n in range(5)] == [401] * 5
    assert _change(client, kim, CODE, NEW_CODE).status_code == 429
    assert _signs_in(client, "klee", NEW_CODE) == 429


def test_the_right_code_clears_the_count(client: TestClient, admin: dict) -> None:
    kim, _ = _person(client, admin)
    assert [_change(client, kim, f"wrong-code-{n}", NEW_CODE).status_code for n in range(4)] == [
        422
    ] * 4
    changed = _change(client, kim, CODE, NEW_CODE)
    assert changed.status_code == 200
    kim = {"Authorization": f"Bearer {changed.json()['token']}"}
    # Four more wrong ones are four, and not nine: the fifth of them is not yet delayed.
    assert [_change(client, kim, f"wrong-code-{n}", CODE).status_code for n in range(5)] == [
        422
    ] * 5
    assert _change(client, kim, NEW_CODE, CODE).status_code == 429
