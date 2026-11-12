"""Render every Markdown file in the repository into the static documentation site.

    uv run --only-group docs python scripts/build_docs.py            # write html/
    uv run --only-group docs python scripts/build_docs.py --watch    # and rebuild on change

README.md becomes index.html in its directory and every other X.md becomes X.html. Each
page carries the same left-hand navigation and a link to the GitHub repository. Links
between Markdown files are rewritten to the matching pages, links to other repository
files point at GitHub, and the pictures in images/ are copied alongside so that the same
relative link works on GitHub and on the published page. An internal link or anchor that
does not resolve fails the build, so CI catches documentation rot.

The output uses relative URLs only and no JavaScript, so it works on GitHub Pages, behind
a web server under any path, and straight from the file system.

A bare URL in the text is not turned into a link. Write it as <https://example.net/> or
as an ordinary Markdown link.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import os
import posixpath
import re
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote, unquote, urlsplit

from markdown_it import MarkdownIt
from markdown_it.token import Token
from mdit_py_plugins.tasklists import tasklists_plugin
from pygments import highlight
from pygments.formatters.html import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from pygments.util import ClassNotFound

ROOT = Path(__file__).resolve().parent.parent
CSS = Path(__file__).with_name("docs.css")
NAME = "hirdir"
REPO = "https://github.com/robert-patrick-texas/hirdir"
BRANCH = "main"
SKIP_DIRS = {
    "node_modules",
    "html",
    "dist",
    "build",
    ".venv",
    "dev-data",
    "__pycache__",
    ".git",
}

# Navigation order and labels (None: the page's first heading). Pages not listed here sit
# after the leading group, alphabetically. Release notes follow under their own heading,
# newest first, and the trailing group closes the list.
LEADING: list[tuple[str, str | None]] = [
    ("README.md", "Overview"),
    ("docs/install.md", None),
    ("docs/requirements.md", None),
    ("docs/data-model.md", None),
    ("docs/architecture.md", None),
    ("docs/interfaces.md", None),
    ("docs/build-plan.md", None),
    ("docs/release-process.md", None),
    ("docs/decisions.md", None),
]
TRAILING: list[tuple[str, str | None]] = [
    ("LICENSE.md", "Licence"),
    ("CLAUDE.md", None),
]
RELEASES = PurePosixPath("docs/releases")
RELEASES_HEADING = "Releases"
TRAILING_HEADING = "Project"

# Every picture in these directories is published, whether a page shows it or not, so a
# link to one keeps working from another site. A picture elsewhere joins when a page
# shows it.
IMAGE_DIRS = ("images", "docs/images")
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}

# The mark beside the name in the top bar, which is also the site's icon.
LOGO = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
    '<defs><linearGradient id="hirdir-mark" x1="0" y1="0" x2="1" y2="1">'
    '<stop offset="0" stop-color="#1fd2ff"/><stop offset=".55" stop-color="#1f5fe0"/>'
    '<stop offset="1" stop-color="#7440f0"/></linearGradient></defs>'
    '<rect width="32" height="32" rx="9" fill="url(#hirdir-mark)"/>'
    '<rect x="8" y="8" width="16" height="4" rx="1.5" fill="#fff"/>'
    '<rect x="8" y="14" width="16" height="4" rx="1.5" fill="#fff" opacity=".82"/>'
    '<rect x="8" y="20" width="16" height="4" rx="1.5" fill="#fff" opacity=".64"/>'
    "</svg>"
)

GITHUB_MARK = (
    '<svg class="mark" viewBox="0 0 16 16" aria-hidden="true" focusable="false">'
    '<path fill="currentColor" d="M8 0c4.42 0 8 3.58 8 8a8.013 8.013 0 0 1-5.45 7.59c-.4.08'
    "-.55-.17-.55-.38 0-.27.01-1.13.01-2.2 0-.75-.25-1.23-.54-1.48 1.78-.2 3.65-.88 3.65-3.95 "
    "0-.88-.31-1.59-.82-2.15.08-.2.36-1.02-.08-2.12 0 0-.67-.22-2.2.82-.64-.18-1.32-.27-2-.27-.68 "
    "0-1.36.09-2 .27-1.53-1.03-2.2-.82-2.2-.82-.44 1.1-.16 1.92-.08 2.12-.51.56-.82 1.28-.82 2.15 "
    "0 3.06 1.86 3.75 3.64 3.95-.23.2-.44.55-.51 1.07-.46.21-1.61.55-2.33-.66-.15-.24-.6-.83-1.23"
    "-.82-.67.01-.27.38.01.53.34.19.73.9.82 1.13.16.45.68 1.31 2.69.94 0 .67.01 1.3.01 1.49 0 "
    '.21-.15.45-.55.38A7.995 7.995 0 0 1 0 8c0-4.42 3.58-8 8-8Z"/></svg>'
)

# A build leaves this file in its output directory. It makes GitHub Pages publish the files
# exactly as written, and it tells the next build that the directory is its own to clear.
MARKER = ".nojekyll"

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>{title}</title>
<meta name="description" content="{description}">
<link rel="icon" href="{root}assets/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="{root}assets/docs.css?v={css_version}">
</head>
<body>
<a class="skip" href="#content">Skip to content</a>
<header class="topbar">
  <div class="topbar-inner">
    <a class="brand" href="{home}">{logo}<span class="brand-name">{name}</span>\
<span class="brand-tag">docs</span></a>
    <a class="repo" href="{repo}">{github}<span class="wide">Source on GitHub</span>\
<span class="narrow">GitHub</span></a>
  </div>
</header>
<div class="layout">
  <nav class="sidebar" aria-label="Documentation">
{nav}
  </nav>
  <main id="content" class="doc">
    <article class="prose">
{body}    </article>
    <footer class="page-foot">
      <a href="{source}">View {src} on GitHub</a>
    </footer>
  </main>
</div>
</body>
</html>
"""


