"""Print a release's notes in the form the GitHub release takes them.

The notes are a page like any other: `docs/releases/v<version>.md`, wrapped at the
width of the other pages. GitHub renders a file of the repository with a line break
inside a paragraph as a space. It renders the text of a release as it renders a
comment, where the same line break ends the line. Given the file as it is, a release
shows every paragraph at half the width of the page, each line ending where the file
wrapped it, beside the few lines that were never wrapped.

So the text of a release is the file with each paragraph and each list item on one
line. Headings, tables, code and the collapsed block are left as they are. A link to
another page of the repository, which on the release would lead nowhere, becomes a link
to that file at the release's tag.

    uv run python scripts/release_body.py            the notes of the current version
    uv run python scripts/release_body.py 0.3.0      those of another
"""

import posixpath
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NOTES = "docs/releases"
REPO = "https://github.com/robert-patrick-texas/hirdir"

_HEADING = re.compile(r"#{1,6}(\s|$)")
_ITEM = re.compile(r"\s*(?:[-*+]|\d+[.)])\s+")
_FENCE = re.compile(r"\s*(```|~~~)")
_LINK = re.compile(r"(?<=\]\()([^)\s]+)(?=\))")
_VERSION = re.compile(r"\d+\.\d+\.\d+")


def current_version() -> str:
    """Return the version the tree is at."""
    text = (ROOT / "src" / "hirdir" / "__init__.py").read_text(encoding="utf-8")
    found = re.search(r'^__version__ = "([^"]+)"', text, re.MULTILINE)
    if found is None:
        raise SystemExit("src/hirdir/__init__.py names no version")
    return found[1]


def _stands_alone(line: str) -> bool:
    """Say whether a line is one that is never joined to its neighbours."""
    start = line.lstrip()
    if _HEADING.match(start) or start.startswith(("|", "<", ">")):
        return True
    return len(start) >= 3 and set(start) <= set("-*_ ")


def unwrapped(text: str) -> str:
    """Return Markdown with each paragraph and each list item on a line of its own."""
    out: list[str] = []
    block: list[str] = []
    fence = ""

    def close() -> None:
        if block:
            out.append(block[0] + "".join(f" {more.strip()}" for more in block[1:]))
            block.clear()

    for line in text.splitlines():
        marked = _FENCE.match(line)
        if fence:
            out.append(line)
            if marked and marked[1] == fence:
                fence = ""
        elif marked:
            close()
            out.append(line)
            fence = marked[1]
        elif not line.strip():
            close()
            out.append("")
        elif _stands_alone(line):
            close()
            out.append(line)
        elif _ITEM.match(line):
            close()
            block.append(line.rstrip())
        else:
            block.append(line.rstrip())
    close()
    return "\n".join(out) + "\n"


def with_whole_links(text: str, version: str) -> str:
    """Return notes whose links to pages of the repository lead to them at the tag."""

    def whole(found: re.Match[str]) -> str:
        target = found[1]
        if re.match(r"[a-z][a-z0-9+.-]*:|#|/", target):
            return target
        path, mark, anchor = target.partition("#")
        there = posixpath.normpath(posixpath.join(NOTES, path))
        if there.startswith(".."):
            return target
        return f"{REPO}/blob/v{version}/{there}{mark}{anchor}"

    return _LINK.sub(whole, text)


def body(version: str) -> str:
    """Return the text of the GitHub release of a version."""
    path = ROOT / NOTES / f"v{version}.md"
    if not path.is_file():
        raise SystemExit(f"there are no notes for {version}: {path.relative_to(ROOT)} is missing")
    return with_whole_links(unwrapped(path.read_text(encoding="utf-8")), version)


def main() -> int:
    """Print the text of a release: of the version named, or of the tree's own."""
    given = sys.argv[1:]
    if len(given) > 1 or (given and not _VERSION.fullmatch(given[0].removeprefix("v"))):
        print("usage: release_body.py [VERSION]", file=sys.stderr)
        return 2
    sys.stdout.write(body(given[0].removeprefix("v") if given else current_version()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
