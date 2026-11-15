"""Move every npm dependency of the web UI to its latest production release, saved exact.

`make upgrade` runs this in place of a downloaded upgrade tool: it asks the registry,
through the npm that builds the web UI, for the `latest` release of each package that
`web/package.json` names, and writes the ones that are behind into `web/package.json`,
exact. `make upgrade` then runs `npm install` once, so that the dependencies and the
development dependencies are resolved together. A `latest` that is a pre-release is
left alone and said so. Nothing is fetched or run but the packages themselves.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"
PRODUCTION = re.compile(r"\d+\.\d+\.\d+")
SECTIONS = ("dependencies", "devDependencies")


def behind(manifest: dict, latest: dict[str, str]) -> dict[str, dict[str, str]]:
    """Return, for each section of the manifest, the version to move each package to.

    `latest` maps a package to the version its `latest` tag names. A package is moved
    when that version is a production release and differs from the one saved.
    """
    moves: dict[str, dict[str, str]] = {}
    for section in SECTIONS:
        for name, saved in sorted(manifest.get(section, {}).items()):
            version = latest.get(name)
            if version is None or not PRODUCTION.fullmatch(version) or version == saved:
                continue
            moves.setdefault(section, {})[name] = version
    return moves


def moved(manifest: dict, moves: dict[str, dict[str, str]]) -> dict:
    """Return the manifest with each package that is behind at its latest release."""
    return {
        key: {**value, **moves[key]} if key in moves else value for key, value in manifest.items()
    }


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
    """Ask the registry for each package's latest release, and write those that are
    behind into `web/package.json`."""
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
    for packages in moves.values():
        print("moving", " ".join(f"{name}@{version}" for name, version in packages.items()))
    path = WEB / "package.json"
    path.write_text(json.dumps(moved(manifest, moves), indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
