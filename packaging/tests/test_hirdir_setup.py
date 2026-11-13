"""The parsing and editing that hirdir-setup does, without nginx or a host to change."""

import re
import subprocess
from pathlib import Path

import hirdir_setup as setup
import pytest

PACKAGING = Path(__file__).resolve().parents[1]
SNIPPET = (PACKAGING / "nginx" / "snippet.conf").read_text(encoding="utf-8")

NGINX_CONF = """\
user www-data;
events { worker_connections 768; }
http {
    include /etc/nginx/mime.types;
    log_format main '$remote_addr "$request" {braces} in a string';
    include /etc/nginx/conf.d/*.conf;
    include /etc/nginx/sites-enabled/*;
}
mail {
    server { listen 993 ssl; }
}
stream {
    server { listen 8443 ssl; proxy_pass backend; }
}
"""

PLAIN_SITE = """\
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;
    location / { try_files $uri $uri/ =404; }
}
"""

TLS_SITE = """\
# The site of the example network.
server {
    listen 80;
    server_name www.example.net;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name www.example.net
                example.net;   # two names, on two lines
    ssl_certificate     /etc/ssl/example.net.pem;
    ssl_certificate_key /etc/ssl/example.net.key;

    location ~ \\.php$ { return 404; }
    location / {
        root /var/www/html;
    }
}
"""

TWO_TLS = (
    TLS_SITE
    + """
server {
\tlisten 8443 ssl;
\tssl_certificate /etc/ssl/example.org.pem;
\tssl_certificate_key /etc/ssl/example.org.key;
}
"""
)

FILES = {
    "/etc/nginx/nginx.conf": NGINX_CONF,
    "/etc/nginx/sites-enabled/default": PLAIN_SITE,
    "/etc/nginx/sites-enabled/example": TLS_SITE,
}


def dump(files: dict[str, str]) -> str:
    """Build what `nginx -T` prints for these files."""
    return "".join(f"# configuration file {path}:\n{text}\n" for path, text in files.items())


def test_parse_builds_a_tree_with_line_numbers() -> None:
    tree = setup.parse(TLS_SITE)
    assert [directive.name for directive in tree] == ["server", "server"]
    second = tree[1]
    assert (second.line, second.end, second.close) == (8, 8, 20)
    assert second.block is not None
    names = next(child for child in second.block if child.name == "server_name")
    assert names.args == ["www.example.net", "example.net"]
    assert (names.line, names.end) == (11, 12)


def test_parse_ignores_comments_and_braces_inside_strings() -> None:
    tree = setup.parse(NGINX_CONF)
    http = next(directive for directive in tree if directive.name == "http")
    assert http.block is not None
    assert [child.name for child in http.block] == ["include", "log_format", "include", "include"]
    assert setup.parse("# server { listen 443 ssl; }\n") == []


def test_parse_keeps_a_variable_in_braces_inside_one_word() -> None:
    (directive,) = setup.parse("return 301 https://example.net${request_uri};\n")
    assert directive.args == ["301", "https://example.net${request_uri}"]


def test_split_dump_gives_each_file_its_text() -> None:
    files = setup.split_dump("nginx: a line before the first file\n" + dump(FILES))
    assert list(files) == list(FILES)
    assert files["/etc/nginx/sites-enabled/example"].rstrip("\n") == TLS_SITE.rstrip("\n")


def test_only_http_servers_that_listen_with_ssl_are_listed() -> None:
    (server,) = setup.tls_servers(FILES)
    assert server.file == "/etc/nginx/sites-enabled/example"
    assert server.line == 8
    assert server.names == ["www.example.net", "example.net"]
    assert server.listens == ["443 ssl", "[::]:443 ssl"]
    assert not server.included
    assert "www.example.net" in server.label()


def test_a_port_named_443_without_ssl_is_not_tls() -> None:
    assert setup.tls_servers({"/etc/nginx/conf.d/a.conf": "server { listen 443; }\n"}) == []


