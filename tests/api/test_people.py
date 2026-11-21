"""People are contacts, and a user and an operator are each a part one of them plays
(P-172); a username is changed by an Admin (P-173); the kinds of external system are an
editable list (P-170). Through the API."""

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.api.inventory import API, Maker, errors, left_retired
from tests.api.test_files import Files, table
from tests.conftest import INVENTORY_CODE, sign_in


def _user(make: Maker, hid: str) -> dict[str, Any]:
    return make.get(f"/users/{hid}")


# --- a user is a contact who signs in ------------------------------------------------


def test_a_user_is_made_with_its_contact_and_shows_that_contacts_details(
    client: TestClient, admin: dict
) -> None:
    desk = Maker(client, admin)
    robin = desk.contact("Robin Achterberg", phone="+1 202 555 0142", phone2="+1 202 555 0177")
    made = desk.post("/users", {"username": "robin", "contact_hid": robin["hid"]})["user"]
    assert made["contact_hid"] == robin["hid"]
    assert made["contact"] == {
        "hid": robin["hid"],
        "name": "Robin Achterberg",
        "email": "robin.achterberg@example.net",
        "phone": "+1 202 555 0142",
        "phone2": "+1 202 555 0177",
        "record_status": "active",
    }
    assert (made["display_name"], made["email"]) == (
        "Robin Achterberg",
        "robin.achterberg@example.net",
    )

    # A new contact is made with the user, in the same change, and audited as a contact.
    dana = desk.post(
        "/users",
        {
            "username": "dana",
            "contact": {"name": "Dana Ruiz", "email": "dana.ruiz@example.org", "phone2": "x9"},
        },
    )["user"]
    assert (dana["display_name"], dana["contact"]["phone2"]) == ("Dana Ruiz", "x9")
    made_contact = desk.audit(record_type="contact", record_hid=dana["contact_hid"])
    # Newest first: made, then given to the user.
    assert [event["action"] for event in made_contact] == ["update", "create"]
    assert desk.audit(record_type="user", record_hid=dana["hid"])[0]["changes"][-1] == {
        "field": "contact_hid",
        "old": None,
        "new": dana["contact_hid"],
    }

    # Neither: the user is shown by its username until it is given one.
    lee = desk.post("/users", {"username": "lee"})["user"]
    assert (lee["contact"], lee["display_name"], lee["email"]) == (None, "", "")

    # A new number on the contact is what the user shows, with nothing written to it.
    version = desk.get(f"/contacts/{robin['hid']}")["row_version"]
    desk.patch(f"/contacts/{robin['hid']}", {"row_version": version, "phone": "+1 202 555 0150"})
    shown = _user(desk, made["hid"])
    assert shown["contact"]["phone"] == "+1 202 555 0150"
    assert shown["row_version"] == made["row_version"]
    assert [user["username"] for user in desk.get("/users", q="achter")["items"]] == ["robin"]


def test_what_a_user_cannot_be_given_as_its_contact(client: TestClient, admin: dict) -> None:
    desk = Maker(client, admin)
    robin = desk.contact("Robin Achterberg")
    desk.post("/users", {"username": "robin", "contact_hid": robin["hid"]})
    # A contact is one user's at most.
    refused = desk.post("/users", {"username": "robin2", "contact_hid": robin["hid"]}, 409)
    assert "another user's" in errors(refused)["contact_hid"]
    # A service account is no person.
    bot = desk.post(
        "/users", {"username": "bot", "is_service_account": True, "contact": {"name": "Bot"}}, 422
    )
    assert "service account" in errors(bot)["contact"]
    sync = desk.post("/users", {"username": "sync", "is_service_account": True})["user"]
    other = desk.contact("Sync Desk")
    refused = desk.patch(
        f"/users/{sync['hid']}",
        {"row_version": sync["row_version"], "contact_hid": other["hid"]},
        422,
    )
    assert "service account" in errors(refused)["contact_hid"]
    # A retired contact, and one there is not.
    gone = desk.contact("Gone Person")
    desk.post(f"/contacts/{gone['hid']}/retire", {"row_version": gone["row_version"]}, 200)
    refused = desk.post("/users", {"username": "gone", "contact_hid": gone["hid"]}, 422)
    assert "retired" in errors(refused)["contact_hid"]
    # Both at once.
    refused = desk.post(
        "/users", {"username": "two", "contact_hid": other["hid"], "contact": {"name": "X"}}, 422
    )
    assert "contact" in errors(refused)
    # The name and email are the contact's: a change of the user does not take them.
    me = desk.get("/auth/me")
    refused = desk.patch(
        f"/users/{me['hid']}", {"row_version": me["row_version"], "email": "a@b.c"}, 422
    )
    assert "email" in errors(refused)


