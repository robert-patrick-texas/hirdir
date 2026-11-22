"""Accounts of three kinds, and agents (P-316): the kind, the person answerable for an
agent, never Admin, the role in force capped by the person at each request, the mark
of the audit trail, and an agent retired with its person or handed to another."""

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import event, select

from hirdir.api import views
from hirdir.auth.roles import Role
from hirdir.db.models import AuditEvent, User
from hirdir.domain import accounts, audit
from hirdir.io import imports
from tests.api.inventory import API, Maker, errors
from tests.conftest import sign_in

SAM_CODE = "sam-roe-code-001"
KIM_CODE = "kim-lee-code-001"


class Desk(Maker):
    """An Admin's maker of accounts, with the steps these tests take again and again."""

    def person(self, username: str, role: str | None = "inventory", **more: Any) -> dict:
        code = SAM_CODE if username == "sam" else KIM_CODE
        body = {"username": username, "access_code": code, **more}
        if role:
            body["role"] = role
        return self.post("/users", body)["user"]

    def agent(self, username: str, person: dict, role: str | None = "inventory") -> dict:
        body: dict[str, Any] = {
            "username": username,
            "kind": "agent",
            "answerable_hid": person["hid"],
        }
        if role:
            body["role"] = role
        return self.post("/users", body)["user"]

    def token(self, user: dict) -> dict[str, str]:
        made = self.post(f"/users/{user['hid']}/service-tokens", {"name": "a job"})
        return {"Authorization": f"Bearer {made['secret']}"}

    def user(self, user: dict) -> dict:
        return self.get(f"/users/{user['hid']}")

    def grants(self, user: dict) -> list[dict]:
        return [one for one in self.get("/role-grants") if one["user_hid"] == user["hid"]]

    def revoke(self, grant: dict) -> None:
        answer = self.client.delete(f"{API}/role-grants/{grant['hid']}", headers=self.headers)
        assert answer.status_code == 204, answer.text


def _desk(client: TestClient, admin: dict) -> Desk:
    return Desk(client, admin)


# --- the kind ------------------------------------------------------------------------


def test_every_account_has_a_kind_set_when_it_is_made(client: TestClient, admin: dict) -> None:
    desk = _desk(client, admin)
    sam = desk.person("sam")
    assert sam["kind"] == "person"
    tool = desk.post("/users", {"username": "ex-tool", "kind": "service"})["user"]
    agent = desk.agent("agent-reconcile", sam)
    assert (tool["kind"], agent["kind"]) == ("service", "agent")
    assert "is_service_account" not in sam
    # The kind it has is no change; any other is refused.
    same = desk.patch(
        f"/users/{tool['hid']}", {"row_version": tool["row_version"], "kind": "service"}
    )
    assert same["row_version"] == tool["row_version"]
    refused = desk.patch(
        f"/users/{tool['hid']}", {"row_version": tool["row_version"], "kind": "agent"}, 422
    )
    assert errors(refused) == {"kind": "the kind is set when the account is made"}
    assert "ex-tool is a service account" in refused["detail"]
    # A list keeps one kind, and sorts by it.
    assert [one["username"] for one in desk.get("/users", kind="agent")["items"]] == [
        "agent-reconcile"
    ]
    assert [one["username"] for one in desk.get("/users", kind="service")["items"]] == ["ex-tool"]
    assert desk.get("/users", sort="kind")["items"][0]["username"] == "agent-reconcile"
    assert desk.get("/users", sort="-kind")["items"][0]["username"] == "ex-tool"
    desk.get("/users", 422, kind="robot")


def test_the_create_event_says_the_kind_and_the_person(client: TestClient, admin: dict) -> None:
    desk = _desk(client, admin)
    sam = desk.person("sam")
    agent = desk.agent("agent-reconcile", sam, role=None)
    event = desk.get("/audit-events", record_hid=agent["hid"], action="create")["items"][0]
    assert event["changes"] == [
        {"field": "username", "old": None, "new": "agent-reconcile"},
        {"field": "kind", "old": None, "new": "agent"},
        {"field": "answerable_hid", "old": None, "new": sam["hid"]},
    ]


