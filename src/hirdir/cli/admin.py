"""`hirdir admin`: commands that run on the server and work on the database directly.

They exist because they must work before any account does. Everything else the CLI does
goes through the API.
"""

import os
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
import uvicorn
from sqlalchemy import text

from hirdir import config as config_module
from hirdir.auth.roles import Role
from hirdir.config import Config
from hirdir.db import migrate as migrations
from hirdir.db.engine import SQLITE_PRAGMAS, make_engine, make_sessions
from hirdir.domain import accounts, audit
from hirdir.domain.errors import DomainError

DEV_CONFIG = '[server]\nstate_dir = "."\n'

admin = typer.Typer(
    no_args_is_help=True,
    pretty_exceptions_enable=False,
    help="Commands that run on the server itself, as root or the hirdir user.",
)


def _fail(message: str, code: int = 1) -> typer.Exit:
    typer.echo(f"hirdir: {message}", err=True)
    return typer.Exit(code)


def _become_owner_of(directory: Path) -> None:
    """When run as root, carry on as the user that owns directory.

    The service runs as an unprivileged user. A file that root created in the state
    directory would be one the service could not write, so root steps down first.
    """
    if os.geteuid() != 0 or not directory.is_dir():
        return
    owner = directory.stat()
    if owner.st_uid != 0:
        os.setgroups([])
        os.setgid(owner.st_gid)
        os.setuid(owner.st_uid)


def _load() -> Config:
    config = config_module.load()
    _become_owner_of(config.state_dir)
    try:
        config.state_dir.mkdir(parents=True, exist_ok=True)
        if not os.access(config.state_dir, os.W_OK):
            raise PermissionError
    except PermissionError:
        raise _fail(
            f"cannot write to {config.state_dir}: run this as root or as the hirdir user"
        ) from None
    return config


def _sqlite_path(config: Config) -> Path:
    path = config.database_path
    if path is None:
        raise _fail("this command works on a SQLite database only")
    return path


@admin.command()
def serve(
    dev: Annotated[
        bool, typer.Option("--dev", help="Keep state beside the config file and migrate at start.")
    ] = False,
) -> None:
    """Run the server. This is what the hirdir service starts."""
    from hirdir.app import create_app

    if dev:
        path = config_module.config_path()
        if not path.is_file():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(DEV_CONFIG, encoding="utf-8")
    config = _load()
    if dev:
        migrations.upgrade(config.database_url)
    host, port = config.host_port
    # The application's own gateway reads the proxy's headers, and only from the
    # proxies named in the configuration. Uvicorn must leave them alone: if it
    # rewrote the client address first, the gateway would no longer see the proxy.
    uvicorn.run(create_app(config), host=host, port=port, server_header=False, proxy_headers=False)


@admin.command()
def migrate() -> None:
    """Bring the database to the schema this version expects."""
    config = _load()
    migrations.upgrade(config.database_url)
    typer.echo(f"schema is at revision {migrations.head(config.database_url)}")


@admin.command("create-user")
def create_user(
    username: str,
    role: Annotated[str | None, typer.Option(help="viewer, inventory or admin")] = None,
    display_name: Annotated[str, typer.Option(help="The person's name.")] = "",
    access_code: Annotated[
        str | None, typer.Option(help="Set this code instead of generating one.")
    ] = None,
    service_account: Annotated[
        bool, typer.Option("--service-account", help="An account that holds tokens.")
    ] = False,
) -> None:
    """Create a user and print the access code, which is not shown again."""
    if role is not None and role not in [r.value for r in Role]:
        raise _fail("the role must be viewer, inventory or admin", 2)
    config = _load()
    with make_sessions(make_engine(config.database_url))() as db:
        try:
            user, code = accounts.create_user(
                db,
                audit.SYSTEM,
                username=username,
                display_name=display_name,
                is_service_account=service_account,
                access_code=access_code,
            )
            if role:
                accounts.grant_role(db, audit.SYSTEM, role=role, user_hid=user.hid)
            db.commit()
        except DomainError as error:
            raise _fail(str(error), 4) from error
    typer.echo(f"created {user.username}" + (f" with the {role} role" if role else ""))
    if code and access_code is None:
        typer.echo(f"access code: {code}")


