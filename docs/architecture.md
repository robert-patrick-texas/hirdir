# Architecture

How `hirdir` is built, packaged and run. The records are in
[data-model.md](data-model.md) and the interfaces in [interfaces.md](interfaces.md).

## Shape

```text
browser ──HTTPS──┐
hirdir CLI ──────┤   nginx (Ubuntu's)            hirdir.service
integrations ────┘   terminates TLS,      ──▶    one Python process       ──▶  SQLite file
                     strips the prefix           FastAPI: API + web UI         /var/lib/hirdir
```

One process serves both the API and the built web UI. nginx does TLS and nothing else
of ours. There is no second service, no queue and no cache in the MVP.

## Components

| Part | Choice | Notes |
|---|---|---|
| Operating system | Ubuntu 26.04 LTS, amd64 | |
| Python | 3.15.2, shipped inside the package | moves to each new production release; 3.16 when it is released |
| Python tooling | uv, ruff, ty | uv for the lock, the environment and the bundled interpreter |
| Server | FastAPI on Uvicorn, Pydantic models | one worker |
| Database access | SQLAlchemy 2 with Alembic migrations | |
| Database | SQLite in WAL mode | PostgreSQL as an option LATER |
| CLI | Typer, with httpx2 to call the API | same package as the server; httpx2 is the continuation of httpx under Pydantic |
| Web UI | TypeScript, React, built with Vite | npm; Node is needed to build, never to run |
| Grid | AG Grid Community | infinite row model: the server sorts, filters and pages |
| Reverse proxy | nginx from Ubuntu | not shipped by `hirdir` |

Every component is taken at its latest production release when a release of `hirdir` is
cut. See [release-process.md](release-process.md).

## Repository layout

```text
src/hirdir/
  __init__.py        the version, and nothing else
  app.py             application factory, middleware, static UI
  config.py          /etc/hirdir/config.toml and its defaults
  db/                engine, models, dialect helpers, migrations/
  domain/            the rules: inheritance, lifecycle, matching, counting, geography
  api/               routers under /api/v1, one module per record type
  auth/              providers (local now; RADIUS and SAML later), tokens, roles
  io/                filter grammar, CSV and JSON import and export
  cli/               the hirdir command: client commands and `hirdir admin`
  static/            the built web UI (generated, not committed)
web/                 TypeScript source of the web UI
tests/               unit/, api/, acceptance/, e2e/
packaging/           build-deb.sh, control files, systemd units, nginx files, hirdir-setup, container/
scripts/             build_docs.py, docs.css, release_facts.py, release_body.py, seed_examples.py, seed_fixture.py
docs/                these pages, and releases/
images/              pictures used by README.md and docs/
examples/            fictional CSV and JSON for every record type
```

Routers hold no rules. A router parses the request, calls one function in `domain/` or
`io/`, and shapes the answer. That is what keeps the web UI, the API, the CLI and file
imports on one set of rules.

## URL prefix

`hirdir` can be served at the root of a host name or under any prefix, such as
`/hirdir/` or `/inventory/`. The prefix is written in one place, the nginx snippet:

```nginx
location ^~ /hirdir/ {
    proxy_pass http://hirdir/;                      # the trailing slash strips /hirdir
    client_max_body_size 20m;                       # an import is a file of up to 20 MB
    proxy_set_header X-Forwarded-Prefix /hirdir;
    proxy_set_header X-Forwarded-For   $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Host              $host;
}
```

nginx strips the prefix, so the application always sees `/`. The header tells the
application what was stripped. The application trusts it only from the proxy addresses
named in its configuration (the loopback address by default), sets the ASGI `root_path`
from it, and writes `<base href="/hirdir/">` into the page it serves. The web UI takes
its base from `document.baseURI` and uses relative URLs for everything, so deep links
work and nothing is rebuilt to change the prefix.

This is the way `texas2step` does it. The alternative used by `sunstone` and `segl`,
where the application never learns the prefix, is simpler but cannot produce correct
absolute links in the API documentation, in exports that carry URLs, or in a routed
single-page UI. See P-05 in [decisions.md](decisions.md).

## Access

### Signing in

1. The page posts a username and access code to `/api/v1/auth/sign-in`.
2. The server checks the code against an Argon2id hash and returns a session token and
   its expiry.
3. The page keeps the token in `localStorage` under `hirdir.session` and sends it as
   `Authorization: Bearer <token>` on every request.
4. Any `401` clears the stored token and shows the sign-in page.

No response ever sets a cookie, and a test asserts it for every route.

### The session token

