"""A new person is made in one step: the user, the contact it is and the operator it works
as, with its role and its groups (P-282, P-283); who is a user, a contact and an operator
is said on each list, which finds the gaps (P-280); a user has notes (P-281). Through the
API."""

from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event, update
from sqlalchemy.orm import Session

from hirdir.db.models import UserGroup
from tests.api.inventory import API, Maker, errors
from tests.conftest import ADMIN_CODE, VIEWER_CODE

PERSON = {"name": "Example Person", "email": "example.person@example.net", "phone": "x1"}


def _held(desk: Maker) -> dict[str, Any]:
    """Return how many of each record there is, and how many audit events."""
    return {
        "users": desk.get("/users", limit=1)["total"],
        "contacts": desk.get("/contacts", limit=1, include_drafts="true")["total"],
        "operators": desk.get("/operators", limit=1, include_drafts="true")["total"],
        "grants": len(desk.get("/role-grants")),
        "members": sum(group["member_count"] for group in desk.get("/user-groups")),
        "events": desk.get("/audit-events", limit=1)["total"],
    }


def _groups(desk: Maker, *names: str) -> list[dict[str, Any]]:
    return [desk.post("/user-groups", {"name": name}) for name in names]


def _refused(client: TestClient, admin: dict, body: dict[str, Any], status: int) -> dict:
    response = client.post(f"{API}/users", json=body, headers=admin)
    assert response.status_code == status, response.text
    return response.json()


# --- all three in one step -------------------------------------------------------------


def test_a_person_is_made_with_contact_operator_role_and_groups_in_one_request(
    client: TestClient, admin: dict
) -> None:
    desk = Maker(client, admin)
    engineers, night = _groups(desk, "Example Engineers", "Example Night Shift")
    colour = desk.get("/colours")["next_for_operators"]
    response = client.post(
        f"{API}/users",
        json={
            "username": "ex-ops",
            "contact": PERSON,
            "operator": {},
            "role": "inventory",
            "group_hids": [night["hid"], engineers["hid"], night["hid"]],
            "notes": "  Asked for by the example team; ends 2027-06-30.  ",
        },
        headers=admin,
    )
    assert response.status_code == 201, response.text
    made = response.json()
    user, operator = made["user"], made["operator"]
    assert made["access_code"]

    # The operator is the user's: its label the username, its colour the next unused.
    assert (operator["label"], operator["colour"]) == ("ex-ops", colour)
    assert operator["contact_hid"] == user["contact_hid"]
    assert operator["user"] == {"hid": user["hid"], "username": "ex-ops"}
    assert operator["scope"] == "internal"
    assert operator == desk.get(f"/operators/{operator['hid']}")
    assert user["operators"] == [
        {"hid": operator["hid"], "label": "ex-ops", "colour": colour, "record_status": "active"}
    ]
    assert user["contact"]["name"] == "Example Person"
    assert user["role"] == "inventory"
    assert [group["name"] for group in user["groups"]] == [
        "Example Engineers",
        "Example Night Shift",
    ]
    assert user["notes"] == "Asked for by the example team; ends 2027-06-30."
    assert desk.get(f"/users/{user['hid']}") == user

    # The contact says it is a user and an operator.
    contact = desk.get(f"/contacts/{user['contact_hid']}")
    assert (contact["is_user"], contact["is_operator"]) == (True, True)
    assert contact["operators"] == user["operators"]

    # Each part is audited as if it were made by itself, under the one request.
    request = response.headers["X-Request-Id"]
    events = desk.get("/audit-events", request_id=request, sort="at", limit=100)["items"]
    done = sorted((one["action"], one["record_type"], one["record_hid"]) for one in events)
    assert done == sorted(
        [
            ("create", "contact", user["contact_hid"]),
            ("create", "user", user["hid"]),
            ("update", "contact", user["contact_hid"]),
            ("grant_role", "user", user["hid"]),
            ("add_member", "user_group", engineers["hid"]),
            ("add_member", "user_group", night["hid"]),
            ("create", "operator", operator["hid"]),
        ]
    )
    created_user = next(one for one in events if one["record_type"] == "user")
    assert {"field": "notes", "old": None, "new": user["notes"]} in created_user["changes"]

    # The operator's event is the one POST /operators writes for the same fields.
    alone = client.post(
        f"{API}/operators",
        json={"label": "ex-alone", "colour": "#0169cd", "contact_hid": user["contact_hid"]},
        headers=admin,
    )
    by_itself = desk.audit(record_type="operator", record_hid=alone.json()["hid"])[0]
    with_user = next(one for one in events if one["record_type"] == "operator")
    assert [c["field"] for c in with_user["changes"]] == [c["field"] for c in by_itself["changes"]]
    member = next(one for one in events if one["action"] == "add_member")
    assert member["changes"] == [{"field": "user_hid", "old": None, "new": user["hid"]}]

    # A contact there already, an operator with a label, a colour and a description.
    known = desk.contact("Example Contractor")
    second = desk.post(
        "/users",
        {
            "username": "ex-contractor",
            "contact_hid": known["hid"],
            "operator": {"label": "EX-C", "colour": "#1D84F5", "description": "Night calls."},
        },
    )
    assert (second["operator"]["label"], second["operator"]["colour"]) == ("EX-C", "#1d84f5")
    assert second["operator"]["description"] == "Night calls."
    assert second["operator"]["contact_hid"] == known["hid"]
    # No operator asked for: none made, and the answer says so.
    plain = desk.post("/users", {"username": "ex-plain", "contact": {"name": "Example Plain"}})
    assert (plain["operator"], plain["user"]["operators"]) == (None, [])


