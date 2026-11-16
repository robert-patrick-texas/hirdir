"""`hirdir admin backup`, `restore`, `check` and `reset` with the content of reference
files, which is kept beside the database and goes into the backups beside them (P-161)."""

import errno
import fcntl
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from typer.testing import CliRunner, Result

from hirdir import clock
from hirdir.cli import admin
from hirdir.cli.main import app
from hirdir.config import Config
from hirdir.db import migrate
from hirdir.db.engine import make_engine, make_sessions
from hirdir.db.models import ReferenceFile
from hirdir.io import store as file_store
from hirdir.io.store import Store

runner = CliRunner()


def _install(folder: Path, monkeypatch: pytest.MonkeyPatch, keep: int = 3) -> Config:
    """A configuration file and a migrated database in folder, as `hirdir admin` finds
    them, with nothing listening where the service would."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "config.toml"
    path.write_text(f'[server]\nlisten = "127.0.0.1:1"\nstate_dir = "."\n[backup]\nkeep = {keep}\n')
    monkeypatch.setenv("HIRDIR_CONFIG", str(path))
    config = Config(state_dir=folder, listen="127.0.0.1:1", backup_keep=keep)
    migrate.upgrade(config.database_url)
    return config


@pytest.fixture
def installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    return _install(tmp_path / "host", monkeypatch)


def _minutes() -> Iterator[datetime]:
    moment = datetime(2026, 11, 16, 15, 0, tzinfo=UTC)
    while True:
        yield moment
        moment += timedelta(minutes=1)


@pytest.fixture(autouse=True)
def ticking(monkeypatch: pytest.MonkeyPatch) -> None:
    """A clock that moves on a minute each time it is read, so that each backup has a
    name of its own."""
    moments = _minutes()
    monkeypatch.setattr(clock, "now", lambda: next(moments))


def _pdf(text: str) -> bytes:
    return b"%PDF-1.7\n% " + text.encode() + b"\n%%EOF\n"


def _put(config: Config, content: bytes, file_name: str) -> tuple[str, str]:
    """Keep content in the store and a reference that names it, as an upload does, and
    return its HID and checksum."""
    store = Store(config.files_dir)
    with file_store.LOCK, make_sessions(make_engine(config.database_url))() as db:
        sha256 = store.keep(store.receive_bytes(content, limit=len(content)))
        reference = ReferenceFile(
            title=file_name.rsplit(".", 1)[0],
            kind="floor_plan",
            file_name=file_name,
            media_type="application/pdf",
            size_bytes=len(content),
            sha256=sha256,
        )
        db.add(reference)
        db.commit()
        return reference.hid, sha256


def _stray(config: Config, content: bytes) -> str:
    """Keep content in the store that no reference names, and return its checksum."""
    store = Store(config.files_dir)
    with file_store.LOCK:
        return store.keep(store.receive_bytes(content, limit=len(content)))


def _erase(config: Config, hid: str) -> None:
    """Erase a reference and its content, as the server does."""
    with make_sessions(make_engine(config.database_url))() as db:
        reference = db.get(ReferenceFile, hid)
        assert reference is not None
        sha256 = reference.sha256
        db.delete(reference)
        db.commit()
        assert sha256 is not None
        Store(config.files_dir).remove_unnamed(db, [sha256])


def _named(config: Config) -> set[str]:
    with make_sessions(make_engine(config.database_url))() as db:
        return file_store.named_by(db)


def _run(*arguments: str, code: int = 0) -> Result:
    result = runner.invoke(app, ["admin", *arguments])
    assert result.exit_code == code, result.output
    return result


def _backup() -> Path:
    return Path(_run("backup").stdout.strip())


def _held(config: Config) -> Store:
    """The content held for the backups, beside them."""
    return Store(config.backup_dir / "files")


# --- backup ----------------------------------------------------------------------------


def test_a_backup_holds_each_file_once_however_many_backups_name_it(installed: Config) -> None:
    files = {_put(installed, _pdf(f"plan {n}"), f"plan-{n}.pdf")[1] for n in (1, 2)}
    backups = [_backup() for _ in range(3)]
    held = _held(installed)

    assert set(held.contents()) == files
    live = Store(installed.files_dir)
    for sha256 in files:
        # A hard link: the same file as the store's, which takes no room of its own.
        assert held.path_of(sha256).stat().st_ino == live.path_of(sha256).stat().st_ino
        assert held.path_of(sha256).stat().st_mode & 0o777 == 0o640
        assert held.path_of(sha256).parent.stat().st_mode & 0o777 == 0o750
    assert held.root.stat().st_mode & 0o777 == 0o750
    for backup in backups:
        assert {one.sha256 for one in admin._named_in(backup)} == files
    # Reading what a backup names leaves nothing beside it: a backup is a copy of a
    # database in WAL mode, which a read-only connection would leave a -wal and a -shm of.
    assert {path.name for path in installed.backup_dir.iterdir()} == {
        *(backup.name for backup in backups),
        "files",
        admin.BACKUP_LOCK,
    }


def test_a_backup_copies_the_files_where_a_link_is_refused(
    installed: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = _pdf("site map")
    _, sha256 = _put(installed, content, "site-map.pdf")

    def across(*paths: object) -> None:
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    monkeypatch.setattr(os, "link", across)
    _backup()
    held = _held(installed)
    path = held.path_of(sha256)
    assert path.read_bytes() == content
    assert path.stat().st_ino != Store(installed.files_dir).path_of(sha256).stat().st_ino
    assert path.stat().st_mode & 0o777 == 0o640
    # Nothing is left under another name.
    assert [p.name for p in path.parent.iterdir()] == [sha256]


def test_a_copy_into_the_files_of_the_backups_is_flushed_before_it_takes_its_name(
    installed: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    contents = {_put(installed, _pdf(f"far {n}"), f"far-{n}.pdf")[1] for n in (1, 2)}

    def across(*paths: object) -> None:
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    flushed: list[str] = []
    fsync = os.fsync

    def recorded(descriptor: int) -> None:
        flushed.append(os.readlink(f"/proc/self/fd/{descriptor}"))
        fsync(descriptor)

    monkeypatch.setattr(os, "link", across)
    monkeypatch.setattr(os, "fsync", recorded)
    _backup()
    held = _held(installed)
    assert sorted(Path(path).name for path in flushed) == sorted(
        f".{sha256}{file_store.PART}" for sha256 in contents
    )
    assert set(held.contents()) == contents


def test_a_copy_cut_short_leaves_nothing_under_the_name_of_content(
    installed: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, sha256 = _put(installed, _pdf("x" * 100), "x.pdf")

    def across(*paths: object) -> None:
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    copy = shutil.copyfileobj

    def half(origin: Any, target: Any, *more: object) -> None:
        target.write(b"half")
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(os, "link", across)
    monkeypatch.setattr(shutil, "copyfileobj", half)
    failed = _run("backup", code=1)
    assert "the backup could not be made: [Errno 28] No space left on device" in failed.output
    assert not isinstance(failed.exception, OSError)
    assert [p.name for p in _held(installed).path_of(sha256).parent.iterdir()] == []
    monkeypatch.setattr(shutil, "copyfileobj", copy)
    _backup()
    assert _held(installed).path_of(sha256).read_bytes() == _pdf("x" * 100)
    # And a part that a backup stopped by force left is removed by the next one.
    part = _held(installed).path_of(sha256).with_name(f".{sha256}{file_store.PART}")
    part.write_bytes(b"left by a backup that was killed")
    _backup()
    assert [p.name for p in part.parent.iterdir()] == [sha256]


def test_a_file_uploaded_while_the_copy_is_taken_is_held_too(
    installed: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    copy = admin._copy_database
    came: list[str] = []

    def uploaded_meanwhile(source: Path, target: Path) -> None:
        came.append(_put(installed, _pdf("came while copying"), "late.pdf")[1])
        copy(source, target)

    monkeypatch.setattr(admin, "_copy_database", uploaded_meanwhile)
    backup = _backup()
    assert {one.sha256 for one in admin._named_in(backup)} == set(came)
    assert set(_held(installed).contents()) == set(came)


def test_a_file_erased_while_the_copy_is_taken_is_named_and_the_backup_made(
    installed: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    copy = admin._copy_database
    gone: list[str] = []

    def erased_meanwhile(source: Path, target: Path) -> None:
        hid, sha256 = _put(installed, _pdf("came and went"), "brief.pdf")
        copy(source, target)
        _erase(installed, hid)
        gone.append(sha256)

    monkeypatch.setattr(admin, "_copy_database", erased_meanwhile)
    result = _run("backup")
    assert Path(result.stdout.strip()).is_file()
    assert gone[0] in result.stderr
    assert "--allow-missing-files" in result.stderr


def test_the_rotation_removes_from_the_files_what_no_kept_backup_names(
    installed: Config,
) -> None:
    gone, sha_gone = _put(installed, _pdf("first edition"), "guide.pdf")
    _, sha_kept = _put(installed, _pdf("rack elevation"), "rack.pdf")
    # Written by 0.8.0, which knows no reference, and kept among the newest three.
    installed.backup_dir.mkdir()
    (installed.backup_dir / "hirdir-20261116T090000-0500.db").write_bytes(b"")
    first = _backup()
    _erase(installed, gone)
    assert sha_gone not in set(Store(installed.files_dir).contents())

    # The first backup still names the content that was erased, so it is held.
    _backup()
    assert set(_held(installed).contents()) == {sha_gone, sha_kept}
    # Rotated out, the last backup that named it takes it from the host.
    _backup()
    _backup()
    assert not first.exists()
    assert set(_held(installed).contents()) == {sha_kept}
    assert not _held(installed).path_of(sha_gone).exists()


def test_a_kept_backup_that_cannot_be_read_keeps_every_file(installed: Config) -> None:
    hid, sha256 = _put(installed, _pdf("only once"), "once.pdf")
    _backup()
    _erase(installed, hid)
    unreadable = installed.backup_dir / "hirdir-20261116T200000-0500.db"
    unreadable.write_bytes(b"not a database, " * 512)
    for _ in range(3):
        result = _run("backup")
    assert str(unreadable) in result.stderr
    assert sha256 in set(_held(installed).contents())


# --- restore ---------------------------------------------------------------------------


def test_a_restore_on_the_same_host_puts_back_the_files_and_sets_aside_the_others(
    installed: Config,
) -> None:
    kept, sha_kept = _put(installed, _pdf("kept"), "kept.pdf")
    erased, sha_erased = _put(installed, _pdf("erased after"), "erased.pdf")
    backup = _backup()
    _erase(installed, erased)
    _, sha_after = _put(installed, _pdf("uploaded after"), "after.pdf")

    result = _run("restore", str(backup))
    live = Store(installed.files_dir)
    assert set(live.contents()) == {sha_kept, sha_erased}
    assert live.path_of(sha_erased).read_bytes() == _pdf("erased after")
    # From the backups' own files/, on the same file system, a link, as the backup made
    # one: a restored host holds each file once.
    assert (
        live.path_of(sha_erased).stat().st_ino == _held(installed).path_of(sha_erased).stat().st_ino
    )
    assert live.path_of(sha_erased).stat().st_mode & 0o777 == 0o640
    assert _named(installed) == {sha_kept, sha_erased}
    aside = Store(installed.state_dir / "files.before-restore")
    assert set(aside.contents()) == {sha_after}
    assert aside.path_of(sha_after).read_bytes() == _pdf("uploaded after")
    assert (installed.state_dir / "hirdir.db.before-restore").is_file()
    assert f"the content of 1 files was taken from {_held(installed).root}" in result.stdout
    assert f"is kept at {aside.root}" in result.stdout
    assert kept not in result.stdout


def test_a_restore_onto_an_empty_state_directory_from_a_copied_backup(
    installed: Config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contents = {
        _put(installed, _pdf(f"page {n}"), f"page-{n}.pdf")[1]: _pdf(f"page {n}") for n in (1, 2, 3)
    }
    backup = _backup()

    # Another host: the backup and the files beside it are copied there.
    clean = tmp_path / "clean"
    clean.mkdir()
    (clean / "config.toml").write_text('[server]\nlisten = "127.0.0.1:1"\nstate_dir = "."\n')
    monkeypatch.setenv("HIRDIR_CONFIG", str(clean / "config.toml"))
    (clean / "backups").mkdir()
    shutil.copy2(backup, clean / "backups" / backup.name)
    shutil.copytree(backup.parent / "files", clean / "backups" / "files")

    # Run as an operator runs it under sudo, whose umask lets others read.
    umask = os.umask(0o022)
    try:
        result = _run("restore", str(clean / "backups" / backup.name))
    finally:
        os.umask(umask)
    assert "before-restore" not in result.stdout
    config = Config(state_dir=clean)
    live = Store(config.files_dir)
    assert {sha256: live.path_of(sha256).read_bytes() for sha256 in live.contents()} == contents
    assert live.root.stat().st_mode & 0o777 == 0o750
    # Made as the service makes them, whatever the umask of whoever restores.
    for directory in {live.path_of(sha256).parent for sha256 in contents}:
        assert directory.stat().st_mode & 0o777 == 0o750
    # Linked to the files beside the backup, which are the backups' own there.
    copied = Store(clean / "backups" / "files")
    for sha256 in contents:
        assert live.path_of(sha256).stat().st_ino == copied.path_of(sha256).stat().st_ino
    assert _named(config) == set(contents)
    checked = _run("check")
    assert "reference files: 3 with content, kept in 3 files of" in checked.stdout


def test_a_restore_refuses_when_a_file_is_missing_and_changes_nothing(
    installed: Config, tmp_path: Path
) -> None:
    lost, sha_lost = _put(installed, _pdf("lost"), "lost.pdf")
    _put(installed, _pdf("found"), "found.pdf")
    backup = _backup()
    # The content is lost from both places: erased, and gone from the backups' files.
    _erase(installed, lost)
    _held(installed).path_of(sha_lost).unlink()
    _, sha_after = _put(installed, _pdf("after"), "after.pdf")

    refused = _run("restore", str(backup), code=1)
    assert "1 of the 2 reference files" in refused.output
    assert f"{lost} (lost.pdf)" in refused.output
    assert "--allow-missing-files" in refused.output
    assert "Nothing was changed" in refused.output
    assert not (installed.state_dir / "hirdir.db.before-restore").exists()
    assert sha_after in _named(installed)

    # Named elsewhere, a file whose checksum is not its name is no better than none.
    elsewhere = tmp_path / "elsewhere"
    shutil.copytree(_held(installed).root, elsewhere)
    damaged = file_store.path_in(elsewhere, sha_lost)
    damaged.parent.mkdir(exist_ok=True)
    damaged.write_bytes(_pdf("not what was lost"))
    refused = _run("restore", str(backup), "--files", str(elsewhere), code=1)
    assert f"with its checksum, in {elsewhere}" in refused.output

    # With --allow-missing-files it restores all the same, and lists what is missing.
    restored = _run("restore", str(backup), "--allow-missing-files")
    assert f"  {lost}  lost  (lost.pdf)" in restored.stdout
    assert sha_lost in _named(installed)
    checked = _run("check", code=1)
    assert f"missing content: {sha_lost} of {lost} (lost.pdf)" in checked.stdout


def test_a_restore_takes_the_files_from_the_directory_it_is_told(
    installed: Config, tmp_path: Path
) -> None:
    hid, sha256 = _put(installed, _pdf("moved off the host"), "moved.pdf")
    backup = _backup()
    elsewhere = tmp_path / "copied-off"
    shutil.copytree(_held(installed).root, elsewhere)
    shutil.rmtree(_held(installed).root)
    _erase(installed, hid)

    refused = _run("restore", str(backup), code=1)
    assert f"there is no {_held(installed).root}" in refused.output
    _run("restore", str(backup), "--files", str(elsewhere))
    live = Store(installed.files_dir)
    assert live.path_of(sha256).read_bytes() == _pdf("moved off the host")
    # From anywhere but the backups' own files/, a copy: that may be another host's, or
    # a disk that is taken away again.
    assert live.path_of(sha256).stat().st_ino != Store(elsewhere).path_of(sha256).stat().st_ino
    assert live.path_of(sha256).stat().st_nlink == 1


def test_a_second_restore_keeps_what_the_first_set_aside(installed: Config) -> None:
    """Restoring one backup twice, with files uploaded between: what each restore set
    aside is kept, beside the one copy of the database as it was."""
    backup = _backup()
    _, first = _put(installed, _pdf("first"), "first.pdf")
    _run("restore", str(backup))
    _, second = _put(installed, _pdf("second"), "second.pdf")
    _run("restore", str(backup))
    aside = Store(installed.state_dir / "files.before-restore")
    assert set(aside.contents()) == {first, second}
    assert aside.path_of(first).read_bytes() == _pdf("first")
    assert set(Store(installed.files_dir).contents()) == set()
    # Content set aside once already is the same, and is let go from the store.
    _put(installed, _pdf("first"), "first-again.pdf")
    _run("restore", str(backup))
    assert set(aside.contents()) == {first, second}
    assert not Store(installed.files_dir).has(first)


def test_a_restore_that_stops_as_it_puts_the_database_in_place_leaves_every_file(
    installed: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The content that the database as it was names is set aside before the database
    is replaced, so that a restore stopped there leaves none of it in the store unnamed,
    where the server's sweep would remove it once it is a day old."""
    backup = _backup()
    _, sha_after = _put(installed, _pdf("uploaded after"), "after.pdf")
    live = Store(installed.files_dir)
    week = time.time() - 7 * 24 * 3600
    os.utime(live.path_of(sha_after), (week, week))
    copy = shutil.copyfile

    def full(*paths: object) -> None:
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(shutil, "copyfile", full)
    _run("restore", str(backup), code=1)
    monkeypatch.setattr(shutil, "copyfile", copy)
    aside = Store(installed.state_dir / "files.before-restore")
    assert aside.has(sha_after)
    assert not live.has(sha_after)
    # The database as it was is in place still, whole, and nothing of the copy is left.
    assert sha_after in _named(installed)
    assert not (installed.state_dir / "hirdir.db.restoring").exists()
    # The way back from there is the restore that the database's copy allows.
    kept = installed.backup_dir / "before-restore.db"
    shutil.copy2(installed.state_dir / "hirdir.db.before-restore", kept)
    _run("restore", str(kept), "--files", str(aside.root))
    assert live.path_of(sha_after).read_bytes() == _pdf("uploaded after")


