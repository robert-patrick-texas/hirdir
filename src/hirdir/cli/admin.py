"""`hirdir admin`: commands that run on the server and work on the database directly.

They exist because they must work before any account does. Everything else the CLI does
goes through the API.
"""

import contextlib
import fcntl
import hashlib
import os
import shutil
import socket
import sqlite3
import stat
import tomllib
from collections.abc import Iterable
from pathlib import Path
from typing import Annotated, NamedTuple, TextIO

import typer
import uvicorn
from sqlalchemy import Engine, func, inspect, select, text

from hirdir import clock
from hirdir import config as config_module
from hirdir.auth.roles import Role
from hirdir.config import Config
from hirdir.db import migrate as migrations
from hirdir.db.engine import SQLITE_PRAGMAS, make_engine, make_sessions
from hirdir.db.models import ReferenceFile
from hirdir.domain import accounts, audit, settings
from hirdir.domain import reset as reset_rules
from hirdir.domain.errors import DomainError
from hirdir.io import store as file_store
from hirdir.io.store import Store

DEV_CONFIG = '[server]\nstate_dir = "."\n'
# How many references a message names before it says how many more there are.
NAMED_IN_A_MESSAGE = 5
# The umask of hirdir.service, UMask= in its unit: what it writes in the state directory
# is for the hirdir user and its group alone.
SERVICE_UMASK = 0o027

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
    # One server to a database: a second one started on the same state directory would
    # take for stopped the import the first is applying, and work it twice.
    lock = _one_server(config.state_dir)
    try:
        app = create_app(config, scheduled=True)
        uvicorn.run(app, host=host, port=port, server_header=False, proxy_headers=False)
    finally:
        lock.close()


def _one_server(state_dir: Path) -> TextIO:
    """Hold the lock that only one server holds on a state directory, or stop."""
    state_dir.mkdir(parents=True, exist_ok=True)
    held = (state_dir / "server.lock").open("a")
    try:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        held.close()
        typer.echo(f"another hirdir server is running on {state_dir}: stop it first", err=True)
        raise typer.Exit(1) from None
    return held


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


class Named(NamedTuple):
    """A reference with content, as a database file names it."""

    hid: str
    title: str
    file_name: str
    sha256: str


def _named_in(path: Path) -> list[Named]:
    """Return every reference with content that a database file names, read without
    changing it. A database of 0.8.0 or before has no references, and names none.

    A backup is a copy of a database in WAL mode, and a connection that may not write
    leaves a -wal and a -shm file beside what it read. It is read as immutable instead,
    which it is once it is written, so that SQLite makes neither.
    """
    uri = f"{path.absolute().as_uri()}?mode=ro&immutable=1"
    with contextlib.closing(sqlite3.connect(uri, uri=True)) as connection:
        found = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'reference_files'"
        ).fetchone()
        if found is None:
            return []
        rows = connection.execute(
            "SELECT hid, title, file_name, sha256 FROM reference_files"
            " WHERE sha256 IS NOT NULL ORDER BY title, hid"
        )
        return [Named(*row) for row in rows]


def _private_directory(path: Path) -> None:
    """Make a directory for the service and its group alone, whatever the umask of whoever
    makes it."""
    if not path.is_dir():
        path.mkdir(exist_ok=True)
        path.chmod(0o750)


def _hold(live: Store, kept: Store, checksums: Iterable[str]) -> list[str]:
    """Put into the files of the backups each content of checksums that they lack, from
    the store, and return those that neither has.

    A hard link takes no room where the two directories are on one file system, and
    content is never changed, so a link is as good as a copy. Where they are on two, or
    the link is refused, the content is copied, under another name until it is whole.
    """
    lacking = []
    for sha256 in checksums:
        target = kept.path_of(sha256)
        if target.is_file():
            continue
        source = live.path_of(sha256)
        if not source.is_file():
            lacking.append(sha256)
            continue
        _private_directory(target.parent)
        try:
            os.link(source, target)
        except FileExistsError:
            continue
        except FileNotFoundError:
            # Erased since it was looked for.
            lacking.append(sha256)
        except OSError:
            part = target.with_name(f".{target.name}{file_store.PART}")
            try:
                shutil.copyfile(source, part)
            except FileNotFoundError:
                part.unlink(missing_ok=True)
                lacking.append(sha256)
                continue
            part.chmod(0o640)
            os.replace(part, target)
    return lacking


def _prune(kept: Store, backups: Iterable[Path]) -> None:
    """Remove from the files of the backups every content that no backup kept names.

    A backup that cannot be read may name any of them, so then nothing is removed.
    """
    named: set[str] = set()
    for backup in backups:
        try:
            named.update(reference.sha256 for reference in _named_in(backup))
        except sqlite3.Error as error:
            typer.echo(
                f"hirdir: {backup} cannot be read ({error}), so nothing was removed from "
                f"{kept.root}",
                err=True,
            )
            return
    for sha256 in list(kept.contents()):
        if sha256 not in named:
            path = kept.path_of(sha256)
            path.unlink(missing_ok=True)
            with contextlib.suppress(OSError):
                # The directory of the first two characters, once it holds nothing.
                path.parent.rmdir()