def test_an_agent_names_a_person_who_is_not_retired(client: TestClient, admin: dict) -> None:
    desk = _desk(client, admin)
    sam = desk.person("sam")
    tool = desk.post("/users", {"username": "ex-tool", "kind": "service"})["user"]
    body = {"username": "agent-reconcile", "kind": "agent"}
    assert errors(desk.post("/users", body, 422)) == {
        "answerable_hid": "an agent is answerable to a person"
    }
    assert errors(desk.post("/users", {**body, "answerable_hid": "nobody"}, 422)) == {
        "answerable_hid": "there is no user nobody"
    }
    refused = desk.post("/users", {**body, "answerable_hid": tool["hid"]}, 422)
    assert refused["detail"] == ("ex-tool is a service account: an agent is answerable to a person")
    # Refused to the other kinds.
    for kind in ("person", "service"):
        refused = desk.post(
            "/users",
            {"username": "other", "kind": kind, "answerable_hid": sam["hid"], "role": "viewer"},
            422,
        )
        assert errors(refused) == {"answerable_hid": "an agent alone is answerable to a person"}
    # Like a service account, it has no contact, no access code and no operator.
    for more, field in (
        ({"contact": {"name": "Agent Example"}}, "contact"),
        ({"access_code": "an-agent-code-01"}, "access_code"),
    ):
        refused = desk.post("/users", {**body, "answerable_hid": sam["hid"], **more}, 422)
        assert field in errors(refused), refused
    refused = desk.post(
        "/users", {**body, "answerable_hid": sam["hid"], "operator": {"label": "AR"}}, 422
    )
    assert errors(refused) == {"operator": "an agent works as no operator"}
    agent = desk.agent("agent-reconcile", sam)
    assert agent["answerable_hid"] == sam["hid"]
    assert agent["answerable"] == {
        "hid": sam["hid"],
        "username": "sam",
        "name": "sam",
        "record_status": "active",
    }
    assert agent["agents"] == []
    assert desk.user(sam)["agents"] == [
        {
            "hid": agent["hid"],
            "username": "agent-reconcile",
            "name": "agent-reconcile",
            "record_status": "active",
        }
    ]
    # Its code is not set, and it signs in nowhere.
    refused = client.post(f"{API}/users/{agent['hid']}/access-code", json={}, headers=admin)
    assert refused.status_code == 409
    assert refused.json()["detail"] == "an agent has no access code; it holds tokens"


# --- never Admin -----------------------------------------------------------------------


def test_an_agent_is_never_admin(client: TestClient, admin: dict) -> None:
    desk = _desk(client, admin)
    sam = desk.person("sam")
    agent = desk.agent("agent-reconcile", sam, role=None)
    # A grant of its own.
    refused = desk.post("/role-grants", {"role": "admin", "user_hid": agent["hid"]}, 422)
    assert refused["detail"] == "agent-reconcile is an agent, and an agent is never Admin"
    assert errors(refused) == {"role": "an agent is never Admin"}
    # Made with it.
    refused = desk.post(
        "/users",
        {"username": "agent-two", "kind": "agent", "answerable_hid": sam["hid"], "role": "admin"},
        422,
    )
    assert refused["detail"] == "agent-two is an agent, and an agent is never Admin"
    admins = desk.post("/user-groups", {"name": "Admins"})
    desk.post("/role-grants", {"role": "admin", "group_hid": admins["hid"]})
    refused = desk.post(
        "/users",
        {
            "username": "agent-two",
            "kind": "agent",
            "answerable_hid": sam["hid"],
            "group_hids": [admins["hid"]],
        },
        422,
    )
    assert refused["detail"] == "the group Admins grants Admin, and an agent is never Admin"
    # Put in a group that grants Admin.
    put = client.put(f"{API}/user-groups/{admins['hid']}/members/{agent['hid']}", headers=admin)
    assert put.status_code == 409, put.text
    assert put.json()["detail"] == (
        "the group Admins grants Admin, and agent-reconcile is an agent: an agent is never Admin"
    )
    # Admin granted to a group that holds it.
    ops = desk.post("/user-groups", {"name": "Ops"})
    assert (
        client.put(
            f"{API}/user-groups/{ops['hid']}/members/{agent['hid']}", headers=admin
        ).status_code
        == 204
    )
    refused = desk.post("/role-grants", {"role": "admin", "group_hid": ops["hid"]}, 409)
    assert refused["detail"] == (
        "the group Ops holds the agent agent-reconcile, and an agent is never Admin: take it "
        "out of the group first"
    )
    assert refused["depends_on"] == [
        {"hid": agent["hid"], "record_type": "user", "label": "agent-reconcile"}
    ]
    # Nothing was granted, and the agent holds no role.
    assert desk.user(agent)["role"] is None
    assert [one["roles"] for one in desk.get("/user-groups")] == [["admin"], []]
    # Any other role is granted as to anybody.
    desk.post("/role-grants", {"role": "inventory", "group_hid": ops["hid"]})
    assert desk.user(agent)["role"] == "inventory"


