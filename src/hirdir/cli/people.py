"""The commands that retire a user, a contact or an operator, and bring a user back
(P-296 to P-298).

Each prints what is linked to the record, with what the options say becomes of each,
and sends the one request. The server holds the rules: a linked record that the
options do not say is refused by it, and the refusal is printed. `--dry-run` prints the
plan and sends nothing.
"""

from typing import Annotated, Any

import typer

from hirdir import ids
from hirdir.cli import client
from hirdir.cli.client import Target

Url = Annotated[str | None, typer.Option(help="The server, such as https://host/hirdir.")]
Token = Annotated[str | None, typer.Option(help="A session or service token.")]
Fate = Annotated[
    str | None,
    typer.Option(help="What becomes of it: retire or keep.", metavar="retire|keep"),
]
Labels = Annotated[
    list[str] | None,
    typer.Option(
        "--operator",
        metavar="LABEL=ACTION",
        help="What becomes of an operator, once for each: LABEL=retire, which releases "
        "what the label is on, LABEL=keep, LABEL=open, which leaves it with nobody "
        "behind it, or LABEL=hand_over:CONTACT, the email address, name or HID of who "
        "it goes to.",
    ),
]
DryRun = Annotated[
    bool, typer.Option("--dry-run", help="Print what would be done, and send nothing.")
]
ACTIONS = ("retire", "keep", "open", "hand_over")
WORDS = {
    "retire": "retire",
    "keep": "keep",
    "open": "leave open",
    "hand_over": "hand over",
    "bring_back": "bring back",
}


def find_user(target: Target, text: str) -> dict[str, Any]:
    """Return the user with a username or an HID, a retired one too.

    The whole username is looked for first, without regard to case, among the retired as
    among the rest: a username may have the form of an HID, another account's HID too,
    and it is the username that a person types. What is no username and has the form of
    an HID is read by that HID, which the list of users never finds: it looks at parts
    of usernames and of the names of contacts.
    """
    found = client.call(
        target, "GET", "/users", params={"q": text, "retired": "yes", "limit": 1000}
    )["items"]
    for user in found:
        if user["username"].lower() == text.lower():
            return user
    if ids.is_hid(text):
        return client.call(target, "GET", f"/users/{text}")
    raise client.fail(f"there is no user {text}", client.EXIT_INVALID)


def _fate(name: str, value: str | None) -> str | None:
    if value is not None and value not in ("retire", "keep"):
        raise client.fail(f"--{name} is retire or keep", 2)
    return value


def _operators(
    target: Target,
    person: dict[str, Any],
    given: list[str] | None,
    find_contact: Any,
) -> list[dict[str, Any]]:
    """Return what the options say of the operators, each named by its label or its HID."""
    said = []
    for text in given or []:
        label, _, what = text.rpartition("=")
        action, _, to = what.partition(":")
        if not label or action not in ACTIONS or (action == "hand_over") != bool(to):
            raise client.fail(
                f"--operator {text}: LABEL=retire, LABEL=keep, LABEL=open or "
                "LABEL=hand_over:CONTACT",
                2,
            )
        known = [
            one
            for one in person["operators"]
            if label in (one["hid"], one["label"]) or one["label"].lower() == label.lower()
        ]
        # One that is not linked is sent as it was typed, and the server says so.
        entry: dict[str, Any] = {"hid": known[0]["hid"] if known else label, "action": action}
        if to:
            entry["contact_hid"] = find_contact(target, to)["hid"]
            entry["to"] = to
        said.append(entry)
    return said


def _lines(
    person: dict[str, Any], kind: str, hid: str, linked: dict[str, Any], own: str
) -> list[str]:
    """Return the chain of a person, operator, contact, user, each with what becomes of it."""

    def fate(of: str, record: dict[str, Any], said: str | None) -> str:
        if (of, record["hid"]) == (kind, hid):
            return own
        if record["record_status"] == "retired":
            return "retired already"
        return said or "not said"

    by_hid = {one["hid"]: one for one in linked.get("operators", [])}
    lines = []
    for one in person["operators"]:
        entry = by_hid.get(one["hid"])
        said = None
        if entry is not None:
            said = WORDS[entry["action"]] + (f" to {entry['to']}" if entry.get("to") else "")
        on = f"on {one['uses']} records of its own"
        lines.append(f"  operator  {one['label']:<24}{on:<28}{fate('operator', one, said)}")
    contact = person["contact"]
    if contact is not None:
        named = f"named by {contact['uses']} records"
        said = WORDS.get(linked.get("contact") or "")
        lines.append(
            f"  contact   {contact['name']:<24}{named:<28}{fate('contact', contact, said)}"
        )
    user = person["user"]
    if user is not None:
        role = f"role: {user['role'] or '-'}"
        said = WORDS.get(linked.get("user") or "")
        lines.append(f"  user      {user['username']:<24}{role:<28}{fate('user', user, said)}")
    return lines