A compact signed token (JWS, HMAC-SHA-256) carrying the user's HID, the time it was
issued in milliseconds, its expiry and a random ID. The signing key is 32 random bytes
in `/var/lib/hirdir/secret.key`, created at install and readable only by the service.

On every request the server checks the signature and the expiry, loads the user, and
refuses the token when the user is disabled or when the token was issued before the
user's `tokens_valid_after`. Roles are read from the database on each request and are
never in the token, so a change of role or group takes effect at once.

`tokens_valid_after` is set to now when an Admin resets the access code, disables the
account, or chooses "sign out everywhere". Replacing the signing key ends every session
of every user.

### Throttling

Access codes may be short in the MVP, so guessing is slowed on the server: after five
failures in a row for one username or from one address, each further failure doubles
the wait before another attempt is looked at, from one second up to five minutes. An
attempt made during the wait is refused with `429` and a `Retry-After` header, whether
or not its code is right. A successful sign-in clears the count. Failures and refusals
are audit events. The counts are held in memory, so a restart of the service clears
them.

### Service tokens

A service account is a user that cannot sign in with a code. An Admin creates named
tokens for it. A token is 32 random bytes with the prefix `hsv_`, shown once, stored as
a SHA-256 hash, sent as a bearer token like a session, and can carry an expiry and be
revoked alone.

An installation always keeps one person who holds Admin and can sign in: a change that
would remove the last one is refused.

### What comes later

`auth/` defines one interface, "check this username and secret, return who it is". The
local provider implements it for the MVP. RADIUS implements the same interface. SAML
adds a redirect flow that ends by issuing the same session token. Nothing outside
`auth/` knows which provider answered.

### What a browser fetches

The built web UI is a small first file and one file for each page, the grid among them.
A built file's name changes whenever its content does, so it is served with
`Cache-Control: public, max-age=31536000, immutable` and a browser asks for it once for
each release. The page itself and every answer of the API are `no-store`. Any answer
larger than a kilobyte is compressed with gzip when the browser accepts it, by the
application itself, so no nginx setting is needed for it. A page of a list shrinks to
about a tenth.

### Browser hardening

The token is readable by any script on the page, so no script from anywhere else is
allowed to run: `Content-Security-Policy: default-src 'self'; frame-ancestors 'none'`,
with the narrowest style allowance the grid needs. All front-end code and fonts ship in
the package. Requests are same-origin and CORS is off. Text from the inventory is
rendered as text, never as HTML.

## Database

- SQLite with `journal_mode=WAL`, `foreign_keys=ON`, `busy_timeout=5000`, set on every
  connection and checked by the readiness probe.
- One writer at a time. Imports and bulk edits validate first, then write in one short
  transaction.
- **Previews.** A preview of an import or a bulk edit is made by doing the work for
  real, through the same functions as any other change, inside a transaction that is
  then undone. What it reports is therefore what an apply will do, and no rule is
  written twice. Apply does the same work again, compares each row with what was
  previewed, and keeps the result only when they agree.

  SQLite has one writer at a time, and a transaction that writes holds every other
  writer up until it ends, also when it ends by being undone. A preview of more than a
  hundred rows is therefore worked on a copy of the database, made with SQLite's
  online backup in the service's private temporary directory and thrown away
  afterwards, so that nobody waits for a preview. An apply cannot be spared the same
  way: it is one transaction, and while it works, about five seconds for each thousand
  rows, another change waits. One that waits longer than `busy_timeout` is answered
  `503` with `Retry-After`, and nothing of it was done. Reading is never held up.
- Schema changes are Alembic migrations, applied by `hirdir admin migrate`.
- Everything that differs between SQLite and PostgreSQL lives in `db/dialect.py`:
  case-insensitive comparison, regular expression matching, and upsert. The test suite
  runs against SQLite; a PostgreSQL run is added with that option.
- **Regular expressions.** SQLite gets a matching function from the application. It
  uses a linear-time engine (RE2) when a production release of its Python binding
  exists for the Python in use, and otherwise the `regex` package with a per-match
  time limit. Patterns are at most 200 characters. A pattern that cannot be compiled or
  runs out of time is a `422`, never a stalled database.

  For Python 3.15 it is the `regex` package: `google-re2`, the binding from the RE2
  project, has no release for it yet. One match may take 50 ms, and all the matches of
  one request together one second. Compiling is bounded too: the counted repeats of a
  pattern, `{n}` and `{n,m}`, multiplied together, may come to at most 100, because a
  pattern such as `(?:a{3000}){3000}` costs gigabytes before any match is tried.