def test_an_admin_gives_a_user_its_contact_and_takes_it_away(
    client: TestClient, admin: dict
) -> None:
    desk = Maker(client, admin)
    lee = desk.post("/users", {"username": "lee"})["user"]
    marchetti = desk.contact("Lee Marchetti")
    given = desk.patch(
        f"/users/{lee['hid']}", {"row_version": lee["row_version"], "contact_hid": marchetti["hid"]}
    )
    assert given["display_name"] == "Lee Marchetti"
    contact = desk.get(f"/contacts/{marchetti['hid']}")
    assert contact["user"] == {"hid": lee["hid"], "username": "lee", "record_status": "active"}
    listed = desk.get("/contacts", filter="is_user:eq:true")["items"]
    assert [one["name"] for one in listed] == ["Lee Marchetti"]
    taken = desk.patch(
        f"/users/{lee['hid']}", {"row_version": given["row_version"], "contact_hid": None}
    )
    assert (taken["contact"], taken["display_name"]) == (None, "")
    assert desk.get(f"/contacts/{marchetti['hid']}")["user"] is None
    # Only an Admin changes a user.
    ivy = sign_in(client, "ivy", INVENTORY_CODE)
    response = client.patch(
        f"{API}/users/{lee['hid']}",
        json={"row_version": taken["row_version"], "contact_hid": marchetti["hid"]},
        headers=ivy,
    )
    assert response.status_code == 403


# --- an operator is internal or external -------------------------------------------


def test_an_operator_is_internal_where_its_contact_is_a_user(
    client: TestClient, admin: dict, make: Maker
) -> None:
    robin = make.contact("Robin Achterberg", phone="+1 202 555 0142", phone2="+1 202 555 0177")
    dana = make.contact("Dana Ruiz")
    lm = make.post("/operators", {"label": "LM", "contact_hid": robin["hid"]})
    op2 = make.post("/operators", {"label": "Op2", "contact_hid": dana["hid"]})
    open_ = make.post("/operators", {"label": "Op3"})
    assert (lm["scope"], op2["scope"], open_["scope"]) == ("external", "external", None)
    assert (lm["contact"]["phone"], lm["contact"]["phone2"], lm["user"]) == (
        "+1 202 555 0142",
        "+1 202 555 0177",
        None,
    )

    desk = Maker(client, admin)
    user = desk.post("/users", {"username": "robin", "contact_hid": robin["hid"]})["user"]
    lm = make.get(f"/operators/{lm['hid']}")
    shown = {"hid": user["hid"], "username": "robin", "record_status": "active"}
    assert (lm["scope"], lm["user"]) == ("internal", shown)
    # Nothing was written to the operator: the scope is read with it.
    assert lm["row_version"] == 1
    assert [
        one["label"] for one in make.get("/operators", filter="scope:eq:internal")["items"]
    ] == ["LM"]
    assert [one["label"] for one in make.get("/operators", sort="-scope")["items"]][:2] == [
        "LM",
        "Op2",
    ]

    item = make.item(name="site2-sw-01", operator_hid=lm["hid"])
    make.item(name="site2-sw-02", operator_hid=op2["hid"])
    assert make.found(filter="operator.scope:eq:internal") == ["site2-sw-01"]
    assert make.found(filter="operator.scope:eq:external") == ["site2-sw-02"]
    shown = make.get(f"/items/{item['hid']}")
    assert shown["operator"]["scope"] == "internal"
    assert shown["effective"]["operator_hid"]["scope"] == "internal"


def test_files_carry_the_second_number_and_say_who_is_a_user(
    client: TestClient, admin: dict, inventory: dict, make: Maker
) -> None:
    files = Files(client, inventory)
    files.load(
        "contacts",
        "name,email,phone,phone2\nRobin Achterberg,robin.achterberg@example.net,202 555 0142,"
        "202 555 0177\n",
    )
    robin = make.get("/contacts", filter="name:eq:Robin Achterberg")["items"][0]
    assert robin["phone2"] == "202 555 0177"
    Maker(client, admin).post("/users", {"username": "robin", "contact_hid": robin["hid"]})
    make.post("/operators", {"label": "LM", "contact_hid": robin["hid"]})

    contacts = table(files.export("contacts", columns=["name", "phone2", "user"]))
    assert (contacts[0]["phone2"], contacts[0]["user"]) == ("202 555 0177", "robin")
    operators = table(
        files.export("operators", columns=["label", "scope", "contact_email", "contact_phone2"])
    )
    assert {key: operators[0][key] for key in ("scope", "contact_email", "contact_phone2")} == {
        "scope": "internal",
        "contact_email": "robin.achterberg@example.net",
        "contact_phone2": "202 555 0177",
    }
    # The columns to read are passed over by an import, which sets the contact's number
    # on the contact alone.
    again = files.preview(
        "operators", "label,contact,scope,contact_phone\nLM,robin.achterberg@example.net,x,y\n"
    )
    assert (again["job"]["unchanged"], again["job"]["rejected"]) == (1, 0)