def test_the_include_goes_after_server_name_with_its_indent() -> None:
    (server,) = setup.tls_servers(FILES)
    edited = setup.add_include(TLS_SITE, server)
    lines = edited.splitlines()
    assert lines[11] == "                example.net;   # two names, on two lines"
    assert lines[12] == "    include snippets/hirdir.conf;  # added by hirdir-setup"
    assert len(lines) == len(TLS_SITE.splitlines()) + 1
    (after,) = setup.tls_servers({server.file: edited})
    assert after.included


def test_adding_twice_changes_nothing_the_second_time() -> None:
    (server,) = setup.tls_servers(FILES)
    once = setup.add_include(TLS_SITE, server)
    (again,) = setup.tls_servers({server.file: once})
    assert setup.add_include(once, again) == once


def test_without_a_server_name_the_include_goes_after_the_last_listen() -> None:
    servers = setup.tls_servers({"/etc/nginx/sites-enabled/example": TWO_TLS})
    assert [server.line for server in servers] == [8, 22]
    edited = setup.add_include(TWO_TLS, servers[1])
    assert edited.splitlines()[23] == "\tinclude snippets/hirdir.conf;  # added by hirdir-setup"
    assert [s.included for s in setup.tls_servers({"x": edited})] == [False, True]


def test_a_server_block_on_one_line_is_refused_not_guessed_at() -> None:
    text = "server { listen 443 ssl; server_name www.example.net; }\n"
    (server,) = setup.tls_servers({"/etc/nginx/conf.d/one.conf": text})
    with pytest.raises(setup.SetupError, match="by hand"):
        setup.add_include(text, server)


def test_removing_gives_back_the_file_as_it_was() -> None:
    (server,) = setup.tls_servers(FILES)
    assert setup.remove_include(setup.add_include(TLS_SITE, server)) == TLS_SITE
    assert setup.remove_include(TLS_SITE) == TLS_SITE


def test_removing_takes_an_include_written_by_hand_too() -> None:
    text = "server {\n    listen 443 ssl;\n    include /etc/nginx/snippets/hirdir.conf;\n}\n"
    assert setup.remove_include(text) == "server {\n    listen 443 ssl;\n}\n"
    other = "server {\n    include snippets/hirdir.conf.d/*.conf;\n}\n"
    assert setup.remove_include(other) == other


def test_the_packaged_snippet_serves_under_hirdir() -> None:
    assert setup.snippet_prefix(SNIPPET) == "/hirdir"
    assert setup.with_prefix(SNIPPET, "/hirdir") == SNIPPET


def test_a_new_prefix_rewrites_the_three_prefix_lines_and_nothing_else() -> None:
    moved = setup.with_prefix(SNIPPET, "/inventory")
    assert setup.snippet_prefix(moved) == "/inventory"
    changed = [
        (old, new)
        for old, new in zip(SNIPPET.splitlines(), moved.splitlines(), strict=True)
        if old != new
    ]
    assert len(changed) == 3
    assert all(old.rstrip().endswith("# prefix") for old, _ in changed)
    location, redirect = setup.parse(moved)
    assert location.args == ["^~", "/inventory/"]
    assert location.block is not None
    header = next(d for d in location.block if d.args[:1] == ["X-Forwarded-Prefix"])
    assert header.args == ["X-Forwarded-Prefix", "/inventory"]
    assert redirect.args == ["=", "/inventory"]
    assert redirect.block is not None
    assert redirect.block[-1].args == ["301", "/inventory/"]
    assert "hirdir/;" in moved  # The upstream keeps its name: proxy_pass http://hirdir/;
    assert setup.with_prefix(moved, "/hirdir") == SNIPPET