- **Text without regard to case.** Text is compared as if it were all in lower case.
  SQLite's own `lower()` knows the letters A to Z only, so the application gives SQLite
  one that knows every alphabet, and every comparison and sort of text goes through
  it. PostgreSQL uses its `lower()`.
- **Writes.** A request's changes are committed when its route returns and before any
  of the answer is sent. Every update of a row names the `row_version` it was read at.
- **Backup.** `hirdir admin backup` uses SQLite's online backup into
  `/var/lib/hirdir/backups/`, and a daily timer keeps the last 14. A backup is named
  for when it was made, in the application's time zone with its offset from UTC:
  `hirdir-20261111T210000-0500.db`. Which are the last 14 is told from the moment in
  each name, so a change of time zone, or the hour that comes twice in the autumn, puts
  none out of order. `hirdir admin restore
  FILE` puts one back. Copying backups off the host is the host's job.
- **Reset.** `hirdir admin reset` is the one place where records are deleted. It is a
  command on the server, with no route behind it, and runs only while the service is
  stopped, after a backup. Every table is named in `domain/reset.py` as one that a
  reset clears or one that it keeps, and a test fails when a new table is in neither.

## Package

`make deb` builds `hirdir_<version>_amd64.deb` in a clean Ubuntu 26.04 container with
`dpkg-deb`, and checks it with `lintian`.

| Path | Content |
|---|---|
| `/opt/hirdir/python/` | CPython, a standalone build installed with `uv python install` |
| `/opt/hirdir/venv/` | the locked dependencies and `hirdir` itself, with the web UI inside |
| `/usr/bin/hirdir` | the command |
| `/usr/sbin/hirdir-setup` | adds `hirdir` to an nginx site, brings the snippet and the settings file up to date, and checks GitHub for a newer release, fetches it and installs it |
| `/var/cache/hirdir/` | the packages `hirdir-setup --upgrade` fetched, the newest two (made when first needed, never shipped) |
| `/usr/share/hirdir/config.toml` | the settings file as this version ships it: every setting, commented out at its default |
| `/etc/hirdir/config.toml` | configuration. Written at install, given the new settings of a version at each upgrade, never shipped, and not a conffile |
| `/etc/nginx/conf.d/hirdir.conf` | the `upstream hirdir` block (a conffile) |
| `/usr/share/hirdir/nginx/snippet.conf` | the nginx snippet as this version ships it: the `location` block above, under `/hirdir`, with the upload limit |
| `/etc/nginx/snippets/hirdir.conf` | that snippet under the prefix of this host. Written at install and at each upgrade, never shipped, and not a conffile |
| `/usr/lib/systemd/system/hirdir.service` | runs `hirdir admin serve` as user `hirdir`, listening on `127.0.0.1:8715` |
| `/usr/lib/systemd/system/hirdir-backup.{service,timer}` | the daily backup |
| `/usr/lib/systemd/system/hirdir-upgrade.{service,timer}` | the nightly upgrade from GitHub. Shipped, and not enabled: a site turns it on |
| `/var/lib/hirdir/` | database, signing key, backups (created at install, never shipped) |
| `/usr/share/doc/hirdir/` | this documentation as HTML, and the release notes |
| `/usr/share/doc/hirdir/examples/` | the CSV and JSON files of `examples/`, to try an import with and to start a file from |

The package carries Python and every Python dependency. It depends on `libc6`,
`adduser`, `ca-certificates` and `tzdata`, and recommends `nginx`; apt supplies those.

**On install** the maintainer script creates the user, the state directory and its
backup directory, both for the `hirdir` user alone, creates the signing key, runs the
migrations, writes the nginx snippet, enables and starts the service, and prints two
lines: how to create the first Admin (`sudo hirdir admin create-user --role admin
NAME`), and how to add the site (`sudo hirdir-setup`).

**On upgrade** it stops the service, backs the database up into
`/var/lib/hirdir/backups/` and says where, runs the migrations, writes the nginx
snippet again under the prefix it has, puts the settings that are new in this version
into `/etc/hirdir/config.toml`, and starts the service again. The signing key and the
one conffile, the nginx upstream, are left as they are, and no value of the settings
file is changed, so sessions and service tokens go on working, and `hirdir` stays under
its prefix.

**The settings file** is not a conffile, for the reason the snippet is not: a release
that adds a setting ships a different file, and dpkg would ask every site that had
edited its own, and stop an upgrade with nobody to answer. `hirdir-setup --settings`
keeps it up to date instead. It reads the file as the site has it and the text this
version ships, and puts in each setting the file does not have, set or commented out:
at the end of its table, as the shipped text has it, commented out at its default. A
table the file lacks goes at the end. No line of the site's is changed or moved, the
file must set exactly what it set before or it is left alone, and the file as it was
is kept beside it.

