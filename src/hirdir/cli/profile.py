"""The client commands of a person's own profile (P-289, P-294, P-295): show it, change
the contact the person is and the operators they are behind, and change their access
code.

Every command calls the routes under `/auth/me`, which change the records of whoever is
signed in and no other. What may be changed, and by which rules, the server decides.
"""

import json
import os
from datetime import datetime
from typing import Annotated, Any

import typer

from hirdir import clock
from hirdir.cli import client, inventory

Url = inventory.Url
Token = inventory.Token
Format = Annotated[str, typer.Option("--format", help="table or json")]

group = typer.Typer(
    no_args_is_help=True,
    help="Your own profile: the contact you are, your operators and your access code.",
)

# The fields of the contact a person changes, in the order they are shown.
CONTACT_FIELDS = ("name", "email", "phone", "phone2", "organization")
ASK_AN_ADMIN = "an Admin gives an account its contact"


def lines(me: dict[str, Any]) -> list[str]:
    """Return what a person is, line by line: the contact and each operator."""
    contact = me["contact"]
    if contact is None:
        shown = [f"{'contact':<14}none: {ASK_AN_ADMIN}"]
    else:
        shown = [f"{name:<14}{contact[name] or '-'}" for name in CONTACT_FIELDS]
        if contact["record_status"] == "retired":
            shown.append(f"{'contact':<14}retired: an Admin brings a contact back")
    for operator in me["operators"]:
        shown.append(f"{'operator':<14}{operator['label']}  {operator['colour'] or '-'}")
    if contact is not None and not me["operators"]:
        shown.append(f"{'operator':<14}-")
    return shown


def _show(me: dict[str, Any]) -> None:
    typer.echo(f"{'username':<14}{me['username']}")
    typer.echo(f"{'role':<14}{me['role'] or '-'}")
    for line in lines(me):
        typer.echo(line)


@group.command("show")
def show(url: Url = None, token: Token = None, output: Format = "table") -> None:
    """Show your profile: the contact you are and the operators you are behind."""
    me = client.call(client.load_target(url, token), "GET", "/auth/me")
    if output == "json":
        typer.echo(json.dumps(me, indent=2))
        return
    _show(me)


def zone(target: client.Target, role: str | None) -> str:
    """Return the time zone a time is shown in: the application's, as the server has it
    set, or the one it starts with for an account with no role, which the settings are
    closed to."""
    if role is None:
        return clock.DEFAULT_ZONE
    for setting in client.call(target, "GET", "/settings"):
        if setting["key"] == "time_zone":
            return setting["value"]
    return clock.DEFAULT_ZONE


def _the_operator(me: dict[str, Any], named: str | None) -> dict[str, Any]:
    """Return the operator of the person that a change is for: the one named, by its
    label or its HID, or the only one there is."""
    own = me["operators"]
    if not own:
        raise client.fail("you are behind no operator", client.EXIT_INVALID)
    if named is None:
        if len(own) > 1:
            labels = ", ".join(one["label"] for one in own)
            raise client.fail(f"you are behind several operators: say --operator ({labels})", 2)
        return own[0]
    for one in own:
        if named == one["hid"] or named.strip().casefold() == one["label"].casefold():
            return one
    raise client.fail(f"you are behind no operator {named}", client.EXIT_INVALID)


@group.command("set")
def set_(
    name: Annotated[str | None, typer.Option(help="Your name.")] = None,
    email: Annotated[str | None, typer.Option(help="Your email address; '' for none.")] = None,
    phone: Annotated[str | None, typer.Option(help="Your number; '' for none.")] = None,
    phone2: Annotated[str | None, typer.Option(help="Your second number; '' for none.")] = None,
    organization: Annotated[
        str | None, typer.Option(help="Your organization; '' for none.")
    ] = None,
    label: Annotated[str | None, typer.Option(help="Another label for your operator.")] = None,
    colour: Annotated[
        str | None, typer.Option(help="The colour of your operator, as #1f6feb; '' for none.")
    ] = None,
    operator: Annotated[
        str | None,
        typer.Option(help="Which operator --label and --colour are for, where you have several."),
    ] = None,
    url: Url = None,
    token: Token = None,
) -> None:
    """Change your own name, email, numbers and organization, and the label and the
    colour of your operator. Your contact and an operator are two changes, your contact
    first: where the operator's is refused, your contact's is kept, and is said."""
    given = {"name": name, "email": email, "phone": phone, "phone2": phone2}
    given["organization"] = organization
    contact = {field: value for field, value in given.items() if value is not None}
    marks = {"label": label, "colour": colour}
    marks = {field: value for field, value in marks.items() if value is not None}
    if operator is not None and not marks:
        raise client.fail("--operator says which operator --label and --colour are for", 2)
    if not contact and not marks:
        raise client.fail("say what to change, such as --phone or --label", 2)
    target = client.load_target(url, token)
    me = client.call(target, "GET", "/auth/me")
    if contact and me["contact"] is None:
        raise client.fail(f"this account has no contact: {ASK_AN_ADMIN}", client.EXIT_CONFLICT)
    # Which operator is meant is settled before anything is sent.
    which = _the_operator(me, operator) if marks else None
    stored = False
    if contact:
        version = me["contact"]["row_version"]
        me = client.call(target, "PATCH", "/auth/me/contact", {"row_version": version, **contact})
        stored = me["contact"]["row_version"] != version
    if which is not None:
        body = {"row_version": which["row_version"], **marks}
        # The contact is changed by now, where the request changed it: a refusal of
        # the operator's change says so first, and exits as that refusal does.
        done = (
            f"your contact is changed ({', '.join(contact)}); "
            f"your operator {which['label']} is not:"
            if stored
            else None
        )
        me = client.call(
            target, "PATCH", f"/auth/me/operators/{which['hid']}", body, done_before=done
        )
    _show(me)


@group.command("access-code")
def access_code(url: Url = None, token: Token = None) -> None:
    """Change your access code. Asks for the code you have and for the new one, neither
    shown as it is typed, ends every other session of yours and keeps this one."""
    target = client.load_target(url, token)
    current = typer.prompt("Current access code", hide_input=True)
    new = typer.prompt(
        "New access code",
        hide_input=True,
        confirmation_prompt="New access code again",
    )
    session = client.call(
        target,
        "POST",
        "/auth/me/access-code",
        {"current_access_code": current, "access_code": new},
    )
    target.token = session["token"]
    path = client.save_target(target)
    until = clock.shown(
        datetime.fromisoformat(session["expires_at"]), zone(target, session["user"]["role"])
    )
    typer.echo(
        f"the access code of {session['user']['username']} is changed; every other "
        f"session has ended, and this one goes on until {until}"
    )
    typer.echo(f"session kept in {path}", err=True)
    if token or os.environ.get("HIRDIR_TOKEN"):
        typer.echo(
            "the token given by --token or HIRDIR_TOKEN has ended: use the one kept",
            err=True,
        )