def test_the_colour_left_out_is_the_next_unused_and_a_blank_one_is_none(
    client: TestClient, admin: dict
) -> None:
    desk = Maker(client, admin)
    first = desk.post("/users", {"username": "ex-a", "contact": {"name": "A"}, "operator": {}})
    after = desk.get("/colours")["next_for_operators"]
    second = desk.post("/users", {"username": "ex-b", "contact": {"name": "B"}, "operator": {}})
    assert first["operator"]["colour"] != second["operator"]["colour"] == after
    none = desk.post(
        "/users", {"username": "ex-c", "contact": {"name": "C"}, "operator": {"colour": None}}
    )
    blank = desk.post(
        "/users",
        {"username": "ex-d", "contact": {"name": "D"}, "operator": {"colour": "", "label": " "}},
    )
    assert none["operator"]["colour"] is blank["operator"]["colour"] is None
    # A blank label is the username, as one left out is.
    assert blank["operator"]["label"] == "ex-d"


# --- a refusal makes nothing -----------------------------------------------------------


REFUSALS = [
    pytest.param(
        {"username": "ex-ops", "operator": {}}, 422, "operator", id="operator without contact"
    ),
    pytest.param(
        {"username": "ex-bot", "is_service_account": True, "operator": {}},
        422,
        "operator",
        id="operator of a service account",
    ),
    pytest.param(
        {"username": "ex-ops", "contact": PERSON, "operator": {"label": "EX-TAKEN"}},
        409,
        "operator.label",
        id="label another has",
    ),
    pytest.param(
        {"username": "ex-taken", "contact": PERSON, "operator": {}},
        409,
        "operator.label",
        id="username another operator's label",
    ),
    pytest.param(
        {"username": "ex-" + "o" * 40, "contact": PERSON, "operator": {}},
        422,
        "operator.label",
        id="username too long for a label",
    ),
    pytest.param(
        {"username": "ex-ops", "contact": PERSON, "operator": {"label": "ex;ops"}},
        422,
        "operator.label",
        id="label with a semicolon",
    ),
    pytest.param(
        {"username": "ex-ops", "contact": PERSON, "operator": {"colour": "orange"}},
        422,
        "operator.colour",
        id="colour not of the form",
    ),
    pytest.param(
        {"username": "ex-ops", "contact": PERSON, "group_hids": ["GROUP"]},
        422,
        "group_hids",
        id="group there is not",
    ),
    pytest.param(
        {"username": "ex-ops", "contact": PERSON, "operator": {}, "role": "owner"},
        422,
        "role",
        id="role there is not",
    ),
    pytest.param(
        {"username": "ex-ops", "contact": {"name": " "}, "operator": {}},
        422,
        "contact.name",
        id="contact with a blank name",
    ),
    pytest.param(
        {"username": "ada", "contact": PERSON, "operator": {}},
        409,
        "username",
        id="username another user has",
    ),
]