def _backup(config: Config) -> Path:
    """Copy the database into the backup directory with the content of the reference
    files it names, keep only the newest few, and return the copy (P-161)."""
    source = _sqlite_path(config)
    if not source.is_file():
        raise _fail(f"there is no database at {source}")
    # Readable by the service and its group and by nobody else, whatever the umask of
    # whoever takes the first backup.
    config.backup_dir.parent.mkdir(parents=True, exist_ok=True)
    _private_directory(config.backup_dir)
    live, kept = Store(config.files_dir), Store(config.backup_dir / "files")
    _private_directory(kept.root)
    # The content first, so that the copy names nothing that is not there; then what was
    # uploaded while the copy was taken. Content that the copy names and that is in
    # neither place was erased in the moment between.
    _hold(live, kept, list(live.contents()))
    target = config.backup_dir / f"hirdir-{clock.stamp(clock.now(), _time_zone(config))}.db"
    _copy_database(source, target)
    lost = _hold(live, kept, sorted({reference.sha256 for reference in _named_in(target)}))
    if lost:
        typer.echo(
            f"hirdir: {target} names {len(lost)} reference files whose content is not in "
            f"{live.root}: {', '.join(lost[:NAMED_IN_A_MESSAGE])}"
            f"{' and more' if len(lost) > NAMED_IN_A_MESSAGE else ''}. A restore of it "
            "needs --allow-missing-files.",
            err=True,
        )
    backups = sorted(config.backup_dir.glob("hirdir-*.db"), key=_made_at)
    for old in backups[: -config.backup_keep]:
        old.unlink()
    _prune(kept, backups[-config.backup_keep :])
    return target


@admin.command()
def backup() -> None:
    """Copy the database into the backup directory and keep only the newest few."""
    typer.echo(str(_backup(_load())))


def _time_zone(config: Config) -> str:
    """Return the application's time zone, or the default where it cannot be read.

    A backup is taken before a migration too, when the database may be older than the
    settings themselves.
    """
    try:
        with make_sessions(make_engine(config.database_url))() as db:
            return settings.value(db, "time_zone")
    except Exception:
        return clock.DEFAULT_ZONE


def _made_at(path: Path) -> float:
    """Return when a backup was made: from its name, or from the file when it has none.

    The names are not put in order as text, because their zone can change.
    """
    moment = clock.of_stamp(path.name)
    return moment.timestamp() if moment is not None else path.stat().st_mtime


def _checksum(path: Path) -> str | None:
    """Return the SHA-256 of a file read through, or None when there is no such file."""
    try:
        with path.open("rb") as handle:
            return hashlib.file_digest(handle, "sha256").hexdigest()
    except FileNotFoundError, IsADirectoryError:
        return None


def _listed(references: list[Named]) -> str:
    """Name the first few references for a message, and say how many more there are."""
    shown = ", ".join(f"{one.hid} ({one.file_name})" for one in references[:NAMED_IN_A_MESSAGE])
    more = len(references) - NAMED_IN_A_MESSAGE
    return shown + (f" and {more} more" if more > 0 else "")


def _copy_into(live: Store, source: Path, sha256: str) -> None:
    """Copy content into the store, checked again on the way: a copy and never a link,
    since the store is the service's own and changes without the backup."""
    with file_store.LOCK, source.open("rb") as handle:
        upload = live.receive(limit=os.fstat(handle.fileno()).st_size)
        try:
            while piece := handle.read(file_store.CHUNK):
                upload.write(piece)
            if upload.finish() != sha256:
                raise _fail(f"{source} changed while it was copied: run the restore again")
            live.keep(upload)
        finally:
            upload.discard()