# --- a username is changed ------------------------------------------------------------


def test_an_admin_renames_a_user_who_keeps_their_sessions(client: TestClient, admin: dict) -> None:
    desk = Maker(client, admin)
    ivy = sign_in(client, "ivy", INVENTORY_CODE)
    me = desk.get("/users", q="ivy")["items"][0]
    renamed = desk.patch(
        f"/users/{me['hid']}", {"row_version": me["row_version"], "username": "ivy.n"}
    )
    assert renamed["username"] == "ivy.n"
    # The session goes on, and the person signs in under the new name, not the old one.
    assert client.get(f"{API}/auth/me", headers=ivy).json()["username"] == "ivy.n"
    sign_in(client, "IVY.N", INVENTORY_CODE)
    old = client.post(
        f"{API}/auth/sign-in", json={"username": "ivy", "access_code": INVENTORY_CODE}
    )
    assert old.status_code == 401
    event = desk.audit(record_type="user", record_hid=me["hid"], action="update")[0]
    assert event["changes"] == [{"field": "username", "old": "ivy", "new": "ivy.n"}]
    # The trail names whoever made a change by the name they have now.
    made = Maker(client, ivy).tag("for-site-3")
    assert desk.audit(record_type="tag", record_hid=made["hid"])[0]["actor_name"] == "ivy.n"

    # A change of case alone is a rename; a name another user has, or one the rule
    # refuses, is not.
    cased = desk.patch(
        f"/users/{me['hid']}", {"row_version": renamed["row_version"], "username": "Ivy.N"}
    )
    assert cased["username"] == "Ivy.N"
    taken = desk.patch(
        f"/users/{me['hid']}", {"row_version": cased["row_version"], "username": "ADA"}, 409
    )
    assert "another user" in errors(taken)["username"]
    bad = desk.patch(
        f"/users/{me['hid']}", {"row_version": cased["row_version"], "username": "a b"}, 422
    )
    assert "username" in errors(bad)


# --- the kinds of external system -----------------------------------------------------


def test_the_kinds_of_external_system_are_a_list_a_site_changes(
    client: TestClient, make: Maker
) -> None:
    kinds = make.get("/choices", list="system_kind")
    assert [(one["value"], one["label"]) for one in kinds] == [
        ("monitoring", "Monitoring"),
        ("config_backup", "Configuration backup"),
        ("access_control", "Access control"),
        ("sdn_controller", "SDN controller"),
        ("cloud_service", "Cloud service"),
        ("dns", "DNS"),
        ("discovery", "Discovery"),
        ("other", "Other"),
    ]
    added = make.post("/choices", {"list": "system_kind", "value": "ipam", "label": "IPAM"})
    ipam = make.post("/external-systems", {"name": "AddressBook", "kind": "IPAM"})
    assert ipam["kind"] == "ipam"
    left_out = make.post("/external-systems", {"name": "NetWatch"})
    assert left_out["kind"] == "other"
    refused = make.post("/external-systems", {"name": "Odd", "kind": "unheard_of"}, 422)
    assert "one of" in errors(refused)["kind"]

    # A value in use is made inactive, not removed, and the system keeps it.
    removed = client.delete(f"{API}/choices/{added['hid']}", headers=make.headers)
    assert removed.status_code == 409
    make.patch(f"/choices/{added['hid']}", {"row_version": added["row_version"], "active": False})
    kept = make.patch(
        f"/external-systems/{ipam['hid']}",
        {"row_version": ipam["row_version"], "kind": "ipam", "notes": "the address plan"},
    )
    assert (kept["kind"], kept["notes"]) == ("ipam", "the address plan")
    refused = make.post("/external-systems", {"name": "Second", "kind": "ipam"}, 422)
    assert "kind" in errors(refused)

    # Where other is not offered, a system with no kind is refused, not given another.
    other = next(one for one in kinds if one["value"] == "other")
    make.patch(f"/choices/{other['hid']}", {"row_version": other["row_version"], "active": False})
    refused = make.post("/external-systems", {"name": "Nameless"}, 422)
    assert "monitoring" in errors(refused)["kind"]


