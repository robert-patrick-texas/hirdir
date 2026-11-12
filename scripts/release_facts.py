"""Print the two tables of a release's notes: its lines of code and its versions.

    make -s facts > /tmp/facts.md

Lines of code are counted by cloc in the files git tracks, and each language's code lines
are split by path into Product, Tests and Tooling. Lock files, generated files and Markdown
are left out of the table.

Versions are read from what was built, where that exists. With dist/hirdir_<version>_amd64.deb
present, the Python version, the Python packages and the SQLite version come from inside
the package. Without it they come from .python-version, uv.lock and the development
interpreter, and a line on standard error says so. Only the two sections go to standard
output, so that it can be pasted into the notes as it is.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
PROJECT = "hirdir"
CONTAINER_BASE = "ubuntu:26.04"
# The web UI's main packages: the name in package-lock.json and the name in the notes.
WEB_PACKAGES = (
    ("typescript", "TypeScript"),
    ("vite", "Vite"),
    ("react", "React"),
    ("ag-grid-community", "AG Grid Community"),
)


class FactsError(Exception):
    """A fact could not be read, and the message says which one."""


def note(message: str) -> None:
    """Tell the person running the script something, away from the tables."""
    print(f"release_facts: {message}", file=sys.stderr)


def run(*cmd: str, cwd: Path | None = None) -> str:
    """The standard output of a command, or FactsError when it is missing or fails."""
    try:
        done = subprocess.run(  # noqa: S603 every caller passes a fixed command, never input
            cmd, capture_output=True, text=True, check=True, cwd=cwd, timeout=300
        )
    except FileNotFoundError:
        raise FactsError(f"{cmd[0]} is not installed") from None
    except subprocess.CalledProcessError as exc:
        raise FactsError(f"{' '.join(cmd)}: {exc.stderr.strip() or exc}") from None
    except subprocess.TimeoutExpired:
        raise FactsError(f"{' '.join(cmd)}: no answer in time") from None
    return done.stdout


# --- Lines of code ------------------------------------------------------------------

# Generated output and lock files, which nobody wrote by hand.
LEFT_OUT_DIRS = ("src/hirdir/static/", "html/", "dist/", "contract/")
# The licence is Markdown, and is not documentation.
LEFT_OUT_NAMES = {"uv.lock", "package-lock.json", "LICENSE.md"}
# Markdown is the documentation, and it is counted in the sentence under the table.
DOCUMENTATION = "Markdown"
# cloc's names for languages, where the notes use another.
# cloc takes Dockerfile.build for a NAnt script, by its extension.
LANGUAGE_NAMES = {
    "make": "Make",
    "Bourne Shell": "Shell",
    "Bourne Again Shell": "Shell",
    "NAnt script": "Dockerfile",
}
# These rows come first, as in the template; the rest follow by code lines, largest first.
FIRST_LANGUAGES = ("Python", "TypeScript")
AREAS = ("product", "tests", "tooling")
TOOLING_DIRS = (
    "scripts/",
    ".github/",
    "packaging/build-",
    "packaging/package-test",
    "packaging/container/",
    "packaging/Dockerfile",
)
TOOLING_FILES = {"Makefile", "pyproject.toml"}


def left_out(path: str) -> bool:
    """Whether a tracked file is generated output or a lock file."""
    return path.startswith(LEFT_OUT_DIRS) or path.rsplit("/", 1)[-1] in LEFT_OUT_NAMES


def area(path: str) -> str:
    """The column a file's code lines belong to: product, tests or tooling.

    Tests are tests/, packaging/tests/, and the web UI's *.test.* files and browser
    scenarios. Tooling is scripts/, the web UI's build scripts, the Makefile,
    the CI files, the build configuration, and the parts of packaging/ that build and test
    the package rather than being installed by it. Everything else is the product.
    """
    name = path.rsplit("/", 1)[-1]
    if path.startswith(("tests/", "packaging/tests/", "web/e2e/")):
        return "tests"
    if path.startswith("web/"):
        if ".test." in name:
            return "tests"
        if (
            name in {"package.json", "biome.json"}
            or name.startswith("tsconfig")
            or ".config." in name
            or path.startswith("web/scripts/")
        ):
            return "tooling"
        return "product"
    if path in TOOLING_FILES or path.startswith(TOOLING_DIRS):
        return "tooling"
    return "product"


@dataclass
class Row:
    files: int = 0
    code: int = 0
    comments: int = 0
    by_area: dict[str, int] = field(default_factory=lambda: dict.fromkeys(AREAS, 0))


@dataclass
class Lines:
    rows: dict[str, Row]
    docs_files: int = 0
    docs_lines: int = 0
    cloc: str = ""


def lines_of_code(by_file: dict[str, Any]) -> Lines:
    """Gather the output of ``cloc --by-file --json`` into one row for each language."""
    rows: dict[str, Row] = defaultdict(Row)
    lines = Lines({}, cloc=str(by_file.get("header", {}).get("cloc_version", "")))
    for key, counts in by_file.items():
        if key in ("header", "SUM"):
            continue
        path = key.removeprefix("./")
        if left_out(path):
            continue
        if counts["language"] == DOCUMENTATION:
            lines.docs_files += 1
            lines.docs_lines += counts["code"]
            continue
        row = rows[LANGUAGE_NAMES.get(counts["language"], counts["language"])]
        row.files += 1
        row.code += counts["code"]
        row.comments += counts["comment"]
        row.by_area[area(path)] += counts["code"]
    rest = sorted(
        (name for name in rows if name not in FIRST_LANGUAGES),
        key=lambda name: (-rows[name].code, name),
    )
    order = [name for name in FIRST_LANGUAGES if name in rows] + rest
    lines.rows = {name: rows[name] for name in order}
    return lines


def count_lines(root: Path = ROOT) -> Lines:
    """Run cloc over the files git tracks in ``root``."""
    out = run("cloc", "--vcs=git", "--by-file", "--json", "--quiet", ".", cwd=root)
    try:
        by_file = json.loads(out)
    except json.JSONDecodeError:
        raise FactsError("cloc printed no table; are there tracked files to count?") from None
    return lines_of_code(by_file)


def _n(value: int) -> str:
    return f"{value:,}"


def _dash(value: int) -> str:
    return f"{value:,}" if value else "-"


def render_lines(lines: Lines) -> str:
    out = [
        "## Lines of code",
        "",
        "| Language | Files | Code | Comments | Product | Tests | Tooling |",
        "|---|--:|--:|--:|--:|--:|--:|",
    ]
    total = Row()
    for name, row in lines.rows.items():
        areas = " | ".join(_dash(row.by_area[a]) for a in AREAS)
        out.append(f"| {name} | {_n(row.files)} | {_n(row.code)} | {_n(row.comments)} | {areas} |")
        total.files += row.files
        total.code += row.code
        total.comments += row.comments
        for a in AREAS:
            total.by_area[a] += row.by_area[a]
    areas = " | ".join(f"**{_dash(total.by_area[a])}**" for a in AREAS)
    out += [
        f"| **All** | **{_n(total.files)}** | **{_n(total.code)}** | **{_n(total.comments)}** "
        f"| {areas} |",
        "",
        f"Counted by cloc {lines.cloc} in the files git tracks. Product is what the package "
        "installs and runs, and Tooling builds, checks and releases it. Lock files, the built "
        "web UI and other generated files are left out. The documentation is another "
        f"{lines.docs_lines:,} lines of Markdown in {lines.docs_files:,} files.",
    ]
    return "\n".join(out) + "\n"


# --- Versions -----------------------------------------------------------------------


def project_version(root: Path = ROOT) -> str:
    text = (root / "src" / PROJECT / "__init__.py").read_text(encoding="utf-8")
    found = re.search(r'^__version__ = "([^"]+)"', text, re.M)
    if not found:
        raise FactsError(f"no __version__ in src/{PROJECT}/__init__.py")
    return found[1]


def canonical(name: str) -> str:
    """A package's name as PyPI compares them: lower case, with runs of -_. as one -."""
    return re.sub(r"[-_.]+", "-", name).lower()