# --- the role in force ---------------------------------------------------------------


def _an_item(client: TestClient, admin: dict) -> dict:
    make = Maker(client, admin)
    vendor = make.vendor("Example Vendor")
    entry = make.entry(vendor, "EX-1000")
    return make.item(catalog_entry_hid=entry["hid"], serial_number="EX0000001")


def test_the_person_caps_the_role_of_the_agent_at_each_request(
    client: TestClient, admin: dict
) -> None:
    desk = _desk(client, admin)
    sam = desk.person("sam")
    agent = desk.agent("agent-reconcile", sam)
    robot = desk.token(agent)
    item = _an_item(client, admin)
    path = f"{API}/items/{item['hid']}"
    changed = client.patch(
        path, json={"row_version": item["row_version"], "comments": "seen"}, headers=robot
    )
    assert changed.status_code == 200, changed.text
    record = desk.user(agent)
    assert (record["role"], record["role_in_force"], record["role_capped_by"]) == (
        "inventory",
        "inventory",
        None,
    )
    # Sam is moved to View-only: the agent changes nothing more, from its next request.
    desk.revoke(desk.grants(sam)[0])
    desk.post("/role-grants", {"role": "viewer", "user_hid": sam["hid"]})
    refused = client.patch(
        path,
        json={"row_version": changed.json()["row_version"], "comments": "again"},
        headers=robot,
    )
    assert refused.status_code == 403, refused.text
    assert client.get(path, headers=robot).json()["comments"] == "seen"
    record = desk.user(agent)
    assert (record["role"], record["role_in_force"], record["role_capped_by"]) == (
        "inventory",
        "viewer",
        "person_role",
    )
    me = client.get(f"{API}/auth/me", headers=robot).json()
    assert (me["kind"], me["answerable"]["username"], me["role_in_force"]) == (
        "agent",
        "sam",
        "viewer",
    )
    assert me["contact"] is None
    assert me["operators"] == []
    # A person's role above the agent's leaves the agent's.
    desk.post("/role-grants", {"role": "admin", "user_hid": sam["hid"]})
    assert desk.user(agent)["role_in_force"] == "inventory"


