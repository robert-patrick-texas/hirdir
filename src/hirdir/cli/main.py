"""The hirdir command."""

import json
from datetime import datetime
from typing import Annotated

import typer

import hirdir
from hirdir import clock
from hirdir.cli import client, inventory, profile, references
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
    """Sign in with a username and access code, and remember the session."""
    target = client.load_target(url)
    target.token = ""
    if not target.url:
        target.url = typer.prompt("Server URL").rstrip("/")
    name = username or typer.prompt("Username")
    code = typer.prompt("Access code", hide_input=True)
    session = client.call(target, "POST", "/auth/sign-in", {"username": name, "access_code": code})
    target.token = session["token"]
    path = client.save_target(target)
    role = session["user"]["role"] or "no role"
    # The settings are closed to an account with no role, which signs in all the same.
    zone = profile.zone(target, session["user"]["role"])
    until = clock.shown(datetime.fromisoformat(session["expires_at"]), zone)
    typer.echo(f"signed in as {session['user']['username']} ({role}) until {until}")
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
    for line in profile.lines(me):
        typer.echo(line)


@users.command("list")
def users_list(url: Url = None, token: Token = None, output: Format = "table") -> None:
    """List users."""
    page = client.call(client.load_target(url, token), "GET", "/users?limit=1000")
    if output == "json":
        typer.echo(json.dumps(page["items"], indent=2))
        return
    typer.echo(f"{'USERNAME':<24}{'ROLE':<11}{'KIND':<9}{'STATE':<10}GROUPS")
    for user in page["items"]:
        kind = "service" if user["is_service_account"] else "person"
        state = "disabled" if user["disabled"] else "active"
        groups = ", ".join(group["name"] for group in user["groups"])
        typer.echo(f"{user['username']:<24}{user['role'] or '-':<11}{kind:<9}{state:<10}{groups}")


if __name__ == "__main__":
    app()