def output_path(src: PurePosixPath) -> PurePosixPath:
    """README.md is its directory's index; everything else keeps its name as .html."""
    if src.name == "README.md":
        return src.parent / "index.html"
    return src.with_suffix(".html")


def relative(target: PurePosixPath, start: PurePosixPath) -> str:
    """The relative URL that leads from the directory ``start`` to ``target``."""
    return posixpath.relpath(str(target), str(start))


def slugify(text: str) -> str:
    """GitHub's heading anchors (github-slugger): lower case, punctuation dropped."""
    return re.sub(r"[^\w\- ]", "", text.lower()).replace(" ", "-")


def release_key(src: PurePosixPath) -> tuple[tuple[int, ...], bool, str] | None:
    """The sort key of a release notes file, or None for any other file.

    docs/releases/v0.10.0.md sorts above v0.9.0.md, because the numbers are compared as
    numbers. A pre-release such as v1.0.0-rc1 sorts below v1.0.0.
    """
    if src.parent != RELEASES:
        return None
    found = re.fullmatch(r"v(\d+(?:\.\d+)*)(.*)", src.stem)
    if not found:
        return None
    numbers = tuple(int(part) for part in found[1].split("."))
    return numbers, not found[2], found[2]


def plain(inline: Token) -> str:
    """The visible text of an inline token, without markup. A line break reads as a space."""
    parts = []
    for child in inline.children or []:
        if child.type in ("text", "code_inline"):
            parts.append(child.content)
        elif child.type in ("softbreak", "hardbreak"):
            parts.append(" ")
    return "".join(parts).strip()


def highlight_code(code: str, lang: str, _attrs: str) -> str:
    """Colour a fenced block. A language Pygments does not know is shown as plain text."""
    try:
        lexer = get_lexer_by_name(lang or "text")
    except ClassNotFound:
        lexer = get_lexer_by_name("text")
    return highlight(code, lexer, HtmlFormatter(nowrap=True))