def test_the_token_is_refused_while_the_person_cannot_answer_for_it(
    client: TestClient, admin: dict
) -> None:
    desk = _desk(client, admin)
    sam = desk.person("sam")
    agent = desk.agent("agent-reconcile", sam)
    robot = desk.token(agent)
    assert client.get(f"{API}/auth/me", headers=robot).status_code == 200
    before = desk.user(agent)

    sam_now = desk.user(sam)
    desk.patch(f"/users/{sam['hid']}", {"row_version": sam_now["row_version"], "disabled": True})
    refused = client.get(f"{API}/auth/me", headers=robot)
    assert refused.status_code == 401
    assert refused.json()["detail"] == (
        "the token is not accepted: the agent agent-reconcile is answerable to sam, who is disabled"
    )
    assert desk.user(agent)["role_capped_by"] == "person_disabled"
    sam_now = desk.user(sam)
    desk.patch(f"/users/{sam['hid']}", {"row_version": sam_now["row_version"], "disabled": False})
    assert client.get(f"{API}/auth/me", headers=robot).status_code == 200

    desk.revoke(desk.grants(sam)[0])
    refused = client.get(f"{API}/auth/me", headers=robot)
    assert refused.status_code == 401
    assert refused.json()["detail"] == (
        "the token is not accepted: the agent agent-reconcile is answerable to sam, who holds "
        "no role"
    )
    record = desk.user(agent)
    assert (record["role_in_force"], record["role_capped_by"]) == (None, "person_no_role")
    # Nothing of the agent changed, and its token answers again once Sam holds a role.
    assert (record["row_version"], record["disabled"], record["role"]) == (
        before["row_version"],
        False,
        "inventory",
    )
    desk.post("/role-grants", {"role": "viewer", "user_hid": sam["hid"]})
    assert client.get(f"{API}/auth/me", headers=robot).json()["role_in_force"] == "viewer"

    # An agent that holds no role of its own is refused for that.
    desk.revoke(desk.grants(agent)[0])
    refused = client.get(f"{API}/auth/me", headers=robot)
    assert refused.json()["detail"] == (
        "the token is not accepted: the agent agent-reconcile holds no role"
    )


def test_an_agent_has_no_profile(client: TestClient, admin: dict) -> None:
    desk = _desk(client, admin)
    agent = desk.agent("agent-reconcile", desk.person("sam"))
    robot = desk.token(agent)
    refused = client.patch(
        f"{API}/auth/me/contact", json={"row_version": 1, "name": "Agent"}, headers=robot
    )
    assert refused.status_code == 403
    assert refused.json()["detail"] == "an agent has no profile"


# --- handing over --------------------------------------------------------------------


def test_an_admin_hands_an_agent_to_another_person(client: TestClient, admin: dict) -> None:
    desk = _desk(client, admin)
    sam, kim = desk.person("sam"), desk.person("klee")
    tool = desk.post("/users", {"username": "ex-tool", "kind": "service"})["user"]
    agent = desk.agent("agent-reconcile", sam)
    version = agent["row_version"]
    for to, field in ((None, "an agent is answerable to a person"), (tool["hid"], None)):
        refused = desk.patch(
            f"/users/{agent['hid']}", {"row_version": version, "answerable_hid": to}, 422
        )
        assert "answerable_hid" in errors(refused)
        if field:
            assert errors(refused)["answerable_hid"] == field
    handed = desk.patch(
        f"/users/{agent['hid']}", {"row_version": version, "answerable_hid": kim["hid"]}
    )
    assert handed["answerable"]["username"] == "klee"
    event = desk.get("/audit-events", record_hid=agent["hid"], action="update")["items"][0]
    assert event["changes"] == [{"field": "answerable_hid", "old": sam["hid"], "new": kim["hid"]}]
    assert desk.user(sam)["agents"] == []
    assert [one["username"] for one in desk.user(kim)["agents"]] == ["agent-reconcile"]
    # Nobody else is answerable to anybody.
    refused = desk.patch(
        f"/users/{tool['hid']}",
        {"row_version": tool["row_version"], "answerable_hid": kim["hid"]},
        422,
    )
    assert errors(refused) == {"answerable_hid": "an agent alone is answerable to a person"}


# --- the audit trail -----------------------------------------------------------------


