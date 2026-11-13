#!/opt/hirdir/venv/bin/python -I
"""hirdir-setup: add hirdir to an nginx site that already terminates TLS.

Installed as /usr/sbin/hirdir-setup and run by the interpreter the package carries. It
uses the standard library alone.

It reads the configuration nginx has loaded (`nginx -T`), lists the server blocks that
listen with ssl, and adds `include snippets/hirdir.conf;` to the one chosen. Every
change is shown as a diff first. After writing, it runs `nginx -t`: when that passes
nginx is reloaded, and when it fails every file is put back as it was.

Running it again with the same options changes nothing.

The snippet itself is written by `--renew`, from the one the package ships and with the
prefix it already has. The package runs that when it is installed and at each upgrade.

`--settings` brings /etc/hirdir/config.toml up to date with this version: a setting the
file does not have yet is put in, commented out at its default, and nothing that is in
the file is changed. The package runs that too, at install and at each upgrade, so the
file is never one that dpkg asks about.

`--upgrade PACKAGE.deb` installs a newer package with apt, without a question to answer.
"""

import argparse
import contextlib
import difflib
import hashlib
import os
import re
import subprocess
import sys
import tempfile
import time
import tomllib
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

NGINX = "/usr/sbin/nginx"
SYSTEMCTL = "/usr/bin/systemctl"
OPENSSL = "/usr/bin/openssl"

NGINX_DIR = Path("/etc/nginx")
SNIPPET = NGINX_DIR / "snippets" / "hirdir.conf"
# The snippet as this version of the package ships it, under the prefix /hirdir.
TEMPLATE = Path("/usr/share/hirdir/nginx/snippet.conf")
INCLUDE = "snippets/hirdir.conf"
# The postrm of the package looks for this mark when the package is purged.
MARK = "# added by hirdir-setup"
INCLUDE_LINE = f"include {INCLUDE};  {MARK}"

SETTINGS = Path("/etc/hirdir/config.toml")
# The settings file as this version of the package ships it: every setting, commented
# out at its default, with what it means.
SETTINGS_TEMPLATE = Path("/usr/share/hirdir/config.toml")
SETTING_LINE = re.compile(r"^\s*(?:#\s?)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*\S")
TABLE_LINE = re.compile(r"^\s*\[([A-Za-z0-9_.-]+)\]\s*(?:#.*)?$")
APT_GET = "/usr/bin/apt-get"
DPKG_DEB = "/usr/bin/dpkg-deb"
DPKG_QUERY = "/usr/bin/dpkg-query"
DPKG = "/usr/bin/dpkg"

SELF_SIGNED_SITE = NGINX_DIR / "sites-available" / "hirdir-self-signed"
SELF_SIGNED_LINK = NGINX_DIR / "sites-enabled" / "hirdir-self-signed"
SELF_SIGNED_DIR = Path("/etc/hirdir/self-signed")
SELF_SIGNED_MARK = "# Written by hirdir-setup --self-signed."
SELF_SIGNED_WARNING = (
    "This site uses a throwaway self-signed certificate. It is for test containers\n"
    "only and is not for production: browsers and clients will not trust it."
)

# The same shape the server accepts in X-Forwarded-Prefix.
PREFIX = re.compile(r"(/[A-Za-z0-9._~-]+)+")

# The three lines of the snippet that hold the prefix.
LOCATION_LINE = re.compile(r"^(\s*location\s+\^~\s+)(\S+)(\s*\{.*)$")
HEADER_LINE = re.compile(r"^(\s*proxy_set_header\s+X-Forwarded-Prefix\s+)([^;\s]+)(\s*;.*)$")
REDIRECT_LINE = re.compile(
    r"^(\s*location\s+=\s+)(\S+)(\s*\{.*\breturn\s+30[1278]\s+)(\S+)(\s*;.*\}.*)$"
)
INCLUDE_ONLY_LINE = re.compile(
    r"^\s*include\s+[\"']?(?:/etc/nginx/)?snippets/hirdir\.conf[\"']?\s*;\s*(#.*)?$"
)

# The snippets that earlier versions shipped, each as the SHA-256 of its text without the
# three lines that hold the prefix (see `body`). A snippet on a host that is one of
# these, or the one this version ships, was changed by this tool alone, and --renew
# replaces it. When packaging/nginx/snippet.conf changes, the hash it had is added
# here and its text is kept in packaging/tests/snippets/. A test fails until then.
SHIPPED_BEFORE = {
    "f0423e2580520437726031bcab33d473cf25b6c97fe590c3fd40d035590ffae6": "0.1.0 to 0.2.1",
}


class SetupError(Exception):
    """Something the operator must put right. The message says what."""


# ---- nginx configuration: parsing ---------------------------------------------------


@dataclass
class Directive:
    """One nginx directive, with the lines it spans."""

    name: str
    args: list[str]
    line: int  # The line it starts on, counted from 1.
    end: int  # The line of its ";" or, for a block, of its "{".
    block: list[Directive] | None = None
    close: int = 0  # For a block, the line of its "}".