def render_heading_close(self: Any, tokens: list[Token], idx: int, options: Any, env: Any) -> str:
    token = tokens[idx]
    anchor = token.meta.get("anchor")
    link = ""
    if anchor and token.tag != "h1":
        link = f'<a class="anchor" href="#{anchor}" aria-label="Link to this section">#</a>'
    return f"{link}</{token.tag}>\n"


def render_table_open(self: Any, tokens: list[Token], idx: int, options: Any, env: Any) -> str:
    # The wrapper scrolls a wide table sideways, so the table itself can fill the column.
    return '<div class="table-wrap">\n' + self.renderToken(tokens, idx, options, env)


def render_table_close(self: Any, tokens: list[Token], idx: int, options: Any, env: Any) -> str:
    return self.renderToken(tokens, idx, options, env) + "</div>\n"


def discover(root: Path) -> list[PurePosixPath]:
    """Every Markdown file under ``root``, leaving out hidden and skipped directories."""
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d not in SKIP_DIRS)
        found += [
            PurePosixPath(Path(dirpath, name).relative_to(root).as_posix())
            for name in filenames
            if name.endswith(".md")
        ]
    return found


def pictures(root: Path) -> set[PurePosixPath]:
    """The pictures in the image directories, which are published whole."""
    found: set[PurePosixPath] = set()
    for directory in IMAGE_DIRS:
        for path in (root / directory).rglob("*"):
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
                found.add(PurePosixPath(path.relative_to(root).as_posix()))
    return found


@dataclass
class Page:
    src: PurePosixPath
    label: str = ""
    title: str = ""
    description: str = ""
    body: str = ""
    ids: set[str] = field(default_factory=set)
    sections: list[tuple[str, str]] = field(default_factory=list)

    @property
    def out(self) -> PurePosixPath:
        return output_path(self.src)

    @property
    def root(self) -> str:
        return "../" * (len(self.out.parts) - 1)