@admin.command()
def restore(
    file: Path,
    files: Annotated[
        Path | None,
        typer.Option(
            "--files",
            metavar="DIR",
            help="Take the content of the reference files from DIR, not from the files/ "
            "directory beside FILE.",
        ),
    ] = None,
    allow_missing_files: Annotated[
        bool,
        typer.Option(
            "--allow-missing-files",
            help="Restore even where the content of some reference files is in neither "
            "place, and list them.",
        ),
    ] = False,
) -> None:
    """Put a backup in place of the database, with the content of the reference files it
    names. Stop the hirdir service first.

    Nothing is changed until every file that the backup names has been found, in the
    store or in DIR with its checksum.
    """
    config = _load()
    target = _sqlite_path(config)
    if not file.is_file():
        raise _fail(f"there is no file {file}")
    verdict = _integrity(file)
    if verdict != "ok":
        raise _fail(f"{file} fails its integrity check: {verdict}")
    live = Store(config.files_dir)
    source = Store(files if files is not None else file.parent / "files")
    references = _named_in(file)
    named = {reference.sha256 for reference in references}
    needed, missing = [], set()
    for sha256 in sorted(named):
        if live.has(sha256):
            continue
        if _checksum(source.path_of(sha256)) == sha256:
            needed.append(sha256)
        else:
            missing.add(sha256)
    lost = [reference for reference in references if reference.sha256 in missing]
    if lost and not allow_missing_files:
        where = f"in {source.root}" if source.root.is_dir() else f"there is no {source.root}"
        raise _fail(
            f"{len(lost)} of the {len(references)} reference files that {file} names have "
            f"their content neither in {live.root} nor, with its checksum, {where}: "
            f"{_listed(lost)}. Nothing was changed. Name where the files are with "
            "--files DIR, or restore without them with --allow-missing-files."
        )

    if target.is_file():
        aside = target.with_name(target.name + ".before-restore")
        _copy_database(target, aside)
        typer.echo(f"the database as it was is kept at {aside}")
    # The content first and the database after it, so that a restore that stops on the
    # way leaves a database whose files are all there. The store makes its directories
    # as the service does, under its umask, whatever the umask of whoever restores.
    _private_directory(live.root)
    umask = os.umask(SERVICE_UMASK)
    try:
        for sha256 in needed:
            _copy_into(live, source.path_of(sha256), sha256)
    finally:
        os.umask(umask)
    if needed:
        typer.echo(f"the content of {len(needed)} files was copied from {source.root}")
    for leftover in (target, Path(f"{target}-wal"), Path(f"{target}-shm")):
        leftover.unlink(missing_ok=True)
    shutil.copyfile(file, target)
    target.chmod(0o600)
    migrations.upgrade(config.database_url)
    # What the restored database does not name is set aside, as the database was.
    unnamed = [sha256 for sha256 in live.contents() if sha256 not in named]
    aside_files = live.root.with_name(f"{live.root.name}.before-restore")
    if aside_files.exists():
        shutil.rmtree(aside_files)
    if unnamed:
        _private_directory(aside_files)
        for sha256 in unnamed:
            moved = file_store.path_in(aside_files, sha256)
            _private_directory(moved.parent)
            # A rename, or a copy where a site keeps the store on a volume of its own.
            shutil.move(live.path_of(sha256), moved)
        typer.echo(
            f"the content of {len(unnamed)} files that the restored database does not name "
            f"is kept at {aside_files}"
        )
    typer.echo(f"restored {file} to {target}")
    if lost:
        typer.echo(
            f"the content of these {len(lost)} reference files is missing, and a download of "
            "one says so; upload a new edition of each, or erase it:"
        )
        for reference in lost:
            typer.echo(f"  {reference.hid}  {reference.title}  ({reference.file_name})")


def _is_serving(config: Config) -> bool:
    """Say whether something answers where the service listens."""
    try:
        with socket.create_connection(config.host_port, timeout=1):
            return True
    except OSError:
        return False


