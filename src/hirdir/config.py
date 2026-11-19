"""Configuration: /etc/hirdir/config.toml and its defaults.

Every key is optional. A missing file is the same as an empty one. Each key is named
once, in `KEYS`, with its default and its description: the defaults of `Config` are
read from there, and so is the file that `hirdir admin config` writes, which is the
file the package ships.
"""

import json
import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

DEFAULT_PATH = Path("/etc/hirdir/config.toml")
DEFAULT_STATE_DIR = Path("/var/lib/hirdir")
# The largest limit a site may set for a reference file, in megabytes (P-159).
MOST_REFERENCE_MEGABYTES = 2048


@dataclass(frozen=True)
class Key:
    """One key of the configuration file: its table, its default, and what it is for."""

    section: str
    name: str
    default: Any
    # The comment above the key, as the file has it, line for line.
    description: str


_LISTEN = """\
The address and port the service listens on. nginx reaches it here: keep
/etc/nginx/conf.d/hirdir.conf in step."""
_TRUSTED_PROXIES = """\
The addresses whose X-Forwarded-* headers are believed. Only the proxy belongs here."""
_STATE_DIR = """\
Where the database, the signing key and the backups are kept. The systemd units
let the service write to /var/lib/hirdir and nowhere else, so a change here needs
the same change to ReadWritePaths in a drop-in for hirdir.service,
hirdir-worker.service and hirdir-backup.service. A relative path is taken from this
file's directory."""
_URL = """\
The database, as a SQLAlchemy URL. Left out, hirdir.db in the state directory."""
_SESSION_HOURS = """\
How long a session lasts before the user signs in again."""
_FAILURES = """\
How many wrong access codes in a row are answered at once. The next ones are delayed."""
_KEEP = """\
How many of the newest backups "hirdir admin backup" keeps in /var/lib/hirdir/backups."""
_MAX_MEGABYTES = """\
The largest file an import takes, in megabytes, and the largest body of any request
but the upload of a reference file. "sudo hirdir-setup --renew" gives nginx the
larger of this and max_reference_megabytes, as client_max_body_size in
/etc/nginx/snippets/hirdir.conf."""
_MAX_REFERENCE_MEGABYTES = """\
The largest reference file, a photograph, a floor plan or a vendor's guide, in
megabytes, from 1 to 2048. Run "sudo hirdir-setup --renew" after a change, so that
nginx lets as much through."""
_PROXY = """\
"hirdir-setup --check" and "hirdir-setup --upgrade" ask GitHub for the latest release,
and so does hirdir-upgrade.timer each night where a site has turned it on. Where the
way out is through a proxy, name it here, as in "http://proxy.example.com:2025/". It
is used whenever --proxy is not given. Every user of the host can read this file: for
a proxy that takes a password, first make the file readable by root and the hirdir
group alone (chgrp hirdir and chmod 640)."""

KEYS: tuple[Key, ...] = (
    Key("server", "listen", "127.0.0.1:8715", _LISTEN),
    Key("server", "trusted_proxies", ["127.0.0.1", "::1"], _TRUSTED_PROXIES),
    Key("server", "state_dir", str(DEFAULT_STATE_DIR), _STATE_DIR),
    Key("database", "url", f"sqlite:///{DEFAULT_STATE_DIR / 'hirdir.db'}", _URL),
    Key("access", "session_hours", 12, _SESSION_HOURS),
    Key("access", "sign_in_failures_before_delay", 5, _FAILURES),
    Key("backup", "keep", 14, _KEEP),
    Key("files", "max_megabytes", 20, _MAX_MEGABYTES),
    Key("files", "max_reference_megabytes", 100, _MAX_REFERENCE_MEGABYTES),
    # Read by hirdir-setup, and not by the service.
    Key("upgrades", "proxy", "", _PROXY),
)


def default(section: str, name: str) -> Any:
    """Return the default of one key."""
    for key in KEYS:
        if (key.section, key.name) == (section, name):
            return key.default
    raise KeyError(f"{section}.{name}")


@dataclass(frozen=True)
class Config:
    """The settings of one installation that are fixed while the server runs."""

    listen: str = default("server", "listen")
    trusted_proxies: tuple[str, ...] = tuple(default("server", "trusted_proxies"))
    state_dir: Path = DEFAULT_STATE_DIR
    database_url: str = ""
    session_hours: int = default("access", "session_hours")
    sign_in_failures_before_delay: int = default("access", "sign_in_failures_before_delay")
    backup_keep: int = default("backup", "keep")
    max_file_megabytes: int = default("files", "max_megabytes")
    max_reference_megabytes: int = default("files", "max_reference_megabytes")
    source: Path | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        if not self.database_url:
            url = f"sqlite:///{(self.state_dir / 'hirdir.db').resolve()}"
            object.__setattr__(self, "database_url", url)

    @property
    def secret_key_path(self) -> Path:
        """Where the key that signs session tokens is kept."""
        return self.state_dir / "secret.key"

    @property
    def max_file_bytes(self) -> int:
        """The largest file an import takes, and so the largest body of a request."""
        return self.max_file_megabytes * 1024 * 1024

    @property
    def max_reference_bytes(self) -> int:
        """The largest reference file, and so the largest body of an upload of one."""
        return self.max_reference_megabytes * 1024 * 1024

    @property
    def files_dir(self) -> Path:
        """Where the content of reference files is kept, beside the database (P-161)."""
        return self.state_dir / "files"

    @property
    def backup_dir(self) -> Path:
        """Where `hirdir admin backup` writes."""
        return self.state_dir / "backups"

    @property
    def database_path(self) -> Path | None:
        """The SQLite file, or None when the database is not SQLite."""
        prefix = "sqlite:///"
        if self.database_url.startswith(prefix):
            return Path(self.database_url[len(prefix) :])
        return None

    @property
    def host_port(self) -> tuple[str, int]:
        """The listen address split into host and port."""
        host, _, port = self.listen.rpartition(":")
        return host.strip("[]"), int(port)


