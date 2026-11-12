"""Refuse to go on if a tracked file holds a term that must not be published.

    uv run python scripts/publish_guard.py

The terms are read from .publish-guard in the top directory of the repository: one term
on each line, with blank lines and lines that start with # ignored. That file is listed
in .gitignore and is never committed, because it names exactly the words that must stay
out of the repository. A maintainer keeps their own copy.

Every text file git tracks is searched, and so is its path. A term matches in any letter
case and only as a whole word, so the term "ore" matches "Ore" and does not match "more".
Each hit is printed as file:line: term, with line 0 for a hit in the path itself, and the
exit status is 1. Nothing else from .publish-guard is ever printed.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUARD = ".publish-guard"


def _normal(text: str) -> str:
    """A term as it is compared and printed: lower case, with single spaces."""
    return " ".join(text.casefold().split())


def read_terms(text: str) -> list[str]:
    """The terms in the text of a guard file, in order and without repeats."""
    terms: dict[str, None] = {}
    for line in text.splitlines():
        term = _normal(line)
        if term and not term.startswith("#"):
            terms.setdefault(term, None)
    return list(terms)


def compile_terms(terms: list[str]) -> re.Pattern[str] | None:
    """One pattern that finds any of the terms as a whole word, in any letter case."""
    if not terms:
        return None
    # The longest term is tried first, so a term that begins another does not hide it.
    longest_first = sorted(terms, key=len, reverse=True)
    # Any run of spaces or tabs stands for the space between the words of a term.
    words = "|".join(
        r"[ \t]+".join(re.escape(part) for part in term.split()) for term in longest_first
    )
    return re.compile(rf"(?<!\w)(?:{words})(?!\w)", re.IGNORECASE)


def hits_in(text: str, pattern: re.Pattern[str]) -> list[tuple[int, str]]:
    """Each line number and term found in the text. A term is listed once for a line."""
    found: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), 1):
        seen = dict.fromkeys(_normal(match[0]) for match in pattern.finditer(line))
        found += [(number, term) for term in seen]
    return found


def tracked(root: Path) -> list[str]:
    """The paths git tracks in ``root``."""
    done = subprocess.run(  # noqa: S603 a fixed command, and no part of it is input
        ["git", "-C", str(root), "ls-files", "-z"],  # noqa: S607 git is found on the PATH
        capture_output=True,
        check=True,
    )
    return [path for path in done.stdout.decode("utf-8", "surrogateescape").split("\0") if path]


def scan(root: Path, paths: list[str], terms: list[str]) -> list[str]:
    """The hits in the given files, each as ``file:line: term``."""
    pattern = compile_terms(terms)
    if pattern is None:
        return []
    found: list[str] = []
    for path in paths:
        shown = path.encode("utf-8", "surrogateescape").decode("utf-8", "replace")
        found += [f"{shown}:0: {term}" for _, term in hits_in(shown, pattern)]
        try:
            data = (root / path).read_bytes()
        except OSError:
            # The file is tracked and absent from the working tree, or it is a directory
            # that stands for a submodule. There is nothing here to read.
            continue
        if b"\0" in data:
            # A picture or another binary file holds no text to search.
            continue
        text = data.decode("utf-8", "replace")
        found += [f"{shown}:{number}: {term}" for number, term in hits_in(text, pattern)]
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--root", type=Path, default=ROOT, help="the repository to check")
    args = parser.parse_args(argv)
    root: Path = args.root

    guard = root / GUARD
    if not guard.is_file():
        print(f"publish guard: no {GUARD} file, nothing checked")
        return 0
    try:
        paths = tracked(root)
    except OSError as exc:
        print(f"publish guard: cannot run git: {exc}", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as exc:
        reason = exc.stderr.decode("utf-8", "replace").strip()
        print(f"publish guard: cannot list the tracked files: {reason}", file=sys.stderr)
        return 2
    if GUARD in paths:
        print(f"{GUARD}:0: this file is tracked by git and must never be committed")
        return 1
    terms = read_terms(guard.read_text(encoding="utf-8", errors="replace"))
    hits = scan(root, paths, terms)
    if hits:
        print("\n".join(hits))
        return 1
    print(f"publish guard: clean ({len(terms)} terms)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
