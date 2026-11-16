"""`hirdir admin backup`, `restore`, `check` and `reset` with the content of reference
files, which is kept beside the database and goes into the backups beside them (P-161)."""

import errno
import os
import shutil
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

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
    # A copy, never a link: the store is the service's own.
    assert (
        live.path_of(sha_erased).stat().st_ino != _held(installed).path_of(sha_erased).stat().st_ino
    )
    assert live.path_of(sha_erased).stat().st_mode & 0o777 == 0o640
    assert _named(installed) == {sha_kept, sha_erased}
    aside = Store(installed.state_dir / "files.before-restore")
    assert set(aside.contents()) == {sha_after}
    assert aside.path_of(sha_after).read_bytes() == _pdf("uploaded after")
    assert (installed.state_dir / "hirdir.db.before-restore").is_file()
    assert "the content of 1 files was copied" in result.stdout
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

    result = _run("restore", str(clean / "backups" / backup.name))
    assert "before-restore" not in result.stdout
    config = Config(state_dir=clean)
    live = Store(config.files_dir)
    assert {sha256: live.path_of(sha256).read_bytes() for sha256 in live.contents()} == contents
    assert live.root.stat().st_mode & 0o777 == 0o750
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
    assert Store(installed.files_dir).path_of(sha256).read_bytes() == _pdf("moved off the host")


def test_a_restore_replaces_what_an_earlier_one_set_aside(installed: Config) -> None:
    backup = _backup()
    _, first = _put(installed, _pdf("first"), "first.pdf")
    _run("restore", str(backup))
    _, second = _put(installed, _pdf("second"), "second.pdf")
    _run("restore", str(backup))
    assert set(Store(installed.state_dir / "files.before-restore").contents()) == {second}
    assert first not in set(Store(installed.files_dir).contents())


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