def _pieces(text: str) -> Iterator[tuple[str, int, bool]]:
    """Yield (piece, line, quoted) for nginx configuration text, without comments."""
    position, line, length = 0, 1, len(text)
    while position < length:
        char = text[position]
        if char == "\n":
            line += 1
            position += 1
        elif char.isspace():
            position += 1
        elif char == "#":
            while position < length and text[position] != "\n":
                position += 1
        elif char in "{};":
            yield char, line, False
            position += 1
        elif char in "\"'":
            start, cursor, buffer = line, position + 1, []
            while cursor < length and text[cursor] != char:
                if text[cursor] == "\\" and cursor + 1 < length:
                    buffer.append(text[cursor])
                    cursor += 1
                if text[cursor] == "\n":
                    line += 1
                buffer.append(text[cursor])
                cursor += 1
            yield "".join(buffer), start, True
            position = cursor + 1
        else:
            cursor = position
            while cursor < length and not text[cursor].isspace() and text[cursor] not in "{};":
                # ${name} inside a word is a variable, not a block.
                if text[cursor] == "$" and text[cursor + 1 : cursor + 2] == "{":
                    closing = text.find("}", cursor)
                    cursor = closing if closing != -1 else cursor + 1
                cursor += 1
            yield text[position:cursor], line, False
            position = cursor


def parse(text: str) -> list[Directive]:
    """Return the directives of nginx configuration text as a tree.

    It is forgiving, because it only ever reads configuration that nginx has accepted.
    """
    root: list[Directive] = []
    stack: list[list[Directive]] = [root]
    open_blocks: list[Directive] = []
    words: list[str] = []
    first = 0
    for piece, line, quoted in _pieces(text):
        if quoted or piece not in "{};":
            if not words:
                first = line
            words.append(piece)
        elif piece == ";":
            if words:
                stack[-1].append(Directive(words[0], words[1:], first, line))
            words = []
        elif piece == "{":
            block: list[Directive] = []
            name = words[0] if words else ""
            directive = Directive(name, words[1:], first if words else line, line, block)
            stack[-1].append(directive)
            stack.append(block)
            open_blocks.append(directive)
            words = []
        elif open_blocks:
            open_blocks.pop().close = line
            stack.pop()
            words = []
    return root


def split_dump(dump: str) -> dict[str, str]:
    """Split the output of `nginx -T` into the text of each configuration file."""
    files: dict[str, str] = {}
    path: str | None = None
    lines: list[str] = []
    for line in dump.splitlines():
        header = re.fullmatch(r"# configuration file (.+):", line)
        if header:
            if path is not None:
                files[path] = "\n".join(lines) + "\n"
            path, lines = header.group(1), []
        elif path is not None:
            lines.append(line)
    if path is not None:
        files[path] = "\n".join(lines) + "\n"
    return files


@dataclass
class Server:
    """A server block that listens with ssl."""

    file: str
    line: int  # The line of "server {".
    names: list[str]
    listens: list[str]
    included: bool  # Whether it already includes the snippet.
    insert_after: int  # The line the include goes after.
    indent: str

    def label(self) -> str:
        """Describe the block in one line, for a list to choose from."""
        names = " ".join(self.names) or "(no server_name)"
        return f"{self.file}:{self.line}  {names}  listen {', '.join(self.listens)}"


def _includes_snippet(directive: Directive) -> bool:
    return (
        directive.name == "include"
        and bool(directive.args)
        and directive.args[0] in {INCLUDE, str(SNIPPET)}
    )


def tls_servers(files: dict[str, str]) -> list[Server]:
    """Return every http server block in files that listens with ssl, in file order."""
    found: list[Server] = []

    def visit(block: list[Directive], path: str, lines: list[str]) -> None:
        for directive in block:
            if directive.block is None:
                continue
            if directive.name != "server":
                # The server blocks of mail and stream proxies are not web sites, and
                # a "server" line inside an upstream is not a block at all.
                if directive.name not in {"mail", "stream", "upstream"}:
                    visit(directive.block, path, lines)
                continue
            listens = [child for child in directive.block if child.name == "listen"]
            if not any("ssl" in child.args[1:] for child in listens):
                continue
            named = [child for child in directive.block if child.name == "server_name"]
            anchor = named[-1] if named else listens[-1]
            text = lines[anchor.line - 1] if anchor.line <= len(lines) else ""
            found.append(
                Server(
                    file=path,
                    line=directive.line,
                    names=[name for child in named for name in child.args],
                    listens=[" ".join(child.args) for child in listens],
                    included=any(_includes_snippet(child) for child in directive.block),
                    insert_after=anchor.end,
                    indent=text[: len(text) - len(text.lstrip())],
                )
            )

    for path, text in files.items():
        visit(parse(text), path, text.splitlines())
    return found


# ---- nginx configuration: editing ---------------------------------------------------


