"""What the release notes say the package holds, read from this repository's own lock.

`make facts` reads the built package when there is one, and `uv.lock` when there is
none. The two must name the same Python packages, or the notes of a release would
depend on whether `make deb` had been run.
"""

import importlib.util
import sys
import tomllib
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]


def load(name: str) -> ModuleType:
    """Import a script by its file, because scripts/ is not a package.

    It is given a name of its own, so that the copy tests/unit loads is left alone.
    """
    known_as = f"packaging_tests_{name}"
    spec = importlib.util.spec_from_file_location(known_as, ROOT / "scripts" / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[known_as] = module  # The dataclasses in the script look their module up here.
    spec.loader.exec_module(module)
    return module


facts = load("release_facts")


def runs_with() -> dict[str, str]:
    with (ROOT / "uv.lock").open("rb") as handle:
        return facts.lock_packages(tomllib.load(handle))


def test_the_package_carries_httpx2_and_what_it_needs_on_linux() -> None:
    """httpx2 ships from 0.3.0: the command line calls the API with it."""
    packages = runs_with()
    assert "httpx2" in facts.direct_python()
    assert {"httpx2", "httpcore2"} <= set(packages)
    assert "httpx" not in packages
    assert "httpcore" not in packages


def test_a_package_for_another_platform_is_not_counted() -> None:
    """httpx2 asks for httpx2-jsfetch in a browser only. The package is built for Linux."""
    lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
    assert '{ name = "httpx2-jsfetch", marker = "sys_platform == \'emscripten\'" }' in lock
    assert "httpx2-jsfetch" not in runs_with()
    assert facts._marker_excludes_linux("sys_platform == 'emscripten'")
    assert facts._marker_excludes_linux("sys_platform == 'win32'")
    assert not facts._marker_excludes_linux("sys_platform != 'emscripten'")
    assert not facts._marker_excludes_linux("sys_platform == 'linux'")
    assert not facts._marker_excludes_linux("sys_platform == 'emscripten' or os_name == 'posix'")


def test_no_tool_of_development_is_among_the_packages_of_the_package() -> None:
    assert not {"pytest", "ruff", "ty", "mdit-py-plugins"} & set(runs_with())


def test_the_generated_examples_are_not_counted_as_lines_of_code() -> None:
    """They are written by make examples. Their page is documentation, and is counted."""
    lines = facts.lines_of_code(
        {
            "header": {"cloc_version": "2.06"},
            "./examples/items.csv": {"blank": 0, "comment": 0, "code": 36, "language": "CSV"},
            "./examples/items.json": {"blank": 0, "comment": 0, "code": 37, "language": "JSON"},
            "./examples/README.md": {"blank": 9, "comment": 0, "code": 28, "language": "Markdown"},
            "./web/biome.json": {"blank": 0, "comment": 0, "code": 20, "language": "JSON"},
        }
    )
    assert list(lines.rows) == ["JSON"]
    assert (lines.rows["JSON"].files, lines.rows["JSON"].code) == (1, 20)
    assert (lines.docs_files, lines.docs_lines) == (1, 28)
    for name in ("tags", "vendors", "catalog-entries", "owners", "items"):
        assert (ROOT / "examples" / f"{name}.csv").is_file()
        assert facts.left_out(f"examples/{name}.csv")
        assert facts.left_out(f"examples/{name}.json")
    assert not facts.left_out("examples/README.md")


def test_the_release_process_page_says_what_ships() -> None:
    """The page named httpx2 among the packages that never appear. It ships now."""
    page = (ROOT / "docs" / "release-process.md").read_text(encoding="utf-8")
    never = page[page.index("The Python packages are the ones the package installs") :]
    never = never[: never.index("\n- ")]
    assert "pytest, ruff or ty" in " ".join(never.split())
    assert "httpx2, which the command line calls the API with" in " ".join(never.split())
