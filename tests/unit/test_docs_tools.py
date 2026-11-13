"""The release tooling in scripts/: the documentation build, the facts and the guard."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath
from types import ModuleType

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def load(name: str) -> ModuleType:
    """Import a script by its file, because scripts/ is not a package."""
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # The dataclasses in the script look their module up here.
    spec.loader.exec_module(module)
    return module


facts = load("release_facts")
guard = load("publish_guard")


# --- build_docs ---------------------------------------------------------------------


@pytest.fixture(scope="module")
def docs() -> ModuleType:
    """The documentation build, which needs the packages of the docs dependency group."""
    for package in ("markdown_it", "mdit_py_plugins", "pygments"):
        pytest.importorskip(package)
    return load("build_docs")


def write(root: Path, path: str, text: str) -> None:
    (root / path).parent.mkdir(parents=True, exist_ok=True)
    (root / path).write_text(text, encoding="utf-8")


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A small repository: an overview, two pages, two releases and one picture."""
    root = tmp_path / "repo"
    write(
        root,
        "README.md",
        "# Example\n\n![Picture](images/picture.png)\n\n"
        "See [the model](docs/data-model.md#records) and the [Makefile](Makefile).\n",
    )
    write(
        root,
        "docs/data-model.md",
        "# Data model\n\n![Picture](../images/picture.png)\n\n## Records\n\n"
        "Back to the [overview](../README.md).\n\n```nosuchlanguage\na < b\n```\n",
    )
    write(root, "docs/releases/v0.9.0.md", "# example 0.9.0\n\nThe ninth.\n")
    write(root, "docs/releases/v0.10.0.md", "# example 0.10.0\n\nThe tenth.\n")
    write(root, "CLAUDE.md", "# Working here\n\nNotes.\n")
    write(root, "node_modules/package/README.md", "# Not ours\n")
    write(root, "Makefile", "all:\n")
    (root / "images").mkdir()
    (root / "images" / "picture.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    return root


def test_site_is_built_with_pages_pictures_and_rewritten_links(
    docs: ModuleType, tree: Path, tmp_path: Path
) -> None:
    out = tmp_path / "html"
    site = docs.Site(tree)
    site.render()
    site.write(out)

    assert site.problems == []
    assert PurePosixPath("node_modules/package/README.md") not in site.pages
    for page in ("index.html", "docs/data-model.html", "docs/releases/v0.10.0.html", "CLAUDE.html"):
        assert (out / page).is_file()
    # The picture is where the same relative link finds it from either page.
    assert (out / "images" / "picture.png").read_bytes().startswith(b"\x89PNG")
    index = (out / "index.html").read_text(encoding="utf-8")
    model = (out / "docs" / "data-model.html").read_text(encoding="utf-8")
    assert 'src="images/picture.png"' in index
    assert 'src="../images/picture.png"' in model
    assert 'href="docs/data-model.html#records"' in index
    assert f'href="{docs.REPO}/blob/{docs.BRANCH}/Makefile"' in index
    assert 'href="../index.html"' in model
    assert "a &lt; b" in model
    assert "<script" not in index


def test_navigation_lists_releases_newest_first_and_the_trailing_page_last(
    docs: ModuleType, tree: Path
) -> None:
    site = docs.Site(tree)
    site.render()
    nav = site._nav(site.pages[PurePosixPath("README.md")])

    order = [nav.index(text) for text in ("Overview", "Releases", "v0.10.0", "v0.9.0", "Project")]
    assert order == sorted(order)
    assert nav.index("Working here") > nav.index("Project")


def test_unresolved_link_anchor_and_picture_are_problems(docs: ModuleType, tree: Path) -> None:
    write(
        tree,
        "docs/broken.md",
        "# Broken\n\n[a](missing.md) [b](data-model.md#nowhere) ![c](../images/none.png)\n",
    )
    site = docs.Site(tree)
    site.render()

    assert len(site.problems) == 3
    assert all(problem.startswith("docs/broken.md: ") for problem in site.problems)


def test_build_fails_on_a_broken_link(docs: ModuleType, tree: Path, tmp_path: Path) -> None:
    ok, _ = docs.build(tmp_path / "html", tree)
    assert ok
    write(tree, "docs/broken.md", "# Broken\n\n[a](missing.md)\n")
    ok, _ = docs.build(tmp_path / "html", tree)
    assert not ok


def test_a_directory_the_build_did_not_write_is_not_cleared(
    docs: ModuleType, tree: Path, tmp_path: Path
) -> None:
    out = tmp_path / "kept"
    out.mkdir()
    (out / "notes.txt").write_text("keep me", encoding="utf-8")

    assert docs.refusal(tree, out, [PurePosixPath("README.md")]) is not None
    assert docs.refusal(tree, tree, [PurePosixPath("README.md")]) is not None
    assert docs.refusal(tree, tmp_path / "new", [PurePosixPath("README.md")]) is None


def test_release_key_compares_numbers_and_ignores_other_files(docs: ModuleType) -> None:
    key = docs.release_key
    assert key(PurePosixPath("docs/releases/v0.10.0.md")) > key(
        PurePosixPath("docs/releases/v0.9.0.md")
    )
    assert key(PurePosixPath("docs/releases/v1.0.0.md")) > key(
        PurePosixPath("docs/releases/v1.0.0-rc1.md")
    )
    assert key(PurePosixPath("docs/releases/README.md")) is None
    assert key(PurePosixPath("docs/v1.0.0.md")) is None


# --- release_facts ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("src/hirdir/domain/items.py", "product"),
        ("web/src/grid.ts", "product"),
        ("packaging/hirdir.service", "product"),
        ("tests/unit/test_items.py", "tests"),
        ("web/src/grid.test.ts", "tests"),
        ("scripts/build_docs.py", "tooling"),
        ("Makefile", "tooling"),
        ("pyproject.toml", "tooling"),
        (".github/workflows/docs.yml", "tooling"),
        ("packaging/build-deb.sh", "tooling"),
        ("web/vite.config.ts", "tooling"),
        ("web/package.json", "tooling"),
    ],
)
def test_area_by_path(path: str, expected: str) -> None:
    assert facts.area(path) == expected