@pytest.mark.parametrize(("body", "status", "field"), REFUSALS)
def test_a_refused_part_leaves_nothing_made_and_no_event(
    client: TestClient, admin: dict, body: dict[str, Any], status: int, field: str
) -> None:
    desk = Maker(client, admin)
    group = _groups(desk, "Example Engineers")[0]
    taken = desk.post("/operators", {"label": "EX-TAKEN", "colour": "#0169cd"})
    body = {**body, "group_hids": body.get("group_hids", [group["hid"]])}
    if body["group_hids"] == ["GROUP"]:
        body["group_hids"] = [group["hid"], "01J0000000000000000000NONE"]
    before = _held(desk)

    problem = _refused(client, admin, body, status)

    assert field in errors(problem), problem
    if field == "operator.label" and status == 409:
        assert problem["existing"] == {
            "hid": taken["hid"],
            "record_type": "operator",
            "label": "EX-TAKEN",
        }
    assert _held(desk) == before


# --- who is a user, a contact and an operator, and the gaps ------------------------------


def _usernames(desk: Maker, **params: Any) -> list[str]:
    return [one["username"] for one in desk.get("/users", **params)["items"]]


def test_the_users_are_narrowed_to_those_with_no_contact_and_no_operator(
    client: TestClient, admin: dict
) -> None:
    desk = Maker(client, admin)
    # ada, ivy and vic, made by the fixture, are no contact and so behind no operator.
    two = desk.post("/users", {"username": "ex-two", "contact": PERSON, "operator": {"label": "B"}})
    desk.post("/operators", {"label": "A", "contact_hid": two["user"]["contact_hid"]})
    gone = desk.post("/users", {"username": "ex-gone", "contact": {"name": "G"}, "operator": {}})
    desk.post(f"/operators/{gone['operator']['hid']}/retire", {"row_version": 1}, expect=200)
    desk.post("/users", {"username": "ex-none", "contact": {"name": "N"}})
    desk.post("/users", {"username": "ex-bot", "is_service_account": True})

    everyone = ["ada", "ex-bot", "ex-gone", "ex-none", "ex-two", "ivy", "vic"]
    assert _usernames(desk) == _usernames(desk, contact="any", operator="any") == everyone
    assert _usernames(desk, contact="some") == ["ex-gone", "ex-none", "ex-two"]
    # A service account is no person, and is in no gap.
    assert _usernames(desk, contact="none") == ["ada", "ivy", "vic"]
    assert _usernames(desk, operator="some") == ["ex-two"]
    # A retired operator stands for nobody: its user is behind none.
    assert _usernames(desk, operator="none") == ["ada", "ex-gone", "ex-none", "ivy", "vic"]
    assert _usernames(desk, contact="some", operator="none") == ["ex-gone", "ex-none"]
    assert desk.get("/users", operator="none", limit=2)["total"] == 5
    assert client.get(f"{API}/users", params={"operator": "few"}, headers=admin).status_code == 422

    # Each user lists every operator its contact stands behind, by label, a retired one
    # marked so; the list is sorted by the first of them.
    found = {one["username"]: one for one in desk.get("/users")["items"]}
    assert [one["label"] for one in found["ex-two"]["operators"]] == ["A", "B"]
    assert [one["record_status"] for one in found["ex-gone"]["operators"]] == ["retired"]
    assert found["ex-bot"]["operators"] == found["ada"]["operators"] == []
    assert _usernames(desk, sort="operators")[:2] == ["ex-two", "ex-gone"]
    assert _usernames(desk, sort="-operators")[:2] == ["ex-gone", "ex-two"]


def test_the_contacts_say_and_find_who_is_behind_an_operator(
    client: TestClient, admin: dict, viewer: dict
) -> None:
    desk, reader = Maker(client, admin), Maker(client, viewer)
    both = desk.contact("Example Both")
    for label in ("EX-2", "EX-1"):
        desk.post("/operators", {"label": label, "contact_hid": both["hid"]})
    retired = desk.contact("Example Retired")
    gone = desk.post("/operators", {"label": "EX-GONE", "contact_hid": retired["hid"]})
    desk.post(f"/operators/{gone['hid']}/retire", {"row_version": 1}, expect=200)
    desk.contact("Example Nobody")

    # Every role reads them.
    page = {one["name"]: one for one in reader.get("/contacts")["items"]}
    assert [one["label"] for one in page["Example Both"]["operators"]] == ["EX-1", "EX-2"]
    assert page["Example Both"]["is_operator"] is True
    assert page["Example Retired"]["is_operator"] is False
    assert page["Example Retired"]["operators"][0]["record_status"] == "retired"
    assert (page["Example Nobody"]["is_operator"], page["Example Nobody"]["operators"]) == (
        False,
        [],
    )
    assert reader.get(f"/contacts/{both['hid']}")["operators"] == page["Example Both"]["operators"]

    def names(**params: Any) -> list[str]:
        return [one["name"] for one in reader.get("/contacts", **params)["items"]]

    assert names(filter="is_operator:eq:true") == ["Example Both"]
    assert names(filter="is_operator:eq:false") == ["Example Nobody", "Example Retired"]
    assert names(sort="-is_operator,name")[0] == "Example Both"