def _sent(linked: dict[str, Any]) -> dict[str, Any]:
    """Return `linked` as the API takes it: without what is only printed."""
    body: dict[str, Any] = {
        name: linked[name] for name in ("user", "contact") if linked.get(name) is not None
    }
    if linked.get("operators"):
        body["operators"] = [
            {name: value for name, value in entry.items() if name != "to"}
            for entry in linked["operators"]
        ]
    return body


def retire(
    target: Target,
    kind: str,
    path: str,
    record: dict[str, Any],
    known_as: str,
    *,
    user: str | None,
    contact: str | None,
    operators: list[str] | None,
    dry_run: bool,
    find_contact: Any,
    done: str | None = None,
) -> None:
    """Print what is linked to a record and what becomes of each, and retire it."""
    person = client.call(target, "GET", f"{path}/{record['hid']}/linked")
    linked: dict[str, Any] = {
        "user": _fate("user", user),
        "contact": _fate("contact", contact),
        "operators": _operators(target, person, operators, find_contact),
    }
    typer.echo(f"{kind} {known_as}, and what is linked to it:")
    for line in _lines(person, kind, record["hid"], linked, "retire"):
        typer.echo(line)
    if dry_run:
        typer.echo("nothing was sent: this is what would be done")
        return
    body: dict[str, Any] = {"row_version": record["row_version"]}
    if _sent(linked):
        body["linked"] = _sent(linked)
    client.call(target, "POST", f"{path}/{record['hid']}/retire", body)
    typer.echo(done or f"{known_as} is retired")


def bring_back(
    target: Target,
    user: dict[str, Any],
    *,
    contact: bool,
    operators: list[str] | None,
    dry_run: bool,
    role: str | None = None,
) -> None:
    """Print what is linked to a retired user, and bring it back with what is said and
    the role given, which the server asks of a person (P-299)."""
    person = client.call(target, "GET", f"/users/{user['hid']}/linked")
    linked: dict[str, Any] = {"contact": "bring_back" if contact else None, "operators": []}
    for label in operators or []:
        known = [
            one
            for one in person["operators"]
            if label in (one["hid"], one["label"]) or one["label"].lower() == label.lower()
        ]
        linked["operators"].append(
            {"hid": known[0]["hid"] if known else label, "action": "bring_back"}
        )
    typer.echo(f"user {user['username']}, and what is linked to it:")
    by_hid = {one["hid"] for one in linked["operators"]}
    for one in person["operators"]:
        what = "bring back" if one["hid"] in by_hid else one["record_status"]
        typer.echo(f"  operator  {one['label']:<24}{what}")
    if person["contact"] is not None:
        what = "bring back" if contact else person["contact"]["record_status"]
        typer.echo(f"  contact   {person['contact']['name']:<24}{what}")
    typer.echo(
        f"  user      {user['username']:<24}bring back"
        + (f", with the {role} role" if role else "")
    )
    if dry_run and not role and user["kind"] == "person":
        # What the server would refuse is not shown as what would be done: a person is
        # brought back with a role (P-299), and the run itself is refused at `role`.
        raise client.fail(
            f"{user['username']} is a person, brought back with a role: "
            "say --role viewer, inventory or admin",
            client.EXIT_INVALID,
        )
    if dry_run:
        typer.echo("nothing was sent: this is what would be done")
        return
    body: dict[str, Any] = {"row_version": user["row_version"]}
    if _sent(linked):
        body["linked"] = _sent(linked)
    if role:
        body["role"] = role
    back = client.call(target, "POST", f"/users/{user['hid']}/bring-back", body)
    held = back["user"]["role"]
    typer.echo(
        f"{back['user']['username']} is active again, with "
        + (f"the {held} role" if held else "no role")
        + " and no group"
    )
    if back["access_code"]:
        typer.echo(f"access code, shown this once: {back['access_code']}")
