# Release process

How a release of `hirdir` is cut, what its notes contain, and how the documentation is
published. The tooling follows the author's `texas2step` project, with Python shipped
inside the package and line counts taken with `cloc`.

## Version

`hirdir` uses semantic versions. The one place the version is written is
`src/hirdir/__init__.py`:

```python
__version__ = "0.4.1"
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
2. `uv lock --upgrade`, then `uv sync --all-groups`.
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
   the package in containers and runs every package check, the upgrade from the
   previous release among them, and the browser scenarios; `make package-test` is the
   same without the browser. See "The previous release's package" below. `make deb`
   builds the web UI and the documentation first, because the package carries both.
4. `make facts > /tmp/facts.md`, and write `docs/releases/v<version>.md` from the
   template below.
5. `make docs`, and read the built pages once. Then `make deb` and `make package-test`
   once more: the package carries the notes of its own release, so the one that is
   published is built after they are written, and it is the one that was tested.
6. Commit, tag `v<version>`, push.
7. `make -s release-body > /tmp/body.md`, then
   `gh release create v<version> --notes-file /tmp/body.md` with
   `dist/hirdir_<version>_amd64.deb` and `dist/hirdir_<version>_amd64.deb.sha256`
   attached. The text of the release is the notes with each paragraph on one line;
   see "The text of the GitHub release" below. `make deb` writes both. `hirdir-setup --upgrade` on every installation
   looks for exactly these two names on the latest release, so a release without them
   is one that no installation can fetch.

Pushing to `main` publishes the documentation. Nothing else is automatic.

### The previous release's package

A release is not done until `make package-test` has upgraded the previous release to
it. The test installs the previous release in a container, fills it with accounts, a
group, a role grant, a service token, an inventory and audit events, upgrades it with
apt, and checks that all of it is still there and still works. The inventory is made
for what an upgrade could harm, through the API of the previous release, of every kind
of record that release can store: items with every kind of value between them, a draft
and a retired one among them, minor items, stacks, clusters and a controller domain
with their members, memberships that were ended, a replacement, conditions and
observations, networks, addresses, and choices of the site's own. After the upgrade
each item, group, membership, address and choice must be as it was, field for field,
at the `row_version` it had, each item with its history, and the tables of the
inventory are read from the database file as well, their columns, rows, indexes and
uniquenesses.

The test is written for no pair of releases. It reads from the two packages which
versions they are and which revision the migrations of each end at, and so whether the
upgrade runs a migration, and which. What a release has to do for it follows from
what the release is:

- **A release with no migration does nothing.** Nothing that is held may change: every
  table of the inventory must have the columns and the rows it had, the schema must be
  the same statement for statement, and the audit trail must hold no event of the
  upgrade.
- **A release with a migration adds one file**,
  `packaging/package-test.d/migration-<revision>.sh`, and changes nothing else. The
  file makes, with the previous release, what the migration could harm or is meant to
  change in what a site has. It names what is meant to change, so that the comparison
  leaves it out by name, and looks at it by itself after the upgrade. It names the
  columns, indexes and foreign keys that the migration adds to the tables of the
  inventory, which must then be there, and no other. `migration-0006.sh` is the one to
  read first: for 0.4.1 it is the memberships of items that had left the team's hands,
  which the upgrade ends, each with an event in the audit trail. For 0.5.0 it is
  `migration-0007.sh`: the migration is to change no record and to write no event, so
  the file makes what it could harm, an item that is with an owner outside the team
  and choices of a site's own in the two lists that the migration loads, and then
  holds the upgrade to what [install.md](install.md#from-042-to-050) says of it. Where a migration
  provides for something the previous release could not store, the file shows that it
  could not, writes it into the database, and says so: 0.4.0 refuses a choice in the
  list of conditions, which migration `0006` is written to leave alone when it finds
  one. Until the file is there the migration is given what every upgrade is given, and
  both upgrade passes print a `SKIP` line that says its own checks are not written. A
  release is not done with that line in its summary.
- **A release that says or reads differently something that it holds as before**, with
  no migration, adds `release-<version>.sh` in the same place, and it is treated in the
  same way. Most releases have none. For 0.4.2 it is the reason given for a health
  that is not known, and how a time with no zone is read: the test keeps a moment that
  0.4.1 stored from such a time, and sees that the upgrade leaves it the moment it was.
- **A release that brings a new kind of record** adds it to the inventory in
  `packaging/package-test.sh`, to be made where the previous release is at the revision
  that brought it. That is for the upgrades to come, which then carry it: the upgrade
  to the release itself starts from a release that could not store it.

The test also makes the new version's migration fail, to see that the upgrade stops,
names its backup, leaves the inventory as it was and can be undone. It does that in
the database, so that the package tested is the one that was built, and reads from the
package how. Where the new version creates a table, the table it creates last is put
in its way, as `owner_members` is for 0.5.0. Where it creates none, as 0.4.1 creates
none, a trigger refuses the new
revision when the migration comes to write it down, which is the last thing a
migration does, so everything else it does has been done and must be undone. Only a
release with no migration at all has nothing that could fail: nothing writes a
revision, so the trigger would never be asked. The pass then says so in a `SKIP` line,
which stays in the summary of such a release, as it does for 0.4.2, and is read as
what it is. It goes on to upgrade and to go back by installing the previous package
alone, with nothing restored, because that is the way back that
[install.md](install.md#going-back-to-the-release-before) gives for a release that
changed no schema. The passes, and what a file of `packaging/package-test.d/` holds,
are described under "Testing" in [architecture.md](architecture.md#testing).

The run ends with its counts and with every `FAIL` and `SKIP` line once more. Read each
`SKIP` line before a release: it names something that this run did not test.

The previous package is found in this order:

1. The file that `PREVIOUS_DEB` names, when it is set, as in
   `PREVIOUS_DEB=dist/hirdir_0.1.0_amd64.deb make package-test`.
2. Otherwise the `hirdir_*_amd64.deb` in `dist/` with the highest version below the
   one being built. `make deb` replaces only the package of its own version, so the
   package of each release stays in `dist/` once it is there.
3. Otherwise there is nothing to upgrade from. `make package-test` skips the upgrade,
   says so in a `SKIP` line, and tests the fresh install. Before a release, read the
   summary: a release is done when the upgrade was tested, not skipped.

`dist/` is not committed. On a checkout that does not have the previous package, fetch
it from its release, with its checksum, which the test compares when it is there:

```bash
gh release download v<previous version> --dir dist --pattern 'hirdir_*_amd64.deb*'
```

`packaging/package-test.sh --fresh` runs the fresh install alone, for work on the
package between releases. It prints a `SKIP` line for the upgrade and is not the
release check. `packaging/package-test.sh --upgrade-alone` runs the upgrade pass up to
where it goes on to what the fresh pass does, for work on the upgrade passes and for
trying a pair of older releases named by `PREVIOUS_DEB` and `DEB`. It prints a `SKIP`
line for what it left out and is not the release check either.

## Release notes

One file per release, `docs/releases/v<version>.md`, which is also the text of the
GitHub release, given to GitHub by `make release-body`. The form:

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

### The text of the GitHub release

The file of the notes is wrapped like every other page. GitHub shows a file of the
repository with a line break inside a paragraph as a space, and shows the text of a
release as it shows a comment, where the same line break ends the line. Given the file
as it is, a release shows its paragraphs at half the width of the page, each line
ending where the file wrapped it, beside the few lines that were never wrapped, such
as the sentence under the lines-of-code table.

`make release-body` prints the notes as GitHub takes them: every paragraph and every
list item on one line, with headings, tables, code and the collapsed block as they
are. A link to another page, such as `../install.md#upgrade`, would lead nowhere from
a release, and becomes a link to that file at the release's tag. Nothing else is
changed, and the file in `docs/releases/` stays as it is.

