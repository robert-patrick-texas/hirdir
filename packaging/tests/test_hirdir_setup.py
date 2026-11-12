"""The parsing and editing that hirdir-setup does, without nginx or a host to change."""

import re
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