def cloc_file(language: str, code: int, comment: int = 0) -> dict[str, object]:
    return {"blank": 0, "comment": comment, "code": code, "language": language}


def test_lines_table_splits_by_path_and_leaves_out_locks_and_markdown() -> None:
    lines = facts.lines_of_code(
        {
            "header": {"cloc_version": "2.06"},
            "./src/hirdir/app.py": cloc_file("Python", 1200, 30),
            "./tests/unit/test_app.py": cloc_file("Python", 400),
            "./scripts/tool.py": cloc_file("Python", 50, 5),
            "./web/src/grid.ts": cloc_file("TypeScript", 70),
            "./Makefile": cloc_file("make", 45),
            "./web/package-lock.json": cloc_file("JSON", 9000),
            "./src/hirdir/static/app.js": cloc_file("JavaScript", 8000),
            "./README.md": cloc_file("Markdown", 40),
            "SUM": {"blank": 0, "comment": 35, "code": 18805, "nFiles": 8},
        }
    )
    table = facts.render_lines(lines).splitlines()

    assert table[0] == "## Lines of code"
    assert table[2] == "| Language | Files | Code | Comments | Product | Tests | Tooling |"
    assert table[3] == "|---|--:|--:|--:|--:|--:|--:|"
    assert table[4] == "| Python | 3 | 1,650 | 35 | 1,200 | 400 | 50 |"
    assert table[5] == "| TypeScript | 1 | 70 | 0 | 70 | - | - |"
    assert table[6] == "| Make | 1 | 45 | 0 | - | - | 45 |"
    assert table[7] == "| **All** | **5** | **1,765** | **35** | **1,270** | **400** | **95** |"
    assert "40 lines of Markdown in 1 files" in table[-1]


def test_deb_packages_reads_only_the_virtual_environment() -> None:
    row = "drwxr-xr-x root/root         0 2026-01-01 00:00 ./opt/hirdir/"
    listing = "\n".join(
        [
            f"{row}venv/lib/python3.15/site-packages/fastapi-1.2.3.dist-info/",
            f"{row}venv/lib/python3.15/site-packages/fastapi-1.2.3.dist-info/METADATA",
            f"{row}venv/lib/python3.15/site-packages/Typing_Extensions-4.5.6.dist-info/",
            f"{row}venv/lib/python3.15/site-packages/hirdir-0.1.0.dist-info/",
            f"{row}python/lib/python3.15/site-packages/pip-9.9.9.dist-info/",
        ]
    )

    assert facts.deb_packages(listing) == {"fastapi": "1.2.3", "typing-extensions": "4.5.6"}
    assert facts.listed_python(listing) == "3.15"