def test_a_retired_contact_is_as_no_contact_for_the_gaps_and_still_answered(
    client: TestClient, admin: dict, viewer: dict
) -> None:
    """A user whose contact is retired is in both gaps and in neither `some`, as nobody is
    behind its operator; it still answers what is left over (P-280)."""
    desk = Maker(client, admin)
    made = desk.post("/users", {"username": "ex-left", "contact": PERSON, "operator": {}})
    desk.post("/users", {"username": "ex-ops", "contact": {"name": "Example Ops"}, "operator": {}})
    desk.post("/users", {"username": "ex-bot", "is_service_account": True})
    contact = desk.get(f"/contacts/{made['user']['contact_hid']}")
    desk.post(
        f"/contacts/{contact['hid']}/retire", {"row_version": contact["row_version"]}, expect=200
    )

    assert "ex-left" in _usernames(desk, contact="none")
    assert "ex-left" not in _usernames(desk, contact="some")
    assert "ex-left" in _usernames(desk, operator="none")
    assert "ex-left" not in _usernames(desk, operator="some")
    assert _usernames(desk, operator="some") == ["ex-ops"]
    # Every user is in one of `some` and `none`, or is a service account.
    everyone = sorted(_usernames(desk))
    for which in ("contact", "operator"):
        split = _usernames(desk, **{which: "some"}) + _usernames(desk, **{which: "none"})
        assert sorted([*split, "ex-bot"]) == everyone, which

    # What is left over is still answered, for the page to show it.
    user = desk.get(f"/users/{made['user']['hid']}")
    assert user["contact"]["record_status"] == "retired"
    assert [one["hid"] for one in user["operators"]] == [made["operator"]["hid"]]
    # The three lists agree: nobody is behind the operator, and the contact is none.
    reader = Maker(client, viewer)
    assert reader.get(f"/operators/{made['operator']['hid']}")["scope"] is None
    seen = reader.get(f"/contacts/{contact['hid']}")
    assert (seen["is_operator"], len(seen["operators"])) == (False, 1)

    # A list shows a retired record with include_archived, and the filter says the same.
    def names(**params: Any) -> list[str]:
        return [one["name"] for one in reader.get("/contacts", **params)["items"]]

    assert names(filter="record_status:eq:retired", include_archived="true") == ["Example Person"]
    assert names(filter="is_operator:eq:true", include_archived="true") == ["Example Ops"]
    assert names(filter="is_operator:eq:false", include_archived="true") == ["Example Person"]


def _engine(client: TestClient) -> Engine:
    return cast(FastAPI, client.app).state.engine


def test_the_operators_of_a_page_are_read_in_one_statement(client: TestClient, admin: dict) -> None:
    desk = Maker(client, admin)
    for number in range(6):
        desk.post(
            "/users",
            {"username": f"ex-{number}", "contact": {"name": f"N{number}"}, "operator": {}},
        )
    statements: list[str] = []

    def note(_connection: object, _cursor: object, statement: str, *_more: object) -> None:
        statements.append(statement)

    def read(path: str, limit: int) -> int:
        statements.clear()
        desk.get(path, limit=limit)
        return len([one for one in statements if "FROM operators" in one])

    event.listen(_engine(client), "before_cursor_execute", note)
    try:
        assert read("/users", 3) == read("/users", 9) == 1
        # The count of what names a contact reads the operators too, once for the page.
        assert read("/contacts", 3) == read("/contacts", 9) == 2
    finally:
        event.remove(_engine(client), "before_cursor_execute", note)


