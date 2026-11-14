"""The files the package installs agree with the documentation and with the server."""

import re
import tomllib
from pathlib import Path

import hirdir_setup as setup

from hirdir import config
from hirdir.domain import reset
from hirdir.io import files

PACKAGING = Path(__file__).resolve().parents[1]
ROOT = PACKAGING.parent
ARCHITECTURE = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
INSTALL = (ROOT / "docs" / "install.md").read_text(encoding="utf-8")
MB = 1024 * 1024
# The files of examples/ in the order they load in: a record names the ones it refers to.
LOAD_ORDER = [
    "tags",
    "vendors",
    "catalog-entries",
    "regions",
    "sites",
    "locations",
    "contacts",
    "contact-assignments",
    "owners",
    "owner-members",
    "networks",
    "items",
    "device-groups",
    "device-group-members",
    "addresses",
]


def shape(directive: setup.Directive) -> tuple:
    """Reduce a directive to its name, arguments and children, without line numbers."""
    children = sorted(shape(child) for child in directive.block or [])
    return (directive.name, tuple(directive.args), tuple(children))


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
    for name in LOAD_ORDER:
        assert (ROOT / "examples" / f"{name}.csv").is_file()
        assert (ROOT / "examples" / f"{name}.json").is_file()
    # Nothing is in examples/ that the load order leaves out.
    assert {path.stem for path in (ROOT / "examples").glob("*.csv")} == set(LOAD_ORDER)
    assert {path.stem for path in (ROOT / "examples").glob("*.json")} == set(LOAD_ORDER)


def test_the_examples_load_in_one_order_wherever_it_is_written() -> None:
    """The package test, the install page and examples/README.md give the same files."""
    readme = (ROOT / "examples" / "README.md").read_text(encoding="utf-8")
    assert re.findall(r"^\d+\. `(.+)\.csv`$", readme, re.M) == LOAD_ORDER
    script = (PACKAGING / "package-test.sh").read_text(encoding="utf-8")
    (tested,) = re.findall(r"^load_order=\((.+)\)$", script, re.M)
    assert tested.split() == LOAD_ORDER
    # The install page loads each with the entity that the file holds.
    commands = re.findall(
        r"^hirdir import examples/(.+)\.csv --entity (\w+) --apply$", INSTALL, re.M
    )
    assert commands == [(name, name.replace("-", "_")) for name in LOAD_ORDER]


def test_the_package_test_names_the_tables_that_a_reset_clears() -> None:
    """Its check of hirdir admin reset reads every table a reset clears, new ones too."""
    script = (PACKAGING / "package-test.sh").read_text(encoding="utf-8")
    (named,) = re.findall(r'^inventory_tables="(.+)"$', script, re.M)
    assert sorted(named.split()) == sorted(model.__tablename__ for model in reset.CLEARED)


def test_what_one_upgrade_alone_has_is_in_a_file_the_package_test_will_find() -> None:
    """A file of package-test.d is read by its name, and its functions are called by theirs.

    One that is named otherwise would be passed over without a word, and so would a
    function of it whose name does not end in the revision or the version of its file.
    """
    script = (PACKAGING / "package-test.sh").read_text(encoding="utf-8")
    called = {
        what
        for line in script.splitlines()
        if not line.lstrip().startswith("#")
        for what in re.findall(r"(?:^|[;\s])particular ([a-z]+)\b", line)
    }
    assert called == {"before", "changed", "after"}
    revisions = {
        path.name[:4] for path in (ROOT / "src/hirdir/db/migrations/versions").glob("[0-9]*.py")
    }
    files_read = sorted((PACKAGING / "package-test.d").iterdir())
    assert files_read
    for path in files_read:
        name = re.fullmatch(r"(?:migration-(\d{4})|release-(\d+\.\d+\.\d+))\.sh", path.name)
        assert name, f"{path.name} is neither migration-<revision>.sh nor release-<version>.sh"
        revision, version = name.groups()
        assert revision is None or revision in revisions, f"{path.name}: no such migration"
        key = revision or version.replace(".", "_")
        text = path.read_text(encoding="utf-8")
        for function in re.findall(r"^(\w+)\(\) \{$", text, re.M):
            what, _, rest = function.partition("_")
            if what in called:
                assert rest == key, f"{path.name}: {function} is not called; it is for {rest}"