def direct_python(root: Path = ROOT) -> list[str]:
    """The packages pyproject.toml asks for itself, not those they need."""
    with (root / "pyproject.toml").open("rb") as handle:
        deps = tomllib.load(handle)["project"]["dependencies"]
    return sorted(canonical(re.split(r"[\s\[<>=!~;]", dep, maxsplit=1)[0]) for dep in deps)


def deb_packages(listing: str) -> dict[str, str]:
    """The Python packages the package installs, from the listing of ``dpkg-deb -c``.

    Only the virtual environment under /opt/hirdir/venv is read. The bundled interpreter
    has a site-packages directory of its own, which the service does not use.
    """
    found = re.findall(
        r"/opt/hirdir/venv/\S*/site-packages/([A-Za-z0-9_.]+?)-([0-9][^/\s]*)\.dist-info/$",
        listing,
        re.M,
    )
    packages = dict(sorted((canonical(name), ver) for name, ver in found))
    packages.pop(PROJECT, None)
    return packages


def listed_python(listing: str) -> str | None:
    """The interpreter's version as far as the package's file names give it away."""
    full = re.search(r"cpython-(\d+\.\d+\.\d+)", listing)
    if full:
        return full[1]
    short = re.search(r"/opt/hirdir/\S*/python(\d+\.\d+)/", listing)
    return short[1] if short else None


