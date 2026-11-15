"""The configuration file that the application writes, and the two copies of it that
are kept: the file the package ships, and the block on the architecture page."""

import re
import stat
import tomllib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hirdir import config
from hirdir.cli.main import app

ROOT = Path(__file__).resolve().parents[2]
SHIPPED = ROOT / "packaging" / "config.toml"
ARCHITECTURE = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")

runner = CliRunner()


def _written(*options: str) -> str:
    result = runner.invoke(app, ["admin", "config", *options])
    assert result.exit_code == 0, result.output
    return result.stdout


def _defaults() -> dict[str, dict[str, object]]:
    found: dict[str, dict[str, object]] = {}
    for key in config.KEYS:
        found.setdefault(key.section, {})[key.name] = key.default
    return found


def _uncommented(text: str) -> dict[str, dict[str, object]]:
    return tomllib.loads(re.sub(r"^# (\w+ = )", r"\1", text, flags=re.MULTILINE))


def test_the_shipped_file_is_what_the_command_writes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HIRDIR_CONFIG", str(tmp_path / "none.toml"))
    written = _written()
    assert written == SHIPPED.read_text(encoding="utf-8"), (
        "packaging/config.toml is not what `hirdir admin config` writes: "
        "run `uv run hirdir admin config --output packaging/config.toml --force`"
    )
    # Every key is in it, commented out at its default, each with what it is for.
    assert all(not table for table in tomllib.loads(written).values())
    assert _uncommented(written) == _defaults()
    for key in config.KEYS:
        assert f"# {key.description.splitlines()[-1]}\n# {key.name} = " in written, key.name
    assert '[upgrades]\n# "hirdir-setup --check"' in written
    assert written.endswith('# proxy = ""\n')


def test_the_architecture_page_holds_the_same_keys_and_defaults() -> None:
    documented = re.search(r"## Configuration.*?```toml\n(.*?)```", ARCHITECTURE, re.DOTALL)
    assert documented is not None
    assert tomllib.loads(documented.group(1)) == _defaults()


def test_the_defaults_of_the_service_are_those_of_the_file() -> None:
    assert config.load(SHIPPED) == config.Config()
    assert config.Config().session_hours == config.default("access", "session_hours")
    with pytest.raises(KeyError):
        config.default("server", "no_such_key")


def test_current_sets_what_the_file_in_force_sets(tmp_path: Path, monkeypatch) -> None:
    present = tmp_path / "config.toml"
    present.write_text(
        '[server]\nlisten = "192.0.2.10:9000"\ntrusted_proxies = ["192.0.2.1"]\n'
        '[access]\nsession_hours = 8\nold_key = "kept"\n'
        "[ours]\nnote = 1\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HIRDIR_CONFIG", str(present))
    written = _written("--current")
    assert tomllib.loads(written) == {
        "server": {"listen": "192.0.2.10:9000", "trusted_proxies": ["192.0.2.1"]},
        "database": {},
        "access": {"session_hours": 8, "old_key": "kept"},
        "backup": {},
        "files": {},
        "upgrades": {},
        "ours": {"note": 1},
    }
    assert "# sign_in_failures_before_delay = 5" in written
    assert f"# {config.NOT_READ}\nold_key = " in written
    # What it does not set is there to set, as in the file the package ships.
    assert _uncommented(written)["backup"] == {"keep": 14}
    # A file that sets nothing is the shipped file.
    present.write_text("[server]\n", encoding="utf-8")
    assert _written("--current") == SHIPPED.read_text(encoding="utf-8")


def test_current_of_a_file_that_is_not_toml_is_refused(tmp_path: Path, monkeypatch) -> None:
    present = tmp_path / "config.toml"
    present.write_text("[server\n", encoding="utf-8")
    monkeypatch.setenv("HIRDIR_CONFIG", str(present))
    result = runner.invoke(app, ["admin", "config", "--current"])
    assert result.exit_code == 1
    assert "cannot be read" in result.output


def test_output_is_not_written_over_without_force(tmp_path: Path, monkeypatch) -> None:
    present = tmp_path / "config.toml"
    present.write_text('[upgrades]\nproxy = "http://user:secret@proxy.example.com:2025/"\n')
    present.chmod(0o640)
    monkeypatch.setenv("HIRDIR_CONFIG", str(present))
    target = tmp_path / "config.toml.new"
    result = runner.invoke(app, ["admin", "config", "--output", str(target)])
    assert result.exit_code == 0, result.output
    assert target.read_text(encoding="utf-8") == SHIPPED.read_text(encoding="utf-8")
    again = runner.invoke(app, ["admin", "config", "--current", "--output", str(target)])
    assert again.exit_code == 1
    assert "--force" in again.output
    assert target.read_text(encoding="utf-8") == SHIPPED.read_text(encoding="utf-8")
    forced = runner.invoke(
        app, ["admin", "config", "--current", "--output", str(target), "--force"]
    )
    assert forced.exit_code == 0, forced.output
    assert tomllib.loads(target.read_text(encoding="utf-8"))["upgrades"] == {
        "proxy": "http://user:secret@proxy.example.com:2025/"
    }
    # It may hold a password: it is no easier to read than the file it was read from.
    assert stat.S_IMODE(target.stat().st_mode) == 0o640


def test_toml_values_are_written_as_toml_reads_them() -> None:
    values = {
        "text": 'a "quoted" \\ value\twith ünïcode',
        "number": 12,
        "share": 0.5,
        "flag": False,
        "list": ["127.0.0.1", "::1"],
        "table": {"a key": 1, "b": [True]},
    }
    line = "\n".join(f"{name} = {config.toml_value(value)}" for name, value in values.items())
    assert tomllib.loads(line) == values