def add_include(text: str, server: Server) -> str:
    """Return text with the include added to server, a block found in this same text.

    The result is parsed again. If the include did not land in that block, as it would
    not in a block written on one line, the edit is refused rather than guessed at.
    """
    if server.included:
        return text
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    lines.insert(server.insert_after, f"{server.indent}{INCLUDE_LINE}\n")
    edited = "".join(lines)
    for after in tls_servers({server.file: edited}):
        if after.line == server.line and after.included:
            return edited
    raise SetupError(
        f"cannot place the include in the server block at {server.file}:{server.line}. "
        f"Add this line inside it by hand, then run nginx -t:\n    include {INCLUDE};"
    )


def remove_include(text: str) -> str:
    """Return text without any line that only includes the snippet."""
    kept = [line for line in text.splitlines(keepends=True) if not INCLUDE_ONLY_LINE.match(line)]
    return "".join(kept)


def normalise_prefix(value: str) -> str:
    """Return the prefix as the snippet writes it: "/" for the root, else "/name"."""
    prefix = value.strip()
    if prefix != "/":
        prefix = prefix.rstrip("/")
    if prefix != "/" and not PREFIX.fullmatch(prefix):
        raise SetupError(
            f"'{value}' is not a prefix. Use / for the root, or a path such as /inventory "
            "made of letters, digits, '.', '_', '~' and '-'."
        )
    return prefix


def snippet_prefix(text: str) -> str:
    """Return the prefix the snippet serves hirdir under: "/" or "/name"."""
    for line in text.splitlines():
        match = LOCATION_LINE.match(line)
        if match:
            path = match.group(2)
            return "/" if path == "/" else path.rstrip("/")
    raise SetupError(f"{SNIPPET} has no 'location ^~ PREFIX/ {{' line; its prefix cannot be read")


def with_prefix(text: str, prefix: str) -> str:
    """Return the snippet rewritten to serve hirdir under prefix.

    Three lines hold the prefix: the location, the X-Forwarded-Prefix header, and the
    one-line redirect from the address without its last slash. Every other line is kept
    as it is. Served at the root there is nothing to redirect, so that line is left
    out, and the header is set to nothing, which also stops a client from supplying it.
    """
    root = prefix == "/"
    lines = text.splitlines()
    out: list[str] = []
    seen_location = seen_header = seen_redirect = False
    for line in lines:
        if match := REDIRECT_LINE.match(line):
            seen_redirect = True
            if not root:
                head, _, middle, _, tail = match.groups()
                out.append(f"{head}{prefix}{middle}{prefix}/{tail}")
            continue
        if not seen_location and (match := LOCATION_LINE.match(line)):
            seen_location = True
            path = "/" if root else f"{prefix}/"
            line = f"{match.group(1)}{path}{match.group(3)}"
        elif match := HEADER_LINE.match(line):
            seen_header = True
            value = '""' if root else prefix
            line = f"{match.group(1)}{value}{match.group(3)}"
        out.append(line)
    if not (seen_location and seen_header):
        raise SetupError(
            f"{SNIPPET} does not have the 'location ^~' and 'X-Forwarded-Prefix' lines "
            "this tool rewrites. Edit the prefix in it by hand."
        )
    while out and not out[-1].strip():
        out.pop()
    if not root and not seen_redirect:
        # The packaged snippet ends with the comment that explains the redirect, so the
        # line goes back under it. Anything else gets a blank line first.
        if not out[-1].lstrip().startswith("#"):
            out.append("")
        redirect = f"location = {prefix} {{ absolute_redirect off; return 301 {prefix}/; }}"
        out.append(f"{redirect}    # prefix")
    return "\n".join(out) + "\n"


def body(text: str) -> str:
    """Return a snippet without the three lines that hold the prefix.

    These are the lines `with_prefix` rewrites or leaves out, so two snippets with the
    same body differ in their prefix and in nothing else.
    """
    kept: list[str] = []
    seen_location = False
    for line in text.splitlines():
        if REDIRECT_LINE.match(line) or HEADER_LINE.match(line):
            continue
        if not seen_location and LOCATION_LINE.match(line):
            seen_location = True
            continue
        kept.append(line)
    while kept and not kept[-1].strip():
        kept.pop()
    return "\n".join(kept)


def body_hash(text: str) -> str:
    """Return the SHA-256 that names a snippet whatever its prefix."""
    return hashlib.sha256(body(text).encode("utf-8")).hexdigest()


def shipped(text: str, template: str) -> bool:
    """Say whether a snippet is one the package shipped, now or before, under any prefix."""
    found = body_hash(text)
    return found == body_hash(template) or found in SHIPPED_BEFORE


def renewed(before: str | None, template: str, prefix: str | None = None) -> str:
    """Return the snippet as this version ships it, under the prefix it has or is given.

    `before` is the snippet on the host, or None when there is none. One that was edited
    by hand is not replaced: the error says so, and where the shipped one is.
    """
    if before is not None and not shipped(before, template):
        raise SetupError(
            f"{SNIPPET} differs from what hirdir ships in more than its prefix, so it is "
            f"left as it is. This version ships {TEMPLATE}: bring over by hand what is "
            "new there, then run: sudo nginx -t && sudo systemctl reload nginx"
        )
    if prefix is None:
        prefix = snippet_prefix(template if before is None else before)
    return with_prefix(template, normalise_prefix(prefix))