# --- what the review of the server found ------------------------------------------


def test_every_role_is_told_which_user_a_contact_is(
    client: TestClient, admin: dict, viewer: dict
) -> None:
    """Who signs in is the team that runs the network, as the directory of the enterprise
    already tells them (P-172)."""
    desk = Maker(client, admin)
    robin = desk.contact("Robin Achterberg")
    user = desk.post("/users", {"username": "robin", "contact_hid": robin["hid"]})["user"]
    desk.post("/operators", {"label": "LM", "contact_hid": robin["hid"]})
    looker = Maker(client, viewer)
    seen = looker.get(f"/contacts/{robin['hid']}")
    shown = {"hid": user["hid"], "username": "robin", "record_status": "active"}
    assert (seen["is_user"], seen["user"]) == (True, shown)
    operator = looker.get("/operators")["items"][0]
    assert (operator["scope"], operator["user"]["username"]) == ("internal", "robin")


def test_a_label_whose_contact_is_retired_is_open_and_has_no_scope(
    make: Maker, db: Session
) -> None:
    dana = make.contact("Dana Ruiz")
    op2 = make.post("/operators", {"label": "Op2", "contact_hid": dana["hid"]})
    # Left so before 0.9.14: since then a contact is not retired under a label (P-297).
    left_retired(db, dana["hid"])
    shown = make.get(f"/operators/{op2['hid']}")
    assert (shown["is_open"], shown["scope"]) == (True, None)
    assert make.get("/operators", filter="scope:empty:true")["total"] == 1
    item = make.item(name="site2-sw-03", operator_hid=op2["hid"])
    assert make.get(f"/items/{item['hid']}")["operator"]["scope"] is None


def test_what_is_wrong_with_a_new_contact_is_named_as_its_field(
    client: TestClient, admin: dict
) -> None:
    desk = Maker(client, admin)
    desk.contact("Robin Achterberg")
    taken = desk.post(
        "/users",
        {"username": "robin", "contact": {"name": "R", "email": "robin.achterberg@example.net"}},
        409,
    )
    assert "contact.email" in errors(taken)
    bad = desk.post("/users", {"username": "robin", "contact": {"name": "R", "email": "x"}}, 422)
    assert "contact.email" in errors(bad)
    # Nothing was made: the user and its contact are one change.
    assert [one["username"] for one in desk.get("/users", q="robin")["items"]] == []


def test_a_kept_answer_is_worked_out_again_when_a_user_is_given_a_contact(
    client: TestClient, admin: dict, make: Maker
) -> None:
    from hirdir.io import kept

    kept.drop()
    robin = make.contact("Robin Achterberg")
    lm = make.post("/operators", {"label": "LM", "contact_hid": robin["hid"]})
    make.item(name="site2-sw-01", operator_hid=lm["hid"], lifecycle_state="Prod")
    first = make.get("/reports/coverage", section="uncovered")
    assert first["items"][0]["operator"]["scope"] == "external"
    Maker(client, admin).post("/users", {"username": "robin", "contact_hid": robin["hid"]})
    again = make.get("/reports/coverage", section="uncovered")
    assert again["items"][0]["operator"]["scope"] == "internal"
    checked = Maker(client, admin).post("/kept-answers/check", {}, 200)
    assert checked["differed"] == []


def test_the_kind_of_a_system_in_a_file(client: TestClient, inventory: dict, make: Maker) -> None:
    files = Files(client, inventory)
    make.post("/choices", {"list": "system_kind", "value": "ipam", "label": "IPAM"})
    files.load("external_systems", "name,kind\nAddressBook,ipam\nNetWatch,\n")
    found = {one["name"]: one["kind"] for one in make.get("/external-systems")["items"]}
    assert found == {"AddressBook": "ipam", "NetWatch": "other"}
    refused = files.preview("external_systems", "name,kind\nOdd,unheard_of\n")
    assert refused["job"]["rejected"] == 1


def test_a_renamed_service_account_keeps_its_tokens(client: TestClient, admin: dict) -> None:
    desk = Maker(client, admin)
    bot = desk.post("/users", {"username": "sync", "is_service_account": True})["user"]
    token = desk.post(f"/users/{bot['hid']}/service-tokens", {"name": "nightly"})["secret"]
    desk.post("/role-grants", {"role": "viewer", "user_hid": bot["hid"]})
    desk.patch(f"/users/{bot['hid']}", {"row_version": bot["row_version"], "username": "sync-2"})
    me = client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert (me.status_code, me.json()["username"]) == (200, "sync-2")