def test_each_event_of_an_agent_is_kept_for_its_person(client: TestClient, admin: dict, db) -> None:
    desk = _desk(client, admin)
    sam, kim = desk.person("sam"), desk.person("klee")
    agent = desk.agent("agent-reconcile", sam)
    robot = desk.token(agent)
    item = _an_item(client, admin)
    path = f"{API}/items/{item['hid']}"
    first = client.patch(
        path, json={"row_version": item["row_version"], "comments": "one"}, headers=robot
    ).json()
    desk.patch(
        f"/users/{agent['hid']}",
        {"row_version": desk.user(agent)["row_version"], "answerable_hid": kim["hid"]},
    )
    client.patch(path, json={"row_version": first["row_version"], "comments": "two"}, headers=robot)

    history = desk.get(f"/items/{item['hid']}/history")["items"]
    by_agent = [one for one in history if one["actor_kind"] == "agent"]
    # Each keeps whom it was for when it was made, which the hand-over does not change.
    assert [(one["actor_name"], one["for_name"]) for one in by_agent] == [
        ("agent-reconcile", "klee"),
        ("agent-reconcile", "sam"),
    ]
    assert [one["for_hid"] for one in by_agent] == [kim["hid"], sam["hid"]]
    made = next(one for one in history if one["action"] == "create")
    assert (made["actor_kind"], made["for_hid"], made["for_name"]) == ("person", None, None)

    agents = desk.get("/audit-events", actor_kind="agent")
    assert agents["total"] == 2
    assert {one["record_hid"] for one in agents["items"]} == {item["hid"]}
    assert desk.get("/audit-events", for_hid=sam["hid"])["total"] == 1
    assert desk.get("/audit-events", actor_kind="service")["total"] == 0
    sorted_ = desk.get("/audit-events", sort="-for_name", limit=1)["items"][0]
    assert sorted_["for_name"] == "sam"
    # And in the table itself.
    kept = db.scalars(select(AuditEvent.for_hid).where(AuditEvent.actor_hid == agent["hid"]))
    assert sorted(kept) == sorted([sam["hid"], kim["hid"]])


# --- retired with its person, or handed over -------------------------------------------


def test_a_person_is_retired_with_what_becomes_of_each_agent(
    client: TestClient, admin: dict
) -> None:
    desk = _desk(client, admin)
    sam, kim = desk.person("sam"), desk.person("klee")
    tool = desk.post("/users", {"username": "ex-tool", "kind": "service"})["user"]
    reconcile = desk.agent("agent-reconcile", sam)
    scan = desk.agent("agent-scan", sam, role="viewer")
    robot = desk.token(scan)
    linked = desk.get(f"/users/{sam['hid']}/linked")
    assert linked["agents"] == [
        {
            "hid": reconcile["hid"],
            "username": "agent-reconcile",
            "record_status": "active",
            "disabled": False,
            "role": "inventory",
        },
        {
            "hid": scan["hid"],
            "username": "agent-scan",
            "record_status": "active",
            "disabled": False,
            "role": "viewer",
        },
    ]
    path = f"/users/{sam['hid']}/retire"
    version = desk.user(sam)["row_version"]
    # Nothing said of the agents: each is named, and nothing changes.
    unsaid = desk.post(path, {"row_version": version}, 409)
    assert unsaid["detail"] == (
        "records are linked to this one, and it is not said what becomes of each: the agent "
        "agent-reconcile, the agent agent-scan"
    )
    assert errors(unsaid) == {
        "linked.agents": "say what becomes of each of the agents agent-reconcile, agent-scan: "
        "retire it or hand it to another person"
    }
    assert [one["label"] for one in unsaid["depends_on"]] == ["agent-reconcile", "agent-scan"]
    # One of them alone is said.
    one = {"hid": reconcile["hid"], "action": "retire"}
    unsaid = desk.post(path, {"row_version": version, "linked": {"agents": [one]}}, 409)
    assert [one["label"] for one in unsaid["depends_on"]] == ["agent-scan"]
    # What is said wrong is refused at linked.agents.
    for wrong, why in (
        ({"hid": scan["hid"], "action": "hand_over"}, "is handed over to a person: say which"),
        ({"hid": scan["hid"], "action": "retire", "user_hid": kim["hid"]}, "a person is named"),
        ({"hid": scan["hid"], "action": "hand_over", "user_hid": sam["hid"]}, "not to the one"),
        ({"hid": scan["hid"], "action": "hand_over", "user_hid": tool["hid"]}, "service account"),
        ({"hid": tool["hid"], "action": "retire"}, "ex-tool is no agent"),
    ):
        refused = desk.post(path, {"row_version": version, "linked": {"agents": [one, wrong]}}, 422)
        assert why in errors(refused)["linked.agents"], (wrong, refused)
    twice = desk.post(path, {"row_version": version, "linked": {"agents": [one, one]}}, 422)
    assert errors(twice) == {"linked.agents": "the agent agent-reconcile is said twice"}
    assert desk.user(sam)["record_status"] == "active"

    # One retired with Sam, the other handed to Kim.
    plan = [one, {"hid": scan["hid"], "action": "hand_over", "user_hid": kim["hid"]}]
    retired = desk.post(path, {"row_version": version, "linked": {"agents": plan}}, 200)
    assert retired["record_status"] == "retired"
    gone, handed = desk.user(reconcile), desk.user(scan)
    assert (gone["record_status"], gone["role"], gone["answerable"]["username"]) == (
        "retired",
        None,
        "sam",
    )
    assert (handed["record_status"], handed["answerable"]["username"]) == ("active", "klee")
    assert handed["role_in_force"] == "viewer"
    assert client.get(f"{API}/auth/me", headers=robot).status_code == 200
    # Each record audited as if done by itself, under the one request.
    events = desk.get("/audit-events", request_id=retired_request(desk, sam))["items"]
    assert {(one["action"], one["record_hid"]) for one in events} >= {
        ("retire", reconcile["hid"]),
        ("update", scan["hid"]),
        ("retire", sam["hid"]),
    }