def test_a_page_of_users_or_of_groups_costs_the_same_statements_whatever_its_size(
    client: TestClient, admin: dict
) -> None:
    """The role, the groups, the contact and the operators of the users of a page, and the
    roles and the size of each group, are each read once for the page, never for a row."""
    desk = Maker(client, admin)
    groups = _groups(desk, *(f"Example Group {number}" for number in range(8)))
    for number, group in enumerate(groups):
        made = desk.post(
            "/users",
            {"username": f"ex-{number}", "contact": {"name": f"N{number}"}, "operator": {}},
        )["user"]
        desk.post("/role-grants", {"role": "viewer", "group_hid": group["hid"]})
        assert (
            client.put(
                f"{API}/user-groups/{group['hid']}/members/{made['hid']}", headers=admin
            ).status_code
            == 204
        )
    statements: list[str] = []

    def note(_connection: object, _cursor: object, statement: str, *_more: object) -> None:
        statements.append(statement)

    def cost(path: str, **params: Any) -> int:
        statements.clear()
        desk.get(path, **params)
        return len(statements)

    event.listen(_engine(client), "before_cursor_execute", note)
    try:
        assert cost("/users", limit=2) == cost("/users", limit=11)
        assert cost("/users", limit=11, sort="role,groups,operators") == cost(
            "/users", limit=2, sort="role,groups,operators"
        )
        few = cost("/user-groups")
        _groups(desk, *(f"Example Other {number}" for number in range(6)))
        assert cost("/user-groups") == few
    finally:
        event.remove(_engine(client), "before_cursor_execute", note)
    found = {one["username"]: one for one in desk.get("/users")["items"]}
    assert (found["ex-3"]["role"], [g["name"] for g in found["ex-3"]["groups"]]) == (
        "viewer",
        ["Example Group 3"],
    )
    assert found["ada"]["role"] == "admin"


def test_the_gaps_are_found_by_the_index_of_the_operators_contact(
    client: TestClient, admin: dict
) -> None:
    desk = Maker(client, admin)
    desk.post("/users", {"username": "ex-ops", "contact": PERSON, "operator": {}})
    engine = _engine(client)
    seen: list[tuple[str, Any]] = []

    def note(_c: object, _cursor: object, statement: str, parameters: Any, *_more: object) -> None:
        if statement.lstrip().startswith("SELECT") and "FROM users" in statement:
            seen.append((statement, parameters))

    event.listen(engine, "before_cursor_execute", note)
    try:
        assert _usernames(desk, operator="none", contact="none") == ["ada", "ivy", "vic"]
        assert _usernames(desk, operator="some") == ["ex-ops"]
    finally:
        event.remove(engine, "before_cursor_execute", note)
    asked = [one for one in seen if "operators" in one[0]]
    assert asked
    with engine.connect() as connection:
        for statement, parameters in asked:
            plan = connection.exec_driver_sql(f"EXPLAIN QUERY PLAN {statement}", parameters)
            steps = " | ".join(str(row[-1]) for row in plan)
            assert "USING INDEX ix_operators_contact_hid" in steps, steps
            assert "SCAN operators" not in steps, steps


# --- a user's notes ----------------------------------------------------------------------


def test_a_users_notes_are_set_changed_and_cleared_and_each_change_is_audited(
    client: TestClient, admin: dict
) -> None:
    desk = Maker(client, admin)
    made = desk.post("/users", {"username": "ex-ops", "notes": "For the example team."})["user"]
    assert made["notes"] == "For the example team."
    changed = desk.patch(
        f"/users/{made['hid']}", {"row_version": made["row_version"], "notes": "Ends in June."}
    )
    assert changed["notes"] == "Ends in June."
    blank = desk.patch(
        f"/users/{made['hid']}", {"row_version": changed["row_version"], "notes": " "}
    )
    assert blank["notes"] is None
    again = desk.patch(f"/users/{made['hid']}", {"row_version": blank["row_version"], "notes": "x"})
    cleared = desk.patch(
        f"/users/{made['hid']}", {"row_version": again["row_version"], "notes": None}
    )
    assert cleared["notes"] is None
    # Notes left out are left alone; the same notes change nothing.
    same = desk.patch(f"/users/{made['hid']}", {"row_version": cleared["row_version"]})
    assert same["row_version"] == cleared["row_version"]

    trail = desk.audit(record_type="user", record_hid=made["hid"])
    notes = [
        (entry["old"], entry["new"])
        for one in reversed(trail)
        for entry in one["changes"]
        if entry["field"] == "notes"
    ]
    assert notes == [
        (None, "For the example team."),
        ("For the example team.", "Ends in June."),
        ("Ends in June.", None),
        (None, "x"),
        ("x", None),
    ]
    too_long = client.patch(
        f"{API}/users/{made['hid']}",
        json={"row_version": cleared["row_version"], "notes": "n" * 10_001},
        headers=admin,
    )
    assert too_long.status_code == 422
    assert "notes" in errors(too_long.json())
    desk.post("/users", {"username": "ex-b", "notes": "B"})
    desk.post("/users", {"username": "ex-a", "notes": "A"})
    by_notes = [one for one in _usernames(desk, sort="notes") if one in {"ex-a", "ex-b"}]
    assert by_notes == ["ex-a", "ex-b"]
    by_notes = [one for one in _usernames(desk, sort="-notes") if one in {"ex-a", "ex-b"}]
    assert by_notes == ["ex-b", "ex-a"]