def _marker_excludes_linux(marker: str) -> bool:
    """Whether a dependency's marker limits it to Windows or macOS.

    This reads only the simple markers uv writes for platform-only packages. Any other
    marker is taken to apply, which can at worst count a package too many.
    """
    if " or " in marker:
        return False
    names = r"(?:sys_platform|platform_system|os_name)"
    others = r"(?:win32|cygwin|darwin|Windows|Darwin|nt)"
    return re.search(rf"{names}\s*==\s*'{others}'", marker) is not None


def lock_packages(lock: dict[str, Any], project: str = PROJECT) -> dict[str, str]:
    """The packages the project needs when it runs on Linux, from uv.lock.

    The walk starts at the project's own entry and follows ``dependencies``, so the
    development and documentation groups are left out, as they are from the package.
    """
    entries = {canonical(entry["name"]): entry for entry in lock.get("package", [])}
    if project not in entries:
        raise FactsError(f"uv.lock has no entry for {project}")
    wanted: dict[str, str] = {}
    queue = [(project, [])]
    seen: set[tuple[str, str]] = set()
    while queue:
        name, extras = queue.pop()
        entry = entries.get(name)
        if entry is None:
            continue
        if name != project:
            wanted[name] = entry.get("version", "?")
        needs = list(entry.get("dependencies", []))
        for extra in extras:
            needs += entry.get("optional-dependencies", {}).get(extra, [])
        for need in needs:
            if _marker_excludes_linux(need.get("marker", "")):
                continue
            target = canonical(need["name"])
            key = (target, ",".join(sorted(need.get("extra", []))))
            if key not in seen:
                seen.add(key)
                queue.append((target, need.get("extra", [])))
    return dict(sorted(wanted.items()))


def web_versions(lock: dict[str, Any]) -> list[tuple[str, str]]:
    """The label and version of each main web package that package-lock.json installs."""
    packages = lock.get("packages", {})
    found = []
    for name, label in WEB_PACKAGES:
        version = packages.get(f"node_modules/{name}", {}).get("version")
        if version:
            found.append((label, version))
        else:
            note(f"web/package-lock.json does not install {name}; it is left out")
    return found


def tool_version(*cmd: str) -> str | None:
    """The version a tool prints for itself, or None, with a note, when it cannot be asked."""
    try:
        out = run(*cmd)
    except FactsError as exc:
        note(f"{exc}; its version is left out")
        return None
    found = re.search(r"\d+(?:\.\d+)+[^\s,)]*", out)
    return found[0] if found else None


def find_deb(dist: Path, version: str) -> Path | None:
    """The built package for this version, or the newest one, or None."""
    exact = dist / f"{PROJECT}_{version}_amd64.deb"
    if exact.is_file():
        return exact
    built = sorted(dist.glob(f"{PROJECT}_*_amd64.deb"), key=lambda p: p.stat().st_mtime)
    if not built:
        return None
    note(f"{exact.name} is missing; reading {built[-1].name} instead")
    return built[-1]


QUERY = "import sqlite3, sys; print(sys.version.split()[0]); print(sqlite3.sqlite_version)"