```bash
make -s release-body > /tmp/body.md                 # the version of the tree
make -s release-body VERSION=0.3.0 > /tmp/body.md   # an earlier one
gh release edit v0.3.0 --notes-file /tmp/body.md    # to correct a release that is out
```

## `make facts`

`scripts/release_facts.py` prints the two tables.

**Lines of code** runs `cloc --vcs=git --json` on the tagged tree and splits each
language's code lines into three columns by path: Product (`src/`, `web/`,
`packaging/` files that are installed), Tests (`tests/`, `web/**/*.test.*`) and Tooling
(`scripts/`, the Makefile, build and CI files). Generated files and lock files are left
out: the built web UI, the OpenAPI document in `contract/`, and the CSV and JSON files
of `examples/`, which `make examples` writes.

**Versions** is read from what was built, not from what was asked for: the interpreter
and the installed packages inside the `.deb`, `sqlite3.sqlite_version` from that
interpreter, `web/package-lock.json`, and the tools' own `--version`. The direct
dependencies are named; the rest are counted, with the full list in a collapsed block
beneath the table.

- The package read is `dist/hirdir_<version>_amd64.deb`, of the version in
  `src/hirdir/__init__.py`, and no other: the previous release's package also lies in
  `dist/`, for the upgrade test. Without the package of this version the Python rows
  come from `.python-version` and `uv.lock`, and a line on standard error says so.