def test_the_notes_of_an_account_are_answered_to_an_admin_alone(
    client: TestClient, admin: dict
) -> None:
    """A person never reads what an Admin wrote of their account: not from /auth/me, and
    not from signing in; an Admin reads them by the routes of users alone (P-281)."""
    desk = Maker(client, admin)
    found = {one["username"]: one for one in desk.get("/users")["items"]}
    for name in ("vic", "ada"):
        desk.patch(
            f"/users/{found[name]['hid']}",
            {"row_version": found[name]["row_version"], "notes": f"Of {name}: ends in June."},
        )
    for name, code in (("vic", VIEWER_CODE), ("ada", ADMIN_CODE)):
        signed = client.post(f"{API}/auth/sign-in", json={"username": name, "access_code": code})
        assert signed.status_code == 200, signed.text
        assert signed.json()["user"]["notes"] is None
        token = {"Authorization": f"Bearer {signed.json()['token']}"}
        assert client.get(f"{API}/auth/me", headers=token).json()["notes"] is None
        assert desk.get(f"/users/{found[name]['hid']}")["notes"] == f"Of {name}: ends in June."
    listed = {one["username"]: one["notes"] for one in desk.get("/users")["items"]}
    assert listed["vic"] == "Of vic: ends in June."


# --- roles -------------------------------------------------------------------------------


def test_only_an_admin_makes_a_user_and_every_role_reads_the_operators_of_contacts(
    client: TestClient, admin: dict, inventory: dict, viewer: dict
) -> None:
    body = {"username": "ex-ops", "contact": PERSON, "operator": {}}
    for headers in (inventory, viewer):
        assert client.post(f"{API}/users", json=body, headers=headers).status_code == 403
        assert client.get(f"{API}/users", headers=headers).status_code == 403
    made = Maker(client, admin).post("/users", body)
    for headers in (admin, inventory, viewer):
        seen = Maker(client, headers).get(f"/contacts/{made['user']['contact_hid']}")
        assert seen["operators"][0]["hid"] == made["operator"]["hid"]


# --- the name of a user group --------------------------------------------------------------


def test_a_user_groups_name_holds_no_semicolon_which_separates_groups_in_a_file(
    client: TestClient, admin: dict, db: Session
) -> None:
    desk = Maker(client, admin)
    refused = client.post(f"{API}/user-groups", json={"name": "Example; East"}, headers=admin)
    assert refused.status_code == 422
    assert "semicolon" in errors(refused.json())["name"]
    group = desk.post("/user-groups", {"name": "Example East"})
    renamed = client.patch(
        f"{API}/user-groups/{group['hid']}",
        json={"row_version": group["row_version"], "name": "Example; East"},
        headers=admin,
    )
    assert renamed.status_code == 422
    assert "semicolon" in errors(renamed.json())["name"]

    # One that holds one already, from before, keeps its name until it is renamed.
    db.execute(
        update(UserGroup)
        .where(UserGroup.hid == group["hid"])
        .values(name="Example; Old", name_key="example; old")
    )
    db.commit()
    kept = desk.get(f"/user-groups/{group['hid']}")
    kept = desk.patch(
        f"/user-groups/{group['hid']}",
        {"row_version": kept["row_version"], "name": "Example; Old", "description": "Kept."},
    )
    assert (kept["name"], kept["description"]) == ("Example; Old", "Kept.")
    again = desk.patch(
        f"/user-groups/{group['hid']}", {"row_version": kept["row_version"], "name": "Example Old"}
    )
    assert again["name"] == "Example Old"