@admin.command("reset-access-code")
def reset_access_code(
    username: str,
    access_code: Annotated[
        str | None, typer.Option(help="Set this code instead of generating one.")
    ] = None,
) -> None:
    """Give a user a new access code and end every session they have."""
    config = _load()
    with make_sessions(make_engine(config.database_url))() as db:
        user = accounts.find_user(db, username)
        if user is None:
            raise _fail(f"there is no user named {username}", 4)
        try:
            code = accounts.set_access_code(db, audit.SYSTEM, user.hid, access_code)
            db.commit()
        except DomainError as error:
            raise _fail(str(error), 4) from error
    typer.echo(f"every session of {user.username} has ended")
    if access_code is None:
        typer.echo(f"access code: {code}")


def _copy_database(source: Path, target: Path) -> None:
    """Copy a SQLite database with the online backup, which is safe while it is in use."""
    with sqlite3.connect(source) as origin, sqlite3.connect(target) as copy:
        origin.backup(copy)
    target.chmod(0o600)


def _integrity(path: Path) -> str:
    with sqlite3.connect(path) as connection:
        return str(connection.execute("PRAGMA integrity_check").fetchone()[0])


@admin.command()
def backup() -> None:
    """Copy the database into the backup directory and keep only the newest few."""
    config = _load()
    source = _sqlite_path(config)
    if not source.is_file():
        raise _fail(f"there is no database at {source}")
    config.backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = config.backup_dir / f"hirdir-{stamp}.db"
    _copy_database(source, target)
    kept = sorted(config.backup_dir.glob("hirdir-*.db"))
    for old in kept[: -config.backup_keep]:
        old.unlink()
    typer.echo(str(target))


@admin.command()
def restore(file: Path) -> None:
    """Put a backup in place of the database. Stop the hirdir service first."""
    config = _load()
    target = _sqlite_path(config)
    if not file.is_file():
        raise _fail(f"there is no file {file}")
    verdict = _integrity(file)
    if verdict != "ok":
        raise _fail(f"{file} fails its integrity check: {verdict}")
    if target.is_file():
        aside = target.with_name(target.name + ".before-restore")
        _copy_database(target, aside)
        typer.echo(f"the database as it was is kept at {aside}")
    for leftover in (target, Path(f"{target}-wal"), Path(f"{target}-shm")):
        leftover.unlink(missing_ok=True)
    shutil.copyfile(file, target)
    target.chmod(0o600)
    migrations.upgrade(config.database_url)
    typer.echo(f"restored {file} to {target}")


@admin.command()
def check() -> None:
    """Report the schema revision, the database's integrity and its settings."""
    config = _load()
    engine = make_engine(config.database_url)
    at, wanted = migrations.current(engine), migrations.head(config.database_url)
    typer.echo(f"configuration:   {config.source or 'defaults (no file)'}")
    typer.echo(f"database:        {config.database_url}")
    typer.echo(f"schema revision: {at} (this version expects {wanted})")
    healthy = at == wanted
    if engine.dialect.name == "sqlite":
        with engine.connect() as connection:
            verdict = connection.execute(text("PRAGMA integrity_check")).scalar()
            typer.echo(f"integrity check: {verdict}")
            healthy = healthy and verdict == "ok"
            for name, expected in SQLITE_PRAGMAS.items():
                value = connection.execute(text(f"PRAGMA {name}")).scalar()
                typer.echo(f"{name + ':':<17}{value}")
                healthy = healthy and str(value) == str(expected)
    if not healthy:
        raise typer.Exit(1)
