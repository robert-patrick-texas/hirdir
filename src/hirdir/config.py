"""Configuration: /etc/hirdir/config.toml and its defaults.

Every key is optional. A missing file is the same as an empty one.
"""

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PATH = Path("/etc/hirdir/config.toml")
DEFAULT_STATE_DIR = Path("/var/lib/hirdir")


@dataclass(frozen=True)
class Config:
    """The settings of one installation that are fixed while the server runs."""

    listen: str = "127.0.0.1:8715"
    trusted_proxies: tuple[str, ...] = ("127.0.0.1", "::1")
    state_dir: Path = DEFAULT_STATE_DIR
    database_url: str = ""
    session_hours: int = 12
    sign_in_failures_before_delay: int = 5
    backup_keep: int = 14
    max_file_megabytes: int = 20
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


def load(path: Path | None = None) -> Config:
    """Read the configuration file at path.

    A relative state_dir is taken from the directory of the file, which is how a
    development server keeps its state beside its configuration.
    """
    path = path or config_path()
    data: dict = {}
    if path.is_file():
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    server = data.get("server", {})
    access = data.get("access", {})
    state_dir = path.parent / server.get("state_dir", DEFAULT_STATE_DIR)
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
        source=path if path.is_file() else None,
    )