class Site:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.repo = REPO
        # GitHub's tables and strikethrough, and task lists ("- [x] done") as checkboxes.
        self.md = (
            MarkdownIt("commonmark", {"highlight": highlight_code})
            .enable(["table", "strikethrough"])
            .use(tasklists_plugin)
        )
        self.md.add_render_rule("heading_close", render_heading_close)
        self.md.add_render_rule("table_open", render_table_open)
        self.md.add_render_rule("table_close", render_table_close)

        labels = dict(LEADING + TRAILING)
        found = set(discover(root))
        lead = [PurePosixPath(p) for p, _ in LEADING if PurePosixPath(p) in found]
        tail = [PurePosixPath(p) for p, _ in TRAILING if PurePosixPath(p) in found]
        keys = {src: key for src in found if (key := release_key(src)) is not None}
        releases = sorted(keys, key=lambda src: keys[src], reverse=True)
        middle = sorted(found - set(lead) - set(tail) - set(releases))
        # The navigation: each group is a heading, or None, and the pages beneath it.
        self.groups: list[tuple[str | None, list[PurePosixPath]]] = [
            (None, lead + middle),
            (RELEASES_HEADING, releases),
            (TRAILING_HEADING, tail),
        ]
        self.pages = {
            src: Page(src, label=labels.get(str(src)) or (src.stem if src in keys else ""))
            for _, sources in self.groups
            for src in sources
        }
        self.assets: set[PurePosixPath] = pictures(root)
        self.anchors: list[tuple[Page, PurePosixPath, str, str]] = []
        self.problems: list[str] = []

    # ---- rendering -------------------------------------------------------------------

    def render(self) -> None:
        for page in self.pages.values():
            tokens = self.md.parse((self.root / page.src).read_text(encoding="utf-8"))
            self._annotate(page, tokens)
            page.body = self.md.renderer.render(tokens, self.md.options, {})
            page.label = page.label or page.title or page.src.stem
        for page, target, fragment, href in self.anchors:
            if fragment not in self.pages[target].ids:
                self.problems.append(f"{page.src}: no heading for #{fragment} in {target} ({href})")

    def _annotate(self, page: Page, tokens: list[Token]) -> None:
        seen: set[str] = set()
        for i, token in enumerate(tokens):
            if token.type == "heading_open":
                text = plain(tokens[i + 1])
                base = slug = slugify(text)
                n = 0
                while slug in seen:
                    n += 1
                    slug = f"{base}-{n}"
                seen.add(slug)
                page.ids.add(slug)
                token.attrSet("id", slug)
                tokens[i + 2].meta["anchor"] = slug
                if token.tag == "h1" and not page.title:
                    page.title = text
                elif token.tag == "h2":
                    page.sections.append((slug, text))
            elif token.type == "paragraph_open" and not page.description:
                page.description = " ".join(plain(tokens[i + 1]).split())[:200]
            elif token.type == "inline":
                for child in token.children or []:
                    if child.type == "link_open":
                        child.attrSet("href", self._link(page, str(child.attrGet("href"))))
                    elif child.type == "image":
                        child.attrSet("src", self._link(page, str(child.attrGet("src")), True))

    def _link(self, page: Page, href: str, image: bool = False) -> str:
        parts = urlsplit(href)
        if parts.scheme or parts.netloc:
            return href
        fragment = parts.fragment
        if not parts.path:
            if fragment:
                self.anchors.append((page, page.src, fragment, href))
            return href

        path = unquote(parts.path)
        joined = path.lstrip("/") if path.startswith("/") else posixpath.join(page.src.parent, path)
        target = PurePosixPath(posixpath.normpath(joined))
        if target.parts and target.parts[0] == "..":
            self.problems.append(f"{page.src}: {href} points outside the repository")
            return href
        on_disk = self.root / target
        suffix = f"#{fragment}" if fragment else ""

        if image:
            if on_disk.is_file():
                self.assets.add(target)
                return quote(relative(target, page.out.parent)) + suffix
            self.problems.append(f"{page.src}: image {href} does not exist")
            return href
        if target in self.assets:
            return quote(relative(target, page.out.parent)) + suffix
        if on_disk.is_dir() and target / "README.md" in self.pages:
            target = target / "README.md"
        if target in self.pages:
            if fragment:
                self.anchors.append((page, target, fragment, href))
            return quote(relative(self.pages[target].out, page.out.parent)) + suffix
        if on_disk.is_file():
            return f"{self.repo}/blob/{BRANCH}/{quote(str(target))}{suffix}"
        if on_disk.is_dir():
            return f"{self.repo}/tree/{BRANCH}/{quote(str(target))}"
        self.problems.append(f"{page.src}: link {href} does not resolve")
        return href

    # ---- output ----------------------------------------------------------------------

    def _nav(self, current: Page) -> str:
        def items(sources: list[PurePosixPath]) -> str:
            out = []
            for src in sources:
                page = self.pages[src]
                href = quote(relative(page.out, current.out.parent))
                mark = ' aria-current="page"' if page is current else ""
                toc = ""
                if page is current and page.sections:
                    links = "".join(
                        f'<li><a href="#{sid}">{html.escape(text)}</a></li>'
                        for sid, text in page.sections
                    )
                    toc = f'<ul class="toc">{links}</ul>'
                out.append(f'<li><a href="{href}"{mark}>{html.escape(page.label)}</a>{toc}</li>')
            return "".join(out)

        parts = []
        for heading, sources in self.groups:
            if not sources:
                continue
            if heading:
                parts.append(f'    <p class="group">{html.escape(heading)}</p>')
            parts.append(f'    <ul class="pages">{items(sources)}</ul>')
        return "\n".join(parts)

    def write(self, out: Path) -> None:
        css = CSS.read_text(encoding="utf-8")
        logo = LOGO.replace("<svg ", '<svg class="logo" aria-hidden="true" focusable="false" ', 1)
        rendered = {}
        for page in self.pages.values():
            title = (
                f"{NAME} documentation"
                if page.src == PurePosixPath("README.md")
                else f"{page.title or page.label} · {NAME} docs"
            )
            rendered[page.out] = PAGE.format(
                title=html.escape(title),
                description=html.escape(page.description, quote=True),
                root=page.root,
                css_version=hashlib.sha256(css.encode()).hexdigest()[:10],
                home=quote(relative(PurePosixPath("index.html"), page.out.parent)),
                logo=logo,
                name=NAME,
                repo=html.escape(self.repo),
                github=GITHUB_MARK,
                nav=self._nav(page),
                body=page.body,
                source=html.escape(f"{self.repo}/blob/{BRANCH}/{quote(str(page.src))}"),
                src=html.escape(str(page.src)),
            )

        # Everything is rendered before the output directory is touched, so a failure
        # leaves it intact. The directory itself stays, because it may be a symlink target.
        out.mkdir(parents=True, exist_ok=True)
        for child in out.iterdir():
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
        for path, text in rendered.items():
            (out / path).parent.mkdir(parents=True, exist_ok=True)
            (out / path).write_text(text, encoding="utf-8")
        (out / "assets").mkdir(exist_ok=True)
        (out / "assets" / "docs.css").write_text(css, encoding="utf-8")
        (out / "assets" / "favicon.svg").write_text(LOGO + "\n", encoding="utf-8")
        for asset in self.assets:
            (out / asset).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.root / asset, out / asset)
        (out / MARKER).write_text("")


