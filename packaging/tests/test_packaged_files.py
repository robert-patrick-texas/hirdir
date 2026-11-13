"""The files the package installs agree with the documentation and with the server."""

import re
import tomllib
from pathlib import Path

import hirdir_setup as setup

from hirdir import config
from hirdir.io import files

PACKAGING = Path(__file__).resolve().parents[1]
ROOT = PACKAGING.parent
ARCHITECTURE = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
INSTALL = (ROOT / "docs" / "install.md").read_text(encoding="utf-8")
MB = 1024 * 1024


def shape(directive: setup.Directive) -> tuple:
    """Reduce a directive to its name, arguments and children, without line numbers."""
    children = sorted(shape(child) for child in directive.block or [])
    return (directive.name, tuple(directive.args), tuple(children))


# Tables of the configuration that are newer than the shipped file, which is left as it is.
NOT_IN_THE_SHIPPED_FILE = ("files",)


def test_the_snippet_holds_the_location_block_of_the_architecture_page() -> None:
    """The block under "URL prefix", and the upload limit that "Package" tells of.

    The block shows what the prefix needs. It may show the upload limit as well, and
    nothing else may be in the snippet that the page does not tell of.
    """
    documented = re.search(r"```nginx\n(.*?)```", ARCHITECTURE, re.DOTALL)
    assert documented is not None
    (wanted,) = setup.parse(documented.group(1))
    packaged = setup.parse((PACKAGING / "nginx" / "snippet.conf").read_text(encoding="utf-8"))
    location = next(d for d in packaged if d.args == ["^~", "/hirdir/"])
    assert shape(location)[:2] == shape(wanted)[:2]
    assert set(shape(wanted)[2]) <= set(shape(location)[2])
    upload_limit = ("client_max_body_size", ("20m",), ())
    assert upload_limit in shape(location)[2]
    assert set(shape(location)[2]) - set(shape(wanted)[2]) <= {upload_limit}
    assert "`client_max_body_size 20m;`" in ARCHITECTURE


def test_nginx_takes_a_body_as_large_as_an_import_may_be_and_no_larger() -> None:
    """The limit of the snippet is the limit of the application, which is where the rule is."""
    packaged = setup.parse((PACKAGING / "nginx" / "snippet.conf").read_text(encoding="utf-8"))
    location = next(d for d in packaged if d.args == ["^~", "/hirdir/"])
    assert location.block is not None
    (limit,) = [d.args for d in location.block if d.name == "client_max_body_size"]
    assert files.MAX_BYTES % MB == 0
    assert limit == [f"{files.MAX_BYTES // MB}m"]
    # The install page tells an operator the same number.
    assert f"{files.MAX_BYTES // MB} MB" in INSTALL


def test_the_snippet_is_shipped_as_a_template_that_postinst_writes_out() -> None:
    """It is no conffile: dpkg would ask about one whose prefix hirdir-setup has changed."""
    build = (PACKAGING / "container" / "build.sh").read_text(encoding="utf-8")
    assert f'packaging/nginx/snippet.conf "$STAGE{setup.TEMPLATE}"\n' in build
    # Every file the build stages under /etc is made a conffile, so this one is not staged.
    assert "(cd \"$STAGE\" && find etc -type f | sed 's|^|/|'" in build
    assert f"$STAGE{setup.SNIPPET}" not in build
    assert f'install -d "$STAGE{setup.SNIPPET.parent}"\n' in build
    postinst = (PACKAGING / "debian" / "postinst").read_text(encoding="utf-8")
    assert f"\nSNIPPET={setup.SNIPPET}\n" in postinst
    assert "$(hirdir-setup --renew --no-reload --yes)" in postinst


def test_the_examples_are_shipped_where_the_install_page_says() -> None:
    build = (PACKAGING / "container" / "build.sh").read_text(encoding="utf-8")
    assert "local doc=$STAGE/usr/share/doc/hirdir\n" in build
    assert 'install -Dm644 -t "$doc/examples" "${examples[@]}"\n' in build
    assert "/usr/share/doc/hirdir/examples/" in INSTALL
    for name in ("tags", "vendors", "catalog-entries", "owners", "items"):
        assert (ROOT / "examples" / f"{name}.csv").is_file()
        assert (ROOT / "examples" / f"{name}.json").is_file()


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
    known = tomllib.loads(documented.group(1))
    # The file is a conffile. dpkg asks about a conffile that was edited on the host
    # whenever a new version ships a different one, and an upgrade with nobody to answer
    # stops there. So a key that a later release adds is documented and is not put into
    # the shipped file: see P-59 in docs/decisions.md.
    newer = {table: known.pop(table) for table in NOT_IN_THE_SHIPPED_FILE}
    assert newer == {"files": {"max_megabytes": config.Config.max_file_megabytes}}
    assert tomllib.loads(uncommented) == known
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


def test_the_install_page_shows_what_an_upgrade_says_of_the_nginx_snippet() -> None:
    """Both messages of docs/install.md are those the package prints, word for word."""
    postinst = (PACKAGING / "debian" / "postinst").read_text(encoding="utf-8")
    shipped = (PACKAGING / "nginx" / "snippet.conf").read_text(encoding="utf-8")
    setup_source = (PACKAGING / "hirdir_setup.py").read_text(encoding="utf-8")

    # A snippet that the upgrade wrote again: the last line of hirdir-setup --renew
    # --no-reload, and what postinst adds when it had nginx reload.
    assert 'done = f"{SNIPPET} is now as this version of hirdir ships it, for {where}."' in (
        setup_source
    )
    assert 'reloaded=" nginx was reloaded."' in postinst
    assert 'echo "hirdir: $(printf \'%s\\n\' "$renewed" | tail -n 1)$reloaded"' in postinst
    said = (
        f"`hirdir: {setup.SNIPPET} is now as this version of hirdir ships it, for /hirdir/. "
        "nginx was reloaded.`"
    )
    assert said in " ".join(INSTALL.split())

    # A snippet edited by hand: what hirdir-setup says, then what postinst adds.
    edited = shipped.replace("client_max_body_size 20m;", "client_max_body_size 5m;")
    try:
        setup.renewed(edited, shipped)
    except setup.SetupError as error:
        refused = f"hirdir-setup: {error}"
    else:
        raise AssertionError("a snippet edited by hand was taken for a shipped one")
    function = postinst[postinst.index("renew_snippet() {") :]
    function = function[: function.index("return 0")]
    printed = re.findall(r'^\s*echo "(hirdir: .*)" >&2$', function, re.M)
    assert len(printed) == 3
    message = "\n".join([refused, *printed]).replace("$SNIPPET", str(setup.SNIPPET))
    assert "$" not in message
    assert f"```text\n{message}\n```" in INSTALL


def test_an_upgrade_backs_up_before_it_migrates_and_restarts_after() -> None:
    """The order the architecture and install pages give: stop, back up, migrate, start."""
    postinst = (PACKAGING / "debian" / "postinst").read_text(encoding="utf-8")
    steps = [
        "deb-systemd-invoke stop hirdir.service",
        '"$HIRDIR" admin backup',
        '"$HIRDIR" admin migrate',
        # The nginx snippet only once the migration is done: an upgrade that stops
        # there has changed nothing of nginx's.
        'renew_snippet "$2"',
        'deb-systemd-invoke "$action" $UNITS',
    ]
    places = [postinst.index(step) for step in steps]
    assert places == sorted(places)
