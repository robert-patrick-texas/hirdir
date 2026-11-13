"""The files the package installs agree with the documentation and with the server."""

import re
import tomllib
from pathlib import Path

import hirdir_setup as setup

from hirdir import config

PACKAGING = Path(__file__).resolve().parents[1]
ROOT = PACKAGING.parent
ARCHITECTURE = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")


def shape(directive: setup.Directive) -> tuple:
    """Reduce a directive to its name, arguments and children, without line numbers."""
    children = sorted(shape(child) for child in directive.block or [])
    return (directive.name, tuple(directive.args), tuple(children))


def test_the_snippet_holds_the_location_block_of_the_architecture_page() -> None:
    documented = re.search(r"```nginx\n(.*?)```", ARCHITECTURE, re.DOTALL)
    assert documented is not None
    (wanted,) = setup.parse(documented.group(1))
    packaged = setup.parse((PACKAGING / "nginx" / "snippet.conf").read_text(encoding="utf-8"))
    assert shape(wanted) in [shape(directive) for directive in packaged]


def test_the_snippet_redirects_the_prefix_without_its_slash() -> None:
    packaged = setup.parse((PACKAGING / "nginx" / "snippet.conf").read_text(encoding="utf-8"))
    redirect = next(d for d in packaged if d.args == ["=", "/hirdir"])
    assert ("return", ("301", "/hirdir/"), ()) in shape(redirect)[2]
    assert ("absolute_redirect", ("off",), ()) in shape(redirect)[2]


def test_the_upstream_is_where_the_server_listens_by_default() -> None:
    (upstream,) = setup.parse((PACKAGING / "nginx" / "upstream.conf").read_text(encoding="utf-8"))
    assert shape(upstream) == ("upstream", ("hirdir",), (("server", (config.Config.listen,), ()),))


def test_the_configuration_file_is_all_comments_and_shows_every_default(tmp_path: Path) -> None:
    shipped = (PACKAGING / "config.toml").read_text(encoding="utf-8")
    assert all(not table for table in tomllib.loads(shipped).values())

    # With every key uncommented, the file sets each value to what it already was.
    uncommented = re.sub(r"^# (\w+ = )", r"\1", shipped, flags=re.MULTILINE)
    keys = {
        f"{table}.{key}" for table, values in tomllib.loads(uncommented).items() for key in values
    }
    documented = re.search(r"## Configuration.*?```toml\n(.*?)```", ARCHITECTURE, re.DOTALL)
    assert documented is not None
    assert tomllib.loads(uncommented) == tomllib.loads(documented.group(1))
    assert len(keys) == 7

    as_shipped = tmp_path / "shipped.toml"
    as_shipped.write_text(shipped, encoding="utf-8")
    with_keys = tmp_path / "uncommented.toml"
    with_keys.write_text(uncommented, encoding="utf-8")
    assert config.load(with_keys) == config.load(as_shipped) == config.Config()


def test_the_units_run_the_commands_the_architecture_page_names() -> None:
    service = (PACKAGING / "systemd" / "hirdir.service").read_text(encoding="utf-8")
    assert "\nUser=hirdir\n" in service
    assert "\nExecStart=/opt/hirdir/venv/bin/hirdir admin serve\n" in service
    assert "\nStateDirectory=hirdir\n" in service
    assert "\nStateDirectoryMode=0750\n" in service
    backup = (PACKAGING / "systemd" / "hirdir-backup.service").read_text(encoding="utf-8")
    assert "\nUser=hirdir\n" in backup
    assert "\nExecStart=/opt/hirdir/venv/bin/hirdir admin backup\n" in backup
    timer = (PACKAGING / "systemd" / "hirdir-backup.timer").read_text(encoding="utf-8")
    assert "\nOnCalendar=daily\n" in timer


def test_the_install_page_shows_what_postinst_prints_when_a_migration_fails() -> None:
    """The way back in docs/install.md is the one the package prints, word for word."""
    postinst = (PACKAGING / "debian" / "postinst").read_text(encoding="utf-8")
    failed = postinst[postinst.index('echo "hirdir: the migration failed') :]
    printed = re.findall(r'^\s*echo "(hirdir: .*)" >&2$', failed[: failed.index("exit 1")], re.M)
    assert len(printed) == 8

    # As an upgrade from 0.1.0 prints it, with the backup the page uses as its example.
    backup = "/var/lib/hirdir/backups/hirdir-20261111T210000-0500.db"
    message = "\n".join(printed).replace("$backup", backup).replace("$2", "0.1.0")
    assert "$" not in message
    install = (ROOT / "docs" / "install.md").read_text(encoding="utf-8")
    assert f"```text\n{message}\n```" in install
    assert f"sudo hirdir admin restore {backup}\n" in install


def test_an_upgrade_backs_up_before_it_migrates_and_restarts_after() -> None:
    """The order the architecture and install pages give: stop, back up, migrate, start."""
    postinst = (PACKAGING / "debian" / "postinst").read_text(encoding="utf-8")
    steps = [
        "deb-systemd-invoke stop hirdir.service",
        '"$HIRDIR" admin backup',
        '"$HIRDIR" admin migrate',
        'deb-systemd-invoke "$action" $UNITS',
    ]
    places = [postinst.index(step) for step in steps]
    assert places == sorted(places)
