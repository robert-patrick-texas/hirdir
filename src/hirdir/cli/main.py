"""The hirdir command."""

import json
from datetime import datetime
from typing import Annotated, Any

import typer

import hirdir
from hirdir import clock
from hirdir.cli import client, inventory, people, profile, references
from hirdir.cli.admin import admin

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
    help="hirdir: network equipment lifecycle and inventory.",
)
app.add_typer(admin, name="admin")
users = typer.Typer(no_args_is_help=True, help="Accounts. Needs the Admin role.")
app.add_typer(users, name="users")
for name, group in inventory.GROUPS.items():
    app.add_typer(group, name=name)
# References: files kept by hirdir and links to files kept elsewhere (P-162).
app.add_typer(references.group, name="references")
# A person's own profile: their contact, their operators and their access code (P-289).
app.add_typer(profile.group, name="profile")
app.command("import")(inventory.import_file)
app.command("export")(inventory.export)
app.command("renewals")(inventory.renewals_worklist)

Url = Annotated[str | None, typer.Option(help="The server, such as https://host/hirdir.")]
Token = Annotated[str | None, typer.Option(help="A session or service token.")]
Format = Annotated[str, typer.Option("--format", help="table or json")]


@app.command()
def version() -> None:
    """Print the version of this command."""
    typer.echo(hirdir.__version__)


@app.command("sign-in")
def sign_in(
    url: Url = None,
    username: Annotated[str | None, typer.Option(help="Asked for when left out.")] = None,
) -> None:
    """Sign in with a username and access code, and remember the session. An account that
    holds no role is refused, with whom to ask, and no session is kept (P-299)."""
    target = client.load_target(url)
    target.token = ""
    if not target.url:
        target.url = typer.prompt("Server URL").rstrip("/")
    name = username or typer.prompt("Username")
    code = typer.prompt("Access code", hide_input=True)
    session = client.call(target, "POST", "/auth/sign-in", {"username": name, "access_code": code})
    target.token = session["token"]
    path = client.save_target(target)
    until = clock.shown(datetime.fromisoformat(session["expires_at"]), profile.zone(target))
    typer.echo(
        f"signed in as {session['user']['username']} ({session['user']['role']}) until {until}"
    )
    typer.echo(f"session kept in {path}", err=True)


@app.command("sign-out")
def sign_out() -> None:
    """Forget the remembered session."""
    target = client.load_target()
    target.token = ""
    client.save_target(target)
    typer.echo("signed out")


@app.command()
def whoami(url: Url = None, token: Token = None, output: Format = "table") -> None:
    """Show who is signed in, the role they hold, the contact they are and the
    operators they are behind."""
    me = client.call(client.load_target(url, token), "GET", "/auth/me")
    if output == "json":
        typer.echo(json.dumps(me, indent=2))
        return
    groups = ", ".join(group["name"] for group in me["groups"]) or "-"
    typer.echo(f"{me['username']}  role: {me['role'] or '-'}  groups: {groups}")
    if me["kind"] != "person":
        # A service account and an agent are no person: they have no contact and no
        # operator. An agent is answerable to a person, who holds its role (P-316).
        line = f"{'kind':<14}{me['kind']}"
        if me["answerable"] is not None:
            line += f", for {me['answerable']['username']}"
            if me["role_in_force"] != me["role"]:
                line += f", held to {me['role_in_force'] or 'no role'}"
        typer.echo(line)
        return
    for line in profile.lines(me):
        typer.echo(line)


@users.command("list")
def users_list(
    retired: Annotated[
        bool, typer.Option("--retired", help="The retired accounts as well, marked so.")
    ] = False,
    retired_only: Annotated[
        bool, typer.Option("--retired-only", help="The retired accounts alone.")
    ] = False,
    kind: Annotated[
        str | None,
        typer.Option(
            "--kind", metavar="person|service|agent", help="The accounts of one kind (P-316)."
        ),
    ] = None,
    url: Url = None,
    token: Token = None,
    output: Format = "table",
) -> None:
    """List users: those that are not retired, unless the retired are asked for. An agent
    is followed by the person answerable for it."""
    which = "only" if retired_only else "yes" if retired else "no"
    params: dict[str, Any] = {"limit": 1000, "retired": which}
    if kind:
        params["kind"] = kind
    page = client.call(client.load_target(url, token), "GET", "/users", params=params)
    if output == "json":
        typer.echo(json.dumps(page["items"], indent=2))
        return
    typer.echo(f"{'USERNAME':<24}{'ROLE':<11}{'KIND':<9}{'STATE':<10}GROUPS")
    for user in page["items"]:
        kind = user["kind"]
        state = "disabled" if user["disabled"] else "active"
        if user["record_status"] == "retired":
            state = "retired"
        groups = ", ".join(group["name"] for group in user["groups"])
        line = f"{user['username']:<24}{user['role'] or '-':<11}{kind:<9}{state:<10}{groups}"
        if user["answerable"] is not None:
            line += f"  for {user['answerable']['username']}"
            if user["role_in_force"] != user["role"]:
                line += f", held to {user['role_in_force'] or 'no role'}"
        typer.echo(line.rstrip())


@users.command("retire")
def users_retire(
    username: Annotated[str, typer.Argument(help="A username or an HID.")],
    contact: people.Fate = None,
    operator: people.Labels = None,
    agent: people.Agents = None,
    dry_run: people.DryRun = False,
    url: Url = None,
    token: Token = None,
) -> None:
    """Retire the account of somebody who has left: it signs in no longer and loses its
    groups, its role and its code. Prints its contact, the operators of that contact
    and the agents answerable to it, and takes what becomes of each: --contact and, for
    each, --operator and --agent (P-316)."""
    target = client.load_target(url, token)
    found = people.find_user(target, username)
    people.retire(
        target,
        "user",
        "/users",
        found,
        found["username"],
        user=None,
        contact=contact,
        operators=operator,
        dry_run=dry_run,
        find_contact=inventory.find_contact,
        agents=agent,
    )


@users.command("bring-back")
def users_bring_back(
    username: Annotated[str, typer.Argument(help="A username or an HID.")],
    contact: Annotated[
        bool, typer.Option("--contact", help="Bring its retired contact back with it.")
    ] = False,
    operator: Annotated[
        list[str] | None,
        typer.Option(
            "--operator",
            metavar="LABEL",
            help="A retired operator of its contact to bring back with it, once for each.",
        ),
    ] = None,
    role: Annotated[
        str | None,
        typer.Option(
            help="viewer, inventory or admin: the role it holds again, which a person is given."
        ),
    ] = None,
    answerable: Annotated[
        str | None,
        typer.Option(
            "--for",
            metavar="USER",
            help="Of an agent: the person answerable for it from then on, which it needs "
            "where its own is retired (P-316).",
        ),
    ] = None,
    dry_run: people.DryRun = False,
    url: Url = None,
    token: Token = None,
) -> None:
    """Bring a retired account back: active, with a new access code, printed once, the
    role given by --role and no group. A person is given a role, since an account with
    none does not sign in. An account whose contact is retired is brought back with it,
    and an agent whose person is retired is brought back answerable to --for."""
    target = client.load_target(url, token)
    found = people.find_user(target, username)
    people.bring_back(
        target,
        found,
        contact=contact,
        operators=operator,
        dry_run=dry_run,
        role=role,
        answerable=answerable,
    )


if __name__ == "__main__":
    app()