def test_the_copy_a_restore_keeps_is_not_restored_in_place(installed: Config) -> None:
    """A restore writes the database over hirdir.db.before-restore before it reads the
    file it restores, so that file is refused, and so is the database itself."""
    first = _backup()
    _, sha_after = _put(installed, _pdf("uploaded after the backup"), "after.pdf")
    _run("restore", str(first))
    before = installed.state_dir / "hirdir.db.before-restore"
    aside = installed.state_dir / "files.before-restore"
    for refused_file in (before, installed.state_dir / "hirdir.db"):
        refused = _run("restore", str(refused_file), "--files", str(aside), code=1)
        assert "Copy it elsewhere first and restore the copy" in refused.output
    assert sha_after in {one.sha256 for one in admin._named_in(before)}
    assert sha_after not in _named(installed)

    # As the message says: a copy of it, with the files set aside.
    kept = installed.backup_dir / "before-restore.db"
    shutil.copy2(before, kept)
    _run("restore", str(kept), "--files", str(aside))
    assert sha_after in _named(installed)
    assert Store(installed.files_dir).path_of(sha_after).read_bytes() == _pdf(
        "uploaded after the backup"
    )


def _in_a_process(*arguments: str) -> subprocess.CompletedProcess[str]:
    """Run `hirdir admin` as the command is run, in a process of its own that then ends,
    with every ResourceWarning shown: a connection that is not closed gives one."""
    command = [
        sys.executable,
        "-W",
        "always::ResourceWarning",
        "-c",
        "from hirdir.cli.main import app; app()",
        "admin",
    ]
    return subprocess.run(  # noqa: S603 - our own command with fixed arguments
        [*command, *arguments], env=os.environ.copy(), capture_output=True, text=True, check=False
    )