def retired_request(desk: Desk, user: dict) -> str:
    """Return the request ID of the retirement of a user."""
    return desk.get("/audit-events", record_hid=user["hid"], action="retire")["items"][0][
        "request_id"
    ]


def test_agents_are_said_only_where_their_person_is_retired(
    client: TestClient, admin: dict
) -> None:
    desk = _desk(client, admin)
    kim = desk.person("klee", contact={"name": "Kim Lee", "email": "kim.lee@example.com"})
    agent = desk.agent("agent-reconcile", kim)
    contact = desk.get(f"/contacts/{kim['contact_hid']}")
    linked = desk.get(f"/contacts/{kim['contact_hid']}/linked")
    assert [one["username"] for one in linked["agents"]] == ["agent-reconcile"]
    path = f"/contacts/{kim['contact_hid']}/retire"
    body = {"row_version": contact["row_version"]}
    kept = {"user": "keep", "agents": [{"hid": agent["hid"], "action": "retire"}]}
    refused = desk.post(path, {**body, "linked": kept}, 422)
    assert errors(refused)["linked.agents"] == (
        "agents are said only where the user they are answerable to is retired"
    )
    # The contact retired with its user names the agent too.
    unsaid = desk.post(path, {**body, "linked": {"user": "retire"}}, 409)
    assert [one["label"] for one in unsaid["depends_on"]] == ["agent-reconcile"]
    done = desk.post(path, {**body, "linked": {"user": "retire", "agents": kept["agents"]}}, 200)
    assert done["record_status"] == "retired"
    assert desk.user(agent)["record_status"] == "retired"


