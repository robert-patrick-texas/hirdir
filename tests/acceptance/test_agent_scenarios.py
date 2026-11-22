"""Scenarios S61 and S62 of docs/build-plan.md, against a real server process: an agent
answerable to a person, held to the person's role and never Admin, marked in the audit
trail and handed over when the person is retired; and `hirdir admin create-user`, which
makes a person with a role unless `--no-role` says otherwise, beside a user's roles and
where each comes from (R12.12, R12.13, P-307, P-313, P-316)."""

import subprocess

import httpx2

from tests.acceptance.conftest import ADMIN, HIRDIR, Server

SAM = ("sam", "sam-roe-code-01")
KIM = ("klee", "kim-lee-code-01")


def _admin_command(server: Server, *arguments: str) -> subprocess.CompletedProcess[str]:
    """Run `hirdir admin` and return what it did, whatever its exit status."""
    return subprocess.run(  # noqa: S603 - our own command with fixed arguments
        [*HIRDIR, "admin", *arguments],
        env=server.env,
        capture_output=True,
        text=True,
        check=False,
    )


def _errors(response: httpx2.Response) -> dict[str, str]:
    return {entry["field"]: entry["message"] for entry in response.json()["errors"]}


def _made(response: httpx2.Response) -> dict:
    assert response.status_code == 201, response.text
    return response.json()


def test_s61_an_agent_is_held_to_its_person_never_admin_and_handed_over(server: Server) -> None:
    """S61 (R12.12): the change of an agent is in the audit trail for its person and among
    the events of agents; moved to View-only, the person holds the agent to it; Admin is
    refused to the agent, named; the person's retirement names the agent until it is said,
    and the hand-over leaves it answerable to the other person, whose role it then holds
    (P-316)."""
    admin = server.sign_in(*ADMIN)
    sam = _made(
        admin.post("/users", json={"username": SAM[0], "access_code": SAM[1], "role": "inventory"})
    )["user"]
    kim = _made(
        admin.post("/users", json={"username": KIM[0], "access_code": KIM[1], "role": "inventory"})
    )["user"]
    agent = _made(
        admin.post(
            "/users",
            json={
                "username": "agent-reconcile",
                "kind": "agent",
                "answerable_hid": sam["hid"],
                "role": "inventory",
            },
        )
    )["user"]
    assert (agent["kind"], agent["answerable"]["username"], agent["role_in_force"]) == (
        "agent",
        "sam",
        "inventory",
    )
    secret = _made(admin.post(f"/users/{agent['hid']}/service-tokens", json={"name": "reconcile"}))[
        "secret"
    ]
    robot = httpx2.Client(base_url=server.url, headers={"Authorization": f"Bearer {secret}"})

    vendor = _made(admin.post("/vendors", json={"name": "Example Vendor"}))
    entry = _made(admin.post("/catalog-entries", json={"vendor_hid": vendor["hid"], "pid": "EX-1"}))
    item = _made(
        admin.post("/items", json={"catalog_entry_hid": entry["hid"], "serial_number": "EX00001"})
    )

    # The agent changes an item: in the audit trail by the agent, for Sam.
    changed = robot.patch(
        f"/items/{item['hid']}", json={"row_version": item["row_version"], "comments": "seen"}
    )
    assert changed.status_code == 200, changed.text
    events = admin.get("/audit-events", params={"actor_kind": "agent"}).json()
    assert events["total"] == 1
    event = events["items"][0]
    assert (event["record_hid"], event["actor_name"], event["for_hid"], event["for_name"]) == (
        item["hid"],
        "agent-reconcile",
        sam["hid"],
        "sam",
    )
    history = admin.get(f"/items/{item['hid']}/history").json()["items"]
    assert (history[0]["actor_kind"], history[0]["for_name"]) == ("agent", "sam")

    # Sam is moved to View-only: the agent's next change is refused, nothing changed.
    own = next(one for one in admin.get("/role-grants").json() if one["user_hid"] == sam["hid"])
    assert admin.delete(f"/role-grants/{own['hid']}").status_code == 204
    _made(admin.post("/role-grants", json={"role": "viewer", "user_hid": sam["hid"]}))
    refused = robot.patch(
        f"/items/{item['hid']}",
        json={"row_version": changed.json()["row_version"], "comments": "again"},
    )
    assert refused.status_code == 403, refused.text
    assert admin.get(f"/items/{item['hid']}").json()["comments"] == "seen"
    held = admin.get(f"/users/{agent['hid']}").json()
    assert (held["role"], held["role_in_force"], held["role_capped_by"]) == (
        "inventory",
        "viewer",
        "person_role",
    )

    # Admin is refused to the agent, with it named.
    admin_grant = admin.post("/role-grants", json={"role": "admin", "user_hid": agent["hid"]})
    assert admin_grant.status_code == 422, admin_grant.text
    assert admin_grant.json()["detail"] == (
        "agent-reconcile is an agent, and an agent is never Admin"
    )

    # Sam is retired: saying nothing of the agent is refused, with it named.
    path = f"/users/{sam['hid']}/retire"
    version = admin.get(f"/users/{sam['hid']}").json()["row_version"]
    unsaid = admin.post(path, json={"row_version": version})
    assert unsaid.status_code == 409, unsaid.text
    assert [one["label"] for one in unsaid.json()["depends_on"]] == ["agent-reconcile"]
    assert set(_errors(unsaid)) == {"linked.agents"}
    assert admin.get(f"/users/{sam['hid']}").json()["record_status"] == "active"
    handed = admin.post(
        path,
        json={
            "row_version": version,
            "linked": {
                "agents": [{"hid": agent["hid"], "action": "hand_over", "user_hid": kim["hid"]}]
            },
        },
    )
    assert handed.status_code == 200, handed.text
    now = admin.get(f"/users/{agent['hid']}").json()
    assert (now["record_status"], now["answerable"]["username"]) == ("active", "klee")
    assert (now["role_in_force"], now["role_capped_by"]) == ("inventory", None)
    # It holds Kim's role from then on: its change is taken, and is for Kim.
    again = robot.patch(
        f"/items/{item['hid']}",
        json={"row_version": changed.json()["row_version"], "comments": "again"},
    )
    assert again.status_code == 200, again.text
    newest = admin.get("/audit-events", params={"actor_kind": "agent"}).json()["items"][0]
    assert newest["for_name"] == "klee"