def test_at_the_root_there_is_no_redirect_and_no_prefix_header() -> None:
    root = setup.with_prefix(SNIPPET, "/")
    assert setup.snippet_prefix(root) == "/"
    (location,) = setup.parse(root)
    assert location.args == ["^~", "/"]
    assert location.block is not None
    header = next(d for d in location.block if d.args[:1] == ["X-Forwarded-Prefix"])
    assert header.args == ["X-Forwarded-Prefix", ""]
    assert setup.with_prefix(root, "/") == root
    assert setup.with_prefix(root, "/hirdir") == SNIPPET


def test_a_deeper_prefix_is_written_whole() -> None:
    moved = setup.with_prefix(SNIPPET, "/tools/inventory")
    assert "location ^~ /tools/inventory/ {" in moved
    assert "return 301 /tools/inventory/;" in moved


def test_a_snippet_without_the_prefix_lines_is_refused() -> None:
    with pytest.raises(setup.SetupError, match="by hand"):
        setup.with_prefix("location /hirdir/ { proxy_pass http://hirdir/; }\n", "/inventory")
    with pytest.raises(setup.SetupError):
        setup.snippet_prefix("# nothing here\n")


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("/hirdir", "/hirdir"),
        ("/inventory/", "/inventory"),
        ("/", "/"),
        ("/a/b-c_d.e~f", "/a/b-c_d.e~f"),
    ],
)
def test_a_prefix_is_normalised(given: str, expected: str) -> None:
    assert setup.normalise_prefix(given) == expected


@pytest.mark.parametrize("given", ["", "inventory", "/two words", "//", "/a//b", "/a;b", "/a{b}"])
def test_what_is_not_a_prefix_is_refused(given: str) -> None:
    with pytest.raises(setup.SetupError, match="not a prefix"):
        setup.normalise_prefix(given)


def test_the_prefix_shape_is_the_one_the_server_accepts() -> None:
    app = (PACKAGING.parent / "src" / "hirdir" / "app.py").read_text(encoding="utf-8")
    assert f'PREFIX = re.compile(r"{setup.PREFIX.pattern}")' in app


@pytest.mark.parametrize("ipv6", [True, False])
def test_the_self_signed_site_listens_with_ssl_and_includes_the_snippet(ipv6: bool) -> None:
    text = setup.self_signed_site(ipv6)
    assert text.startswith(setup.SELF_SIGNED_MARK)
    assert "not for production" in text
    (server,) = setup.tls_servers({str(setup.SELF_SIGNED_SITE): text})
    assert server.included
    assert ("[::]:443 ssl" in server.listens) is ipv6


def test_choosing_a_server() -> None:
    with pytest.raises(setup.SetupError, match="no nginx site listens with ssl"):
        setup.choose_server([], None)
    (one,) = setup.tls_servers(FILES)
    assert setup.choose_server([one], None) is one
    two = setup.tls_servers({"/etc/nginx/sites-enabled/example": TWO_TLS})
    assert setup.choose_server(two, None) is None
    assert setup.choose_server(two, "/etc/nginx/sites-enabled/example:22") is two[1]
    with pytest.raises(setup.SetupError, match="FILE:LINE"):
        setup.choose_server(two, "/etc/nginx/sites-enabled/example")
    with pytest.raises(setup.SetupError, match="no server block"):
        setup.choose_server(two, "/etc/nginx/sites-enabled/other")
    assert setup.choose_server([one], "/etc/nginx/sites-enabled/example") is one


def test_choosing_a_server_by_the_file_its_link_points_to(tmp_path: Path) -> None:
    available = tmp_path / "sites-available" / "example"
    enabled = tmp_path / "sites-enabled" / "example"
    available.parent.mkdir()
    enabled.parent.mkdir()
    available.write_text(TLS_SITE, encoding="utf-8")
    enabled.symlink_to(available)
    (server,) = setup.tls_servers({str(enabled): TLS_SITE})
    assert setup.choose_server([server], str(available)) is server