**Upgrades with the setup tool.** `hirdir-setup` is in the package, written with the
standard library alone and run by the interpreter the package carries, so a host needs
one file, the `.deb`, for a first install and nothing more afterwards. `--check` asks
GitHub's API for the latest release that is not a pre-release. `--upgrade` fetches its
`hirdir_<version>_<architecture>.deb` and the `.sha256` beside it, keeps the package
only when it has that checksum, refuses one older than is installed, and has apt
install it with no question left to ask. `--proxy URL` sends the requests through a
proxy. It fetches over HTTPS from GitHub's own hosts and follows a redirect to no
other. `--upgrade PACKAGE.deb` installs a package that is already on the host; plain
`apt install` gives the same result.

An upgrade is begun by the tool that is installed and finished by the one the new
package brings. apt replaces the tool and its interpreter while the old one waits, so
the old one does one thing more when apt is done: it runs the new
`hirdir-setup --after-upgrade <the version that was installed>`. That is where a
version puts what it wants done once at an upgrade, beyond what every upgrade does in
the package's own scripts, and it reports how the upgrade went. A tool of an earlier
version therefore never needs to know what a later one requires.

**The nightly upgrade** is `hirdir-upgrade.timer`, which the package ships and does not
enable. A site that turns it on gets `hirdir-setup --upgrade --yes` each night at a
time of its own between 21:00 and 03:00 in the host's local time: `OnCalendar` at
21:00 with a random delay of up to six hours, and not `Persistent`, so a night the host
was off is not made up for in the middle of a working day. It runs as root, because it
installs a package, and goes through the proxy that `[upgrades]` in the configuration
file names. With nothing newer published it changes nothing. Installing the same version again takes
the same steps and changes nothing in the database.

**The nginx snippet** holds the `location` block shown under "URL prefix" and one line
more, `client_max_body_size 20m;`. An import sends its file as the body of a request
and `hirdir` takes a file of up to 20 MB, where nginx left to itself refuses a body of
more than 1 MB. nginx is given the limit of the application and no more. A body over
20 MB is therefore refused by nginx, with a `413` and the page of nginx, and never
reaches `hirdir`, whose own `413` is a problem document. A higher limit in nginx would
let the application answer, but it answers as soon as it has read 20 MB and closes the
connection with the rest unread, which nginx, still sending, can turn into a `502`.
A site that wants larger files raises both limits to the same figure: `max_megabytes`
under `[files]` in the configuration file, and this line of the snippet.

The snippet is not a conffile, because `hirdir-setup --prefix` writes the prefix into
it. dpkg asks about a conffile that was changed on the host whenever a new version
ships another: an upgrade would stop to ask an operator about a file they never
edited, and an upgrade with nobody to answer would fail there. The package ships the
text in `/usr/share/hirdir/nginx/snippet.conf` instead, and `hirdir-setup --renew`
writes `/etc/nginx/snippets/hirdir.conf` from it with the prefix that file already
has. The maintainer script runs it at install and at each upgrade, once the migrations
are done, so that an upgrade that stops there has changed nothing of nginx's. The
result is tested with `nginx -t`: when nginx objects, the file is put back as it was.
When it changed at an upgrade, nginx is reloaded and the upgrade says so. A snippet
that differs from every snippet the package has shipped in more than its three prefix
lines was edited by hand. It is left alone, and the message says where the shipped
one is. A purge removes the snippet with the rest.