def refusal(root: Path, out: Path, sources: list[PurePosixPath]) -> str | None:
    """Why ``out`` must not be cleared and written to, or None when it is safe."""
    resolved = out.resolve()
    if any((root / src).resolve().is_relative_to(resolved) for src in sources):
        return f"refusing to write into {out}: it contains the Markdown sources"
    if out.is_dir() and any(out.iterdir()) and not (out / MARKER).exists():
        return (
            f"refusing to write into {out}: it holds files that an earlier build did not "
            "write; empty it first or choose another directory"
        )
    return None


def build(out: Path, root: Path = ROOT) -> tuple[bool, set[Path]]:
    """Render the site into ``out``. Returns success and the files it was built from."""
    site = Site(root)
    reason = refusal(root, out, list(site.pages))
    if reason:
        sys.exit(reason)
    site.render()
    site.write(out)
    inputs = {root / src for src in site.pages} | {root / a for a in site.assets}
    print(f"{out}: {len(site.pages)} pages, {len(site.assets)} images", file=sys.stderr)
    for problem in site.problems:
        print(f"  error: {problem}", file=sys.stderr)
    return not site.problems, inputs | {CSS}


def watch(out: Path, inputs: set[Path]) -> None:
    """Rebuild whenever a source, a picture, the style sheet or this script changes."""
    script = Path(__file__).resolve()

    def snapshot() -> dict[Path, float]:
        files = inputs | {script}
        files |= {ROOT / src for src in discover(ROOT)} | {ROOT / p for p in pictures(ROOT)}
        return {f: f.stat().st_mtime for f in files if f.exists()}

    print("watching for changes (Ctrl-C to stop)", file=sys.stderr)
    seen = snapshot()
    while True:
        time.sleep(1)
        now = snapshot()
        if now == seen:
            continue
        if now.get(script) != seen.get(script):
            # A running script cannot take up its own changes, so it stops and says so.
            print(f"{script.name} changed; start it again to use the new version", file=sys.stderr)
            return
        _, inputs = build(out)
        seen = snapshot()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "html", help="output directory")
    parser.add_argument("--watch", action="store_true", help="rebuild when a source changes")
    args = parser.parse_args(argv)
    ok, inputs = build(args.out)
    if args.watch:
        try:
            watch(args.out, inputs)
        except KeyboardInterrupt:
            return 0
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