def test_a_diff_names_the_file_and_shows_the_added_line() -> None:
    (server,) = setup.tls_servers(FILES)
    shown = setup.diff(server.file, TLS_SITE, setup.add_include(TLS_SITE, server))
    assert shown.startswith(f"--- {server.file}\n+++ {server.file}\n")
    added = [line for line in shown.splitlines() if line.startswith("+ ")]
    assert added == ["+    include snippets/hirdir.conf;  # added by hirdir-setup"]
    assert setup.diff("/etc/nginx/new", None, "a\n").startswith(
        "--- /dev/null\n+++ /etc/nginx/new\n"
    )
    assert setup.diff(server.file, TLS_SITE, TLS_SITE) == ""


def test_purging_the_package_finds_what_hirdir_setup_wrote() -> None:
    """postrm removes the include and the self-signed site by the marks this tool writes."""
    postrm = (PACKAGING / "debian" / "postrm").read_text(encoding="utf-8")
    found = re.search(r"^INCLUDE='(.+)'$", postrm, re.MULTILINE)
    assert found is not None
    pattern = found.group(1).replace("[[:space:]]", r"\s")
    assert re.search(pattern, f"    {setup.INCLUDE_LINE}")
    assert setup.SELF_SIGNED_MARK.rstrip(".") in postrm
    assert str(setup.SELF_SIGNED_SITE) in postrm
    assert str(setup.SELF_SIGNED_DIR).startswith("/etc/hirdir/")
    # The snippet is written by postinst and is no conffile, so postrm removes it.
    assert f"rm -f {setup.SNIPPET}\n" in postrm


# --- the snippet at an install and at an upgrade ---------------------------------------

# The snippets of earlier versions, each named for the last version that shipped it.
EARLIER = sorted((PACKAGING / "tests" / "snippets").glob("*.conf"))
# The snippet this version ships, by the hash hirdir-setup knows a snippet by. When
# packaging/nginx/snippet.conf changes, three things go together: the text it had is
# kept in packaging/tests/snippets/ under the last version that shipped it, this value
# is added to SHIPPED_BEFORE in hirdir_setup.py, and the new value is written here.
# Without the first two, an upgrade would take the snippet of a host for one edited by
# hand and leave it as it was.
SHIPPED_NOW = "d15e6122c83438ceaae535e5af86611aa0364a6756d94e4eb115a73387590735"


def test_a_changed_snippet_is_not_shipped_without_remembering_the_one_before() -> None:
    assert setup.body_hash(SNIPPET) == SHIPPED_NOW, "see the comment on SHIPPED_NOW"
    assert SHIPPED_NOW not in setup.SHIPPED_BEFORE
    kept = {setup.body_hash(path.read_text(encoding="utf-8")) for path in EARLIER}
    assert kept == set(setup.SHIPPED_BEFORE)


def test_the_body_of_a_snippet_is_the_same_under_every_prefix() -> None:
    assert len(setup.body(SNIPPET).splitlines()) == len(SNIPPET.splitlines()) - 3
    for prefix in ("/inventory", "/tools/inventory", "/"):
        assert setup.body(setup.with_prefix(SNIPPET, prefix)) == setup.body(SNIPPET)


@pytest.mark.parametrize("prefix", ["/hirdir", "/inventory", "/tools/inventory", "/"])
@pytest.mark.parametrize("earlier", EARLIER, ids=lambda path: path.stem)
def test_the_snippet_of_an_earlier_version_is_renewed_under_the_prefix_it_has(
    earlier: Path, prefix: str
) -> None:
    before = setup.with_prefix(earlier.read_text(encoding="utf-8"), prefix)
    after = setup.renewed(before, SNIPPET)
    assert after == setup.with_prefix(SNIPPET, prefix)
    assert setup.snippet_prefix(after) == prefix
    assert "client_max_body_size" not in before
    assert "client_max_body_size 20m;" in after
    # Renewed a second time, it is left as it is.
    assert setup.renewed(after, SNIPPET) == after