def test_an_agent_is_brought_back_answerable_to_a_person_who_is_not_retired(
    client: TestClient, admin: dict
) -> None:
    desk = _desk(client, admin)
    sam, kim = desk.person("sam"), desk.person("klee")
    agent = desk.agent("agent-reconcile", sam)
    robot = desk.token(agent)
    desk.post(
        f"/users/{sam['hid']}/retire",
        {
            "row_version": desk.user(sam)["row_version"],
            "linked": {"agents": [{"hid": agent["hid"], "action": "retire"}]},
        },
        200,
    )
    # Its tokens were revoked with it.
    assert client.get(f"{API}/auth/me", headers=robot).status_code == 401
    path = f"/users/{agent['hid']}/bring-back"
    version = desk.user(agent)["row_version"]
    refused = desk.post(path, {"row_version": version, "role": "viewer"}, 409)
    assert refused["detail"] == (
        "the agent agent-reconcile is answerable to sam, who is retired: name another person "
        "to bring it back"
    )
    assert refused["existing"] == {"hid": sam["hid"], "record_type": "user", "label": "sam"}
    refused = desk.post(
        path, {"row_version": version, "role": "admin", "answerable_hid": kim["hid"]}, 422
    )
    assert errors(refused) == {"role": "an agent is never Admin"}
    back = desk.post(
        path, {"row_version": version, "role": "viewer", "answerable_hid": kim["hid"]}, 200
    )
    assert back["access_code"] is None
    user = back["user"]
    assert (user["record_status"], user["role"], user["answerable"]["username"]) == (
        "active",
        "viewer",
        "klee",
    )
    actions = [one["action"] for one in desk.get("/audit-events", record_hid=agent["hid"])["items"]]
    assert actions[:3] == ["grant_role", "update", "bring_back"]
    # Of any other kind, answerable_hid is refused.
    tool = desk.post("/users", {"username": "ex-tool", "kind": "service"})["user"]
    retired = desk.post(f"/users/{tool['hid']}/retire", {"row_version": tool["row_version"]}, 200)
    refused = desk.post(
        f"/users/{tool['hid']}/bring-back",
        {"row_version": retired["row_version"], "answerable_hid": kim["hid"]},
        422,
    )
    assert errors(refused) == {"answerable_hid": "an agent alone is answerable to a person"}
    # A retired agent is handed to nobody.
    gone = desk.post(
        f"/users/{agent['hid']}/retire", {"row_version": desk.user(agent)["row_version"]}, 200
    )
    refused = desk.patch(
        f"/users/{agent['hid']}",
        {"row_version": gone["row_version"], "answerable_hid": sam["hid"]},
        409,
    )
    assert errors(refused) == {"answerable_hid": "this account is retired"}


# --- where a role comes from ---------------------------------------------------------


def test_a_user_answers_each_role_it_holds_and_where_it_comes_from(
    client: TestClient, admin: dict
) -> None:
    desk = _desk(client, admin)
    kim = desk.person("klee", role="viewer")
    noc = desk.post("/user-groups", {"name": "NOC"})
    field = desk.post("/user-groups", {"name": "Field team"})
    readers = desk.post("/user-groups", {"name": "Auditors"})
    for group, role in ((noc, "inventory"), (field, "inventory"), (readers, "viewer")):
        desk.post("/role-grants", {"role": role, "group_hid": group["hid"]})
        put = client.put(f"{API}/user-groups/{group['hid']}/members/{kim['hid']}", headers=admin)
        assert put.status_code == 204
    own = desk.grants(kim)[0]
    by_group = {
        one["group_hid"]: one["hid"] for one in desk.get("/role-grants") if one["group_hid"]
    }
    record = desk.user(kim)
    assert record["role"] == "inventory"
    assert record["grants"] == [
        {
            "hid": by_group[field["hid"]],
            "role": "inventory",
            "group": {"hid": field["hid"], "name": "Field team"},
        },
        {
            "hid": by_group[noc["hid"]],
            "role": "inventory",
            "group": {"hid": noc["hid"], "name": "NOC"},
        },
        {"hid": own["hid"], "role": "viewer", "group": None},
        {
            "hid": by_group[readers["hid"]],
            "role": "viewer",
            "group": {"hid": readers["hid"], "name": "Auditors"},
        },
    ]
    # The list and the members of a group answer the same.
    listed = next(one for one in desk.get("/users")["items"] if one["username"] == "klee")
    assert listed["grants"] == record["grants"]
    members = desk.get(f"/user-groups/{noc['hid']}")["members"]
    assert members[0]["grants"] == record["grants"]
    me = client.get(f"{API}/auth/me", headers=sign_in(client, "klee", KIM_CODE)).json()
    assert me["grants"] == record["grants"]