# --- the settings file -----------------------------------------------------------------


@dataclass
class Settings:
    """The settings of one table of a settings file, and where the table ends."""

    names: set[str] = field(default_factory=set)
    # The line after the last one of the table that is not blank.
    end: int = 0


def _tables(lines: Sequence[str]) -> dict[str, Settings]:
    """Return the tables of a settings file. "" is what stands before the first table.

    A setting counts as there whether it is set or commented out: either way the one
    who keeps the file has seen it.
    """
    tables = {"": Settings()}
    current = ""
    for number, line in enumerate(lines):
        table = TABLE_LINE.match(line)
        if table is not None:
            current = table[1]
            tables.setdefault(current, Settings())
            tables[current].end = number + 1
            continue
        setting = SETTING_LINE.match(line)
        if setting is not None:
            tables[current].names.add(setting[1])
        if line.strip():
            tables[current].end = number + 1
    return tables


def _template_blocks(template: str) -> list[tuple[str, str, list[str]]]:
    """Return each setting of the shipped file: its table, its name, and its lines.

    The lines of a setting are the comment that explains it and the setting itself.
    """
    blocks: list[tuple[str, str, list[str]]] = []
    current, pending = "", []
    for line in template.splitlines():
        table = TABLE_LINE.match(line)
        setting = SETTING_LINE.match(line)
        if table is not None:
            current, pending = table[1], []
        elif setting is not None and current:
            blocks.append((current, setting[1], [*pending, line]))
            pending = []
        elif line.strip():
            pending.append(line)
        else:
            pending = []
    return blocks


def _set(text: str) -> dict[str, dict[str, object]]:
    """Return what a settings file sets, table by table, leaving out tables that set nothing."""
    return {name: table for name, table in tomllib.loads(text).items() if table}


def with_new_settings(current: str, template: str) -> tuple[str, list[str]]:
    """Return a settings file with the settings it lacks put in, and their names.

    Nothing that is in the file is changed or moved: not a value, not a comment. A
    setting of this version that the file does not have, set or commented out, is put
    at the end of its table as the shipped file has it, commented out at its default.
    A table the file does not have is put at the end. What the file sets must be the
    same afterwards, or nothing is returned but an error.
    """
    lines = current.splitlines()
    tables = _tables(lines)
    added: list[str] = []
    inserts: dict[int, list[str]] = {}
    new_tables: dict[str, list[str]] = {}
    for table, name, block in _template_blocks(template):
        if table not in tables:
            # The whole table is new: it goes at the end, under its heading.
            after = new_tables.setdefault(table, [f"[{table}]"])
            after.extend(block if len(after) == 1 else ["", *block])
        elif name not in tables[table].names:
            inserts.setdefault(tables[table].end, []).extend(["", *block])
        else:
            continue
        added.append(f"{table}.{name}")
    if not added:
        return current, []
    merged: list[str] = []
    for number, line in enumerate(lines):
        merged.extend(inserts.get(number, []))
        merged.append(line)
    merged.extend(inserts.get(len(lines), []))
    for block in new_tables.values():
        while merged and not merged[-1].strip():
            merged.pop()
        merged.extend(["", *block])
    text = "\n".join(merged).rstrip("\n") + "\n"
    try:
        same = _set(text) == _set(current)
    except tomllib.TOMLDecodeError as error:
        raise SetupError(
            f"{SETTINGS} is not well-formed TOML ({error}), and was left as it is"
        ) from None
    if not same:
        raise SetupError(
            f"putting the new settings into {SETTINGS} would have changed what it sets, "
            "so it was left as it is. Please report this."
        )
    return text, added


def self_signed_site(ipv6: bool) -> str:
    """Return the site that --self-signed writes: port 443, a throwaway certificate."""
    warning = "\n".join(f"# {line}" for line in SELF_SIGNED_WARNING.splitlines())
    listen_v6 = "    listen [::]:443 ssl;\n" if ipv6 else ""
    return (
        f"{SELF_SIGNED_MARK}\n"
        f"{warning}\n"
        "# hirdir-setup --remove takes it away again.\n"
        "server {\n"
        "    listen 443 ssl;\n"
        f"{listen_v6}"
        "    server_name _;\n"
        f"    ssl_certificate     {SELF_SIGNED_DIR}/cert.pem;\n"
        f"    ssl_certificate_key {SELF_SIGNED_DIR}/key.pem;\n"
        f"    include {INCLUDE};\n"
        "}\n"
    )


def diff(path: str, before: str | None, after: str | None) -> str:
    """Return the change to one file as a unified diff."""
    return "".join(
        difflib.unified_diff(
            (before or "").splitlines(keepends=True),
            (after or "").splitlines(keepends=True),
            fromfile=path if before is not None else "/dev/null",
            tofile=path if after is not None else "/dev/null",
        )
    )