def test_lock_packages_follows_only_what_runs_on_linux() -> None:
    lock = {
        "package": [
            {
                "name": "hirdir",
                "dependencies": [{"name": "web-kit", "extra": ["fast"]}],
                "dev-dependencies": {"dev": [{"name": "checker"}]},
            },
            {
                "name": "web_kit",
                "version": "2.0.0",
                "dependencies": [
                    {"name": "core"},
                    {"name": "console", "marker": "sys_platform == 'win32'"},
                ],
                "optional-dependencies": {"fast": [{"name": "speedup"}]},
            },
            {"name": "core", "version": "1.0.0"},
            {"name": "speedup", "version": "0.3.0"},
            {"name": "console", "version": "0.4.0"},
            {"name": "checker", "version": "9.0.0"},
        ]
    }

    assert facts.lock_packages(lock) == {"core": "1.0.0", "speedup": "0.3.0", "web-kit": "2.0.0"}


def test_versions_table_names_direct_packages_and_counts_the_rest() -> None:
    text = facts.render_versions(
        facts.Versions(
            python="3.15.2",
            packages={"core": "1.0.0", "speedup": "0.3.0", "web-kit": "2.0.0"},
            direct=["web-kit"],
            sqlite="3.50.0",
            web=[],
            node="24.0.0",
            tools=[("uv", "0.9.0"), ("ruff", "0.8.0"), ("ty", "0.0.7")],
        )
    )

    assert "| Its Python packages | web-kit 2.0.0, and the 2 they need |" in text
    assert "| uv, ruff, ty | 0.9.0, 0.8.0, 0.0.7 |" in text
    assert "| The build and test container's base | ubuntu:26.04 |" in text
    assert "TypeScript" not in text
    assert "<details><summary>Every Python package: 3</summary>" in text


