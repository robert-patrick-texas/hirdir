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
scripts/             build_docs.py, docs.css, release_facts.py, seed_examples.py, seed_fixture.py
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
| `/usr/sbin/hirdir-setup` | adds `hirdir` to an nginx site |
| `/etc/hirdir/config.toml` | configuration (a conffile) |
| `/etc/nginx/conf.d/hirdir.conf` | the `upstream hirdir` block (a conffile) |
| `/usr/share/hirdir/nginx/snippet.conf` | the nginx snippet as this version ships it: the `location` block above, under `/hirdir`, with the upload limit |
| `/etc/nginx/snippets/hirdir.conf` | that snippet under the prefix of this host. Written at install and at each upgrade, never shipped, and not a conffile |
| `/usr/lib/systemd/system/hirdir.service` | runs `hirdir admin serve` as user `hirdir`, listening on `127.0.0.1:8715` |
| `/usr/lib/systemd/system/hirdir-backup.{service,timer}` | the daily backup |
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
snippet again under the prefix it has, and starts the service again. The signing key
and the two conffiles are left as they are, so sessions and service tokens go on
working, and `hirdir` stays under its prefix. Installing the same version again takes
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
undoes all of them and the database is as it was. The way back is the backup all the
same: the message gives the commands that install the version that was there before
and restore the backup. An older version stops in the same way at a database that a
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
| `make acceptance` | the scenarios in [build-plan.md](build-plan.md) against a running server |
| `make e2e` | `make package-test`, with Playwright through nginx and a prefix against the fresh install |
| `make deb` | builds the web UI and the documentation, then the package with both inside, and writes its SHA-256 and lintian's report beside it |
| `make package-test` | installs the package in containers and exercises it: upgraded from the previous release, with a migration that fails, and fresh |
| `make fixture` | fills a database with 50,000 fictional items for timing |

`make package-test` runs `packaging/package-test.sh`, which makes three passes. Each
pass starts an Ubuntu 26.04 container of its own with systemd as its init under rootful
Docker and installs with apt, as an operator does.

| Pass | What it does |
|---|---|
| `--upgrade` | Installs the previous release behind nginx under a prefix of its own, changes the configuration file, and through that release's API makes an Admin, a second user in a group that holds a role, a service account with a token, a vendor with a catalog entry and an item, and the audit events of all of it. It keeps a session token in hand, upgrades with apt, and checks: the backup was taken before the migration and is named; the schema is at the new revision by `hirdir admin check`, the readiness probe and `/api/v1/about`, and every table the migration creates is there; every account, group, grant, token and audit event is as it was, and so are the vendor, the catalog entry and the item, with every vendor `reviewed`; the session token, the access codes and the service token from before still work; the two conffiles are untouched and dpkg asked nothing; the nginx snippet is the new version's under the old prefix, the upgrade said that it reloaded nginx, and a file of more than a megabyte, which nginx refused before the upgrade, is previewed under the old prefix before anything else has touched nginx. Then it does everything the fresh pass does |
| `--failed-upgrade` | Installs the previous release and puts a table in the way of the new version's migration, in the database, so that the package under test is the one that was built. The table is the one the migration creates last. The upgrade must fail, name a backup that holds the database as it was, and leave the service stopped, the schema as it was statement for statement, and the nginx snippet untouched. The commands of the message are then run, the previous release must serve again, and with the table gone the upgrade must go through. Last, it goes back from the good upgrade to the previous release by the steps in [install.md](install.md#going-back-to-the-release-before), where dpkg must ask nothing about the snippet. When no migration of the new version creates a table, the pass has nothing to put in the way and says so in a `SKIP` line |
| `--fresh` | Installs on a system that never had `hirdir`, as a new installation does. `hirdir-setup --self-signed --prefix /hirdir`; the health probe, the first Admin and signing in through nginx; files, as below; the default choices and lifecycle rules; a vendor, catalog entries, an owner and items made through the API, their effective values and sources, filtered and sorted lists with a glob and a regular expression, a pattern that is too long, a lifecycle move and the item's history; the same version installed again, which must add nothing; restart and backup; another prefix, a site of the host's own, the root of the site; that no response set a cookie; and the purge |

**Files**, in the fresh pass and so in the upgrade pass too, all through nginx under the
prefix. The files of `examples/` are sent in load order to `POST /imports/preview` and
applied: every row is created. Sent a second time, as CSV and as JSON, every row is
unchanged. A filtered export is taken as CSV and as JSON: its rows are those the
examples hold for the filter and those the list gives, and `hid` comes first. An export
of stored values is imported back unchanged. A file of more than a megabyte is imported,
and its apply sent twice with an `Idempotency-Key`. Then the limits: a body of exactly
20 MB passes nginx and is answered by `hirdir`; one byte more is refused by nginx with
its own `413`; the same body sent straight to the service is refused by `hirdir` with a
`413` problem document; and a file of 100,001 rows is refused by `hirdir` with its own
`413`, which nginx passes on. The package's copy of `examples/` is compared with the
repository's.

The examples are imported into an inventory that does not hold them, and the checks
that follow make records of the same names by hand. So the pass takes a backup before
the import and restores it afterwards, with `hirdir admin backup` and `hirdir admin
restore`. In between, with the examples still loaded, `hirdir admin reset` is
tried as an operator would use it: it must refuse while the service runs, change
nothing without the word `reset`, and then clear the inventory and keep the accounts.

The client commands of the CLI are run in the container, from the package, while the
examples are loaded: `hirdir export` and `hirdir items list` must write the very file
that `POST /exports` gave for the same filter, and `hirdir items show`, `hirdir items
set` for one item and for many, and `hirdir import` with and without `--apply` are
tried, with the exit codes for a rejected row and for no session. They are pointed at
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
```

Installation-wide values that people change in the course of work, such as the stack
discount, are settings in the database, edited in the web UI by an Admin.