def choose_server(servers: Sequence[Server], site: str | None) -> Server | None:
    """Pick the server block to edit when it can be picked without asking.

    Returns None when the operator must be asked. site is what --site was given: a file
    as nginx names it, the file a link points to, or either followed by ":LINE".
    """
    if not servers:
        raise SetupError(
            "no nginx site listens with ssl. Add TLS to a site first, then run this again. "
            "In a test container only, hirdir-setup --self-signed creates such a site."
        )
    if site is None:
        return servers[0] if len(servers) == 1 else None
    name, _, number = site.rpartition(":") if re.search(r":\d+$", site) else (site, "", "")
    wanted = {name, os.path.realpath(name)}
    matches = [
        server
        for server in servers
        if (server.file in wanted or os.path.realpath(server.file) in wanted)
        and (not number or server.line == int(number))
    ]
    if len(matches) == 1:
        return matches[0]
    listing = "\n".join(f"    {server.label()}" for server in matches or servers)
    if not matches:
        raise SetupError(
            f"no server block that listens with ssl is in {site}. There are:\n{listing}"
        )
    raise SetupError(
        f"{name} holds more than one server block that listens with ssl. "
        f"Name one as --site FILE:LINE:\n{listing}"
    )


# ---- the host: reading, asking, writing ----------------------------------------------


@dataclass
class Change:
    """One file to write (after is text), or to remove (after is None)."""

    path: Path
    before: str | None
    after: str | None


@dataclass
class Plan:
    """Everything one run will do to the host, worked out before any of it is done."""

    changes: list[Change] = field(default_factory=list)
    links: list[tuple[Path, Path]] = field(default_factory=list)  # (link, target) to create
    unlinks: list[tuple[Path, Path]] = field(default_factory=list)  # (link, target) to remove
    certificate: bool = False  # Whether to create the throwaway certificate.

    def empty(self) -> bool:
        """Say whether there is nothing to do."""
        return not (self.changes or self.links or self.unlinks or self.certificate)

    def show(self) -> None:
        """Print what will be done: a diff for each file, a line for anything else."""
        for link, _ in self.unlinks:
            print(f"remove the link {link}")
        for change in self.changes:
            print(diff(str(change.path), change.before, change.after), end="")
        for link, target in self.links:
            print(f"link {link} -> {target}")
        if self.certificate:
            print(f"create a throwaway self-signed certificate in {SELF_SIGNED_DIR}")


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    # Every caller passes a fixed program path and arguments that this file builds.
    return subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603


def loaded_files() -> dict[str, str]:
    """Return the configuration files nginx loads, each with its text as it is on disk."""
    if not Path(NGINX).is_file():
        raise SetupError("nginx is not installed. Install it first: sudo apt install nginx")
    result = _run([NGINX, "-T"])
    if result.returncode != 0:
        raise SetupError(
            "nginx does not accept its configuration as it is now. "
            f"Put that right first:\n{result.stderr.strip()}"
        )
    files: dict[str, str] = {}
    for path, dumped in split_dump(result.stdout).items():
        try:
            files[path] = Path(path).read_text(encoding="utf-8")
        except OSError:
            files[path] = dumped
    return files