def config_path() -> Path:
    """Return the configuration file in force: HIRDIR_CONFIG, or the default."""
    return Path(os.environ.get("HIRDIR_CONFIG", DEFAULT_PATH))


def read(path: Path) -> dict[str, Any]:
    """Return what the file at path sets, table by table. A missing file sets nothing."""
    if not path.is_file():
        return {}
    with path.open("rb") as handle:
        return tomllib.load(handle)


def load(path: Path | None = None) -> Config:
    """Read the configuration file at path.

    A relative state_dir is taken from the directory of the file, which is how a
    development server keeps its state beside its configuration.
    """
    path = path or config_path()
    data = read(path)
    server = data.get("server", {})
    access = data.get("access", {})
    state_dir = path.parent / server.get("state_dir", default("server", "state_dir"))
    return Config(
        listen=server.get("listen", Config.listen),
        trusted_proxies=tuple(server.get("trusted_proxies", Config.trusted_proxies)),
        state_dir=state_dir,
        database_url=data.get("database", {}).get("url", ""),
        session_hours=int(access.get("session_hours", Config.session_hours)),
        sign_in_failures_before_delay=int(
            access.get("sign_in_failures_before_delay", Config.sign_in_failures_before_delay)
        ),
        backup_keep=int(data.get("backup", {}).get("keep", Config.backup_keep)),
        max_file_megabytes=max(
            1, int(data.get("files", {}).get("max_megabytes", Config.max_file_megabytes))
        ),
        max_reference_megabytes=min(
            MOST_REFERENCE_MEGABYTES,
            max(
                1,
                int(
                    data.get("files", {}).get(
                        "max_reference_megabytes", Config.max_reference_megabytes
                    )
                ),
            ),
        ),
        source=path if path.is_file() else None,
    )


# --- the file the application writes -------------------------------------------------

_HEADER = """\
Configuration of hirdir. Every key is optional, and each one below is commented out
and shows its default. To change a value, remove the "# " in front of the key, edit
it, and restart the service:"""
_HEADER_OF_CURRENT = """\
Configuration of hirdir. Every key is optional. A key this file sets is set below,
and every other one is commented out and shows its default. To change a value,
remove the "# " in front of a key, edit it, and restart the service:"""
_FOOTER = """
    sudo systemctl restart hirdir

Values that people change in the course of work are settings in the database,
edited in the web UI by an Admin. They are not in this file."""
NOT_READ = "Not read by this version of hirdir:"


def toml_value(value: Any) -> str:
    """Return a value as TOML writes it."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, str):
        # A JSON string with nothing escaped that need not be is a TOML string too.
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(one) for one in value) + "]"
    if isinstance(value, Mapping):
        inner = ", ".join(f"{_name(name)} = {toml_value(one)}" for name, one in value.items())
        return "{ " + inner + " }" if inner else "{}"
    raise TypeError(f"TOML has no value for {value!r}")


def _name(name: str) -> str:
    """Return a key as TOML writes it: bare where it can be, quoted where it must be."""
    bare = bool(name) and all(char.isascii() and (char.isalnum() or char in "-_") for char in name)
    return name if bare else json.dumps(name, ensure_ascii=False)


def _comment(text: str) -> list[str]:
    return [f"# {line}".rstrip() for line in text.splitlines()]


def _unknown(given: Mapping[str, Any], known: set[str]) -> list[str]:
    """Return what a file sets that this version does not read, set as it was."""
    lines = [f"{_name(name)} = {toml_value(value)}" for name, value in given.items()]
    kept = [line for name, line in zip(given, lines, strict=True) if name not in known]
    return [f"# {NOT_READ}", *kept] if kept else []


def written(current: Mapping[str, Any] | None = None) -> str:
    """Return a complete configuration file: every key of every table, with its
    description, commented out at its default.

    With `current`, what a file sets, each key that it sets is set to its value, and
    what it sets that this version does not read is kept, set, at the end of its
    table, so that the file written in its place sets everything it did.
    """
    current = current or {}
    sets = any(value or not isinstance(value, Mapping) for value in current.values())
    lines = [*_comment(_HEADER_OF_CURRENT if sets else _HEADER), *_comment(_FOOTER)]
    loose = {name: value for name, value in current.items() if not isinstance(value, Mapping)}
    if loose:
        lines += ["", *_unknown(loose, set())]
    tables = list(dict.fromkeys(key.section for key in KEYS))
    tables += [name for name, value in current.items() if isinstance(value, Mapping)]
    for table in dict.fromkeys(tables):
        given = current.get(table, {})
        given = given if isinstance(given, Mapping) else {}
        lines += ["", f"[{_name(table)}]"]
        known = [key for key in KEYS if key.section == table]
        for place, key in enumerate(known):
            if place:
                lines.append("")
            lines += _comment(key.description)
            setting = f"{_name(key.name)} = {toml_value(given.get(key.name, key.default))}"
            lines.append(setting if key.name in given else f"# {setting}")
        unknown = _unknown(given, {key.name for key in known})
        if unknown:
            lines += ["", *unknown] if known else unknown
    return "\n".join(lines) + "\n"