def test_the_snippet_redirects_the_prefix_without_its_slash() -> None:
    packaged = setup.parse((PACKAGING / "nginx" / "snippet.conf").read_text(encoding="utf-8"))
    redirect = next(d for d in packaged if d.args == ["=", "/hirdir"])
    assert ("return", ("301", "/hirdir/"), ()) in shape(redirect)[2]
    assert ("absolute_redirect", ("off",), ()) in shape(redirect)[2]


def test_the_upstream_is_where_the_server_listens_by_default() -> None:
    (upstream,) = setup.parse((PACKAGING / "nginx" / "upstream.conf").read_text(encoding="utf-8"))
    assert shape(upstream) == ("upstream", ("hirdir",), (("server", (config.Config.listen,), ()),))


def test_the_settings_file_is_shipped_as_a_text_that_postinst_writes_out() -> None:
    """It is no conffile: dpkg would ask every site that had edited its own."""
    build = (PACKAGING / "container" / "build.sh").read_text(encoding="utf-8")
    assert f'packaging/config.toml "$STAGE{setup.SETTINGS_TEMPLATE}"\n' in build
    assert f"$STAGE{setup.SETTINGS}" not in build
    assert f'install -d "$STAGE{setup.SETTINGS.parent}"\n' in build
    postinst = (PACKAGING / "debian" / "postinst").read_text(encoding="utf-8")
    assert "$(hirdir-setup --settings --yes)" in postinst
    # After the migrations, so that an upgrade that stops there has changed no file.
    assert postinst.index("admin migrate") < postinst.index('renew_settings "$2"')
    # A purge takes the file and the copies kept beside it with the directory.
    postrm = (PACKAGING / "debian" / "postrm").read_text(encoding="utf-8")
    assert "rm -rf /var/lib/hirdir /etc/hirdir\n" in postrm
    # And the packages the setup tool fetched.
    assert f"rm -rf {setup.DOWNLOADS}\n" in postrm


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
    assert len(keys) == 9

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


def test_the_nightly_upgrade_is_shipped_and_is_for_a_site_to_turn_on() -> None:
    service = (PACKAGING / "systemd" / "hirdir-upgrade.service").read_text(encoding="utf-8")
    assert "\nExecStart=/usr/sbin/hirdir-setup --upgrade --yes\n" in service
    assert "\nType=oneshot\n" in service
    timer = (PACKAGING / "systemd" / "hirdir-upgrade.timer").read_text(encoding="utf-8")
    # Between 21:00 and 03:00, at a time of its own, and never made up for by day.
    assert "\nOnCalendar=*-*-* 21:00:00\n" in timer
    assert "\nRandomizedDelaySec=6h\n" in timer
    assert "\nPersistent=false\n" in timer
    build = (PACKAGING / "container" / "build.sh").read_text(encoding="utf-8")
    assert (
        "packaging/systemd/hirdir-upgrade.service packaging/systemd/hirdir-upgrade.timer" in build
    )
    # The package enables and starts the service and the backup, and not this.
    postinst = (PACKAGING / "debian" / "postinst").read_text(encoding="utf-8")
    postrm = (PACKAGING / "debian" / "postrm").read_text(encoding="utf-8")
    assert '\nUNITS="hirdir.service hirdir-backup.timer"\n' in postinst
    assert '\nUNITS="hirdir.service hirdir-backup.timer"\n' in postrm
    assert "hirdir-upgrade" not in postinst
    # Removed, the package stops it and takes away the link that turned it on.
    prerm = (PACKAGING / "debian" / "prerm").read_text(encoding="utf-8")
    assert "deb-systemd-invoke stop hirdir-upgrade.timer" in prerm
    assert "rm -f /etc/systemd/system/timers.target.wants/hirdir-upgrade.timer\n" in postrm
    assert "sudo systemctl enable --now hirdir-upgrade.timer" in INSTALL
