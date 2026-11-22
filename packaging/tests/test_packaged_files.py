"""The files the package installs agree with the documentation and with the server."""

import re
import tomllib
from pathlib import Path

import hirdir_setup as setup
import pytest

from hirdir import config
from hirdir.domain import reset
from hirdir.io import entities, files

PACKAGING = Path(__file__).resolve().parents[1]
ROOT = PACKAGING.parent
ARCHITECTURE = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
INSTALL = (ROOT / "docs" / "install.md").read_text(encoding="utf-8")
MB = 1024 * 1024
# The files of examples/ in the order they load in: a record names the ones it refers to.
LOAD_ORDER = [
    "countries",
    "states",
    "tags",
    "vendors",
    "catalog-entries",
    "contacts",
    "vendor-contacts",
    "operators",
    "regions",
    "sites",
    "locations",
    "contact-assignments",
    "owners",
    "owner-members",
    "networks",
    "external-systems",
    "agreements",
    "contracts",
    "contract-contacts",
    "purchase-requests",
    "purchase-lines",
    "device-groups",
    "items",
    "device-group-members",
    "item-replacements",
    "addresses",
    "contract-coverage",
    "registrations",
    "capacity-lines",
    "circuit-groups",
    "circuits",
    "circuit-carriers",
    "circuit-costs",
    "circuit-contacts",
    "circuit-devices",
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
    upload_limit = ("client_max_body_size", ("100m",), ())
    assert upload_limit in shape(location)[2]
    assert set(shape(location)[2]) - set(shape(wanted)[2]) <= {upload_limit}
    assert "`client_max_body_size 100m;`" in ARCHITECTURE


def test_nginx_takes_a_body_as_large_as_a_reference_file_may_be_and_no_larger() -> None:
    """The limit of the snippet is the larger of the application's two, an import and a
    reference file (P-162), which is where the rule is."""
    packaged = setup.parse((PACKAGING / "nginx" / "snippet.conf").read_text(encoding="utf-8"))
    location = next(d for d in packaged if d.args == ["^~", "/hirdir/"])
    assert location.block is not None
    (limit,) = [d.args for d in location.block if d.name == "client_max_body_size"]
    assert files.MAX_BYTES % MB == 0
    larger = max(
        config.default("files", "max_megabytes"), config.default("files", "max_reference_megabytes")
    )
    assert limit == [f"{larger}m"]
    # The install page tells an operator the same numbers.
    assert f"{files.MAX_BYTES // MB} MB" in INSTALL
    assert f"{larger} MB" in INSTALL


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
    # And it is the order the server itself gives its entities.
    assert [name.replace("_", "-") for name in entities.LOAD_ORDER] == LOAD_ORDER
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
    assert len(keys) == 10

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
    worker = (PACKAGING / "systemd" / "hirdir-worker.service").read_text(encoding="utf-8")
    assert "\nUser=hirdir\n" in worker
    assert "\nExecStart=/opt/hirdir/venv/bin/hirdir admin work\n" in worker
    backup = (PACKAGING / "systemd" / "hirdir-backup.service").read_text(encoding="utf-8")
    assert "\nUser=hirdir\n" in backup
    assert "\nExecStart=/opt/hirdir/venv/bin/hirdir admin backup\n" in backup
    timer = (PACKAGING / "systemd" / "hirdir-backup.timer").read_text(encoding="utf-8")
    assert "\nOnCalendar=daily\n" in timer


def _settings_of(unit: str, section: str) -> list[str]:
    """The lines of one section of a unit that set something, in their order."""
    text = (PACKAGING / "systemd" / unit).read_text(encoding="utf-8")
    body = text.split(f"[{section}]\n", 1)[1].split("\n[", 1)[0]
    return [line for line in body.splitlines() if line and not line.startswith("#")]


def test_the_worker_is_a_unit_of_the_service_under_the_limits_of_the_server() -> None:
    """P-267: started, stopped and restarted with hirdir.service, under the same limits."""
    server = _settings_of("hirdir.service", "Service")
    worker = _settings_of("hirdir-worker.service", "Service")
    # Line for line the server's, but for what each runs.
    assert [line for line in worker if not line.startswith("ExecStart=")] == [
        line for line in server if not line.startswith("ExecStart=")
    ]
    assert "ReadWritePaths=/var/lib/hirdir" in worker
    assert "NoNewPrivileges=true" in worker
    tied = _settings_of("hirdir-worker.service", "Unit")
    # A stop or a restart of the server is handed on to it, and a stop of the server
    # comes back once it has stopped, since it is ordered after the server.
    assert "PartOf=hirdir.service" in tied
    assert "After=hirdir.service" in tied
    # Enabled, it is wanted by the server, so a start of the server starts it; it has
    # no place of its own in the start of the host.
    assert _settings_of("hirdir-worker.service", "Install") == ["WantedBy=hirdir.service"]
    assert _settings_of("hirdir.service", "Install") == ["WantedBy=multi-user.target"]
    build = (PACKAGING / "container" / "build.sh").read_text(encoding="utf-8")
    assert build.count("hirdir-worker.service") == 2  # installed, and verified

    postinst = (PACKAGING / "debian" / "postinst").read_text(encoding="utf-8")
    prerm = (PACKAGING / "debian" / "prerm").read_text(encoding="utf-8")
    postrm = (PACKAGING / "debian" / "postrm").read_text(encoding="utf-8")
    # Enabled by the package, and started by the server, not beside it.
    assert '\nUNITS="hirdir.service hirdir-worker.service hirdir-backup.timer"\n' in postinst
    assert '\nSTARTED="hirdir.service hirdir-backup.timer"\n' in postinst
    # Stopped with the server for a migration, and before its files go.
    assert "deb-systemd-invoke stop hirdir-worker.service hirdir.service" in postinst
    assert "hirdir-worker.service hirdir.service >/dev/null" in prerm
    # Going back to a release that has no such unit: stopped by the script that leaves,
    # and what enabled it taken away once the unit is gone.
    assert 'dpkg --compare-versions "$2" lt 0.9.10' in prerm
    assert 'dpkg --compare-versions "$2" lt 0.9.10' in postrm
    assert 'deb-systemd-helper purge "$WORKER"' in postrm
    assert '\nUNITS="hirdir.service hirdir-worker.service hirdir-backup.timer"\n' in postrm
    # The setup tool reports on both after an upgrade.
    assert setup.SERVICE_UNITS == ("hirdir.service", "hirdir-worker.service")
    # A site that moved the state directory is told of all three units.
    shipped = (PACKAGING / "config.toml").read_text(encoding="utf-8")
    assert "hirdir.service,\n# hirdir-worker.service and hirdir-backup.service" in shipped


def test_the_install_page_names_both_units_and_what_the_commands_say(
    tmp_path: Path, capsys
) -> None:
    """docs/install.md says of the two processes what the code says."""
    import typer

    from hirdir.cli import admin
    from hirdir.io import background

    page = " ".join(INSTALL.split())
    assert "| `hirdir.service` | `hirdir admin serve` |" in page
    assert "| `hirdir-worker.service` | `hirdir admin work` |" in page
    assert "journalctl -u hirdir-worker" in page
    assert "### From 0.9.9 to 0.9.10" in INSTALL
    source = (ROOT / "src" / "hirdir" / "cli" / "admin.py").read_text(encoding="utf-8")
    for said in (
        "another hirdir server is running on {state_dir}: stop it first",
        "another process of the background work is running on {state_dir}: stop it first",
        "hirdir: the background work of {config.state_dir} is under way",
        "hirdir: the background work of {config.state_dir} is stopped",
    ):
        assert said in source
        shown = said.replace("{config.state_dir}", "/var/lib/hirdir")
        assert f"`{shown.replace('{state_dir}', '/var/lib/hirdir')}`" in page
    # The refusal of a command that needs the service stopped, as the page shows it:
    # here with the process of the background work alone running.
    installed = config.Config(state_dir=tmp_path, listen="127.0.0.1:1")
    held = background.hold_lock(tmp_path)
    try:
        with pytest.raises(typer.Exit):
            admin._need_stopped(installed, "nobody is at work while the inventory goes")
    finally:
        held.close()
    refused = capsys.readouterr().err.strip()
    assert refused.startswith("hirdir: the service is running, the process of the background")
    assert f"```text\n{refused}\n```" in INSTALL


def test_the_install_page_and_the_package_test_say_of_the_long_reports_what_the_code_says() -> None:
    """The notes of the upgrade to 0.9.11 and what the package test asks for
    it: the table, the setting and its bounds, the line of the journal, and the four
    reports that the second process works out ahead (P-275, P-276)."""
    import importlib

    from hirdir.db.models import KeptAnswer
    from hirdir.domain import settings
    from hirdir.io import background, kept

    assert "### From 0.9.10 to 0.9.11" in INSTALL
    notes = INSTALL.split("### From 0.9.10 to 0.9.11\n", 1)[1].split("\n### ", 1)[0]
    page = " ".join(notes.split())
    revision = "0015"
    assert list((ROOT / "src/hirdir/db/migrations/versions").glob(f"{revision}_*.py"))
    assert f"to `{revision}`. One table is added, `{KeptAnswer.__tablename__}`" in page
    assert KeptAnswer in reset.CLEARED
    assert "`hirdir admin reset` clears it" in page

    # The setting, as the page gives it to an operator.
    name = settings.AHEAD_SETTING
    assert settings.SPECS[name].default == settings.DEFAULT_AHEAD_AFTER_SECONDS
    assert f"`{name}`, {settings.DEFAULT_AHEAD_AFTER_SECONDS} unless set" in page
    assert f"a whole number from 0 to {settings.MOST_AHEAD_AFTER_SECONDS:,}" in page
    assert f"{settings.DEFAULT_AHEAD_AFTER_SECONDS} seconds after the last change" in page
    # And the line that the journal of the second process has where working ahead failed.
    said = "the long reports could not be worked out ahead; it is tried again in %d seconds"
    source = (ROOT / "src" / "hirdir" / "io" / "background.py").read_text(encoding="utf-8")
    assert f'"{said}"' in source
    assert f"`{said % background.AHEAD_AGAIN_AFTER}`" in page

    # The package test waits for the reports that are worked out ahead, each by its name,
    # sets the setting by its name, and the file of the migration asks for each by its
    # route: a fifth report would be waited for by nobody.
    # The reports say which of them are worked out ahead as their modules are loaded.
    importlib.import_module("hirdir.api.reports")
    ahead = sorted(kept._ahead)
    assert len(ahead) == 4
    script = (PACKAGING / "package-test.sh").read_text(encoding="utf-8")
    (four,) = re.findall(r"^four = (\[.+\])$", script, re.M)
    assert sorted(re.findall(r'"(\w+)"', four)) == ahead
    assert f"put_setting {name} " in script
    hook = (PACKAGING / "package-test.d" / f"migration-{revision}.sh").read_text(encoding="utf-8")
    (routes,) = re.findall(r'^routes_0015="(.+)"$', hook, re.M)
    assert sorted(route.split(":")[0] for route in routes.split()) == ahead
    # The migration writes no event, as the page says, and its file says so to the test.
    assert "the upgrade writes no audit event" in page
    assert "\nwrites_no_event=yes\n" in hook


def test_the_install_page_and_the_package_test_say_of_the_notes_of_a_user_what_the_code_says() -> (
    None
):
    """The notes of the upgrade to 0.9.13 and what the package test asks for
    it: migration 0016 adds `users.notes`, blank, creates no table and writes no event,
    and the file of the package test declares the column as the model does (P-281); the
    routes and the command that the page names are those of the contract and of the
    command line; and the package test looks for the columns of the users file and the
    events of the two exports that are audited by the names that the code gives them
    (P-286, P-288)."""
    import json

    from sqlalchemy import inspect
    from sqlalchemy.dialects import sqlite

    from hirdir.db.models import User
    from hirdir.io import exports, users_file

    versions = ROOT / "src/hirdir/db/migrations/versions"
    revision = "0016"
    (migration,) = versions.glob(f"{revision}_*.py")
    source = migration.read_text(encoding="utf-8")
    assert 'down_revision = "0015"' in source
    # A column and no table: the pass whose migration fails puts the trigger in its way.
    assert "op.create_table" not in source
    assert 'add_column(sa.Column("notes", sa.Text))' in source

    assert "### From 0.9.12 to 0.9.13" in INSTALL
    notes = INSTALL.split("### From 0.9.12 to 0.9.13\n", 1)[1].split("\n### ", 1)[0]
    page = " ".join(notes.split())
    column = inspect(User).columns["notes"]
    assert (
        f"from revision `0015` to `{revision}`. One column is added, `{column.name}` of the "
        f"{User.__tablename__}, blank for every user; no table is added, nothing that is "
        "held is changed, and the upgrade writes no audit event" in page
    )
    assert "Going back to 0.9.12 is by the backup the upgrade took" in page

    # The file of the package test says so, and declares the column as SQLite has it.
    hook = (PACKAGING / "package-test.d" / f"migration-{revision}.sh").read_text(encoding="utf-8")
    assert "\nwrites_no_event=yes\n" in hook
    declared = column.type.compile(dialect=sqlite.dialect())
    nullable = "NULL" if column.nullable else "NOT NULL"
    said = f"{column.name} {declared} {nullable} -"
    assert f"\nalso new_columns {User.__tablename__} '{said}'\n" in hook
    assert f'*) more_tables="${{more_tables:+$more_tables }}{User.__tablename__}" ;;' in hook

    # The routes and the command that the page names.
    contract = json.loads((ROOT / "contract" / "openapi.json").read_text(encoding="utf-8"))
    for method, path in (
        ("get", "/colours"),
        ("get", "/exports/tables"),
        ("post", "/exports/all"),
        ("post", "/users/export"),
    ):
        assert method in contract["paths"][f"/api/v1{path}"]
        assert f"`{method.upper()} {path}`" in page
    assert "`hirdir export --all`" in page
    assert '"--all"' in (ROOT / "src/hirdir/cli/inventory.py").read_text(encoding="utf-8")

    # What the package test looks for in the users file and in the audit trail.
    script = (PACKAGING / "package-test.sh").read_text(encoding="utf-8")
    (header,) = re.findall(r'\[(\\"username\\", .*?)\]', script)
    assert json.loads("[" + header.replace('\\"', '"') + "]") == list(users_file.COLUMNS)
    assert f'[\\"{exports.TAKEN_ACTION}\\", \\"{exports.TAKEN_RECORD}\\", null' in script
    assert f'[\\"{users_file.ACTION}\\", \\"{users_file.RECORD}\\", null' in script


def test_the_install_page_and_the_package_test_say_of_a_retired_user_what_the_code_says() -> None:
    """The notes of the upgrade to 0.9.14, and what the package test asks for
    it: migration 0017 adds `users.record_status`, `active` for every user, creates no
    table and writes no event, and the file of the package test declares the column as
    the model does (P-296); and the access codes that the file types to the previous
    release are shorter than a code may be typed from this one, so that the upgrade is
    held to keep them (P-295). The setting, the routes and the commands that the page
    names are the code's, and the package test asks for the three scenarios of the
    release, S56 to S58, on the fresh install and on what the upgrade carried over."""
    import json

    from sqlalchemy import ColumnDefault, String, inspect
    from sqlalchemy.dialects import sqlite

    from hirdir.db.models import User
    from hirdir.domain import settings
    from hirdir.io import users_file

    versions = ROOT / "src/hirdir/db/migrations/versions"
    # The revision of 0.9.14, which 0018 of 0.9.17 follows (P-316).
    revision = "0017"
    (migration,) = versions.glob(f"{revision}_*.py")
    source = migration.read_text(encoding="utf-8")
    assert 'down_revision = "0016"' in source
    # A column and no table: the pass whose migration fails puts the trigger in its way.
    assert "op.create_table" not in source
    column = inspect(User).columns["record_status"]
    kind, default = column.type, column.default
    assert isinstance(kind, String)
    assert isinstance(default, ColumnDefault)
    held = default.arg
    assert held == "active"
    assert (
        f'sa.Column("{column.name}", sa.String({kind.length}), nullable=False, '
        f'server_default="{held}")' in source
    )
    # Every user is given that one value by the column itself: the migration runs no
    # statement of its own over the rows.
    assert "op.execute" not in source

    assert "### From 0.9.13 to 0.9.14" in INSTALL
    notes = INSTALL.split("### From 0.9.13 to 0.9.14\n", 1)[1].split("\n### ", 1)[0]
    page = " ".join(notes.split())
    assert (
        f"from revision `0016` to `{revision}`. One column is added, `{column.name}` of the "
        f"{User.__tablename__}, `{held}` for every user; no table is added, nothing that is "
        "held is changed, and the upgrade writes no audit event" in page
    )
    assert "A user that is disabled stays disabled and is not retired" in page
    assert "Going back to 0.9.13 is by the backup the upgrade took" in page

    # The file of the package test says so, and declares the column as SQLite has it.
    hook = (PACKAGING / "package-test.d" / f"migration-{revision}.sh").read_text(encoding="utf-8")
    assert "\nwrites_no_event=yes\n" in hook
    declared = column.type.compile(dialect=sqlite.dialect())
    nullable = "NULL" if column.nullable else "NOT NULL"
    said = f"{column.name} {declared} {nullable} -"
    assert f"\nalso new_columns {User.__tablename__} '{said}'\n" in hook
    assert f'*) more_tables="${{more_tables:+$more_tables }}{User.__tablename__}" ;;' in hook
    # And it looks for the value that the model gives a new user, in every row: the
    # rows are counted by what the column holds, and one value holds them all.
    counted = f"{column.name}, count(*) FROM {User.__tablename__} GROUP BY {column.name}"
    assert counted in hook
    assert f'"{held} $(sqlite_value' in hook

    # The least length of a typed code, as the page gives it to an operator, and the two
    # codes that the file types to the previous release, which takes them: each is
    # shorter, so that a code from before which could not be typed now is carried over.
    name = settings.CODE_LENGTH_SETTING
    least = settings.SPECS[name].default
    assert least == settings.DEFAULT_CODE_LENGTH
    assert f"**A typed access code has at least {least} characters.**" in page
    assert (
        f"`{name}`, {least} unless set, a whole number from 1 to {settings.MOST_CODE_LENGTH}"
        in page
    )
    assert f"shorter than {least} characters" in page
    typed = re.findall(r"^typed(?:_cli)?_0017=(\S+)$", hook, re.M)
    assert len(typed) == 2
    assert all(0 < len(code) < least for code in typed)
    # The package test sets the setting by its name, and looks for what the server says
    # of a code that is too short as the server says it.
    assert f"put_setting {name} " in hook
    # The server says the length in words a person reads at the box, with no name of a
    # setting in them.
    refusal = f'["access_code", "at least {least} characters"]'
    assert refusal in hook
    script = (PACKAGING / "package-test.sh").read_text(encoding="utf-8")
    assert refusal in script
    assert f"({name})" not in hook + script
    # Every code that the package test types to this version is long enough, but the one
    # that is to be refused and the one typed under a setting that the test lowered.
    sent = re.findall(r'access_code\\?": \\?"([^"\\$]+)\\?"', script + hook)
    sent += re.findall(r"=(pkg-[a-z-]+-code-\d+)\b", script)
    assert len(sent) > 10
    assert {code for code in sent if len(code) < least} == {"eleven-char"}

    # The routes and the commands that the page names are those of the contract and of
    # the command line, and the column of the users' file is the file's.
    contract = json.loads((ROOT / "contract" / "openapi.json").read_text(encoding="utf-8"))
    for method, path in (
        ("patch", "/auth/me/contact"),
        ("patch", "/auth/me/operators/{hid}"),
        ("post", "/auth/me/access-code"),
        ("post", "/users/{hid}/retire"),
        ("post", "/users/{hid}/bring-back"),
        ("get", "/users/{hid}/linked"),
        ("get", "/contacts/{hid}/linked"),
        ("get", "/operators/{hid}/linked"),
        ("post", "/contacts/{hid}/retire"),
        ("post", "/operators/{hid}/retire"),
        ("post", "/users/export"),
    ):
        assert method in contract["paths"][f"/api/v1{path}"]
        assert f"`{method.upper()} {path}`" in page
    asked = contract["paths"]["/api/v1/users"]["get"]["parameters"]
    (retired,) = [one for one in asked if one["name"] == "retired"]
    assert retired["schema"]["enum"] == ["no", "yes", "only"]
    assert "take `retired`, `no`, `yes` or `only`" in page
    assert "record_status" in users_file.COLUMNS
    main = (ROOT / "src/hirdir/cli/main.py").read_text(encoding="utf-8")
    inventory = (ROOT / "src/hirdir/cli/inventory.py").read_text(encoding="utf-8")
    assert 'app.add_typer(profile.group, name="profile")' in main
    for group, command, source in (
        ("users", "retire", main),
        ("users", "bring-back", main),
        ("contacts", "retire", inventory),
        ("operators", "retire", inventory),
    ):
        assert f'@{group}.command("{command}")' in source
        assert f"`hirdir {group} {command}`" in page
    assert "`hirdir profile`" in page
    # A label is not brought back onto a retired contact: the page names the field that
    # the rule refuses on, and the package test asks for that answer.
    assert '"record_status": "a label is not brought back onto a retired contact' in (
        ROOT / "src/hirdir/domain/operators.py"
    ).read_text(encoding="utf-8")
    assert "a `409` on `record_status` by `PATCH /operators/{hid}` that names the contact" in page
    assert '409 [["record_status"], "contact", ' in script

    # The package test runs the three scenarios on the fresh install, and the file of
    # the migration on what the upgrade carried over.
    assert "\n    own_and_retired\n" in script
    for scenario in ("S56", "S57", "S58"):
        assert f'expect "{scenario} ' in script
        assert f'expect "{scenario} after the upgrade, ' in hook


def test_the_install_page_and_the_package_test_say_of_no_role_what_the_code_says() -> None:
    """The notes of the upgrade to 0.9.15, and what the package test asks for
    it: no migration, and an account that holds no role refused at sign-in, its session
    and its token refused, and given a role when it is made or brought back (P-299); a
    new code that is the one in hand refused, and a code made as long as the setting asks
    (P-300). The routes and the commands that the page names are the code's, the words
    that the package test looks for are those the server says, and the package test asks
    for S59 and S60 on the fresh install and, by the file of the release, for what an
    account with no role held before the upgrade."""
    import json

    from hirdir.auth import codes
    from hirdir.domain import accounts, settings

    versions = ROOT / "src/hirdir/db/migrations/versions"
    # 0.9.15 stayed at 0017, which 0018 of 0.9.17 follows (P-316).
    assert list(versions.glob("0017_*.py"))
    assert "### From 0.9.14 to 0.9.15" in INSTALL
    notes = INSTALL.split("### From 0.9.14 to 0.9.15\n", 1)[1].split("\n### ", 1)[0]
    page = " ".join(notes.split())
    assert "The schema stays at revision `0017`: 0.9.15 has no migration." in page
    assert "it writes no audit event" in page
    assert "does not come back when the account is given a role" in page
    assert "sudo apt install --allow-downgrades ./hirdir_0.9.14_amd64.deb" in page

    contract = json.loads((ROOT / "contract" / "openapi.json").read_text(encoding="utf-8"))
    for method, path in (
        ("post", "/auth/sign-in"),
        ("post", "/users"),
        ("post", "/users/{hid}/bring-back"),
        ("post", "/auth/me/access-code"),
        ("get", "/auth/new-access-code"),
    ):
        assert method in contract["paths"][f"/api/v1{path}"]
        assert f"`{method.upper()} {path}`" in page
    assert '"sign_in_no_role"' in (ROOT / "src/hirdir/domain/accounts.py").read_text(
        encoding="utf-8"
    )
    assert "`sign_in_no_role`" in page
    main = (ROOT / "src/hirdir/cli/main.py").read_text(encoding="utf-8")
    profile = (ROOT / "src/hirdir/cli/profile.py").read_text(encoding="utf-8")
    assert "role: Annotated[" in main.split('@users.command("bring-back")', 1)[1]
    assert '"--generate"' in profile
    for named in (
        "`--role` of `hirdir users bring-back`",
        "`--generate` of `hirdir profile access-code`",
        "`hirdir sign-in` of an account with no role exits `3`",
    ):
        assert named in page

    # What the package test looks for, in the words the server says it in.
    script = (PACKAGING / "package-test.sh").read_text(encoding="utf-8")
    hook = (PACKAGING / "package-test.d" / "release-0.9.15.sh").read_text(encoding="utf-8")
    session = "the session has been ended: this account holds no role"
    token = "the token is not accepted: its service account holds no role"
    source = (ROOT / "src/hirdir/domain/accounts.py").read_text(encoding="utf-8")
    # The longer words are said to a session that was never ended, as the one from
    # before the upgrade is; a revocation of the last role ends the sessions, which are
    # then refused as any ended one is.
    for words in (session, token):
        assert f'NotSignedIn("{words}")' in source
        assert words in hook
    assert token in script
    assert '204 401 the session has been ended"' in script
    assert f'"No role", "{accounts.NO_ROLE}"' in script
    assert f'"No role", "{accounts.NO_ROLE}"' in hook
    assert f"^hirdir: {accounts.NO_ROLE}$" in script
    assert f'[["role", "{accounts.GIVE_A_ROLE}"]]' in script
    assert '\\"role\\", \\"give the role the account is to hold\\"' in script
    assert "this is the access code you have now" in source
    assert '[["access_code", "this is the access code you have now"]]' in script

    # The lengths of a made code that the package test looks for are the generator's.
    least = settings.SPECS[settings.CODE_LENGTH_SETTING].default
    assert len(codes.generate(least)) == 14
    assert len(codes.generate(20)) == 24
    assert '"200 20 200 [24, 4] ' in script
    assert "14, true] another" in script

    # The package test runs the two scenarios on the fresh install, and the file of the
    # release on what the upgrade carried over.
    assert "\n    roles_and_codes\n" in script
    for scenario in ("S59", "S60"):
        assert f'expect "{scenario} ' in script
    for function in ("before_0_9_15", "changed_0_9_15", "after_0_9_15"):
        assert f"\n{function}() {{\n" in hook


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
    edited = shipped.replace(
        "    proxy_set_header Host", "    proxy_read_timeout 300s;\n    proxy_set_header Host"
    )
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
        "deb-systemd-invoke stop hirdir-worker.service hirdir.service",
        '"$HIRDIR" admin backup',
        '"$HIRDIR" admin migrate',
        # The nginx snippet only once the migration is done: an upgrade that stops
        # there has changed nothing of nginx's.
        'renew_snippet "$2"',
        'deb-systemd-invoke "$action" $STARTED',
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
    assert '\nUNITS="hirdir.service hirdir-worker.service hirdir-backup.timer"\n' in postinst
    assert '\nUNITS="hirdir.service hirdir-worker.service hirdir-backup.timer"\n' in postrm
    assert "hirdir-upgrade" not in postinst
    # Removed, the package stops it and takes away the link that turned it on.
    prerm = (PACKAGING / "debian" / "prerm").read_text(encoding="utf-8")
    assert "deb-systemd-invoke stop hirdir-upgrade.timer" in prerm
    assert "rm -f /etc/systemd/system/timers.target.wants/hirdir-upgrade.timer\n" in postrm
    assert "sudo systemctl enable --now hirdir-upgrade.timer" in INSTALL


def test_the_short_browser_check_is_a_pass_that_runs_a_spec_file_of_the_web_ui() -> None:
    """The pass --browser-check runs web/e2e/browser-check.spec.ts, which is there, keeps
    the rules of support.ts and is no project's that runs alone, so that the host's run
    and --e2e run it beside the others; every pass runs the check last, by itself, and
    the release process and the architecture page name it for an ordinary release, in
    the place of --e2e (P-305, P-309)."""
    script = (PACKAGING / "package-test.sh").read_text(encoding="utf-8")
    (spec,) = re.findall(r"^check_spec=(\S+)$", script, re.M)
    source = (ROOT / spec).read_text(encoding="utf-8")
    assert 'from "./support";' in source
    assert "await signIn(page, account);" in source
    assert "expectClean(" in source
    name = Path(spec).name
    config = (ROOT / "web" / "playwright.config.ts").read_text(encoding="utf-8")
    alone = re.findall(r"^const [A-Z_]+ = /(.+)/;$", config, re.M)
    assert len(alone) >= 6
    assert not any(re.search(pattern.replace("\\/", "/"), name) for pattern in alone)

    # A pass of its own, which every pass runs by itself once the others have ended.
    assert "--upgrade | --failed-upgrade | --fresh | --browser-check)" in script
    assert "| --fresh | --browser-check]" in script
    every = script.split("\nevery_pass() {\n", 1)[1].split("\n}\n", 1)[0]
    assert every.index("    wait\n") < every.index("one_pass --browser-check")
    (pass_itself,) = re.findall(
        r'\n    if \[ "\$mode" = browser-check \]; then\n(.*?)\n    elif ', script, re.S
    )
    called = [line.strip() for line in pass_itself.splitlines() if not line.strip().startswith("#")]
    assert called == ["setup", "through_nginx", "browser_check"]
    assert '"${check_spec#web/}"' in script

    process = " ".join((ROOT / "docs" / "release-process.md").read_text(encoding="utf-8").split())
    assert "for an ordinary release `--failed-upgrade` and `--browser-check`" in process
    assert f"`{spec}`" in process
    assert "| `--browser-check` |" in ARCHITECTURE
    assert f"`{spec}`" in ARCHITECTURE


def test_the_install_page_and_the_package_test_say_of_kinds_and_agents_what_the_code_says() -> None:
    """The notes of the upgrade to 0.9.17, the newest, and what the package test asks for
    it: migration 0018 makes the users' table anew, kind in the place of
    is_service_account and answerable_hid, adds for_hid to the audit trail, creates no
    table and writes no event, and the file of the package test declares each column as
    the model does (P-316); the routes, fields and commands that the page names are those
    of the contract and of the command line; and the package test asks for S61 and S62 on
    the fresh install and on what the upgrade carried over, in the words of the server and
    of hirdir admin, with its exit codes (P-307, P-313)."""
    import json

    from sqlalchemy import inspect
    from sqlalchemy.dialects import sqlite

    from hirdir.cli import admin
    from hirdir.db.models import AuditEvent, User
    from hirdir.domain import accounts
    from hirdir.io import users_file

    versions = ROOT / "src/hirdir/db/migrations/versions"
    # 0018 was the newest when 0.9.17 was made; 0019 of 0.9.18 follows it.
    revision = "0018"
    (migration,) = versions.glob(f"{revision}_*.py")
    source = migration.read_text(encoding="utf-8")
    assert 'down_revision = "0017"' in source
    # No table: the pass whose migration fails puts the trigger in its way.
    assert "op.create_table" not in source
    assert 'users.drop_column("is_service_account")' in source

    # The file of the package test says what the migration adds and drops, and declares
    # each column as SQLite has it from the model.
    hook = (PACKAGING / "package-test.d" / f"migration-{revision}.sh").read_text(encoding="utf-8")
    assert "\nwrites_no_event=yes\n" in hook

    def said(model: type, name: str) -> str:
        column = inspect(model).columns[name]
        declared = column.type.compile(dialect=sqlite.dialect())
        return f"{column.name} {declared} {'NULL' if column.nullable else 'NOT NULL'} -"

    users = User.__tablename__
    added = f"{said(User, 'kind')}\n{said(User, 'answerable_hid')}"
    assert f"\nalso new_columns {users} '{added}'\n" in hook
    events = AuditEvent.__tablename__
    assert f"\nalso new_columns {events} '{said(AuditEvent, 'for_hid')}'\n" in hook
    assert "is_service_account" not in inspect(User).columns
    gone = f'gone_columns[{users}]="${{gone_columns[{users}]:+${{gone_columns[{users}]}} }}'
    assert f"{gone}is_service_account" in hook
    (key,) = re.findall(
        r'create_foreign_key\("\w+", "users", \["answerable_hid"\], \["hid"\]\)', source
    )
    (index,) = re.findall(r'create_index\("(\w+)", \["answerable_hid"\], unique=False\)', source)
    assert key
    assert f"index {index} on answerable_hid unique=0 origin=c partial=0'" in hook
    assert "foreign key answerable_hid to users.hid\n" in hook
    # And the indexes of the audit trail, as the model declares them.
    trail = re.findall(r'events\.create_index\("(\w+)", \["(\w+)"\], unique=False\)', source)
    assert sorted(trail) == sorted(
        (index.name, column.name)
        for index in AuditEvent.metadata.tables[AuditEvent.__tablename__].indexes
        for column in index.columns
        if column.name in ("actor_hid", "for_hid")
    )
    assert len(trail) == 2
    for name, column in trail:
        assert f"index {name} on {column} unique=0 origin=c partial=0" in hook
    assert f'*) more_tables="${{more_tables:+$more_tables }}{users}" ;;' in hook

    # The notes.
    assert "### From 0.9.16 to 0.9.17" in INSTALL
    notes = INSTALL.split("### From 0.9.16 to 0.9.17\n", 1)[1].split("\n### ", 1)[0]
    page = " ".join(notes.split())
    assert f"The schema goes from revision `0017` to `{revision}`." in page
    assert (
        "`kind` takes the place of `is_service_account`, `service` for every service account "
        "and `person` for every other account" in page
    )
    assert "the audit trail gains `for_hid`, empty for every event" in page
    assert "the upgrade writes no audit event" in page
    assert "Going back to 0.9.16 is by the backup the upgrade took" in page

    # The routes, the fields and the questions that the page names are the contract's.
    contract = json.loads((ROOT / "contract" / "openapi.json").read_text(encoding="utf-8"))
    for method, path in (
        ("post", "/users"),
        ("patch", "/users/{hid}"),
        ("get", "/users"),
        ("get", "/audit-events"),
        ("get", "/users/{hid}/linked"),
        ("get", "/contacts/{hid}/linked"),
        ("get", "/operators/{hid}/linked"),
    ):
        assert method in contract["paths"][f"/api/v1{path}"]
        assert f"`{method.upper()} {path}`" in page
    schemas = contract["components"]["schemas"]
    assert schemas["UserCreate"]["additionalProperties"] is False
    assert "is_service_account" not in schemas["UserCreate"]["properties"]
    assert schemas["UserCreate"]["properties"]["kind"]["enum"] == list(accounts.KINDS)
    for field in (
        "kind",
        "answerable_hid",
        "answerable",
        "agents",
        "grants",
        "role_in_force",
        "role_capped_by",
    ):
        assert field in schemas["UserOut"]["properties"]
        assert f"`{field}`" in page
    for field in ("actor_kind", "for_hid", "for_name"):
        assert field in schemas["AuditEventOut"]["properties"]
        assert f"`{field}`" in page
    asked = {one["name"] for one in contract["paths"]["/api/v1/audit-events"]["get"]["parameters"]}
    assert {"actor_kind", "for_hid"} <= asked
    asked = {one["name"] for one in contract["paths"]["/api/v1/users"]["get"]["parameters"]}
    assert "kind" in asked
    assert "agents" in schemas["Linked"]["properties"]
    assert "`linked.agents`" in page
    columns = list(users_file.COLUMNS)
    assert columns[columns.index("kind") + 1] == "answerable"
    assert "a column `answerable` after `kind`" in page

    # The commands and their exit codes, as the page names them.
    command = (ROOT / "src/hirdir/cli/admin.py").read_text(encoding="utf-8")
    main = (ROOT / "src/hirdir/cli/main.py").read_text(encoding="utf-8")
    people = (ROOT / "src/hirdir/cli/people.py").read_text(encoding="utf-8")
    for option in ('"--kind"', '"--for"', '"--no-role"'):
        assert option in command
    assert '"--service-account"' not in command
    assert "raise _fail(NO_ROLE_REFUSED, 4)" in command
    assert 'raise _fail("--role and --no-role are not given together", 2)' in command
    assert '"--kind", metavar="person|service|agent"' in main
    assert '"--agent",' in people
    for named in (
        "`--kind person`, `--kind service` or `--kind agent`",
        "in the place of `--service-account`, which is gone",
        "`sudo hirdir admin create-user --kind agent --for sam agent-reconcile`",
        "exit `4`",
        "`--role` with `--no-role` is a mistake of usage, exit `2`",
        "`hirdir users list --kind agent`",
        "`hirdir users retire` takes `--agent`",
    ):
        assert named in page

    # The package test asks for it in the words of the server and of hirdir admin.
    script = (PACKAGING / "package-test.sh").read_text(encoding="utf-8")
    assert f"^hirdir: {admin.NO_ROLE_REFUSED}$" in script
    warned = admin.NO_ROLE_WARNING
    assert f"^pkg-admin-made holds no role, and {warned[accounts.PERSON]}$" in script
    assert f"^pkg-cli-robot holds no role, and {warned[accounts.SERVICE]}$" in script
    assert f'[["role", "{accounts.NEVER_ADMIN}"]]' in script
    assert f'[["user_hid", "{accounts.NEVER_ADMIN}"]]' in script
    assert f"is an agent, and {accounts.NEVER_ADMIN}$" in script
    domain = (ROOT / "src/hirdir/domain/accounts.py").read_text(encoding="utf-8")
    assert (
        'f"the token is not accepted: the agent {agent.username} is answerable to {whom}, '
        'who {what}"' in domain
    )
    assert (
        "the token is not accepted: the agent pkg-agent-reconcile is answerable to pkg-sam, "
        "who holds no role" in script
    )
    assert (
        "the token is not accepted: the agent upgrade-18-off-agent is answerable to "
        "upgrade-18-off, who is disabled" in hook
    )
    for word in (accounts.PERSON_ROLE, accounts.PERSON_NO_ROLE):
        assert f'"{word}"' in script
    assert f'"{accounts.PERSON_ROLE}"' in hook
    # S61 and S62 on the fresh install, and S61 on what the upgrade carried over.
    assert "\n    agents_and_kinds\n" in script
    assert "\n    no_role_made\n" in script
    for scenario in ("S61", "S62"):
        assert f'expect "{scenario} ' in script
    assert 'expect "S61 after the upgrade, ' in hook
    for function in ("before_0018", "changed_0018", "after_0018"):
        assert f"\n{function}() {{\n" in hook


def test_the_install_page_and_the_package_test_say_of_circuit_sides_and_lists_as_the_code() -> None:
    """The notes of the upgrade to 0.9.18, the newest, and what the package test asks for
    it: migration 0019 renames the A side's dates in their places, adds the Z side's and
    its network, gives every circuit group a kind and a carrier, and creates and loads the
    lists of countries and states from the data file beside it, which the wheel carries,
    before it writes the codes into the addresses with audit events of its own; the file
    of the package test says each of these as the model and the migration do, and asks
    for the trigger (P-317 to P-321); the formats' defaults are those of the settings and
    tidy nothing held (P-322); and the package test looks for the lists, by the names the
    code gives them, on the fresh install and after the upgrade."""
    import json

    from sqlalchemy import inspect
    from sqlalchemy.dialects import sqlite

    from hirdir.db.models import Circuit, CircuitGroup, Country, State
    from hirdir.domain import settings
    from hirdir.io import examples
    from hirdir.io.entities import LISTS

    versions = ROOT / "src/hirdir/db/migrations/versions"
    revision = max(path.name[:4] for path in versions.glob("[0-9]*.py"))
    assert revision == "0019"
    (migration,) = versions.glob(f"{revision}_*.py")
    source = migration.read_text(encoding="utf-8")
    assert 'down_revision = "0018"' in source
    hook = (PACKAGING / "package-test.d" / f"migration-{revision}.sh").read_text(encoding="utf-8")
    script = (PACKAGING / "package-test.sh").read_text(encoding="utf-8")

    # Two tables, created before the addresses are written: the pass whose migration
    # fails asks for the trigger, so that it fails with all of that done.
    created = re.findall(r'op\.create_table\(\s*"(\w+)"', source)
    assert created == [Country.__tablename__, State.__tablename__]
    assert source.index("_lists(now)") < source.index("_addresses(now,")
    assert "\nfail_by=trigger\n" in hook
    (request,) = re.findall(r'"request_id": "([\w-]+)"', source)
    assert f"\nupgrade_events={request}\n" in hook
    assert "writes_no_event" not in hook

    # The data file the migration reads, beside it, and in the wheel with it: the wheel
    # takes the package's whole folder, and no pattern of the files left out of the
    # repository, which the wheel leaves out too, names a data file of the migrations.
    data_file = "0019_iso3166_americas.json"
    assert f'Path(__file__).with_name("{data_file}")' in source
    data = json.loads((versions / data_file).read_text(encoding="utf-8"))
    assert data["source"] == "iso-codes 4.20.1"
    assert len(data["countries"]) == 55
    assert len(data["states"]) == 633
    assert data["countries"][0] == ["US", "United States"]
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    wheel = project["tool"]["hatch"]["build"]["targets"]["wheel"]
    assert wheel["packages"] == ["src/hirdir"]
    assert "exclude" not in wheel
    left_out = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert not [line for line in left_out if "json" in line or "migrations" in line]
    # The package test reads it from the installed package, after the upgrade and on the
    # fresh install, where the migrations loaded the lists from it.
    assert f"/site-packages/hirdir/db/migrations/versions/{data_file}" in hook
    assert f"local data=src/hirdir/db/migrations/versions/{data_file} " in script
    assert "\n    countries_and_states\n" in script

    # The columns the migration renames, each in its place, and those it adds, as SQLite
    # declares them from the model; and the indexes and foreign keys it adds.
    def said(model: type, name: str) -> str:
        column = inspect(model).columns[name]
        declared = column.type.compile(dialect=sqlite.dialect())
        return f"{column.name} {declared} {'NULL' if column.nullable else 'NOT NULL'} -"

    dates = ("installed_on", "activated_on", "disconnected_on")
    assert re.search(
        r'^DATES = \("installed_on", "activated_on", "disconnected_on"\)$', source, re.M
    )
    assert 'alter_column(name, new_column_name=f"a_{name}", existing_type=sa.Date)' in source
    circuits = Circuit.__tablename__
    renamed = "\n".join(f"{name} a_{name}" for name in dates)
    assert f"\nalso renamed_columns {circuits} '{renamed}'\n" in hook
    for name in dates:
        assert name not in inspect(Circuit).columns
        assert said(Circuit, f"a_{name}") == f"a_{name} DATE NULL -"
    added = "\n".join(said(Circuit, name) for name in [*(f"z_{d}" for d in dates), "z_group_hid"])
    assert f"\nalso new_columns {circuits} '{added}'\n" in hook
    groups = CircuitGroup.__tablename__
    added = f"{said(CircuitGroup, 'kind')}\n{said(CircuitGroup, 'carrier_hid')}"
    assert f"\nalso new_columns {groups} '{added}'\n" in hook
    for column, target in (("z_group_hid", f"{groups}.hid"), ("carrier_hid", "vendors.hid")):
        (index,) = re.findall(rf'create_index\("(\w+)", \["{column}"\], unique=False\)', source)
        assert f"index {index} on {column} unique=0 origin=c partial=0" in hook
        assert f"foreign key {column} to {target}" in hook
    assert "z_location_hid IS NULL OR z_group_hid IS NULL" in source
    assert "z_location_hid IS NULL OR z_group_hid IS NULL" in hook
    # The package test reads a renamed column under its new name.
    assert "renamed_columns[TABLE]" in script
    assert '"$(columns_now "$table" "$(columns_then "$table")")"' in script

    # The lists every inventory holds, which the files of the examples load as unchanged,
    # a reset keeps and hirdir admin load-examples leaves out.
    (held,) = re.findall(r"^held_lists=\((.+)\)$", script, re.M)
    assert tuple(held.split()) == LISTS
    assert not set(LISTS) & set(examples.LOADED)
    assert set(LISTS) <= set(LOAD_ORDER)

    # The notes.
    assert "### From 0.9.17 to 0.9.18" in INSTALL
    notes = INSTALL.split("### From 0.9.17 to 0.9.18\n", 1)[1].split("\n### ", 1)[0]
    page = " ".join(notes.split())
    assert f"The schema goes from revision `0018` to `{revision}`." in page
    for name in dates:
        assert f"`{name}`" in page
        assert f"`a_{name}`" in page
        assert f"`z_{name}`" in page
    assert "and no alias of the old names is kept" in page
    assert "`kind` is added, `collection` for every group, and `carrier_hid`, blank" in page
    assert "every country of the Americas, 55 of them, the United States first" in page
    assert "their 633 states and other subdivisions" in page
    package, release = data["source"].split()
    assert f"from the ISO 3166 data of `{package}` {release}" in page
    assert f"the request ID `{request}`" in page
    assert "`Untied States` stays `Untied States`" in page
    assert "Going back to 0.9.17 is by the backup the upgrade took" in page
    # The formats, at the defaults the settings give them, and nothing held tidied.
    assert settings.SPECS[settings.PHONE_FORMATS].default == []
    assert f"`{settings.PHONE_FORMATS}` is empty, so no telephone number is formatted" in page
    assert settings.SPECS[settings.EMAIL_LOWER_CASE].default is True
    assert f"`{settings.EMAIL_LOWER_CASE}` is on" in page
    assert settings.SPECS[settings.TITLE_CASE_NAMES].default is True
    assert f"`{settings.TITLE_CASE_NAMES}` is on, and only the web page reads it" in page
    assert "**Nothing held is tidied by the input formats**" in page

    # The routes and the fields that the page names are the contract's.
    contract = json.loads((ROOT / "contract" / "openapi.json").read_text(encoding="utf-8"))
    for method, path in (
        ("get", "/countries"),
        ("get", "/states"),
        ("get", "/places/unlisted-addresses"),
        ("get", "/settings"),
    ):
        assert method in contract["paths"][f"/api/v1{path}"]
        assert f"`{method.upper()} {path}`" in page
    for path in ("/countries", "/states"):
        assert "post" in contract["paths"][f"/api/v1{path}"]
        assert {"patch", "delete"} <= set(contract["paths"][f"/api/v1{path}/{{hid}}"])
    schemas = contract["components"]["schemas"]
    for name in dates:
        assert f"a_{name}" in schemas["CircuitOut"]["properties"]
        assert f"z_{name}" in schemas["CircuitOut"]["properties"]
        assert f"z_{name}" in schemas["CircuitEffective"]["properties"]
        assert name not in schemas["CircuitOut"]["properties"]
    assert "`z_group_hid`" in page
    assert "z_group_hid" in schemas["CircuitOut"]["properties"]
    for field in ("kind", "carrier_hid"):
        assert field in schemas["CircuitGroupOut"]["properties"]
    assert "z_side" in schemas["CircuitGroupMemberOut"]["properties"]
    assert "`z_side`" in page
    for field in ("country_name", "state_name", "ship_country_name", "ship_state_name"):
        assert field in schemas["SiteOut"]["properties"]
        assert field in schemas["LocationOut"]["properties"]
        assert f"`{field}`" in page
    assert "as_in_file" in schemas["RowChange"]["properties"]

    # What the package test asks for it, by scenario, on the fresh install and after the
    # upgrade, and in the words the API answers with.
    for function in ("before_0019", "changed_0019", "after_0019"):
        assert f"\n{function}() {{\n" in hook
    assert 'expect "S64 GET $prefix/api/v1/countries ' in script
    assert 'expect "S64 $when ' in hook
    assert 'expect "S65 $when ' in hook
    assert 'expect "S63 after the upgrade, ' in hook
    assert "tidied[contacts]=1" in hook
    assert "unset 'tidied[contacts]'" in hook