def test_a_page_of_users_costs_the_same_statements_whatever_its_size(db) -> None:
    """Where each role comes from, the person of an agent and the agents of a person are
    read for the whole page at once (P-307, P-316): a page of three hundred costs the
    statements of a page of three."""
    groups = [accounts.create_group(db, audit.SYSTEM, name=f"Team {n}") for n in range(5)]
    for n, group in enumerate(groups):
        accounts.grant_role(
            db, audit.SYSTEM, role=("viewer", "inventory")[n % 2], group_hid=group.hid
        )
    people = []
    for n in range(300):
        if n % 3 == 2:
            user, _ = accounts.create_user(
                db,
                audit.SYSTEM,
                username=f"agent-{n:03}",
                kind="agent",
                answerable_hid=people[-1].hid,
            )
        else:
            user, _ = accounts.create_user(db, audit.SYSTEM, username=f"user-{n:03}")
            people.append(user)
        accounts.grant_role(db, audit.SYSTEM, role="viewer", user_hid=user.hid)
        accounts.add_member(db, audit.SYSTEM, groups[n % 5].hid, user.hid)
    db.commit()
    everyone = list(db.scalars(select(User).order_by(User.username_key)))

    def statements(page: list[User]) -> int:
        seen: list[str] = []

        def note(_connection: object, _cursor: object, statement: str, *_more: object) -> None:
            seen.append(statement)

        # Read afresh, as the list of users reads its page, and nothing else kept.
        db.expunge_all()
        users = list(db.scalars(select(User).where(User.hid.in_([one.hid for one in page]))))
        event.listen(db.get_bind(), "before_cursor_execute", note)
        try:
            shown = views.users_out(db, users)
        finally:
            event.remove(db.get_bind(), "before_cursor_execute", note)
        assert len(shown) == len(users)
        return len(seen)

    kinds = {kind: [one for one in everyone if one.kind == kind] for kind in ("person", "agent")}
    few = statements(kinds["person"][:2] + kinds["agent"][:1])
    assert statements(everyone) == few


def test_an_agent_is_in_no_gap_and_is_named_so_by_the_measures(
    client: TestClient, admin: dict
) -> None:
    """An agent is no person: it is in neither `none` of the lists of users, as a service
    account is not; and the server's own measures name it as an agent (P-316)."""
    desk = _desk(client, admin)
    agent = desk.agent("agent-reconcile", desk.person("sam"))
    for gaps in (
        [one["username"] for one in desk.get("/users", contact="none")["items"]],
        [one["username"] for one in desk.get("/users", operator="none")["items"]],
    ):
        assert "sam" in gaps
        assert "agent-reconcile" not in gaps
    assert client.get(f"{API}/auth/me", headers=desk.token(agent)).status_code == 200
    measured = desk.get("/about/load")
    assert ("agent-reconcile", "agent") in [
        (one["username"], one["kind"]) for one in measured["people"]
    ]


def test_an_apply_for_an_agent_is_held_to_the_role_of_its_person_now(db) -> None:
    """An import or a bulk edit applied in the background for an agent is held, at each
    batch, to the role its person holds it to then, as a request is (P-316)."""
    sam, _ = accounts.create_user(db, audit.SYSTEM, username="sam")
    grant = accounts.grant_role(db, audit.SYSTEM, role="inventory", user_hid=sam.hid)
    agent, _ = accounts.create_user(
        db, audit.SYSTEM, username="agent-reconcile", kind="agent", answerable_hid=sam.hid
    )
    accounts.grant_role(db, audit.SYSTEM, role="inventory", user_hid=agent.hid)
    asked = audit.AuditContext(actor_hid=agent.hid, via="api", for_hid=sam.hid)
    assert imports._role(db, asked) is Role.INVENTORY
    accounts.revoke_grant(db, audit.SYSTEM, grant.hid)
    accounts.grant_role(db, audit.SYSTEM, role="viewer", user_hid=sam.hid)
    assert imports._role(db, asked) is Role.VIEWER
    sam.disabled = True
    assert imports._role(db, asked) is None