@admin.command()
def reset(
    everything: Annotated[
        bool,
        typer.Option(
            "--everything",
            help="Accounts, settings and the audit trail as well: back to a fresh installation.",
        ),
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", help="Go on without asking. For a script.")] = False,
) -> None:
    """Clear the inventory, to start over after trying things out. Stop the service first.

    Removes every item with its addresses and memberships, every device group,
    network, catalog entry, vendor, owner and tag, every reference with the content of
    its file, the stored imports and the history of those records. Accounts, roles,
    settings, choices and lifecycle rules stay, unless --everything is given. A backup
    is taken first, with the files.
    """
    config = _load()
    target = _sqlite_path(config)
    if not target.is_file():
        raise _fail(f"there is no database at {target}")
    if _is_serving(config):
        raise _fail(
            f"the service is running on {config.listen}: stop it first, with "
            "`sudo systemctl stop hirdir`, so that nobody is at work while the inventory goes"
        )
    engine = make_engine(config.database_url)
    with make_sessions(engine)() as db:
        held = reset_rules.counts(db)
        accounts_held = len(accounts.list_users(db, limit=1_000_000)[0])
    live = Store(config.files_dir)
    contents, size = live.size()
    typer.echo("This removes, for good:")
    for name, count in held.items():
        typer.echo(f"  {count:>8,}  {name.replace('_', ' ')}")
    if contents:
        typer.echo(f"  the content of {contents:,} files, {size:,} bytes, in {live.root}")
    typer.echo("  and the history of those records.")
    if everything:
        typer.echo(
            f"  and, with --everything, the {accounts_held} accounts, the groups, roles and "
            "tokens, the settings, the choices, the lifecycle rules and the whole audit trail."
        )
    else:
        typer.echo("Accounts, roles, settings, choices and lifecycle rules stay.")
    if not yes and typer.prompt('Type "reset" to go on', default="", show_default=False) != "reset":
        raise _fail("nothing was changed")
    kept = _backup(config)
    typer.echo(f"backup: {kept}")
    if everything:
        engine.dispose()
        for file in (target, Path(f"{target}-wal"), Path(f"{target}-shm")):
            file.unlink(missing_ok=True)
        migrations.upgrade(config.database_url)
        target.chmod(0o600)
        engine = make_engine(config.database_url)
    else:
        with make_sessions(engine)() as db:
            reset_rules.clear_inventory(db, audit.SYSTEM, kept.name)
            db.commit()
    # No record names any content now; the backup holds it all.
    with make_sessions(engine)() as db:
        erased = live.remove_unnamed(db, list(live.contents()))
    engine.dispose()
    if erased:
        typer.echo(
            f"the content of {len(erased):,} files was erased from {live.root}; the backup "
            f"holds it in {kept.parent / 'files'}"
        )
    if everything:
        typer.echo("the database is as a fresh installation has it: create the first Admin with")
        typer.echo("  hirdir admin create-user --role admin NAME")
    else:
        typer.echo("the inventory is empty. Accounts and settings are as they were.")
    typer.echo(f"to put back what was there: hirdir admin restore {kept}")


def _check_files(config: Config, engine: Engine) -> bool:
    """Report the store of reference files beside what the database names, and say
    whether every content that a reference names is there. Content that none names is
    reported and is no failure: the server removes it when it starts, a day after it was
    put there."""
    live = Store(config.files_dir)
    with make_sessions(engine)() as db:
        references = db.scalar(
            select(func.count()).select_from(ReferenceFile).where(ReferenceFile.sha256.is_not(None))
        )
        named = file_store.named_by(db)
        held = set(live.contents())
        missing = sorted(named - held)
        lacking = db.execute(
            select(ReferenceFile.sha256, ReferenceFile.hid, ReferenceFile.file_name)
            .where(ReferenceFile.sha256.in_(missing))
            .order_by(ReferenceFile.sha256, ReferenceFile.hid)
        ).all()
    count, size = live.size()
    typer.echo(
        f"reference files: {references:,} with content, kept in {count:,} files of "
        f"{size:,} bytes in {live.root}"
    )
    for sha256, hid, file_name in lacking:
        typer.echo(f"missing content: {sha256} of {hid} ({file_name})")
    for sha256 in sorted(held - named):
        typer.echo(f"unnamed content: {sha256}, which no reference names")
    return not missing


@admin.command()
def check() -> None:
    """Report the schema revision, the database's integrity and its settings, and the
    reference files beside it."""
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
    # A database of a version before 0.9.0, not yet migrated, has no references.
    if inspect(engine).has_table(ReferenceFile.__tablename__):
        healthy = _check_files(config, engine) and healthy
    engine.dispose()
    if not healthy:
        raise typer.Exit(1)


@admin.command("config")
def write_config(
    current: Annotated[
        bool,
        typer.Option(
            "--current", help="Set what the configuration file in force sets, as it sets it."
        ),
    ] = False,
    output: Annotated[
        Path | None, typer.Option("--output", help="Write to this file, not to standard output.")
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", help="With --output, write over a file that is there.")
    ] = False,
) -> None:
    """Write a complete configuration file: every key, with its default and what it is
    for, commented out at its default."""
    given, source = None, None
    if current:
        source = config_module.config_path()
        try:
            given = config_module.read(source)
        except (OSError, tomllib.TOMLDecodeError) as error:
            raise _fail(f"{source} cannot be read: {error}") from None
    text = config_module.written(given)
    if output is None:
        typer.echo(text, nl=False)
        return
    if output.exists() and not force:
        raise _fail(f"{output} is there already: add --force to write over it")
    try:
        if source is not None and source.is_file():
            _write_as(output, text, source)
        else:
            output.write_text(text, encoding="utf-8")
    except OSError as error:
        raise _fail(f"{output} cannot be written: {error}") from None
    typer.echo(f"wrote {output}", err=True)


def _write_as(path: Path, text: str, like: Path) -> None:
    """Write text to a file that may be read by whoever may read the file `like` and by
    nobody else: what that file sets, the password of a proxy among it, is in text."""
    held = like.stat()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        os.fchmod(handle.fileno(), 0o600)
        handle.write(text)
    with contextlib.suppress(OSError):
        # Only root gives a file to another group; anybody else keeps their own.
        os.chown(path, -1, held.st_gid)
    path.chmod(stat.S_IMODE(held.st_mode))