A failed migration stops the upgrade with the backup's path in the message, and leaves
the service stopped. The migrations of one upgrade run in one transaction, so a failure
undoes all of them and the database is as it was, also where a migration had changed
tables that hold a site's records, or made one anew, before it failed. The way back is
the backup all the same: the message gives the commands that install the version that
was there before and restore the backup. An older version stops in the same way at a database that a
newer one has migrated. The steps for an operator are under "Upgrade" in
[install.md](install.md#upgrade).

**`hirdir-setup`** reads `nginx -T`, lists the sites that already terminate TLS, and
adds `include snippets/hirdir.conf;` to the one chosen, after showing the change.
`--prefix /inventory` rewrites the snippet's three prefix lines. `--renew` writes the
snippet again as this version ships it, under the prefix it has. `--self-signed`
creates a site with a throwaway certificate, for test containers only.

A container image is LATER. It runs the same package contents with the database on a
volume.

## Testing

| Command | What it does |
|---|---|
| `make check` | `ruff format --check`, `ruff check`, `ty check`, `pytest` over `tests/unit`, `tests/api` and `packaging/tests`, and the web UI's type check, lint and unit tests |
| `make test` | the Python tests of `make check`, alone |
| `make test-changed` | only the Python tests that what has changed since their last run can reach; for use while working, never in place of `make check` |
| `make acceptance` | the scenarios in [build-plan.md](build-plan.md) against a running server |
| `make e2e` | `make package-test`, with Playwright through nginx and a prefix against the fresh install |
| `make deb` | builds the web UI and the documentation, then the package with both inside, and writes its SHA-256 and lintian's report beside it |
| `make package-test` | installs the package in containers and exercises it: upgraded from the previous release, with a migration that fails, and fresh |
| `make fixture` | fills a database with 50,000 fictional items for timing |

### How long the tests take

The tests are run several at once, and what every test would otherwise do again for
itself is done once.

- **As many at once as the host has free.** `scripts/test_load.py` says how many: the
  cores that are not busy at that moment, and no more than the free memory allows, one
  at the least. The build host is shared, so before a run starts a busy host is waited
  for, ten minutes at the most, and the tests are then run all the same with fewer at
  once. `make check`, `make test`, `make test-changed` and `make acceptance` ask it,
  and so does `make package-test` for its three passes. `HIRDIR_TEST_WORKERS` sets the
  number outright and `HIRDIR_TEST_WAIT` the longest wait in seconds.
- **One migrated database, copied.** The database of a test is a copy of one that was
  migrated once for each worker. The migrations themselves are tested on databases of
  their own, in `tests/unit/test_database.py`.
- **The routes built once.** The application holds everything of one installation in
  one place, which `bind` in `src/hirdir/app.py` fills: its settings, its database, its
  key and its count of failed sign-ins. A worker builds the routes once and binds them
  to the state of each test in turn. A test whose settings differ in more than where
  its state lives gets an application of its own.
- **Access codes hashed cheaply, inside the test process only.** Argon2 at its full
  cost is slow on purpose, and nearly every test makes three users and signs one in.
  One test keeps the cost that is released and checks it. The acceptance scenarios and
  the package test start the server as a process of its own, and so always run with
  the full cost.
- **Only what a change can reach, while working.** `make test-changed` keeps a record,
  in `.testmondata`, of the lines of Python each test runs, and runs the tests whose
  lines have changed since. It does not see a change to a file that is not Python, such
  as the contract, an example or a script of the package, and it does not cover the
  acceptance scenarios, whose server is another process. So it is for the minutes
  between changes, and `make check` and `make acceptance` are what a task is done by.

Measured on the four-core build host with nothing else running, at 0.4.1: the 672
Python tests of `make check` take 33 seconds, and the 22 scenarios of `make acceptance`
42 seconds. Run one at a time and with everything done again for each test, as before
0.4.1, the two together took 475 seconds. A scenario is not shortened further: nearly
all of its time is the server and `hirdir admin` starting as real processes, which is
what it is there to show.

`make package-test` runs `packaging/package-test.sh`, which makes three passes, side by
side when the host has cores and memory free for it and one after another when it has
not. Each pass starts an Ubuntu 26.04 container of its own with systemd as its init under rootful
Docker and installs with apt, as an operator does.

| Pass | What it does |
|---|---|
| `--upgrade` | Installs the previous release behind nginx under a prefix of its own, changes the configuration file, and through that release's API makes an Admin, a second user in a group that holds a role, a service account with a token, an inventory as below, and the audit events of all of it. It keeps a session token in hand, upgrades with apt, and checks: the backup was taken before the migration and is named; the schema is at the new revision by `hirdir admin check`, the readiness probe and `/api/v1/about`, and every table the migration creates is there, or, where it creates none, the database has the tables it had; every account, group, grant, token and audit event is as it was, and so is the inventory, with every vendor `reviewed`; the session token, the access codes and the service token from before still work; the one conffile is untouched and dpkg asked nothing; the settings file, which the operator edited, holds every line it had, and the new settings after them when the version has any; the nginx snippet is the new version's under the old prefix, and when it changed the upgrade said that it reloaded nginx; a file of more than a megabyte is previewed under the old prefix before anything else has touched nginx. Then it does everything the fresh pass does |
| `--failed-upgrade` | Installs the previous release, makes the same inventory with it, and makes the new version's migration fail, in the database, so that the package under test is the one that was built. How is under "A migration that fails" below. The upgrade must fail, say what stopped it, name a backup that holds the database as it was, and leave the service stopped, the schema as it was statement for statement, every table of the inventory with the columns, indexes and rows it had, and the nginx snippet untouched. The commands of the message are then run, the previous release must serve again with every item and its history, and every group, membership, network and address, as they were, and with the cause taken out the upgrade must go through and keep them. Last, it goes back from the good upgrade to the previous release by the steps in [install.md](install.md#going-back-to-the-release-before), where dpkg must ask nothing about the snippet, and the inventory must be as it was once more. Only a release with no migration at all has nothing that could fail: the pass then says so in a `SKIP` line |
| `--fresh` | Installs on a system that never had `hirdir`, as a new installation does. `hirdir-setup --self-signed --prefix /hirdir`; the health probe, the first Admin and signing in through nginx; files, as below, and the records of 0.4.0 and of 0.4.1; the default choices and lifecycle rules; a vendor, catalog entries, an owner and items made through the API, their effective values and sources, filtered and sorted lists with a glob and a regular expression, a pattern that is too long, a lifecycle move and the item's history; the same version installed again, which must add nothing; restart and backup; another prefix, a site of the host's own, the root of the site; that no response set a cookie; and the purge |

**The inventory that is upgraded** is made for what a migration could harm, through
the API of the previous release, so that it holds what that release could store.
Migration `0006` adds three columns to `items`, and six to `device_groups`, which
SQLite does by making that table anew and copying the rows; it says of every cluster
that it is managed as one node, and it loads the `item_condition` list. So the two
upgrade passes make, with 0.4.0:

- items with every kind of value between them: one with a value in every field a
  caller may set, serial number, asset tag, MAC address, dates, quantity, owner, two
  tags and every override, moved from Delivered to Prod in three moves and set aside as
  a spare; the same serial number under another model, with the same MAC address; a
  draft that has an asset tag and no serial number; an item that has a name and nothing
  else; and a retired one;
- minor items: a power supply and a module in a switch, and an optic in the module;
- a stack of four switches with a master, an owner and a tag, of which one leaves
  again and one is replaced, so that it has three members, two memberships that were
  ended and a replacement;
- a cluster of two; a controller domain with a controller, a cluster of two more
  within it and two endpoints, one of them moved to Released, which 0.4.0 leaves a
  member; a second stack, of two, whose second switch is moved to Released as well;
  and a group that is a draft;
- two networks and seven addresses, of items and of groups, of both families, three
  of them primary, one address under two networks and twice under one of them;
- choices of the site's own: a reason for a move, a reason for a replacement, and a
  label of the site's for a default.

0.4.0 has no list of conditions and refuses a choice in one, so no site can have
entered a condition through it. The migration leaves alone what it finds in that list
all the same, and the test shows the refusal and then writes two rows into the
database, one of them `good` under a label of the site's: the one thing of this
inventory that is not made through the API.

Afterwards every item, group, membership, network and address must be as it was,
field for field and at the `row_version` it had, and every item with its history event
for event, but for what the migration is meant to change: the two memberships of the
items that are Released, the groups those two items say they are in, and the number of
members of their two groups. Those are left out of the comparison by name and looked
at by themselves, below. Each item must have no condition, nothing observed and a
health of `unknown`. The tables are read from the database file too. `items` must have every
column it had and the three new ones after them, with nothing in those, every row as
it was in the old columns, and every index, uniqueness and foreign key it had, with the
indexes of `condition` and `observed_status`. `device_groups` must have its columns and
the six new ones, its rows as they were, `managed_as` of `one` on each cluster and on
no other group, nothing in the other five, and its keys with the foreign key of
`observed_master_hid`. The tables of replacements, networks and addresses, which the
migration leaves alone, must be as they were in every column, key and row, and the
table of members in its columns, its keys and every row but the two that are meant to
change. A second item with a serial number of the same model, one with an asset tag that is
taken, and a second group of a name that is taken must still be refused. The stack
must still show the serial number of its master, as the one intended, with nothing
seen. The cluster must be counted as it was, and so must the inventory but for the
second stack: items, components, managed nodes and support weight from the summary,
value and cost from the management report, against what the summary of 0.4.0 said.
The two memberships that 0.4.0 let stand must be ended: each on the day of the
upgrade, at its next `row_version`, with one event in the audit trail that the system
made, of `left_on` from nothing to that day, and with its item in no group. The domain
must have two current members where it had three. The second stack must be one switch
alone and say that it is `degraded` for it, and its switch must have its whole support
weight where it had half, with the same component, value and cost. Every choice
must be the record it was, and `item_condition` must hold its six defaults and the
site's two, with `good` once, under the site's label. Last, an item from before is
given the site's own condition and an observation, and the cluster is said to be
managed by its members and counts as two nodes.

**A migration that fails** is made to fail in the database, never by changing the
package. Where the new version creates a table, the table it creates last is put
there beforehand, as `addresses` was for 0.4.0, so that everything else the migration
does is done before it fails. 0.4.1 creates no table. For such a release a trigger is
put on `alembic_version` that refuses any change to it. Writing the new revision into
that table is the last thing a migration does, so the failure comes when the columns
are added, the `device_groups` table is made anew, the clusters are marked, the
conditions are loaded and the memberships of the items that are Released are ended,
each with its audit event, and all of that has to be undone: the pass looks for the
rows of the members as they were, and for an audit trail with no event more. The trigger disturbs nothing
else: the previous release serves with it in place, and the backup that the upgrade
takes holds it. A column of a name the migration adds, put there beforehand, was tried
and does not serve. Where the column is added to the table as it stands, as on `items`,
SQLite refuses it, but at the migration's first statement, with nothing yet to undo.
Where the table is made anew, as `device_groups` is, the column that is already there
is taken over without a word and the migration goes through.

**Files**, in the fresh pass and so in the upgrade pass too, all through nginx under the
prefix. The nine files of `examples/` are sent in load order to `POST /imports/preview`
and applied: every row is created, and the lists of minor items, networks, device
groups with their members, and addresses hold what the files hold. What the examples
show of 0.4.1 is looked for: the core stack is found by the serial number of the master
that is intended and shows that of the master that is seen; the address that two
routers share is held once, by their cluster; `GET /reports/duplicates` lists the one
address that two virtual machines hold by mistake, and no other; the item list finds
as many items of each condition as the file has; a router that is Down and observed
unreachable is `degraded`, and a stack that is short of a member says so. The summary
must hold no money and count every component once by health, and the components of
each condition in its totals must be those of the rows when it is asked for by
condition; the management report must hold the money and refuse `by=health`. Sent a
second time, as CSV and as JSON, every row is
unchanged. A filtered export is taken as CSV and as JSON: its rows are those the
examples hold for the filter and those the list gives, and `hid` comes first. An export
of stored values is imported back unchanged. A file of more than a megabyte is imported,
and its apply sent twice with an `Idempotency-Key`. Then the limits: a body of exactly
20 MB passes nginx and is answered by `hirdir`; one byte more is refused by nginx with
its own `413`; the same body sent straight to the service is refused by `hirdir` with a
`413` problem document; and a file of 100,001 rows is refused by `hirdir` with its own
`413`, which nginx passes on. The package's copy of `examples/` is compared with the
repository's.

**The records of 0.4.0** are then made through nginx under the prefix, beside the
examples, as scenarios S18 to S21 and S23 have them, each in small. A power supply
given a switch as its parent shows the owner and the state of the switch with the
source `parent_item`, the summary counts one component more and not two, and the
switch moved to Test shows the power supply in Test with nothing written to it. Four
switches are made a stack with one master: the stack shows the master's serial number,
and another member made master changes it at once and makes the former master a member.
A member that is seen to be master, which is not the one intended, gives the stack its
serial number, and the stack says that it shows the observed one and that the two
differ; a switch that is no member is refused; with the observation taken back the
intended master's serial number is shown again. The stack is found by the serial
number of a member that is neither. A file of members that names two intended masters
of the stack, or two observed ones, is previewed with its second row rejected.
`GET /reports/summary` for the stack gives four components, one managed node, a
support weight of 2.0 at the global discount of 50 and of 2.8 at a discount of 30 set
on the model, and `GET /reports/management` the annual support cost of four switches
throughout. The master is
replaced through `POST /items/{hid}/replace`: two item records are linked, the
membership of the one that left ends that day, and the stack is the same record with
the new serial number: the new switch has the role of the one that left, the
intended master, and not what was seen of it, so the stack shows no observed master
afterwards. One address is put under two networks and is not in
`GET /reports/duplicates`; put under one of them a second time, that pair is, and no
other. An IPv6 address of the stack is kept in its short form, and the list and the
export of addresses filter and sort by `family`. Last, every network,
device group, membership and address is exported and imported back unchanged, as CSV
and as JSON, and so is every item, sorted by `depth` so that a parent stands before its
minor items.

**The records of 0.4.1** follow, in the same way. An item is given a condition, then an
observation, then both: its health is `unknown`, `good`, `failed` when it is expected
online and observed unreachable, and `degraded`, each time with its reason; a
condition that the list does not offer is refused; the item is found by its health,
and each change is in its history. An observation that is stated again as it is, with
no moment, has its moment set to now, at the next `row_version`; the moment is not
cleared by itself, one that is three days ahead is refused, and one with no zone is
in the application's time zone. A stack of one switch with no master is `degraded`
for being alone, has no serial number until its switch is seen to be master, and has
the whole support weight of its switch; told to expect one member it is no longer
degraded; with a second switch it earns the discount, and its value and cost in the
management report are those of two; with that switch in Pending-Removal it is degraded
again. A cluster of two is one managed node, then two when it is managed by its
members, then three when it is managed as a cluster as well, with two components and
the same support weight each time, and `managed_as` is refused on a stack. Four
items that are failed, degraded, unknown and good are listed in that order when the
item list is sorted by health. A member
moved to Pending-Removal stays a member; moved on to Released it is in no group, and
is refused when it is to join the cluster again or to take a member's place in a
replacement; the other, moved straight to Archived, leaves too, and both memberships
stay on record with the day they ended. Last, a file of `hostname` and `IP_address`
columns is sent as it is: its three rows are created, each address is the primary
management address of its family, and the same file a second time changes nothing; a
second file with `ipv4`, `ipv6` and `observed_status` columns gives two of the items an
address of the other family and a health of `good`, and sent again, stating what was
observed with no moment, it changes nothing. A third file, of `hostname` and
`observed_status` alone, names two switches that have serial numbers: each row finds
its switch by the host name and updates it, and no second item is made.

The examples are imported into an inventory that does not hold them, and the checks
that follow make records of the same names by hand. So the pass takes a backup before
the import and restores it afterwards, with `hirdir admin backup` and `hirdir admin
restore`. In between, with the examples and the records above still loaded, `hirdir
admin reset` is tried as an operator would use it: it must refuse while the service
runs, change nothing without the word `reset`, and then clear every table of the
inventory, those of the replacements, groups, members, networks and addresses among
them, and keep the accounts.

The client commands of the CLI are run in the container, from the package, while the
examples are loaded: `hirdir export` and `hirdir items list` must write the very file
that `POST /exports` gave for the same filter, and `hirdir items show`, `hirdir items
set` for one item and for many, and `hirdir import` with and without `--apply` are
tried, with the exit codes for a rejected row and for no session. `hirdir groups show`
must name a stack of the examples with the serial number of the master that is
observed, both masters and its health, `hirdir groups list` must write the file that
`POST /exports` gives, `hirdir items show` must say what a minor item has from the item
it is in, `hirdir report summary` must count what `GET /reports/summary` counts, by
owner and by health, and print the health and no money, `hirdir report management`
must give what `GET /reports/management` gives and print the money and no health, and
`hirdir report duplicates` must list the address that two virtual machines of the
examples hold by mistake, and not the one that two routers share. They are pointed at
the service itself, past nginx, because the test site's certificate is a throwaway
that no client should be told to trust.

**The previous release** is the package named by `PREVIOUS_DEB`. Left unset, it is the
`hirdir_*_amd64.deb` in `dist/` with the highest version below the one under test, so
keeping each release's package in `dist/` is all it takes. When none is found, the two
upgrade passes are skipped: the run prints a `SKIP` line that says no upgrade was
tested and how to test it, and goes on with the fresh install. Run by hand with
`--fresh`, the script makes the fresh pass alone and says the same.

Every check prints a line that starts with `PASS`, `FAIL` or `SKIP`, each pass ends
with its counts, and the run ends with the counts of all three and every `FAIL` and
`SKIP` line once more. `systemd-nspawn` is available on the build host as an
alternative runner for the same script.

## Configuration

`/etc/hirdir/config.toml`, every key optional:

```toml
[server]
listen = "127.0.0.1:8715"
trusted_proxies = ["127.0.0.1", "::1"]
state_dir = "/var/lib/hirdir"        # a relative path is taken from this file's directory

[database]
url = "sqlite:////var/lib/hirdir/hirdir.db"

[access]
session_hours = 12
sign_in_failures_before_delay = 5

[backup]
keep = 14

[files]
max_megabytes = 20                   # the largest file an import takes; nginx must allow as much

[upgrades]
proxy = ""                           # the proxy through which hirdir-setup reaches GitHub, if any
```

Installation-wide values that people change in the course of work, such as the stack
discount, are settings in the database, edited in the web UI by an Admin.