def test_with_no_snippet_on_the_host_the_shipped_one_is_written() -> None:
    assert setup.renewed(None, SNIPPET) == SNIPPET
    assert setup.renewed(None, SNIPPET, "/inventory/") == setup.with_prefix(SNIPPET, "/inventory")


def test_a_prefix_given_with_renew_takes_the_place_of_the_one_the_snippet_has() -> None:
    before = setup.with_prefix(EARLIER[0].read_text(encoding="utf-8"), "/inventory")
    assert setup.renewed(before, SNIPPET, "/tools") == setup.with_prefix(SNIPPET, "/tools")


@pytest.mark.parametrize("source", [SNIPPET, *(path.read_text("utf-8") for path in EARLIER)])
def test_a_snippet_edited_by_hand_is_left_as_it_is(source: str) -> None:
    edited = setup.with_prefix(source, "/inventory").replace(
        "    proxy_set_header Host", "    proxy_read_timeout 300s;\n    proxy_set_header Host"
    )
    assert edited != setup.with_prefix(source, "/inventory")
    with pytest.raises(setup.SetupError, match="left as it is") as refused:
        setup.renewed(edited, SNIPPET)
    assert str(setup.TEMPLATE) in str(refused.value)


class Host:
    """A host for --renew: the two files in a directory of the test, and an nginx that
    answers as the test says. No command is run."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.snippet = tmp_path / "etc" / "nginx" / "snippets" / "hirdir.conf"
        self.template = tmp_path / "share" / "snippet.conf"
        self.template.parent.mkdir(parents=True)
        self.template.write_text(SNIPPET, encoding="utf-8")
        self.nginx = tmp_path / "nginx"
        self.site = str(tmp_path / "etc" / "nginx" / "site")
        self.includes = True  # Whether a site includes the snippet.
        self.loads = True  # Whether nginx accepts its configuration before the change.
        self.accepts = True  # Whether it accepts it afterwards.
        self.commands: list[list[str]] = []
        monkeypatch.setattr(setup, "SNIPPET", self.snippet)
        monkeypatch.setattr(setup, "TEMPLATE", self.template)
        monkeypatch.setattr(setup, "NGINX", str(self.nginx))
        monkeypatch.setattr(setup, "_run", self.run)

    def install_nginx(self) -> None:
        self.nginx.write_text("", encoding="utf-8")

    def run(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        code, out, err = 0, "", ""
        if command == [str(self.nginx), "-T"]:
            files = {self.site: TLS_SITE}
            if self.includes and self.snippet.is_file():
                files[str(self.snippet)] = self.snippet.read_text(encoding="utf-8")
            out = dump(files)
            code = 0 if self.loads else 1
        elif command == [str(self.nginx), "-t"]:
            code, err = (0, "") if self.accepts else (1, "nginx: [emerg] unknown directive")
        return subprocess.CompletedProcess(command, code, out, err)

    def renew(self, *options: str) -> int:
        return setup._renew(setup._arguments(["--renew", "--yes", *options]))

    def reloaded(self) -> bool:
        return any("reload" in command for command in self.commands)


@pytest.fixture
def host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Host:
    return Host(tmp_path, monkeypatch)


def test_renew_writes_the_snippet_on_a_host_without_nginx(
    host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    assert host.renew() == 0
    assert host.snippet.read_text(encoding="utf-8") == SNIPPET
    assert host.snippet.stat().st_mode & 0o777 == 0o644
    assert "nginx is not installed" in capsys.readouterr().out
    assert host.commands == []

    assert host.renew() == 0
    assert capsys.readouterr().out.startswith("Nothing to change: ")


def test_renew_keeps_the_prefix_and_reloads_nginx_when_a_site_includes_the_snippet(
    host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    host.install_nginx()
    host.snippet.parent.mkdir(parents=True)
    before = setup.with_prefix(EARLIER[0].read_text(encoding="utf-8"), "/inventory")
    host.snippet.write_text(before, encoding="utf-8")

    assert host.renew() == 0
    assert host.snippet.read_text(encoding="utf-8") == setup.with_prefix(SNIPPET, "/inventory")
    shown = capsys.readouterr().out
    assert "+    client_max_body_size 20m;" in shown
    last = shown.splitlines()[-1]
    assert last.startswith(f"{host.snippet} is now as this version of hirdir ships it, for ")
    assert "for /inventory/. " in last
    assert host.reloaded()


def test_renew_leaves_the_reload_to_the_package_when_told_to(
    host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    host.install_nginx()
    host.snippet.parent.mkdir(parents=True)
    host.snippet.write_text(EARLIER[0].read_text(encoding="utf-8"), encoding="utf-8")

    assert host.renew("--no-reload") == 0
    assert host.snippet.read_text(encoding="utf-8") == SNIPPET
    # postinst prints this line, and says itself whether it had nginx reload.
    assert capsys.readouterr().out.splitlines()[-1] == (
        f"{host.snippet} is now as this version of hirdir ships it, for /hirdir/."
    )
    assert [command[1:] for command in host.commands] == [["-T"], ["-t"]]
    assert not host.reloaded()


def test_renew_reloads_nothing_when_no_site_includes_the_snippet(
    host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    host.install_nginx()
    host.includes = False

    assert host.renew() == 0
    assert host.snippet.read_text(encoding="utf-8") == SNIPPET
    assert "No site includes it yet" in capsys.readouterr().out
    assert not host.reloaded()


def test_renew_puts_the_snippet_back_when_nginx_refuses_the_new_one(host: Host) -> None:
    host.install_nginx()
    host.accepts = False
    host.snippet.parent.mkdir(parents=True)
    before = setup.with_prefix(EARLIER[0].read_text(encoding="utf-8"), "/inventory")
    host.snippet.write_text(before, encoding="utf-8")

    with pytest.raises(setup.SetupError, match="every file was put back"):
        host.renew()
    assert host.snippet.read_text(encoding="utf-8") == before
    assert not host.reloaded()


def test_renew_leaves_the_snippet_when_nginx_is_already_out_of_order(host: Host) -> None:
    host.install_nginx()
    host.loads = False
    host.snippet.parent.mkdir(parents=True)
    before = EARLIER[0].read_text(encoding="utf-8")
    host.snippet.write_text(before, encoding="utf-8")

    with pytest.raises(setup.SetupError, match="does not accept its configuration"):
        host.renew()
    assert host.snippet.read_text(encoding="utf-8") == before


def test_renew_still_writes_a_first_snippet_when_nginx_is_out_of_order(host: Host) -> None:
    host.install_nginx()
    host.loads = False

    assert host.renew() == 0
    assert host.snippet.read_text(encoding="utf-8") == SNIPPET
    assert not host.reloaded()


def test_renew_leaves_a_snippet_edited_by_hand_and_says_where_the_shipped_one_is(
    host: Host,
) -> None:
    host.install_nginx()
    host.snippet.parent.mkdir(parents=True)
    edited = SNIPPET.replace("client_max_body_size 20m;", "client_max_body_size 5m;")
    host.snippet.write_text(edited, encoding="utf-8")

    with pytest.raises(setup.SetupError, match="left as it is") as refused:
        host.renew()
    assert str(host.template) in str(refused.value)
    assert host.snippet.read_text(encoding="utf-8") == edited
    assert host.commands == []


@pytest.mark.parametrize(
    "options",
    [
        ["--renew", "--site", "/etc/nginx/sites-enabled/example"],
        ["--renew", "--self-signed"],
        ["--renew", "--remove"],
        ["--no-reload"],
        ["--no-reload", "--prefix", "/inventory"],
    ],
)
def test_options_that_do_not_go_together_are_refused(options: list[str]) -> None:
    with pytest.raises(SystemExit):
        setup._arguments(options)