def test_s62_create_user_asks_for_a_role_and_a_page_says_where_each_comes_from(
    server: Server,
) -> None:
    """S62 (R12.13): a person with no --role and no --group is refused, exit 4, nothing
    made, naming the three ways on; with --no-role it is made, with its warning; --role
    with --no-role is a mistake of usage, exit 2 (P-313); and a user's record answers each
    role it holds, of its own or through each group, named (P-307)."""
    admin = server.sign_in(*ADMIN)
    users = admin.get("/users", params={"limit": 1}).json()["total"]

    refused = _admin_command(server, "create-user", "--name", "Kim Lee", "klee")
    assert refused.returncode == 4, refused.stderr
    for way in ("--role", "a --group that grants one", "--no-role"):
        assert way in refused.stderr
    assert admin.get("/users", params={"limit": 1}).json()["total"] == users
    assert admin.get("/contacts", params={"q": "Kim Lee"}).json()["total"] == 0

    made = _admin_command(server, "create-user", "--no-role", "klee")
    assert made.returncode == 0, made.stderr
    assert "klee holds no role, and cannot sign in until an Admin gives it one" in made.stderr

    both = _admin_command(server, "create-user", "--role", "viewer", "--no-role", "sam")
    assert both.returncode == 2, both.stderr
    assert "--role and --no-role are not given together" in both.stderr
    assert admin.get("/users", params={"q": "sam"}).json()["total"] == 0

    # Kim is given a role of her own and two through groups: the record says each.
    kim = next(one for one in admin.get("/users").json()["items"] if one["username"] == "klee")
    own = _made(admin.post("/role-grants", json={"role": "viewer", "user_hid": kim["hid"]}))
    given = {}
    for name, role in (("Network team", "inventory"), ("Help desk", "viewer")):
        group = _made(admin.post("/user-groups", json={"name": name}))
        given[name] = (
            group,
            _made(admin.post("/role-grants", json={"role": role, "group_hid": group["hid"]})),
        )
        assert admin.put(f"/user-groups/{group['hid']}/members/{kim['hid']}").status_code == 204
    record = admin.get(f"/users/{kim['hid']}").json()
    team, desk = given["Network team"], given["Help desk"]
    assert record["role"] == "inventory"
    assert record["grants"] == [
        {
            "hid": team[1]["hid"],
            "role": "inventory",
            "group": {"hid": team[0]["hid"], "name": "Network team"},
        },
        {"hid": own["hid"], "role": "viewer", "group": None},
        {
            "hid": desk[1]["hid"],
            "role": "viewer",
            "group": {"hid": desk[0]["hid"], "name": "Help desk"},
        },
    ]
    # The list of users answers the same, for the page as a whole.
    listed = next(one for one in admin.get("/users").json()["items"] if one["username"] == "klee")
    assert listed["grants"] == record["grants"]
