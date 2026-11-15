"""Move every npm dependency of the web UI to its latest production release, saved exact.

`make upgrade` runs this in place of a downloaded upgrade tool: it asks the registry,
through the npm that builds the web UI, for the `latest` release of each package that
`web/package.json` names, and installs the ones that are behind with `--save-exact`.
A `latest` that is a pre-release is left alone and said so. Nothing is fetched or run
but the packages themselves.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"
PRODUCTION = re.compile(r"\d+\.\d+\.\d+")
SECTIONS = {"dependencies": "--save-prod", "devDependencies": "--save-dev"}


def behind(manifest: dict, latest: dict[str, str]) -> dict[str, list[str]]:
    """Return, for each npm save flag, the `name@version` of each package to move.

    `latest` maps a package to the version its `latest` tag names. A package is moved
    when that version is a production release and differs from the one saved.
    """
    moves: dict[str, list[str]] = {}
    for section, flag in SECTIONS.items():
        for name, saved in sorted(manifest.get(section, {}).items()):
            version = latest.get(name)
            if version is None or not PRODUCTION.fullmatch(version) or version == saved:
                continue
            moves.setdefault(flag, []).append(f"{name}@{version}")
    return moves


def prereleases(manifest: dict, latest: dict[str, str]) -> list[str]:
    """Return the packages whose `latest` tag names something that is not a release."""
    names = [name for section in SECTIONS for name in manifest.get(section, {})]
    return sorted(
        f"{name}@{latest[name]}"
        for name in names
        if name in latest and not PRODUCTION.fullmatch(latest[name])
    )


def _npm(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - npm with fixed arguments and package names
        ["npm", "--prefix", str(WEB), *args],  # noqa: S607 - the npm on the PATH builds the UI
        capture_output=True,
        text=True,
        check=False,
    )


def _latest(name: str) -> str | None:
    result = _npm("view", f"{name}@latest", "version", "--json")
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        return None
    value = json.loads(result.stdout or "null")
    return value if isinstance(value, str) else None


def main() -> int:
    """Ask the registry for each package's latest release and install those behind."""
    manifest = json.loads((WEB / "package.json").read_text(encoding="utf-8"))
    names = sorted({name for section in SECTIONS for name in manifest.get(section, {})})
    latest: dict[str, str] = {}
    for name in names:
        version = _latest(name)
        if version is None:
            print(f"the registry gave no latest release of {name}", file=sys.stderr)
            return 1
        latest[name] = version
    for held in prereleases(manifest, latest):
        print(f"left as it is, latest is not a production release: {held}")
    moves = behind(manifest, latest)
    if not moves:
        print("every npm dependency is at its latest release")
        return 0
    for flag, packages in moves.items():
        print("moving", " ".join(packages))
        result = _npm("install", "--save-exact", flag, *packages)
        if result.returncode != 0:
            print(result.stdout, result.stderr, sep="\n", file=sys.stderr)
            return result.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