def test_a_restore_leaves_nothing_beside_the_copy_it_keeps(installed: Config) -> None:
    """Every connection to a database is closed: none leaves a -wal or a -shm behind."""
    first = _backup()
    _put(installed, _pdf("uploaded after the backup"), "after.pdf")
    for _ in range(2):
        done = _in_a_process("restore", str(first))
        assert done.returncode == 0, done.stderr
        assert "ResourceWarning" not in done.stderr
    beside = sorted(p.name for p in installed.state_dir.iterdir() if "before-restore" in p.name)
    assert beside == ["files.before-restore", "hirdir.db.before-restore"]
    assert sorted(p.name for p in installed.backup_dir.iterdir()) == sorted(
        [first.name, "files", admin.BACKUP_LOCK]
    )


def test_a_backup_waits_for_one_that_is_at_work(installed: Config) -> None:
    """The daily timer and a backup taken by hand at once: the second waits for the
    first, rotation and pruning included, so that neither prunes what the other names."""
    installed.backup_dir.mkdir()
    lock = os.open(installed.backup_dir / admin.BACKUP_LOCK, os.O_RDWR | os.O_CREAT, 0o640)
    fcntl.flock(lock, fcntl.LOCK_EX)
    command = [sys.executable, "-c", "from hirdir.cli.main import app; app()", "admin", "backup"]
    waiting = subprocess.Popen(  # noqa: S603 - our own command with fixed arguments
        command, env=os.environ.copy(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    try:
        assert waiting.stderr is not None
        assert "waiting for it" in waiting.stderr.readline()
        assert waiting.poll() is None
        assert list(installed.backup_dir.glob("hirdir-*.db")) == []
    finally:
        os.close(lock)
    made, _ = waiting.communicate(timeout=120)
    assert waiting.returncode == 0
    assert Path(made.strip()).is_file()


def test_a_restore_from_files_it_may_not_read_says_so(installed: Config, tmp_path: Path) -> None:
    if os.geteuid() == 0:
        pytest.skip("root reads a file whatever its mode")
    hid, sha256 = _put(installed, _pdf("on a disk of its own"), "disk.pdf")
    backup = _backup()
    elsewhere = tmp_path / "usb"
    shutil.copytree(_held(installed).root, elsewhere)
    shutil.rmtree(_held(installed).root)
    _erase(installed, hid)
    Store(elsewhere).path_of(sha256).chmod(0)
    try:
        refused = _run("restore", str(backup), "--files", str(elsewhere), code=1)
    finally:
        Store(elsewhere).path_of(sha256).chmod(0o640)
    assert not isinstance(refused.exception, PermissionError)
    assert f"1 of the 1 reference files that {backup} names" in refused.output
    assert f"readable and with its checksum, in {elsewhere}" in refused.output
    assert f"{hid} (disk.pdf)" in refused.output
    assert "Nothing was changed" in refused.output


def test_a_backup_of_a_version_before_references_names_no_file(installed: Config) -> None:
    # A backup of 0.8.0, at the revision before the references.
    old = installed.backup_dir / "hirdir-20261116T080000-0500.db"
    old.parent.mkdir()
    command.upgrade(migrate.alembic_config(f"sqlite:///{old}"), "0010")
    with sqlite3.connect(old) as connection:
        assert connection.execute(
            "SELECT count(*) FROM sqlite_master WHERE name = 'reference_files'"
        ).fetchone() == (0,)
    _, sha256 = _put(installed, _pdf("new in 0.9.0"), "new.pdf")

    assert admin._named_in(old) == []
    _run("restore", str(old))
    assert _named(installed) == set()
    assert set(Store(installed.state_dir / "files.before-restore").contents()) == {sha256}


# --- check and reset -------------------------------------------------------------------


def test_the_check_names_missing_content_and_content_that_no_reference_names(
    installed: Config,
) -> None:
    _, sha_one = _put(installed, _pdf("one"), "one.pdf")
    two, sha_two = _put(installed, _pdf("two"), "two.pdf")
    checked = _run("check")
    size = len(_pdf("one")) + len(_pdf("two"))
    assert (
        f"reference files: 2 with content, kept in 2 files of {size:,} bytes in "
        f"{installed.files_dir}"
    ) in checked.stdout
    assert "missing content" not in checked.stdout

    # Content that no reference names is reported, and is no failure.
    stray = _stray(installed, _pdf("left behind"))
    checked = _run("check")
    assert f"unnamed content: {stray}, which no reference names" in checked.stdout

    # Content that a reference names and the store lacks is a failure.
    Store(installed.files_dir).path_of(sha_two).unlink()
    checked = _run("check", code=1)
    assert f"missing content: {sha_two} of {two} (two.pdf)" in checked.stdout
    assert sha_one not in checked.stdout


def test_the_check_takes_no_file_erased_or_uploaded_while_it_reads_for_one_missing(
    installed: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The service at work while the check runs: between its reading of the names and
    of the store, a file is erased, and another is uploaded."""
    erased, _ = _put(installed, _pdf("erased meanwhile"), "erased.pdf")
    listed = Store.contents
    done: list[str] = []

    def meanwhile(self: Store) -> Iterator[str]:
        if not done and self.root == installed.files_dir:
            _erase(installed, erased)
            done.append(_put(installed, _pdf("uploaded meanwhile"), "uploaded.pdf")[1])
        return listed(self)

    monkeypatch.setattr(Store, "contents", meanwhile)
    checked = _run("check")
    assert "missing content" not in checked.stdout
    assert "unnamed content" not in checked.stdout


@pytest.mark.parametrize("everything", [False, True])
def test_a_reset_erases_every_file_after_its_backup_holds_them(
    installed: Config, everything: bool
) -> None:
    files = {_put(installed, _pdf(f"sheet {n}"), f"sheet-{n}.pdf")[1] for n in (1, 2)}
    result = _run("reset", "--yes", *(["--everything"] if everything else []))
    assert "the content of 2 files" in result.stdout
    assert "the content of 2 files was erased" in result.stdout
    assert list(Store(installed.files_dir).contents()) == []
    assert set(_held(installed).contents()) == files
    assert _named(installed) == set()

    # And the restore that the reset names puts them back.
    backup = next(line for line in result.stdout.splitlines() if line.startswith("backup: "))
    _run("restore", backup.removeprefix("backup: "))
    assert set(Store(installed.files_dir).contents()) == files