def bundled_interpreter(deb: Path) -> tuple[str, str] | None:
    """Unpack the package and ask its own Python for its version and its SQLite's.

    Returns None, with a note, when the interpreter is not found or will not run here.
    """
    with tempfile.TemporaryDirectory(prefix="hirdir-facts-") as tmp:
        try:
            run("dpkg-deb", "-x", str(deb), tmp)
        except FactsError as exc:
            note(f"cannot unpack {deb.name}: {exc}")
            return None
        home = Path(tmp) / "opt" / PROJECT / "python"
        found = sorted(home.glob("bin/python3")) or sorted(home.glob("**/bin/python3"))
        if not found:
            note(f"{deb.name} holds no interpreter under /opt/{PROJECT}/python")
            return None
        try:
            answer = run(str(found[0]), "-I", "-c", QUERY).split()
        except FactsError as exc:
            note(f"the interpreter in {deb.name} did not run: {exc}")
            return None
    return (answer[0], answer[1]) if len(answer) == 2 else None


@dataclass
class Versions:
    python: str
    packages: dict[str, str]  # every Python package at run time, hirdir itself left out
    direct: list[str]
    sqlite: str
    web: list[tuple[str, str]]
    node: str | None
    tools: list[tuple[str, str]]
    base: str = CONTAINER_BASE


def development_sqlite() -> str:
    return run("uv", "run", "python", "-c", "import sqlite3; print(sqlite3.sqlite_version)").strip()


def versions(root: Path = ROOT, dist: Path | None = None) -> Versions:
    """Read every version, from the built package when there is one."""
    deb = find_deb(dist or root / "dist", project_version(root))
    if deb is not None:
        listing = run("dpkg-deb", "-c", str(deb))
        packages = deb_packages(listing)
        asked = bundled_interpreter(deb)
        if asked is not None:
            python, sqlite = asked
        else:
            python = listed_python(listing) or "?"
            sqlite = development_sqlite()
            note(
                f"Python {python} is read from the file names in {deb.name}, and SQLite "
                "from the development interpreter"
            )
    else:
        note(
            f"no dist/{PROJECT}_*_amd64.deb; Python and its packages are read from "
            ".python-version and uv.lock, and SQLite from the development interpreter. "
            "Run make deb first for a release."
        )
        python = (root / ".python-version").read_text(encoding="utf-8").strip()
        with (root / "uv.lock").open("rb") as handle:
            packages = lock_packages(tomllib.load(handle))
        sqlite = development_sqlite()

    web: list[tuple[str, str]] = []
    web_lock = root / "web" / "package-lock.json"
    if web_lock.is_file():
        web = web_versions(json.loads(web_lock.read_text(encoding="utf-8")))
    else:
        note("no web/package-lock.json; the web UI's row is left out")

    node = tool_version(shutil.which("node") or "node", "--version")
    tools = [
        ("uv", tool_version("uv", "--version")),
        ("ruff", tool_version("uv", "run", "ruff", "--version")),
        ("ty", tool_version("uv", "run", "ty", "--version")),
    ]
    return Versions(
        python=python,
        packages=packages,
        direct=direct_python(root),
        sqlite=sqlite,
        web=web,
        node=node,
        tools=[(name, version) for name, version in tools if version],
    )


def render_versions(v: Versions) -> str:
    direct = [name for name in v.direct if name in v.packages]
    for name in v.direct:
        if name not in v.packages:
            note(f"{name} is a direct dependency that was not found among the packages")
    named = ", ".join(f"{name} {v.packages[name]}" for name in direct)
    others = len(v.packages) - len(direct)
    out = [
        "## Versions",
        "",
        "| Part | Version |",
        "|---|---|",
        f"| Python, shipped in the package | {v.python} |",
        f"| Its Python packages | {named}, and the {others} they need |",
        f"| SQLite, as built into that Python | {v.sqlite} |",
    ]
    if v.web:
        labels = ", ".join(label for label, _ in v.web)
        out.append(f"| {labels} | {', '.join(version for _, version in v.web)} |")
    if v.node:
        out.append(f"| Node, which builds the web UI | {v.node} |")
    if v.tools:
        names = ", ".join(name for name, _ in v.tools)
        out.append(f"| {names} | {', '.join(version for _, version in v.tools)} |")
    out += [
        f"| The build and test container's base | {v.base} |",
        "",
        f"<details><summary>Every Python package: {len(v.packages)}</summary>",
        "",
        "| Python package | Version |",
        "|---|---|",
        *(f"| {name} | {version} |" for name, version in v.packages.items()),
        "",
        "</details>",
    ]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--dist", type=Path, default=ROOT / "dist", help="where the package is")
    args = parser.parse_args(argv)
    try:
        text = render_lines(count_lines()) + "\n" + render_versions(versions(dist=args.dist))
    except FactsError as exc:
        note(str(exc))
        return 1
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