def test_only_the_package_of_this_version_is_read(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The previous release's package lies in dist/ for the upgrade test."""
    previous = tmp_path / "hirdir_0.1.0_amd64.deb"
    previous.write_bytes(b"")

    assert facts.find_deb(tmp_path, "0.2.0") is None
    assert "hirdir_0.1.0_amd64.deb is not read in its place" in capsys.readouterr().err

    built = tmp_path / "hirdir_0.2.0_amd64.deb"
    built.write_bytes(b"")
    assert facts.find_deb(tmp_path, "0.2.0") == built
    assert facts.find_deb(tmp_path, "0.1.0") == previous


def web_lock(**versions: str) -> dict[str, object]:
    """A package-lock.json that installs the named packages, underscores read as hyphens."""
    installed = {
        f"node_modules/{name.replace('_', '-')}": {"version": version}
        for name, version in versions.items()
    }
    return {"packages": {"": {"name": "web"}, **installed}}


def versions_with(web: list[tuple[str, str]]) -> str:
    return facts.render_versions(
        facts.Versions(
            python="3.15.2",
            packages={"web-kit": "2.0.0"},
            direct=["web-kit"],
            sqlite="3.50.0",
            web=web,
            node="24.0.0",
            tools=[],
        )
    )


def test_the_web_row_names_the_grid_when_the_lock_installs_it(
    capsys: pytest.CaptureFixture[str],
) -> None:
    lock = web_lock(
        typescript="7.0.2",
        vite="8.3.8",
        react="19.3.1",
        react_dom="19.3.1",
        ag_grid_community="36.1.0",
        ag_grid_react="36.1.0",
    )

    web = facts.web_versions(lock)

    assert web == [
        ("TypeScript", "7.0.2"),
        ("Vite", "8.3.8"),
        ("React", "19.3.1"),
        ("AG Grid Community", "36.1.0"),
    ]
    assert (
        "| TypeScript, Vite, React, AG Grid Community | 7.0.2, 8.3.8, 19.3.1, 36.1.0 |"
        in versions_with(web)
    )
    assert capsys.readouterr().err == ""


def test_the_web_row_leaves_the_grid_out_when_the_lock_does_not_install_it(
    capsys: pytest.CaptureFixture[str],
) -> None:
    web = facts.web_versions(web_lock(typescript="7.0.2", vite="8.3.8", react="19.3.1"))

    assert web == [("TypeScript", "7.0.2"), ("Vite", "8.3.8"), ("React", "19.3.1")]
    text = versions_with(web)
    assert "| TypeScript, Vite, React | 7.0.2, 8.3.8, 19.3.1 |" in text
    assert "AG Grid" not in text
    # Said to the person running it, and never in the table.
    assert "does not install ag-grid-community" in capsys.readouterr().err


def test_the_web_row_shows_a_react_binding_that_is_not_at_the_grids_version(
    capsys: pytest.CaptureFixture[str],
) -> None:
    lock = web_lock(
        typescript="7.0.2",
        vite="8.3.8",
        react="19.3.1",
        ag_grid_community="36.1.0",
        ag_grid_react="36.0.2",
    )

    assert facts.web_versions(lock)[-1] == ("AG Grid Community", "36.1.0 (ag-grid-react 36.0.2)")
    assert "ag-grid-react is at 36.0.2" in capsys.readouterr().err


def test_the_project_names_regex_and_ships_none_of_its_development_tools() -> None:
    """Read from this repository's own pyproject.toml and uv.lock."""
    development = {"pytest", "ruff", "ty"}
    direct = facts.direct_python()
    with (facts.ROOT / "uv.lock").open("rb") as handle:
        runs_with = facts.lock_packages(facts.tomllib.load(handle))

    assert "regex" in direct
    assert "regex" in runs_with
    # The command line calls the API with httpx2, so it ships; httpx, which it took the
    # place of, is in neither list.
    assert "httpx2" in direct
    assert "httpx2" in runs_with
    assert "httpx" not in runs_with
    assert not development & set(direct)
    assert not development & set(runs_with)
    # The lock does hold them, for the development group: the walk is what leaves them out.
    text = (facts.ROOT / "uv.lock").read_text(encoding="utf-8")
    assert all(f'name = "{name}"' in text for name in development)


# --- publish_guard ------------------------------------------------------------------


def test_terms_skip_blank_lines_and_comments() -> None:
    assert guard.read_terms("# a comment\n\nOre\n  example-core-1  \nore\n") == [
        "ore",
        "example-core-1",
    ]


def test_a_term_matches_whole_words_in_any_case() -> None:
    pattern = guard.compile_terms(["ore", "north campus"])
    text = "It bores nobody.\nAsk ORE, or ore.\nAt the North  Campus.\nAn ore-rich seam.\n"

    assert guard.hits_in(text, pattern) == [(2, "ore"), (3, "north campus"), (4, "ore")]


def test_scan_reports_file_line_and_term_and_skips_binary_files(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("one\nthe Ore file\n", encoding="utf-8")
    (tmp_path / "picture.png").write_bytes(b"\x89PNG\0 ore \0")
    (tmp_path / "ore.txt").write_text("nothing here\n", encoding="utf-8")

    hits = guard.scan(tmp_path, ["notes.txt", "picture.png", "ore.txt", "gone.txt"], ["ore"])

    assert hits == ["notes.txt:2: ore", "ore.txt:0: ore"]


def test_without_a_guard_file_nothing_is_checked(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert guard.main(["--root", str(tmp_path)]) == 0
    assert capsys.readouterr().out == "publish guard: no .publish-guard file, nothing checked\n"


def test_guard_checks_the_files_git_tracks(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    git = shutil.which("git")
    if git is None:
        pytest.skip("git is not installed")
    (tmp_path / "tracked.md").write_text("Nothing to see.\n", encoding="utf-8")
    (tmp_path / "untracked.md").write_text("Dug for ore.\n", encoding="utf-8")
    (tmp_path / ".publish-guard").write_text("# terms\nore\nexample-core-1\n", encoding="utf-8")
    for command in (["init", "--quiet"], ["add", "tracked.md"]):
        subprocess.run(  # noqa: S603 a fixed git command in a temporary directory
            [git, "-C", str(tmp_path), *command], check=True, capture_output=True
        )

    assert guard.main(["--root", str(tmp_path)]) == 0
    assert capsys.readouterr().out == "publish guard: clean (2 terms)\n"

    (tmp_path / "tracked.md").write_text("Nothing to see.\nMoved to EXAMPLE-CORE-1.\n", "utf-8")
    assert guard.main(["--root", str(tmp_path)]) == 1
    assert capsys.readouterr().out == "tracked.md:2: example-core-1\n"
