# Release process

How a release of `hirdir` is cut, what its notes contain, and how the documentation is
published. The tooling follows the author's `texas2step` project, with Python shipped
inside the package and line counts taken with `cloc`.

## Version

`hirdir` uses semantic versions. The one place the version is written is
`src/hirdir/__init__.py`:

```python
__version__ = "0.1.0"
```

The build reads it from there. `make version` prints it. Releases before 1.0.0 are the
steps of [build-plan.md](build-plan.md); 1.0.0 is the MVP.

## Dependency rule

**Every release uses the latest production release of every component.** Not a
pre-release, not a beta, not a release candidate. This covers Python itself, every
Python package, Node, every npm package, the base image of the build container, uv,
ruff, ty and the build tools.

`make upgrade` does the work:

1. `uv python install` the newest production CPython, and set it in `.python-version`.
2. `uv lock --upgrade`, then `uv sync`.
3. Every npm dependency to `@latest`, saved exact.
4. Rebuild the web UI.
5. `make check`.

**Waiver.** If a new version causes a fault in testing that is not readily overcome, it
is held at the last good version for this release only, and the release notes say so
under Additional Notes: the component, the version held, the version skipped and the
fault. The hold is recorded in `docs/waivers.md` and is tried again at the next release.
A hold is never left in place silently.

## Steps

1. `make upgrade`.
2. Set the version.
3. `make check`, `make acceptance`, `make docs`, `make deb`, `make e2e`. The last installs
   the package in a container and runs every package check and the browser scenarios;
   `make package-test` is the same without the browser.
4. `make facts > /tmp/facts.md`, and write `docs/releases/v<version>.md` from the
   template below.
5. `make docs`, and read the built pages once.
6. Commit, tag `v<version>`, push.
7. `gh release create v<version> --notes-file docs/releases/v<version>.md` with the
   `.deb` and its SHA-256 attached.

Pushing to `main` publishes the documentation. Nothing else is automatic.

## Release notes

One file per release, `docs/releases/v<version>.md`, which is also the text of the
GitHub release. The form:

```markdown
# hirdir 0.4.0

One to three sentences that say what this release is.

## New
## Changed
## Fixes
## Additional Notes

## Lines of code

| Language | Files | Code | Comments | Product | Tests | Tooling |
|---|--:|--:|--:|--:|--:|--:|
| Python | | | | | | |
| TypeScript | | | | | | |
| **All** | | | | | | |

## Versions

| Part | Version |
|---|---|
| Python, shipped in the package | 3.15.2 |
| Its Python packages | fastapi x.y.z, sqlalchemy x.y.z, ... and the N they need |
| SQLite, as built into that Python | x.y.z |
| TypeScript, Vite, React (and AG Grid Community from 0.2.0) | ... |
| Node, which builds the web UI | ... |
| uv, ruff, ty | ... |
| The build and test container's base | ubuntu:26.04 |
```

Rules for the notes:

- The summary is always there. Of New, Changed, Fixes and Additional Notes, only the
  sections that have something to say appear.
- Lines of code and Versions are always there, and are pasted from `make facts`, never
  typed.
- Entries say what a person using `hirdir` will notice, in plain words.
- A waiver from the dependency rule goes under Additional Notes.

## `make facts`

`scripts/release_facts.py` prints the two tables.

**Lines of code** runs `cloc --vcs=git --json` on the tagged tree and splits each
language's code lines into three columns by path: Product (`src/`, `web/`,
`packaging/` files that are installed), Tests (`tests/`, `web/**/*.test.*`) and Tooling
(`scripts/`, the Makefile, build and CI files). Generated files and lock files are left
out.

**Versions** is read from what was built, not from what was asked for: the interpreter
and the installed packages inside the `.deb`, `sqlite3.sqlite_version` from that
interpreter, `web/package-lock.json`, and the tools' own `--version`. The direct
dependencies are named; the rest are counted, with the full list in a collapsed block
beneath the table.

## Documentation

Every Markdown file in the repository is published as an HTML page.

- `scripts/build_docs.py` renders them into `html/` (not committed). `README.md`
  becomes `index.html`; `docs/x.md` becomes `docs/x.html`. Each page gets the same
  navigation and a link back to the repository.
- Links between Markdown files are rewritten to the pages. A link or anchor that does
  not resolve fails the build.
- Pictures live in `images/` at the top of the repository and are used with a relative
  link from any page: `![Lifecycle](images/lifecycle-workflow.png)` in `README.md`,
  `../images/...` from `docs/`. PNG and JPEG are copied to the site as they are, so the
  same link works on GitHub and on the published page.
- The pages use relative URLs and no JavaScript, so they work on GitHub Pages, under any
  path behind a web server, from `/usr/share/doc/hirdir/` and straight from a folder.
- `.github/workflows/docs.yml` builds and deploys to GitHub Pages on each push to
  `main` that touches Markdown or images.
- `make docs` builds locally; `make docs-watch` rebuilds on change.
- Navigation order is the `LEADING` and `TRAILING` lists at the top of the script.
  Release notes are listed newest first under one heading.

## Publishing rule

The repository is public. Before anything is committed:

- No name, address, host name, serial number, contract number, count or screenshot from
  a real network. Examples follow the "Example data" section of
  [requirements.md](requirements.md).
- No secret of any kind, including in test fixtures.
- `make check` scans the tracked files for each term in `.publish-guard`, one term per
  line. That file is listed in `.gitignore` and is never committed, because it names
  exactly the words that must not be published. A maintainer keeps their own copy.