def _write(path: Path, text: str) -> None:
    """Replace path with text in one step, keeping the owner and mode of an existing file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
        if path.exists():
            status = path.stat()
            os.chown(temporary, status.st_uid, status.st_gid)
            os.chmod(temporary, status.st_mode & 0o7777)
        else:
            os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)
        raise


def _put(path: Path, text: str | None) -> None:
    if text is None:
        path.unlink(missing_ok=True)
    else:
        _write(path, text)


def _make_certificate() -> None:
    """Create the throwaway key and certificate of the --self-signed site."""
    SELF_SIGNED_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    command = [OPENSSL, "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256"]
    command += ["-nodes", "-days", "30", "-subj", "/CN=hirdir self-signed test certificate"]
    command += ["-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1"]
    command += ["-keyout", str(SELF_SIGNED_DIR / "key.pem")]
    command += ["-out", str(SELF_SIGNED_DIR / "cert.pem")]
    result = _run(command)
    if result.returncode != 0:
        raise SetupError(f"openssl could not create a certificate:\n{result.stderr.strip()}")
    (SELF_SIGNED_DIR / "key.pem").chmod(0o600)


def _remove_certificate() -> None:
    for name in ("cert.pem", "key.pem"):
        (SELF_SIGNED_DIR / name).unlink(missing_ok=True)
    with contextlib.suppress(OSError):
        SELF_SIGNED_DIR.rmdir()


def _reload_nginx() -> str:
    """Make nginx take up its configuration, and say what was done."""
    if Path("/run/systemd/system").is_dir():
        if _run([SYSTEMCTL, "is-active", "--quiet", "nginx.service"]).returncode != 0:
            return "nginx is not running. Start it with: sudo systemctl start nginx"
        result = _run([SYSTEMCTL, "reload", "nginx.service"])
    else:
        result = _run([NGINX, "-s", "reload"])
    if result.returncode != 0:
        return f"nginx was not reloaded:\n{result.stderr.strip()}"
    return "nginx was reloaded."


def _confirm(question: str, yes: bool) -> bool:
    if yes:
        return True
    if not sys.stdin.isatty():
        raise SetupError("nothing was changed. Run it again with --yes to make this change.")
    return input(f"{question} [y/N] ").strip().lower() in {"y", "yes"}


def _ask_server(servers: Sequence[Server], yes: bool) -> Server:
    listing = "\n".join(f"  {number}. {s.label()}" for number, s in enumerate(servers, 1))
    if yes or not sys.stdin.isatty():
        raise SetupError(
            "more than one site listens with ssl. Name one as --site FILE or "
            f"--site FILE:LINE:\n{listing}"
        )
    print(f"These server blocks listen with ssl:\n{listing}")
    answer = input("Add hirdir to which one? Give its number: ").strip()
    if not answer.isdigit() or not 1 <= int(answer) <= len(servers):
        raise SetupError("nothing was changed: that is not one of the numbers listed.")
    return servers[int(answer) - 1]


def _apply(plan: Plan) -> None:
    """Do what the plan says, test it with nginx, and put everything back if it objects."""
    unlinked: list[tuple[Path, Path]] = []
    linked: list[Path] = []
    made_certificate = False
    try:
        if plan.certificate:
            _make_certificate()
            made_certificate = True
        # Links go before their files, so that nginx never sees a link to nothing.
        for link, target in plan.unlinks:
            link.unlink(missing_ok=True)
            unlinked.append((link, target))
        for change in plan.changes:
            _put(change.path, change.after)
        for link, target in plan.links:
            link.symlink_to(target)
            linked.append(link)
        result = _run([NGINX, "-t"])
        if result.returncode != 0:
            raise SetupError(
                "nginx refused the new configuration, so every file was put back as it was. "
                f"nginx said:\n{result.stderr.strip()}"
            )
    except BaseException:
        for link in linked:
            link.unlink(missing_ok=True)
        for change in plan.changes:
            _put(change.path, change.before)
        for link, target in unlinked:
            link.symlink_to(target)
        if made_certificate:
            _remove_certificate()
        raise


def _plan_add(args: argparse.Namespace) -> Plan:
    """Work out what adding hirdir to a site must change. Nothing is written here."""
    plan = Plan()
    files = loaded_files()

    if args.prefix is not None:
        before = SNIPPET.read_text(encoding="utf-8")
        after = with_prefix(before, normalise_prefix(args.prefix))
        if after != before:
            plan.changes.append(Change(SNIPPET, before, after))

    if args.self_signed:
        if not SELF_SIGNED_LINK.parent.is_dir():
            raise SetupError(
                f"--self-signed needs {SELF_SIGNED_LINK.parent}, which Ubuntu's nginx has."
            )
        site = self_signed_site(ipv6=Path("/proc/net/if_inet6").is_file())
        before = (
            SELF_SIGNED_SITE.read_text(encoding="utf-8") if SELF_SIGNED_SITE.is_file() else None
        )
        if before != site:
            plan.changes.append(Change(SELF_SIGNED_SITE, before, site))
        if not SELF_SIGNED_LINK.is_symlink():
            plan.links.append((SELF_SIGNED_LINK, SELF_SIGNED_SITE))
        plan.certificate = not all(
            (SELF_SIGNED_DIR / name).is_file() for name in ("cert.pem", "key.pem")
        )
        return plan

    servers = tls_servers(files)
    if args.site is None and any(server.included for server in servers):
        return plan
    server = choose_server(servers, args.site) or _ask_server(servers, args.yes)
    if not server.included:
        before = files[server.file]
        path = Path(os.path.realpath(server.file))
        plan.changes.append(Change(path, before, add_include(before, server)))
    return plan


def _plan_remove() -> Plan:
    """Work out what taking hirdir out of nginx must change. Nothing is written here."""
    plan = Plan()
    seen: set[Path] = set()
    for name, before in loaded_files().items():
        path = Path(os.path.realpath(name))
        if path in seen or path == SELF_SIGNED_SITE:
            continue
        seen.add(path)
        after = remove_include(before)
        if after != before:
            plan.changes.append(Change(path, before, after))
    if SELF_SIGNED_SITE.is_file():
        site = SELF_SIGNED_SITE.read_text(encoding="utf-8")
        if site.startswith(SELF_SIGNED_MARK):
            if SELF_SIGNED_LINK.is_symlink():
                plan.unlinks.append((SELF_SIGNED_LINK, SELF_SIGNED_SITE))
            plan.changes.append(Change(SELF_SIGNED_SITE, site, None))
    return plan


def _remove(args: argparse.Namespace) -> int:
    plan = _plan_remove()
    if plan.empty():
        print("Nothing to change: no nginx site includes hirdir.")
        return 0
    plan.show()
    if not _confirm("Take hirdir out of nginx as shown?", args.yes):
        print("Nothing was changed.")
        return 1
    _apply(plan)
    if any(change.path == SELF_SIGNED_SITE for change in plan.changes):
        _remove_certificate()
    print(f"hirdir is no longer in any nginx site. {_reload_nginx()}")
    return 0


def _renew(args: argparse.Namespace) -> int:
    """Write the snippet as this version of the package ships it, keeping its prefix.

    nginx is asked whether it accepts the result, and is reloaded when a site includes
    the snippet. Where nginx is not installed the file is written all the same, for the
    day it is.
    """
    if not TEMPLATE.is_file():
        raise SetupError(f"{TEMPLATE} does not exist. Is the hirdir package installed?")
    template = TEMPLATE.read_text(encoding="utf-8")
    before = SNIPPET.read_text(encoding="utf-8") if SNIPPET.is_file() else None
    after = renewed(before, template, args.prefix)
    prefix = snippet_prefix(after)
    where = "/" if prefix == "/" else f"{prefix}/"
    if after == before:
        print(f"Nothing to change: {SNIPPET} is as this version of hirdir ships it, for {where}")
        return 0
    plan = Plan(changes=[Change(SNIPPET, before, after)])
    plan.show()
    if not _confirm("Write the snippet as shown?", args.yes):
        print("Nothing was changed.")
        return 1
    done = f"{SNIPPET} is now as this version of hirdir ships it, for {where}."
    if not Path(NGINX).is_file():
        _put(SNIPPET, after)
        print(f"{done} nginx is not installed, so nothing was reloaded.")
        return 0
    try:
        files = loaded_files()
    except SetupError:
        if before is not None:
            raise
        # A snippet that is new is in no site yet, so it cannot be what nginx objects to.
        _put(SNIPPET, after)
        print(f"{done} nginx does not accept its configuration as it is now, for other reasons.")
        return 0
    _apply(plan)
    if args.no_reload:
        print(done)
    elif str(SNIPPET) in files:
        print(f"{done} {_reload_nginx()}")
    else:
        print(f"{done} No site includes it yet. To add hirdir to one: sudo hirdir-setup")
    return 0


def _settings(args: argparse.Namespace) -> int:
    """Bring the settings file up to date with this version, changing nothing it sets."""
    if not SETTINGS_TEMPLATE.is_file():
        raise SetupError(f"{SETTINGS_TEMPLATE} does not exist. Is the hirdir package installed?")
    template = SETTINGS_TEMPLATE.read_text(encoding="utf-8")
    if not SETTINGS.is_file():
        _write(SETTINGS, template)
        print(f"{SETTINGS} was written: every setting is in it, commented out at its default.")
        return 0
    before = SETTINGS.read_text(encoding="utf-8")
    try:
        after, added = with_new_settings(before, template)
    except tomllib.TOMLDecodeError as error:
        raise SetupError(
            f"{SETTINGS} is not well-formed TOML ({error}), and was left as it is"
        ) from None
    if not added:
        print(f"Nothing to change: {SETTINGS} has every setting of this version of hirdir.")
        return 0
    print(diff(str(SETTINGS), before, after), end="")
    if not _confirm("Put these settings into the file, commented out?", args.yes):
        print("Nothing was changed.")
        return 1
    kept = SETTINGS.with_name(f"{SETTINGS.name}.{time.strftime('%Y%m%dT%H%M%S')}.bak")
    _write(kept, before)
    os.chmod(kept, SETTINGS.stat().st_mode & 0o7777)
    _write(SETTINGS, after)
    print(
        f"{SETTINGS} has the new settings of this version, commented out at their defaults: "
        f"{', '.join(added)}. Nothing you set was changed. The file as it was is {kept}."
    )
    return 0


def _field(package: Path, name: str) -> str:
    return _run([DPKG_DEB, "--field", str(package), name]).stdout.strip()


def _upgrade(args: argparse.Namespace) -> int:
    """Install a newer package of hirdir with apt, with no question left to answer.

    The package does the work of an upgrade itself: it backs the database up, brings the
    schema, the settings file and the nginx snippet up to date, and starts the service
    again. This checks that the file is what it should be and hands over to apt.
    """
    package = Path(args.upgrade).resolve()
    if not package.is_file():
        raise SetupError(f"there is no file {package}")
    if _field(package, "Package") != "hirdir":
        raise SetupError(f"{package} is not a package of hirdir")
    new = _field(package, "Version")
    installed = _run([DPKG_QUERY, "--show", "--showformat", "${Version}", "hirdir"]).stdout.strip()
    older = subprocess.run([DPKG, "--compare-versions", new, "lt", installed], check=False)  # noqa: S603
    if installed and older.returncode == 0:
        raise SetupError(
            f"{package.name} is version {new}, older than the {installed} that is installed. "
            'Going back takes the steps in the documentation, under "Going back to the '
            'release before".'
        )
    checksum = package.with_name(package.name + ".sha256")
    if checksum.is_file():
        wanted = checksum.read_text(encoding="utf-8").split()[0]
        if hashlib.sha256(package.read_bytes()).hexdigest() != wanted:
            raise SetupError(f"{package.name} does not have the checksum in {checksum.name}")
        print(f"{package.name} has the checksum in {checksum.name}.")
    else:
        print(f"There is no {checksum.name} beside the package, so its checksum was not compared.")
    print(f"hirdir {installed or 'is not installed'} -> {new}")
    again = ["--reinstall"] if new == installed else []
    if again:
        print("That version is installed already: it is installed again.")
    print("The package backs the database up, brings the schema up to date, puts the new")
    print(f"settings of this version into {SETTINGS} without changing yours, writes the")
    print("nginx snippet under the prefix it has, and starts the service again.")
    if not _confirm("Go on?", args.yes):
        print("Nothing was changed.")
        return 1
    sys.stdout.flush()
    # apt takes over from here. This program is part of the package that is about to be
    # replaced, so it does nothing more once apt has begun.
    os.execve(  # noqa: S606 - a fixed program with the package's own path
        APT_GET,
        [
            APT_GET,
            "install",
            "--yes",
            *again,
            "-o",
            "Dpkg::Options::=--force-confdef",
            "-o",
            "Dpkg::Options::=--force-confold",
            str(package),
        ],
        {**os.environ, "DEBIAN_FRONTEND": "noninteractive"},
    )


def _add(args: argparse.Namespace) -> int:
    if not SNIPPET.is_file():
        raise SetupError(
            f"{SNIPPET} does not exist. Write it again with: sudo hirdir-setup --renew"
        )
    if args.self_signed:
        print(SELF_SIGNED_WARNING)
    plan = _plan_add(args)
    snippet = next((c.after for c in plan.changes if c.path == SNIPPET and c.after), None)
    prefix = snippet_prefix(snippet or SNIPPET.read_text(encoding="utf-8"))
    where = "/" if prefix == "/" else f"{prefix}/"
    if plan.empty():
        print(f"Nothing to change: hirdir is already served under {where}")
        return 0
    plan.show()
    if not _confirm("Make these changes?", args.yes):
        print("Nothing was changed.")
        return 1
    _apply(plan)
    print(f"hirdir is served under {where} on the site. {_reload_nginx()}")
    return 0


def _arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="hirdir-setup",
        description="Add hirdir to an nginx site that already terminates TLS.",
        epilog="Every change is shown before it is made, and undone if nginx -t then fails.",
    )
    parser.add_argument(
        "--site",
        metavar="FILE",
        help="the site to add hirdir to, without asking; FILE:LINE names one server block",
    )
    parser.add_argument(
        "--prefix",
        metavar="/PATH",
        help="serve hirdir under this prefix, such as /inventory; / is the root of the site",
    )
    parser.add_argument(
        "--self-signed",
        action="store_true",
        help="for test containers only, not for production: create a site on port 443 "
        "with a throwaway self-signed certificate",
    )
    parser.add_argument("--yes", action="store_true", help="make the changes without asking")
    parser.add_argument("--remove", action="store_true", help="take hirdir out of nginx again")
    parser.add_argument(
        "--renew",
        action="store_true",
        help=f"write {SNIPPET} again as this version of hirdir ships it, keeping its "
        "prefix; the package does this itself when it is installed and at each upgrade",
    )
    parser.add_argument(
        "--settings",
        action="store_true",
        help=f"put the settings {SETTINGS} does not have yet into it, commented out at "
        "their defaults, changing nothing it sets; the package does this itself too",
    )
    parser.add_argument(
        "--upgrade",
        metavar="PACKAGE.deb",
        help="install this newer package of hirdir with apt, with no question to answer",
    )
    parser.add_argument(
        "--no-reload",
        action="store_true",
        help="with --renew: leave it to the caller to reload nginx, as the package's scripts do",
    )
    args = parser.parse_args(argv)
    if args.remove and (args.site or args.prefix or args.self_signed or args.renew):
        parser.error("--remove is used on its own, or with --yes")
    alone = [name for name in ("settings", "upgrade") if getattr(args, name)]
    others = args.site or args.prefix or args.self_signed or args.renew or args.remove
    if alone and (len(alone) > 1 or others or args.no_reload):
        parser.error(f"--{alone[0]} is used on its own, or with --yes")
    if args.renew and (args.site or args.self_signed):
        parser.error("--renew is used on its own, or with --prefix, --no-reload and --yes")
    if args.no_reload and not args.renew:
        parser.error("--no-reload goes with --renew")
    if args.self_signed and args.site:
        parser.error("--self-signed creates its own site; leave --site out")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    """Run hirdir-setup and return its exit status."""
    args = _arguments(argv)
    if os.geteuid() != 0:
        print("hirdir-setup: run this as root: sudo hirdir-setup", file=sys.stderr)
        return 1
    try:
        if args.remove:
            return _remove(args)
        if args.settings:
            return _settings(args)
        if args.upgrade:
            return _upgrade(args)
        return _renew(args) if args.renew else _add(args)
    except SetupError as error:
        # What was shown so far comes first, also when the output is not a terminal.
        sys.stdout.flush()
        print(f"hirdir-setup: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nhirdir-setup: stopped.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