- The Python packages are the ones the package installs, so a package that only the
  development or the documentation group asks for, such as pytest, ruff or ty, never
  appears. The direct dependencies are those of `pyproject.toml`. `regex` joins them
  with 0.2.0. With 0.3.0 so does httpx2, which the command line calls the API with: it
  takes the place of httpx, and brings httpcore2 where httpx brought httpcore.
- Read from `uv.lock`, the packages are those that are installed on Linux. A package
  that another one asks for on some other platform alone is left out, as it is from
  the `.deb`: httpx2 asks for one in a browser.
- The web UI's row names TypeScript, Vite and React, and AG Grid Community beside them
  once `web/package-lock.json` installs `ag-grid-community`. Its binding for React,
  `ag-grid-react`, is published at the grid's version and is not named apart; if the
  lock ever holds the two at different versions, the row gives both. A package the lock
  does not install is left out of the row, and a line on standard error says so.

## Documentation

Every Markdown file in the repository is published as an HTML page.

- `scripts/build_docs.py` renders them into `html/` (not committed). `README.md`
  becomes `index.html`; `docs/x.md` becomes `docs/x.html`. A `README.md` in a directory
  is that directory's `index.html`, so `examples/README.md` becomes
  `examples/index.html`. Each page gets the same navigation and a link back to the
  repository.
- A link to a file that is not a page, such as a CSV file of `examples/`, leads to the
  file on GitHub.
- Links between Markdown files are rewritten to the pages. A link or anchor that does
  not resolve fails the build.
- Pictures live in `images/` at the top of the repository and are used with a relative
  link from any page: `![Lifecycle](images/lifecycle-workflow.png)` in `README.md`,
  `../images/...` from `docs/`. PNG and JPEG are copied to the site as they are, so the
  same link works on GitHub and on the published page.
- The pages use relative URLs and no JavaScript, so they work on GitHub Pages, under any
  path behind a web server, from `/usr/share/doc/hirdir/html/`, where the package puts
  them, and straight from a folder.
- `.github/workflows/docs.yml` builds and deploys to GitHub Pages on each push to
  `main` that touches Markdown or images.
- `make docs` builds locally; `make docs-watch` rebuilds on change.
- Navigation order is the `LEADING` and `TRAILING` lists at the top of the script.
  Examples comes after Interfaces, which describes the files. A page that is in neither
  list follows the leading ones, by its path. Release notes are listed newest first
  under one heading.

## Publishing rule

The repository is public. Before anything is committed:

- No name, address, host name, serial number, contract number, count or screenshot from
  a real network. Examples follow the "Example data" section of
  [requirements.md](requirements.md).
- No secret of any kind, including in test fixtures.
- `make check` scans the tracked files for each term in `.publish-guard`, one term per
  line. That file is listed in `.gitignore` and is never committed, because it names
  exactly the words that must not be published. A maintainer keeps their own copy.
