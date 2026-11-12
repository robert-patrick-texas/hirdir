"""The hirdir command."""

import json
from typing import Annotated

import typer

import hirdir
from hirdir.cli import client
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
    typer.echo(f"signed in as {session['user']['username']} ({role}) until {session['expires_at']}")
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
    """Show who is signed in and the role they hold."""
    me = client.call(client.load_target(url, token), "GET", "/auth/me")
    if output == "json":
        typer.echo(json.dumps(me, indent=2))
        return
    groups = ", ".join(group["name"] for group in me["groups"]) or "-"
    typer.echo(f"{me['username']}  role: {me['role'] or '-'}  groups: {groups}")


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
