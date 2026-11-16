# Architecture

How `hirdir` is built, packaged and run. The records are in
[data-model.md](data-model.md) and the interfaces in [interfaces.md](interfaces.md).

## Shape

```text
browser ──HTTPS──┐
hirdir CLI ──────┤   nginx (Ubuntu's)            hirdir.service
integrations ────┘   terminates TLS,      ──▶    one Python process       ──▶  SQLite file and
                     strips the prefix           FastAPI: API + web UI         reference files
                                                                               /var/lib/hirdir
```

One process serves both the API and the built web UI. nginx does TLS and nothing else
of ours. There is no second service, no queue and no cache in the MVP. An import or a
bulk edit is applied in the background by a thread of that one process, and the jobs
waiting for it are rows of the database: see "Applying in the background" below.

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
  schedule.py        what the server does by itself at set times
  config.py          /etc/hirdir/config.toml and its defaults
  db/                engine, models, dialect helpers, migrations/
  domain/            the rules: inheritance, lifecycle, matching, counting, geography
  api/               routers under /api/v1, one module per record type
  auth/              providers (local now; RADIUS and SAML later), tokens, roles
  io/                filter grammar, CSV and JSON import and export, the store of reference files
  cli/               the hirdir command: client commands and `hirdir admin`
  static/            the built web UI (generated, not committed)
web/                 TypeScript source of the web UI
tests/               unit/, api/, acceptance/, e2e/
packaging/           build-deb.sh, control files, systemd units, nginx files, hirdir-setup, container/,
                     package-test.sh and package-test.d/, what one migration or release alone has in it
scripts/             build_docs.py, docs.css, release_facts.py, release_body.py, seed_examples.py, seed_fixture.py,
                     time_filters.py
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
    client_max_body_size 100m;                      # a reference file is of up to 100 MB
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
allowed to run: `Content-Security-Policy: default-src 'self'; img-src 'self' blob:;
frame-ancestors 'none'`, with the narrowest style allowance the grid needs. All
front-end code and fonts ship in the package. Requests are same-origin and CORS is off.
Text from the inventory is rendered as text, never as HTML.

**Reference files** never run as part of the page (P-159). No cookie is ever set, so a
plain link cannot carry the session to a download: the page fetches the content with
its token, as it fetches everything, and makes of it a `blob:` address of its own. A
JPEG, PNG, GIF or WebP picture is shown from that address in an `<img>`, which runs no
script whatever the picture holds, and is all that `img-src 'self' blob:` allows; every
other file is handed to the browser as a download with its name, typed
`application/octet-stream`, and is never shown in a frame, a tab or an object of the
page. The answer of the content route itself carries `Content-Disposition:
attachment`, `X-Content-Type-Options: nosniff` and `Content-Security-Policy: sandbox;
default-src 'none'`, so that a browser sent to it by other means downloads it too and
runs nothing of it. A web page, an SVG drawing, a script or a program is refused at
upload, by its extension and by its first bytes.

## Database

- SQLite with `journal_mode=WAL`, `foreign_keys=ON`, `busy_timeout=5000`, set on every
  connection and checked by the readiness probe.
- One writer at a time. Imports and bulk edits are previewed first, then written in
  batches, each a short transaction of its own.
- **Previews.** A preview of an import or a bulk edit is made by doing the work for
  real, through the same functions as any other change, inside a transaction that is
  then undone. What it reports is therefore what an apply will do, and no rule is
  written twice. Apply does the same work again, compares each row with what was
  previewed, and keeps each row that agrees.

  SQLite has one writer at a time, and a transaction that writes holds every other
  writer up until it ends, also when it ends by being undone. A preview of more than a
  hundred rows is therefore worked on a copy of the database, made with SQLite's
  online backup in the service's private temporary directory and thrown away
  afterwards, so that nobody waits for a preview. A smaller preview is worked in
  place, and takes the one writer's place before it reads anything: SQLite refuses at
  once, with no waiting, a transaction that has read and then wants to write after
  another has written in between, and a preview that took its turn first waits for it
  like any other change. An apply cannot be spared the same
  way, since what it does is kept, so it is worked a batch at a time beside the
  requests, as the next point says. A change that waits longer than `busy_timeout` for
  another is answered `503` with `Retry-After`, and nothing of it was done. Reading is
  never held up.
- **Applying in the background.** `POST /imports/{hid}/apply`, and the apply of a bulk
  edit, store the job as `applying`, or `queued` behind another, and answer `202` at
  once. A worker in the server's own process, a thread with its own database session
  (`io/background.py`), applies one job at a time: the one applying, then the queued
  ones in the order they were asked for. The route wakes it once the request is
  stored, and it also looks for work by itself every five seconds. It works out the
  order of the rows once for the whole job, then works them 50 to a batch
  (`io/imports.py`), each batch a transaction that takes the one writer's place before
  it looks, as a small preview does, and stores with its rows what it did with each
  one and how far the job has got. Between two batches it leaves the writer's place
  free for 0.12 seconds: SQLite tells a change that waits for the place to try again
  every tenth of a second at the longest, so such a change is sure to get it there,
  and a sign-in waits a batch, a fraction of a second, at most. A batch that waits
  longer than `busy_timeout` itself is tried again from its start. The rows of one
  group, which are checked together, are kept in one batch whatever its size, and a
  group of thousands of members therefore holds others up for as long as it takes.
  The batches are under the request ID of the apply, and as the person who asked for
  it, whose role is looked at again as the worker takes it up. An error nobody foresaw
  undoes the batch it happened in and stops the job, and is logged with its
  traceback. When the server stops, the worker stops after the batch it is in, at
  most a minute later, and the job is `stopped`; when it starts, before the worker
  does anything, a job still `applying` is marked `stopped`, since only a stop that
  cut it short leaves one so. A stopped job is resumed by asking for it to be applied
  again, from the first row that was not applied. There is one worker for one
  database, because there is one process: two servers on one database would each
  take the jobs.
- Schema changes are Alembic migrations, applied by `hirdir admin migrate`.
- Everything that differs between SQLite and PostgreSQL lives in `db/dialect.py`:
  case-insensitive comparison, regular expression matching, the order of addresses,
  the values of a list that is kept as JSON, today's date in the application's time
  zone, and upsert. The test suite runs against
  SQLite; a PostgreSQL run is added with that option, and until then the PostgreSQL
  form of each is written and not run.
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
- **Sorting.** A sort is a statement's ORDER BY and nothing else. What a column of
  several values, a count or a derived value is sorted by is a subquery of its own,
  written beside the field in `io/fields.py`, and it is in the statement only when
  that sort is asked for: a list that is not sorted by its tags reads no tag. The
  tables that are paged and are no list are in `io/tables.py`, and each keeps its own
  order after what is asked for. An address is sorted as its number: SQLite gets a
  function from the application for that, and PostgreSQL casts to `inet`.
- **Today.** What a contract covers today, and which capacity line is in date, is a
  comparison with the application's day: the day in the `time_zone` setting, not the
  day of the host or of UTC. A statement that filters or sorts by it works the day out
  itself, once, from that setting, so a list needs nothing handed to it and two
  requests in one minute agree. SQLite gets a function from the application for that,
  and PostgreSQL uses `now()` in the zone.
- **Writes.** A request's changes are committed when its route returns and before any
  of the answer is sent, and the worker's at the end of each batch. Every update of a
  row names the `row_version` it was read at.
- **What the server does by itself.** A few things are done at set times, by the
  server and not by a request: the record of the capacity balance each Monday just
  after midnight, and each night just after midnight the long reports worked out ahead
  and kept, the coverage report, the renewal worklist, the summary of the renewal alert
  and the capacity report, each for the view its page opens with. `hirdir/schedule.py` holds them as a list of jobs, each a name, when
  it is due and what it does, run by a scheduler in the server's own process. The
  scheduler is started with the application and stopped with it. When the server
  starts, the jobs that run at start are run before the first request is answered, and
  then a thread of its own wakes once a minute and runs, each with a session of its
  own and as one writer among the others, every job that has come due since it last
  looked, by the clock of the `time_zone` setting. What a job writes is audited with
  `via` of `system`. A job that fails is logged and tried again a minute later. A time
  that passed while the server was stopped is not made up for, so a job that must not
  miss one also runs at start and looks for what is missing: the server records the
  balance when it starts in a week that has no record. The tests run a job for a
  moment they choose, through `run_due`, and do not wait for a Monday.
- **Reference files.** The content of a file is kept beside the database and never in
  it, in `files/` under the state directory, `/var/lib/hirdir/files/`, in a file named
  for its SHA-256 checksum under a directory of its first two characters:
  `files/9f/9f86d081...`. The same content is kept once, whatever the number of
  references that hold it. A preview of an import works on a copy of the database and
  a backup copies it whole, neither of which should be made to copy gigabytes of
  photographs. An upload is written as it arrives into `files/.incoming/`, counted and
  checksummed on the way, so that a file of 100 MB is never held in memory, and is
  refused as soon as it is over the limit; it is then checked, moved into place and
  its record stored. Content is written before the record that names it and removed
  only after the last such record is gone, under one lock of the server process, so
  that what the database names is there; there is one process for one database. A
  part left in `files/.incoming/` by an upload that was cut short is removed when the
  server starts, with any content that no record names and that is more than a day
  old. `src/hirdir/io/store.py` keeps them (P-161).
- **Backup.** `hirdir admin backup` uses SQLite's online backup into
  `/var/lib/hirdir/backups/`, and a daily timer keeps the last 14. It puts into
  `backups/files/` the content the store holds that is not there yet, before it copies
  the database and again after, for what was uploaded meanwhile: a hard link where the
  two directories are on one file system, which takes no room, and a copy where they
  are not. Content the copy names that is in neither place, erased in that moment, is
  named in a warning, and the backup is made all the same. Content is never changed, so a link is as
  good as a copy, and each file is held once among all the backups however many name
  it. The rotation then removes from `backups/files/` what no backup that is kept
  names, so that a file erased in the application leaves the host when the last
  backup that held it is rotated out (P-160). A backup is named
  for when it was made, in the application's time zone with its offset from UTC:
  `hirdir-20261111T210000-0500.db`. Which are the last 14 is told from the moment in
  each name, so a change of time zone, or the hour that comes twice in the autumn, puts
  none out of order. `hirdir admin restore
  FILE` puts one back: it takes the content of the files from the `files/` beside the
  backup, or from `--files DIR`, and checks, before it changes anything, that it has
  the content of every reference the backup names, each with its checksum. The
  content that the restored database does not name is set aside in
  `files.before-restore/`, as the database is in `hirdir.db.before-restore`, and only
  what undoing that restore takes is kept there (P-165). Copying
  backups off the host, the `files/` beside them with them, is the host's job.
- **Reset.** `hirdir admin reset` is the one place where records are deleted, beside
  the erasure of a reference, which the owner asked for (P-160); it erases every
  reference and its content after the backup it takes. It is a
  command on the server, with no route behind it, and runs only while the service is
  stopped, after a backup. Every table is named in `domain/reset.py` as one that a
  reset clears or one that it keeps, and a test fails when a new table is in neither.

### Answers that are kept

The coverage report, the renewal worklist, the summary of the renewal alert and, from
0.8.0, the capacity report are worked out once and given again while nothing could
have changed them, to every person and in every session alike (D-184, P-157). Each
answer is kept in the memory of the server process with the database it is of, the
newest audit event there is, the day in the application's time zone and the request
whole: filter, view, section, sort and page. Every change writes an audit event, a
setting's among them, so a newer event, or the turn of the day, leaves a kept answer
unused, and one that a change has made wrong is never given. At most 64 answers are
kept, the least used dropped first, and a restart drops them all. What is kept is no
record: it is worked out again from the records, so nothing inherited is copied down.
The coverage report counts each section with a count of its own, which the database works out from what that section needs alone: one statement that tallied every section in one pass, as D-184 first had it, was measured at three times as long on the fixture. All four are
worked out just after midnight in the application's time zone, and when the server
starts, for the view each page opens with, so that the first person of the day is not
kept waiting; any other view is worked out when it is first asked for, and then kept. A
Try of the capacity report is worked out each time and never kept. An Admin may check
what is kept, `POST /kept-answers/check`: each kept answer is worked out anew and
compared with what was kept, and the check says which report and which request had
differed, which none should. It is audited and leaves the kept answers good, since it
changes no record. `src/hirdir/io/kept.py` keeps them.

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
| `/var/lib/hirdir/` | database, signing key, the content of reference files in `files/`, backups with the files they name in `backups/files/` (created at install, never shipped) |
| `/usr/share/doc/hirdir/` | this documentation as HTML, and the release notes |
| `/usr/share/doc/hirdir/examples/` | the CSV and JSON files of `examples/`, to try an import with and to start a file from |

The package carries Python and every Python dependency. It depends on `libc6`,
`adduser`, `ca-certificates` and `tzdata`, and recommends `nginx`; apt supplies those.

**On install** the maintainer script creates the user, the state directory, its backup
directory and the store of reference files, `files/`, each for the `hirdir` user alone,
creates the signing key, runs the migrations, writes the nginx snippet, enables and
starts the service, and prints two lines: how to create the first Admin (`sudo hirdir
admin create-user --role admin NAME`), and how to add the site (`sudo hirdir-setup`).

**On upgrade** it makes the store of reference files where it is missing, as at
install, stops the service, backs the database up into `/var/lib/hirdir/backups/` with
the files it names and says where, runs the migrations, writes the nginx snippet again
under the prefix it has and with the limit of the configuration file, puts the
settings that are new in this version into `/etc/hirdir/config.toml`, and starts the
service again. The signing key and the
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
more, `client_max_body_size 100m;`. An import sends its file as the body of a request
and `hirdir` takes a file of up to 20 MB, and a reference file of up to 100 MB, where
nginx left to itself refuses a body of more than 1 MB. nginx is given the larger of the
application's two limits and no more: `hirdir-setup --renew` writes the line from
`max_megabytes` and `max_reference_megabytes` under `[files]` in the configuration
file, so a site changes a limit in that file alone and runs it (P-162). A body over
the larger limit is refused by nginx, with a `413` and the page of nginx, and never
reaches `hirdir`. A body under it and over the limit of its route, an import of 30 MB
or a change of an item of 30 MB, is refused by `hirdir` itself with a `413` problem
document. The application reads the rest of such a body and throws it away before it
answers: an answer sent while nginx is still sending can be turned by nginx into a
`502`.

The snippet is not a conffile, because `hirdir-setup --prefix` writes the prefix into
it. dpkg asks about a conffile that was changed on the host whenever a new version
ships another: an upgrade would stop to ask an operator about a file they never
edited, and an upgrade with nobody to answer would fail there. The package ships the
text in `/usr/share/hirdir/nginx/snippet.conf` instead, and `hirdir-setup --renew`
writes `/etc/nginx/snippets/hirdir.conf` from it with the prefix that file already
has and the limit of the configuration file. The maintainer script runs it at install and at each upgrade, once the migrations
are done, so that an upgrade that stops there has changed nothing of nginx's. The
result is tested with `nginx -t`: when nginx objects, the file is put back as it was.
When it changed at an upgrade, nginx is reloaded and the upgrade says so. A snippet
that differs from every snippet the package has shipped in more than its three prefix
lines and its line of the limit was edited by hand. It is left alone, and the message
says where the shipped one is. A purge removes the snippet with the rest.

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
snippet again as this version ships it, under the prefix it has, with the limit of the
configuration file. `--self-signed` creates a site with a throwaway certificate, for
test containers only.

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
| `make time-filters` | times the filters and sorts of the item list on that database; see "Timing at scale" below |

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

**The browser scenarios** of `make e2e` are the spec files in `web/e2e/`, which
Playwright runs against the fresh install. The files run side by side, each in a worker
of its own, and the tests of one file run in order, because the later ones use what the
earlier ones made. `scripts/test_load.py` says how many files run at once, for the host
as it is when they start, so beside the two upgrade passes fewer are started;
`E2E_WORKERS` sets the number outright. All the files use one server and one inventory,
so each has of its own what another could disturb:

- **An account.** The Admin the run is given, in `E2E_USERNAME` and `E2E_ACCESS_CODE`,
  signs in through the API and never in a browser. It makes one Admin for each file
  when the file's first test starts, and the file signs in as that one. Whatever a file
  does to an account, it does to its own or to one it made. When the worker has run the
  file, the account is disabled.
- **Names.** Every record a file makes carries the name of the file and a random part,
  as in `site2-sw-access-items-3fa9c1-01`. No two files make the same name, and a file
  can be run again on the same server.
- **What it counts.** A summary, a report or a grid is filtered down to the file's own
  records before anything in it is counted. In a list that every file adds to, a file
  looks at its own rows: the past imports that its account made, the user it searched
  for.

The browser scenarios of the renewal alert run in a project of their own, "the alert
alone", after the others and with one worker: the alert is shown once a day to each
person, and a scenario that dismisses it must not meet another that expects it shown.
The browser scenarios of the weights, `weights.spec.ts`, run in a project of their own,
"the weights alone", after the alert's and with one worker: they change the six weights
of the settings and the staff lines that the capacity page of every other file reads,
note each setting as they found it, put it back, and retire the lines and places they
made.

No file changes what the others read, a setting, a list of choices or a lifecycle rule,
but `weights.spec.ts`, above, and one more: `stale-term.spec.ts` changes `time_zone` so that a day comes, and so runs in a
Playwright project of its own after all the others, puts the setting back, and is run
by itself with `--no-deps`. Nor does any file hold the one writer for long beside the
others but one: `cover-many.spec.ts` loads a thousand switches from a file and covers a
thousand at once, each a change that holds the writer for seconds, which makes a
sign-in of another file wait past `busy_timeout` and be answered Busy. It runs in a
project of its own after the files of every browser and before `stale-term.spec.ts`. So no other test is kept from running beside those of
another file. The rules a new spec file
keeps to are at the top of `web/e2e/support.ts`.

A run is as long as its longest file, so a file holds only scenarios that build on one
another. The scenarios of 0.4.0 were one file and are three for that reason,
`minor-items.spec.ts`, `stack.spec.ts` and `wireless.spec.ts`: each loads the catalog,
the owners and the items it needs, and what they do alike is in `web/e2e/structure.ts`.

Measured against a development server on the four-core build host, the browser in
Playwright's container: one file after another, which is how they ran before 0.5.0, the
scenarios took 125 seconds with nothing else running. In six files and four at once
they took 85 seconds while other work held one of the four cores. One file at a time
they now take somewhat longer than before, because each of the three files loads for
itself what one file loaded once.

`make package-test` runs `packaging/package-test.sh`, which makes three passes, side by
side when the host has cores and memory free for it and one after another when it has
not. Each pass starts an Ubuntu 26.04 container of its own with systemd as its init under rootful
Docker and installs with apt, as an operator does.

| Pass | What it does |
|---|---|
| `--upgrade` | Installs the previous release behind nginx under a prefix of its own, changes the configuration file, and through that release's API makes an Admin, a second user in a group that holds a role, a service account with a token, an inventory as below, and the audit events of all of it. It keeps a session token in hand, upgrades with apt, and checks: the backup was taken before the migration and is named; the schema is at the new revision by `hirdir admin check`, the readiness probe and `/api/v1/about`, and every table the migration creates is there, or, where it creates none, the database has the tables it had, or, where there is no migration, the schema is the same statement for statement; the audit trail holds no event of the upgrade, but for the one that the service of 0.7.0 or later writes by itself when it starts in a week whose capacity balance has no record, which is allowed for by name; every account, group, grant, token and audit event is as it was, and so is the inventory, with every vendor `reviewed`; the session token, the access codes and the service token from before still work; the one conffile is untouched and dpkg asked nothing; the settings file, which the operator edited, holds every line it had, and the new settings after them when the version has any, and from 0.7.0 `hirdir admin config --current` sets in a complete file what the operator set; the nginx snippet is the new version's under the old prefix, and when it changed the upgrade said that it reloaded nginx; a file of more than a megabyte is previewed under the old prefix before anything else has touched nginx. Then it does everything the fresh pass does |
| `--failed-upgrade` | Installs the previous release, makes the same inventory with it, and makes the new version's migration fail, in the database, so that the package under test is the one that was built. How is under "A migration that fails" below. The upgrade must fail, say what stopped it, name a backup that holds the database as it was, and leave the service stopped, the schema as it was statement for statement, every table of the inventory with the columns, indexes and rows it had, and the nginx snippet untouched. The commands of the message are then run, the previous release must serve again with every item and its history, and every group, membership, network and address, as they were, and with the cause taken out the upgrade must go through and keep them, and leave the settings file, which nobody edited, with every line it had and the new settings after them, for `hirdir-setup --settings` to find nothing to change. Last, it goes back from the good upgrade to the previous release by the steps in [install.md](install.md#going-back-to-the-release-before), where dpkg must ask nothing about the snippet, and the inventory must be as it was once more. Only a release with no migration at all has nothing that could fail: the pass then says so in a `SKIP` line, upgrades, and goes back by installing the previous package alone, as below |
| `--fresh` | Installs on a system that never had `hirdir`, as a new installation does. `hirdir-setup --self-signed --prefix /hirdir`; the health probe, the first Admin and signing in through nginx; files, as below, and the records of 0.4.0, of 0.4.1, of 0.5.0 and of 0.6.0, and two of 0.7.0; that `hirdir admin config` writes the very file the package ships; the default choices and lifecycle rules; a vendor, catalog entries, an owner and items made through the API, their effective values and sources, filtered and sorted lists with a glob and a regular expression, a pattern that is too long, a lifecycle move and the item's history; the capacity balance of the worked example; the same version installed again, which must add nothing; the lock that the service holds on its state directory, and a second server refused; restart and backup; another prefix, a site of the host's own, the root of the site; that no response set a cookie; and the purge |

**The pair of releases** is worked out by the script, and is written nowhere in it.
The package under test is `dist/hirdir_<version>_amd64.deb`, or the one that `DEB`
names, and the previous one is found as
[release-process.md](release-process.md#the-previous-releases-package) has it. From each
package the script reads its version and the revision that its migrations end at.
Where the two revisions are the same, the upgrade has no migration. Where they differ,
the migrations after the first revision are those the upgrade runs, and the tables
they create are read from the package too. Each upgrade pass says what it found in its
first lines. What every upgrade must show is in `packaging/package-test.sh` and holds
for any pair, so a release with no migration changes nothing in the test.

**The inventory that is upgraded** is made for what an upgrade could harm, through
the API of the previous release, so that it holds what that release could store and
nothing else. Each kind of record is made where the schema of the previous release is
at the revision that brought it, or at a later one. With a previous release at
revision `0006` the two upgrade passes make:

- items with every kind of value between them: one with a value in every field a
  caller may set, serial number, asset tag, MAC address, dates, quantity, owner, two
  tags and every override, moved from Delivered to Prod in three moves and set aside as
  a spare; the same serial number under another model, with the same MAC address; a
  draft that has an asset tag and no serial number; an item that has a name and nothing
  else; and a retired one;
- minor items: a power supply and a module in a switch, and an optic in the module;
- a stack of four switches with a master, an owner and a tag, which is to have four
  members and is observed online, of which one leaves again and one is replaced, and
  whose third switch is then seen to be master, at a moment written with no zone;
- a cluster of two that is managed by its members; a controller domain with a
  controller, a cluster of two more within it and two endpoints, one of which is moved
  to Released and so leaves the domain; a stack that is one switch alone; and a group
  that is a draft;
- conditions and observations: a switch that is good and observed online at a moment
  that names its zone, one that is degraded, a member of the cluster that is observed
  unreachable and one that is observed present at a moment written with no zone, a
  controller with a condition of the site's own, and an endpoint that is untested;
- two networks and eight addresses, of items and of groups, of both families, one
  address under two networks and twice under one of them, and on one switch a primary
  management address of each family;
- choices of the site's own: a reason for a move, a reason for a replacement, a
  condition, and a label of the site's for a default reason and a default condition.

A previous release at revision `0005` is given the same without what `0006` brought.
Its stack and its clusters say nothing of the members they are to have, of what is
observed, or of how they are managed; there is no stack of one switch, no condition
and no observation; and a record has one primary address, so there are seven
addresses. A release from before there were groups is given the items alone, and one
from before there was an inventory is given none.

A previous release at revision `0007`, which is 0.5.0, is given what that revision
brought as well, and what was made before is put there:

- places: a region with a region beneath it, a site whose deliveries go to its street
  address, a site that is a draft, a building with a room in it, and a room of the
  draft site;
- people: two contacts, the technical contact of the region, the shipping contact of
  the site and a building where nobody takes shipments, two operators, one of them
  with nobody behind it, and the two people of an owner, a primary and an alternate;
- the item with every value in the room, with an operator of its own; the first item
  planned for the room of the draft site; the first stack in the building, with the
  open operator, so that its switches and their minor items are there and have that
  operator from it; and the other operator on the site.

A previous release at revision `0008`, which is 0.6.0, is given what that revision
brought too. No release before it can store any of this, so the upgrade to 0.6.0
itself does not carry it, and the upgrades after it do:

- a support agreement with two contracts in it, one that says nothing of its own and
  one that overrides the last day and the support level, a contract that stands by
  itself and was renewed once, so that it has an earlier term, one that has expired,
  and one whose term has ended and whose renewal is pending, which covers still;
- a renewal that was entered early, on a contract and on the agreement, each kept as
  the next term while the present one runs on;
- coverage: items under the first contract, one of which was retired afterwards,
  which ended its cover on that day and marked it as having left service, one cover
  that a person ended, two items under more than one contract, and one under the
  contract that has expired;
- a purchase request with two lines, on one of which three items arrived, two with a
  serial number and one as a count, named for its line, a request that is a draft and
  one that was cancelled;
- external systems, one of them retired, and registrations of the first stack and of
  an item, one pending, one confirmed at a moment written with no zone and one
  removed;
- capacity lines of both sides, one in a category of the site's own with a cost, a
  vendor and a site, one a draft, one that has ended and one retired, and a label of
  the site's for a default category.

A previous release at revision `0009`, which is 0.7.0, is given what that revision
brought as well. No release before it can store any of it, so the upgrade to 0.7.0
itself does not carry it, and the upgrades after it do:

- the contacts of the agreement from before, an account manager and a support
  contact, and a contract in it that names an account manager of its own in place of
  the agreement's;
- the flag not to renew on the second model, and so on its items, one of which says
  otherwise for itself, and on a switch of the first model by itself;
- a support agreement whose renewal is entered early with its two members: one is to
  have a new number, which waits on the agreement's next term, and one ends with the
  present term; an endpoint that is not to be renewed is left behind, with a cover
  that ends with that term;
- a purchase request with a line that this inventory does not track, which has a part
  number and no model, and a line of the first model with a part number;
- a line of tools that multiplies the engineers from before, with its target;
- the record of the week's capacity balance, recorded by hand and corrected with a
  reason;
- links on the second model, the region, the site and the room from before; and
- the renewal alert, seen by the Admin.

It is tried, before there is a release after 0.7.0, by upgrading the package of 0.7.0
to itself under a later version number, as
[release-process.md](release-process.md#the-previous-releases-package) says.

A previous release at revision `0010`, which is 0.8.0, is given what that revision
brought as well, in `witness_circuits`:

- three circuits, one of each shape: both sides at locations from before with a router
  from before at its A side, a far end in the carrier's network with its note, and one
  switched to count at its Z side;
- three carriers, one of them another carrier of a circuit with a number of its own,
  and cost lines among which a rate that has ended and a credit;
- an item and a device group connected as devices;
- the account manager and the support desk of a carrier, named once on it, a contact
  that a circuit names of its own and a site contact of a side;
- a circuit group with circuits in it;
- weights on a region, a site and a location; and
- the six weights and `circuit_cost_side` set, which are put back at the end.

It is tried, before there is a release after 0.8.0, by upgrading the package of 0.8.0
to itself under a later version number, as for 0.7.0.

Afterwards every item, group, membership, network, address, owner and choice must be
as it was, field for field and at the `row_version` it had, every item with its history
event for event, and no choice may be added. So must every record of what came after
the groups, list by list: the regions, sites, locations, contacts, operators and
assignments, from `0008` the agreements, contracts, coverage, purchase requests
and lines, external systems, registrations and capacity lines, and from `0009` the
contacts of the agreement and of the contract and the records of the capacity
balance. What is worked out of
those records must be answered as it was: the tree of places with what it counts and
what is planned at each, what the room has in force, the summary by operator, and
from `0008` the earlier term of the contract that was renewed, which is read from the
audit trail, the coverage report, the capacity report, the summary by contract and
the portfolio of the vendor, and from `0009` the renewal worklist, the alert as the
Admin has seen it and what the coverage report counts by model as not to be renewed.
A newer version may give such an answer more, as it may a record: a section more of a
report, which the comparison passes over, and the rest must be as it was. The first
stack must say of itself all that it said, the master that is seen and when among it. A
second item with a serial number of the same model, one with an asset tag that is taken,
and a second group of a name that is taken must still be refused. The whole inventory,
the cluster by how it is managed, and the stack of one switch with its whole support
weight must be counted as the previous release counted them.

The tables are read from the database file too, the eleven of the inventory where
there are groups, eighteen with those of the places and the people, twenty-six
with those of the contracts, the purchases, the external systems and the capacity
lines, thirty with the contacts of contracts, the targets of capacity lines, the
records of the capacity balance and the renewal alerts that were seen, and thirty-eight
with the circuits, their carriers, cost lines, devices and contacts, the contacts of
vendors, and circuit groups and their members. A table that
has no `hid`, as the targets have none, is read by its primary key. Where there is no
migration, each must have the columns, the indexes, uniquenesses and foreign keys, and
the rows it had, the schema must be the same statement for statement, and the audit
trail, read before anything is asked of the new version, must hold the events it held
and no other, but for the one that a service of 0.7.0 or later writes by itself when it
starts in a week that has no record of the capacity balance: one `create` of a
`capacity_record` that the system makes, which every upgrade allows for, by name and at
most once. Where there is a migration, each must have every column it had, as it was,
and after them the columns that the migration is said to add and no other; the indexes,
uniquenesses and foreign keys likewise; and every row must hold what it held in the
columns it had.

**What one upgrade alone has** is kept apart from all of that, in
`packaging/package-test.d/`:

- `migration-<revision>.sh` is read when the upgrade runs that migration.
- `release-<version>.sh` is read when the upgrade crosses that release: the previous
  release is older than it, and the version under test is not. It is for a release
  that says or reads differently, with no migration, something that it holds as
  before. Most releases have none.

Such a file has up to three functions. The first runs while the previous release
serves: it makes, through that release's API, what the migration could harm or is
meant to change, and names what is meant to change. The second runs each time the
inventory has been compared on the new version, in both upgrade passes: it looks, by
itself, at what was left out of the comparison, and at what the migration put into
what it made. The third runs in the upgrade pass alone, last: it tries what is new on
what was carried over. What is meant to change is named, never implied: the fields of
records, each by HID and field, which the comparison passes over; the rows of a table,
by HID, which the comparison of its rows leaves out; the columns, indexes and foreign
keys that the migration adds to a table, which must be there and no other; the columns
that it declares otherwise, each in its place, such as one that may now be blank;
tables that hold what a site made and are no part of the inventory, which the
migration changes, and which are then kept and compared as the inventory's are; a list or a
table that may have more records than before; and the view of the items that must be
counted as before, where some are meant to be counted otherwise. A migration that
writes no audit event says that too, and the audit trail is then read before anything
is asked of the new version, as after an upgrade with no migration. Everything that is
not named is compared as in any upgrade.

A migration that has no file is given what every upgrade is given, and both upgrade
passes print a `SKIP` line that says its own checks are not written. Nobody has then
said what it adds: every record, column and row that was there must be as it was, and
what is there beside them is let be until the file names it. So a release with a
migration adds one file, and nothing else in the test changes on its account.

`migration-0006.sh` is the example of the first kind, for the migration that 0.4.1
brought. The releases before it let an item that had left the team's hands stay a
member of its groups, and the migration ends such memberships. With the previous
release the file moves an endpoint of the controller domain to Released, makes a second
stack of two whose second switch is Released as well, and sees that both are members
still. That release has no list of conditions and refuses a choice in it, which the
file shows; the migration is written to leave alone what it finds in that list, so two
conditions are written into the database as a site's own. The file names the two
memberships, the groups and controllers of their items and the member counts of their
groups as meant to change, the three columns and two indexes that `items` gains, and
the six columns and one foreign key of `device_groups`, which is made anew. After the
upgrade it looks at each membership by itself: ended on the day of the upgrade, at the
next `row_version`, with an event in the audit trail that the system made, and its
item in no group. The new columns must hold nothing, but for `managed_as`, which says
`one` for each cluster; the list of conditions must hold its six defaults and the
site's two, with `good` there once under the site's label; and the second stack, now
one switch alone, must be counted with its whole support weight. Last, an item from
before takes a condition and an observation, and the cluster is said to be managed by
its members and counts as two managed nodes.

`migration-0007.sh` is the one that 0.5.0 brought, and what it looks for is what
[install.md](install.md#from-042-to-050) tells an operator of that upgrade. The
migration creates the tables of contacts, operators, regions, sites, locations and
contact assignments, makes `items` and `device_groups` anew, each with three columns
that refer to a location, a planned location and an operator, loads the lists of
contact roles and of location kinds, and creates the table of the members of owners
last. It is to change no record there is, and to write no audit event, which the file
says. With the previous release the file makes an owner outside the team, an item that
is with it, a minor item in that item and a device group with that owner; six items
that have no owner of their own in a group that has one; and four choices of a site's
own in the two lists, which that release takes although it uses neither. It sees that
a file of items with a `location` column is refused, and one of device groups, and
that the management report with no `by` is by nothing. The file names the three
columns, the three indexes and the three foreign keys that each of `items` and
`device_groups` gains, and says that choices may be added.

After the upgrade the seven new tables must be empty and the new columns hold nothing;
no item and no group may be anywhere or have an operator, the tree of places must be
empty, and every item counted as nowhere. What is with the owner outside the team, the
item, its minor item and the group, must be marked as an exception with the reason
that the owner has, and an item is refused a reason of its own. The six items in a
group that has an owner must have that owner in force, from the group, each at the
`row_version` it had: the count by owner has moved by exactly those six, which is the
one thing the comparison leaves out, by name, and looks at by itself. Each of the two
lists must hold its defaults and the site's own; and the management report with no
`by` must be by site, with one row, of the items that are nowhere, and totals as the
previous release gave them.

Last, what is new is tried on what was carried over. A region, a site and a location
are made, and a contact is given a role of the site's own there. An operator on the
site reaches an item there. The two files that the previous release refused are
applied: the first stack from before is placed by its file, and its switches and
their minor items are where it is, with nothing written to them. An item planned for
a draft location is moved in when the location is made active, with an entry in its
history. All of it is then taken out again, and the places are retired, so that the
rest of the pass starts from an empty tree.

`migration-0008.sh` is the one that 0.6.0 brought, and what it looks for is what
[install.md](install.md#from-050-to-060) tells an operator of that upgrade. The
migration creates the tables of agreements, contracts, coverage, purchase requests and
purchase lines, makes `items` anew with one column more, the purchase line an item
arrived on, creates the tables of external systems and registrations, loads the list
of capacity categories, and creates the table of capacity lines last. It is to change
no record there is, and to write no audit event, which the file says. What it makes
anew, the `items` table, is in the inventory already, from 0.5.0 with a location, a
planned location and an operator on some of its rows; so with the previous release
the file makes only two choices of a site's own in the list that the migration loads,
which that release takes although it does not use it. It sees that the previous
release knows no contract, refuses a summary by contract, says nothing of cover in
the record of an item, and refuses a file of items with a `purchase_line` column. The
file names the one column, the one index and the one foreign key that `items` gains,
and says that choices may be added.

After the upgrade the eight new tables and the eight lists must be empty and the new
column hold nothing; no item may be covered, registered or have arrived on a line,
and no group be registered. The coverage report must count every major item that the
previous release had in Assigned, Test, Prod or Down as in service with no cover, and
nothing else, with no contract lapsed; the `service_states` setting must be at its
default; the summary by contract
must have one row, of what no contract covers; the capacity report must show the
support weight that the previous release counted as its only demand, and no supply;
and the list of capacity categories must hold its six defaults and the site's own,
with `staff` there once under the site's label.

Last, what is new is tried on what was carried over. A purchase request is made for
the model from before, the file that the previous release refused is applied, and
one more item is received on the line. An agreement is made with the vendor from
before and a contract in it, which has its period from the agreement; two items from
before and the one that arrived are put under it, and the item that was retired before
the upgrade is refused. The one that arrived is retired: its coverage is ended on
that day and says that it left service, and the report lists it as out of service
under a contract that still runs. The contract is renewed for a period that has
begun, and the items show the new
number at the `row_version` they had. The first stack is registered with an external
system, and its switches are not. A capacity line is entered in the category that
the site had put into the list before the upgrade. All of it is then retired, ended,
marked as removed or cancelled, so that the rest of the pass starts from reports as
empty as a new installation's.

`migration-0009.sh` is the one that 0.7.0 brought, and what it looks for is what
[install.md](install.md#from-061-to-070) tells an operator of that upgrade. The
migration gives columns to `catalog_entries`, `items`, `regions`, `sites`,
`locations` and `contracts` as they stand, makes `purchase_lines` anew so that its
model may be blank, with a part number and a description, and `capacity_lines` anew
so that its quantity and its units may be blank, with an effect, a factor and a
share. It gives `import_jobs` and `import_rows` the counts and the outcomes of an
apply in the background, and a job that was applied before the counts it would have
had, which is the one thing it changes. Then it creates `contract_contacts`,
`capacity_line_targets` and `renewal_alert_views`, and `capacity_records` last. It
writes no audit event. What it makes anew and what it gives columns to are in the
inventory already from `0008`, with every kind of record, and the file sees that
they are. With the previous release it makes three import jobs, one applied with a
row rejected, one that failed because its record was changed after the preview, and
one that waits, and sees that the previous release refuses a line with no model and
has no record of the balance and no alert. It names the two import tables as tables
beside the inventory, the row of the applied job as meant to change, every column
the migration adds, and the three that it declares as may be blank.

After the upgrade the applied job has worked its three rows and applied two, the
others none, and nothing else of any job is changed; no row says what an apply did
with it. The three new tables are empty and the new columns hold their defaults: no
model or item is flagged, no place or model has a link, no contract is marked, every
line has its model and adds, and no row refers to a record that is not there. The
service has recorded the balance of the week by itself, with the figures of the
capacity report of what was carried over and one event that the system made. The
five settings that were constants are at their defaults; the coverage report counts
nothing as not to be renewed; the renewal worklist and the alert count the contract
whose renewal is pending, and the alert is shown to the Admin, who has not seen it;
and the regions at the top with what is nowhere add up to the support weight of the
capacity report. Last, what is new is tried on what was carried over. The job that
waited is applied in the background, answered `202`, and the one that failed is
refused. The agreement from before has its early renewal withdrawn and entered again
with its member, which is to have a new number that waits, and the items under it
are not written to; withdrawn once more, the number goes with it. A switch in Prod
that no contract covers is flagged and counted by itself under its model, and then
has its model's flag again. A line that multiplies the engineers from before adds
0.75 units, the week is recorded by hand in place of the system's record and
corrected with a reason, and the line is retired. A model and a room are given
links.

`release-0.4.2.sh` is the example of the second kind. 0.4.2 has no migration. One
thing that it says differently of what it holds is left out of the comparison by name
and looked at by itself: the health of the two items whose condition is the site's
own, or untested, is not known, as before, and its reason must now name the condition.
And one thing that it reads differently is tried on what was carried over. The
releases before it read a moment with no zone as UTC and stored that moment, which
the file tells the inventory to expect of them: the moment stored for 09:00 must still
be 09:00 in UTC after the upgrade, while the same words given to the new version must
be 09:00 in the application's zone, 14:00 in UTC, for an item and for the moment a
master was seen at. A filter for 09:00 with no zone must find the item that was told
so after the upgrade, and one for 09:00 with `Z` the item from before.

`release-0.6.1.sh` is the second, and what it looks for is what
[install.md](install.md#from-060-to-061) tells an operator of that upgrade. Each thing
that 0.6.1 says differently is a field, a route or a column more, which the comparison
lets a record have, so the file names nothing in `meant`. With 0.6.0 it makes a support
agreement whose term has ended and a contract in it with no dates of its own, which is
renewed with a new number and so has an earlier term that 0.6.0 gives with no dates;
the agreement is then renewed late, for a period that has begun, and 0.6.0 has no list
of its earlier terms. It puts an item by hand on a purchase line of another model,
which 0.6.0 lets in and says nothing of, and takes an item that two contracts cover to
Archived, which ends both coverages as having left service. It sees that 0.6.0 refuses
a file of items with the columns that 0.6.1 adds. The earlier term is kept as an answer
without its dates. After the upgrade the dates are those of the agreement's term that
was in force when the contract's term began, as the agreement stood then, and not as
its renewal left it, each marked as the
agreement's; the agreement lists the term that its renewal ended, as 0.6.0 wrote it in
the audit trail; a contract says beside each override what the agreement gives; the
item on the line of another model is reported on its record, in the item list and by
its line; and the item in Archived, and the one retired before, are counted by the
contracts that still count them, on their records, in the item list and in a file of
items. Last, the item on the wrong line is edited in another field without a refusal,
is refused a third model, and is put right with the line's; an item put on the line
now takes its model; the files that 0.6.1 exports with the new columns are taken back
unchanged; and `hirdir agreements show` and `hirdir contracts show` print the earlier
terms and an override as they now are.

`migration-0003.sh` is the smallest. The release before that migration kept a support
weight to three places, so the file has the inventory give its first model one of
three, and says what the migration is to make of it. It does not name the rows that
the migration writes anew, and says so in a `SKIP` line of its own. The migrations
`0004` and `0005` have no file.

**Where there is no migration**, the failed-upgrade pass has nothing to make fail:
nothing writes a revision into `alembic_version`, so neither a table in the way nor the
trigger below would stop anything. It prints its `SKIP` line and tests what is left of
it, without nginx. The upgrade must go through with its backup taken, the schema the
same statement for statement, no audit event written, and every table and record of the
inventory as it was. A user group is then entered with the new version, and the previous
package is installed over it with `apt install --allow-downgrades` and nothing else: it
must go through, where after a migration it stops at the database, start the service,
and serve every record as the previous release gave it before, exactly, with that user
group still there. That is the way back that
[install.md](install.md#going-back-to-the-release-before) gives for such a release.

`migration-0010.sh` is the one that 0.8.0 brought, and what it looks for is what
[install.md](install.md#from-070-to-080) tells an operator of that upgrade. The
migration gives `regions`, `sites` and `locations` a support weight, each made anew by
SQLite with its indexes, creates the seven tables of circuits, their parts and the
contacts of vendors, and `circuit_group_members` last, and loads the `circuit_type` and
`carrier_role` lists beside any value a site has put into either. It changes nothing
that is held and writes no audit event. With the previous release the file sees the
places it makes anew in the inventory, with their shipping addresses, operators,
contacts and links, sees that the previous release refuses a value of either list and
a file of regions with a `support_weight` column, and puts three values of a site's own
into the lists in the database. After the upgrade the new tables are empty, the places
weigh nothing, the seven settings are at their defaults, the capacity report is the
items' weight alone, the four long reports are kept since the service started, and both
lists hold their defaults beside the site's values; then a region is weighed by the file
the previous release refused, a circuit is entered between places and with an item from
before, a new circuit counts at its Z side once the setting says so while the old one
stays at A, a circuit group, the report of what circuits cost, a default circuit weight,
a Try that saves and audits nothing, and the check of kept answers, which finds nothing
differing, are tried, and all of it is taken out again.

**A migration that fails**, in a release that has one, is made to fail in the database,
never by changing the package, and how is read from the package as well. Where the new
version creates a table, the table it creates last is put there beforehand, as
`addresses` was for 0.4.0, `owner_members` for 0.5.0, `capacity_lines` for 0.6.0,
`capacity_records` for 0.7.0 and `circuit_group_members` is for 0.8.0, so that
everything else the migration does is done
before it fails: migration `0007`
has by then created five tables, made `items` and `device_groups` anew and loaded two
lists, and migration `0008` has created seven tables, made `items` anew, with the
locations and the operators that its rows refer to, and loaded a list, and migration
`0009` has made
`purchase_lines` and `capacity_lines` anew, given columns to six tables and counts to
the jobs that were applied, and created three tables, and migration `0010` has made
the three tables of places anew and created seven tables, and all of that has to be
undone.
Where it creates none, as 0.4.1 creates none, a trigger is put on
`alembic_version` that refuses any change to it. Writing the new revision into that
table is the last thing a migration does, so for migration `0006` the failure comes
when the columns are added, the `device_groups` table is made anew, the clusters are
marked, the conditions are loaded and the memberships of the items that are Released are
ended, each with its audit event, and all of that has to be undone: the pass looks for
the rows of the members as they were, and for an audit trail with no event more. The
trigger disturbs nothing else: the previous release serves with it in place, and the
backup that the upgrade takes holds it. The file of a migration may ask for the trigger
though the migration creates a table, for one that creates its tables before it changes
those that hold a site's records. A column of a name the migration adds, put there
beforehand, was tried and does not serve. Where the column is added to the table as it
stands, as on `items`, SQLite refuses it, but at the migration's first statement, with
nothing yet to undo. Where the table is made anew, as `device_groups` is, the column
that is already there is taken over without a word and the migration goes through.

`packaging/package-test.sh --upgrade-alone` runs the upgrade pass up to where it goes
on to what the fresh pass does, and stops there with a `SKIP` line. It is for work on
the upgrade passes, and for trying a pair of older releases, as in
`PREVIOUS_DEB=dist/hirdir_0.4.0_amd64.deb DEB=dist/hirdir_0.4.1_amd64.deb
packaging/package-test.sh --upgrade-alone`: the package of an older release cannot do
what the fresh pass asks of this tree's. The failed-upgrade pass does nothing of the
fresh pass and runs whole for such a pair. Neither is the release check.

**Files**, in the fresh pass and so in the upgrade pass too, all through nginx under the
prefix. The thirty-three files of `examples/` are sent in load order to `POST /imports/preview`
and applied: every row is created, and the lists of minor items, networks, device
groups with their members, and addresses hold what the files hold, and so do those of
regions, sites, locations, contacts, their assignments and the members of owners, and
those of agreements, contracts, coverage, purchase requests and their lines, external
systems, registrations and capacity lines,
beside what an upgraded installation had of them. What the examples show of 0.6.0 is
looked for: the two contracts in the Cisco agreement have its period, and one of them
overrides its support level, while the contract for the switches bought lately stands
by itself; a spare arrived on a purchase line, took the place of a switch and is
under that contract, and the switch that left is out of cover, a person having ended
it, and its registration removed; the first line of that request has two of its four
still to come, the second has its part number as procurement gave it, and the third,
of tape, is not tracked and waits for nothing, so that `hirdir purchases show` counts
two of the eight that are tracked as arrived; the core stack is registered with two
systems, and its two switches, which have no registration of their own, say what their
stack is registered with and are found by `registration.system`; the portfolio of Cisco
has all four kinds, its agreement and its three contracts, and its filter lists as many
items as it counts, and the portfolio of the reseller has the contracts that were bought
through it, by the reseller in force; and the summary by contract has a row for each
contract that covers something. The dates of the contracts are fixed in the files, so
what the coverage and the end-of-life reports must count is worked out from the files
for the day the report says it is of, by the rules of D-140 to D-142, D-149, D-150 and
D-182, and never written into the test: the major items in Assigned, Test, Prod or Down,
those of them that are covered and that are not, those that no contract covers and that
are not to be renewed, by their own flag or their model's, which are left off what is
not covered and what runs out soon, those out of service that a contract still counts,
those whose cover runs out within ninety days, those under more than one contract and
those under a renewal that is pending; and for each of the four dates the items past it
and within two years of it. The capacity lines of the examples are those of the worked
example, against a support weight of 32 where the worked example has 2,400: the report
must give a demand of 2.11, the supply of 9 by category, a balance of 6.89 and a
coverage of 427.22%, and a supply of 10 with the draft line. What the examples show of
0.5.0 is looked for: the tree has Americas with its two regions and their sites, and not
the site that is a draft until the drafts are asked for; it counts at Americas, at
Site-2, in Room 102 and in the rack within it the items that `examples/items.csv` puts
at or beneath each, a minor item where the item it is in is, and what is in the tree,
what is nowhere and what is hidden add up to the totals; Room 102 has the shipping
contact of its site, the technical contact of its building and not the two of the
region, the shipping address of its site whole and the instructions of the region; the
store room, which is in no building, has the two technical contacts of the region and
instructions of its own; the room of the small office has no shipping contact, because
its site says that nobody takes shipments there; the one item with an owner outside the
team is marked as an exception, with its reason; and the management report with no `by`
is by site, and by region has the items in the row of each region above them. What the
examples show of 0.4.1 is looked for: the core stack is found by the serial number of
the master that is intended and shows that of the master that is seen; the address that
two routers share is held once, by their cluster; `GET /reports/duplicates` lists the
one address that two virtual machines hold by mistake, and no other; the item list finds
as many items of each condition as the file has; a router that is Down and observed
unreachable is `degraded`, and a stack that is short of a member says so. The summary
must hold no money and count every component once by health, and the components of each
condition in its totals must be those of the rows when it is asked for by condition; the
management report must hold the money and refuse `by=health`. The examples must weigh
and cost what `examples/` says, a support weight of 32 and an annual support cost of
67140.00 in all, with their one licence at quantity 1. Sent a second time, as CSV and as
JSON, every row is unchanged. A filtered export is taken as CSV and as JSON: its rows
are those the examples hold for the filter and those the list gives, and `hid` comes
first. An export of stored values is imported back unchanged. A file of more than a
megabyte is imported, and its apply sent twice with an `Idempotency-Key`. Then the
limits: a body of exactly 20 MB passes nginx and is answered by `hirdir`; one byte more
is refused by nginx with its own `413`; the same body sent straight to the service is
refused by `hirdir` with a
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
online and observed unreachable, and `degraded`, each time with its reason; a condition
that the list does not offer is refused; the item is found by its health, and each
change is in its history. An observation that is stated again as it is, with no moment,
has its moment set to now, at the next `row_version`; the moment is not cleared by
itself, one that is three days ahead is refused, and one with no zone is in the
application's time zone: 09:00 comes back as 14:00 in UTC. A filter reads its value the
same way: 09:00 with no zone finds the item, 09:00 with `Z` does not, and 14:00 with `Z`
and 09:00 with `-05:00`, which are that moment, do. An item with a condition that the
site added to the list has a health that is not known, with a reason that names the
condition and says that it says nothing of health; `untested` is named likewise;
observed present, the item is `good`. A stack of one switch with no master is `degraded`
for being alone, has no serial number until its switch is seen to be master, and has the
whole support weight of its switch; told to expect one member it is no longer degraded;
with a second switch it earns the discount, and its value and cost in the management
report are those of two; with that switch in Pending-Removal it is degraded again. A
cluster of two is one managed node, then two when it is managed by its members, then
three when it is managed as a cluster as well, with two components and the same support
weight each time, and `managed_as` is refused on a stack. Four items that are failed,
degraded, unknown and good are listed in that order when the item list is sorted by
health. A member moved to Pending-Removal stays a member; moved on to Released it is in
no group, and is refused when it is to join the cluster again or to take a member's
place in a replacement; the other, moved straight to Archived, leaves too, and both
memberships stay on record with the day they ended. Last, a file of `hostname` and
`IP_address` columns is sent as it is: its three rows are created, each address is the
primary management address of its family, and the same file a second time changes
nothing; a second file with `ipv4`, `ipv6` and `observed_status` columns gives two of
the items an address of the other family and a health of `good`, and sent again, stating
what was observed with no moment, it changes nothing. A third file, of `hostname` and
`observed_status` alone, names two switches that have serial numbers: each row finds its
switch by the host name and updates it, and no second item is made.

**The records of 0.5.0** follow, as scenarios S24 to S28 have them, each in small, with
the half of S18 that came with this release. A region is made with two regions beneath
it, a site in one of them, two buildings with a room in each, and a location that is a
draft: each has its path, a second room of the same name in one building is refused,
and so is a name that holds the mark between the names of a path. Five switches are
put in the room, the building, the draft location and nowhere, and a power supply in
one of them, which is where its switch is, with the source `parent_item`.
`GET /geography/tree`, asked for these items alone, has three items and two components
in the room and four and three at every level above it; beside the tree stand one item
that is nowhere and one that is hidden, in the draft location, and the three add up to
the totals, as they do over everything there is. Asked for with the drafts and from the
site alone, the tree is the site with the draft location in it and nothing hidden. The
item list finds the same items by `location:within:` with a path and with an HID, by
`location:empty:true`, and by the names of the site and of a region. A switch is moved
to the other building: its power supply is there too, nothing was written to it, and
the tree follows. A technical contact is put on the region and a shipping contact on
the site: `GET /locations/{hid}/effective` shows the room both, each with the level it
came from, and nobody for a role that no level has, and `GET /sites/{hid}/effective`
and `GET /regions/{hid}/effective` answer the same for a site and a region. A contact
with the email address of another, written in capitals, is refused. The building is
given a technical contact of its own and the one of the region is changed: the room
keeps the building's, and the room of the other building shows the new one. The other
building says that nobody takes shipments there, with an assignment that has no
contact and stops the search, and takes no shipping contact beside it. The room has
the shipping address of its site and the instructions of the region; given two lines
of an address on the building and instructions on the room, it has the building's
address whole, with nothing of the site's in the lines the building left out, and its
own instructions. Each of the two regions beneath is given an operational contact, and
the site is moved to the other region: its path and the paths beneath it follow, the
room shows the contact of the region it is in now, the tree and the item list have the
items there, no item was written to, and the move is one audit event, an update of the
site. The summary by site and the management report by region label a row with the
path of its place, have the item that is nowhere in a row of its own, and count an item
once in the totals though it is in the row of each region above it. A room with an item
in it is not retired, nor the site, nor the region above; the region that holds
nothing now is. A building and the room in it are retired, and the room is not brought
back while its building is retired. An owner outside the team is refused with no reason of its
own; an item given to it is marked as an exception with the owner's reason and found
by `filter=owner_exception:eq:true`, as is a minor item of such an item, and an item
is refused a reason of its own. The first
person of an owner is its primary and is refused as an alternate; another made primary
makes the first an alternate in the same change; the primary is not removed while
another remains. A file of the people of an owner that has none, with the row of the
alternate before that of the primary, is applied whole, and
`GET /owners/{hid}/members` lists the two as a page. **Operators, deliveries and plans**, in the fresh pass and so in the upgrade pass
too. An operator is made and is had by an item of its own, from the item above, from
its group and from its place; it is handed over and left open with no item written
to, and released, so that the next level up decides; the two filters, the summary by
operator and the summary with `operators=true` are read, and `hirdir operators list`,
`assign`, `assign --open` and `release` and `hirdir report summary --operators` are
run. The street-address tick is set on a site and had by a location in it, refused
beside a shipping address of its own and with no street address, and shown as an
override of a region's address. A planned location is given to an item and to a
group; a room in use is refused as a plan; the tree counts what is planned; and a
site made active moves in what was planned for it, with an audit entry for each
record under the one request. A member with nothing of its own has its group's
location, plan and owner.

Last, every region, site, location, contact, operator, assignment, owner and
member of an owner is exported and imported back unchanged, as CSV and as JSON, and an
export of the items placed here writes the location of each as its path.

**The records of 0.6.0** follow, as scenarios S29 to S35 have them, each in small and
asked for with a filter that finds these items alone. Two switches in Prod, each in a
room of a region of its own, are put under one contract by one request, and the
coverage report counts both as in service and covered; one is moved to Archived: its
coverage ends on that day and says that the item left service, the report lists it as
out of service under a contract that still runs, the filter of that section lists the
same item on the item list, and the contract has both in scope and counts one as
covered. A switch under no contract is the one item listed as in service with no
cover, also once it was put under a contract by mistake and that coverage removed
outright, with an audit event; and a switch of a model whose LDoS is next June is the
one that the end-of-life report lists as approaching it, in the fiscal year of that
date. A renewal with a period that starts after today is kept as the next term: the
contract keeps its number and its period, its item is covered to the last day of the
next term with nothing written to it, and the next term is withdrawn again. The
contract's period is ended a month ago and its status said to be `renewal_pending`:
it covers still, and the report lists its item under the renewals that are pending
and not as uncovered; said to be `active` again, it has lapsed, covers nothing, and is
found by the filter that the report gives for the lapsed contracts. A second
vendor is given two switches, a virtual machine, a software application and a
service: its portfolio has the four kinds, each with its items, its cost and its
weight, the totals and the four models, and its filter exports the five items. A
purchase request has a line of ten switches, none of which is an item or a component;
six are received and are six items in Delivered that name the line, still no
component, with four still to come, five more are refused, and the receipt is in the
audit trail as one request: the receipt of the line, and the creation of each item.
The other four are received as a count: each is named for its line and its place on
it, and the request says `received` by itself, by the same request. A stack of four is
registered with a monitoring system and an SDN controller, and not a second time with
the first: both registrations are on the stack, none is a registration of its
switches, and each switch says in `group_registrations` what its stack is registered
with; `filter=registration.system:eq:` finds the stack, and among the items the four
switches, while `ne` finds a fifth switch that is in no stack; a registration of that
one, made by mistake, is removed outright, with an audit event. A site that is a draft,
with a draft room and three draft switches in Prod, is in no list, no summary, no
management report, no tree and no coverage report until the drafts are asked for, and
the capacity report has their support weight with its drafts alone; made active, the
site, the room and the items are in every count. Of two switches one is moved to
Archived: it is hidden by default, listed with its state when the archived are asked
for, reached by its HID, and has its creation and its three moves in its history. A
service account that holds View-only reads the lists, the reports and the portfolio of
0.6.0, and is refused each of its twenty-three writes with a `403`, the removal of a
coverage and of a registration among them.
Last, every agreement, contract, coverage, purchase request and line, external
system, registration, capacity line and replacement is exported and imported back
unchanged, as CSV and as JSON, and an export of the items that arrived names the line
of each.

The examples are imported into an inventory that does not hold them, and the checks
that follow make records of the same names by hand. So the pass takes a backup before
the import and restores it afterwards, with `hirdir admin backup` and `hirdir admin
restore`. In between, with the examples and the records above still loaded, `hirdir
admin reset` is tried as an operator would use it: it must refuse while the service
runs, change nothing without the word `reset`, and then clear every table of the
inventory, those of the replacements, groups, members, networks and addresses, of the
regions, sites, locations, contacts, assignments and members of owners, of the
agreements, contracts, coverage, purchase requests and lines, external systems,
registrations and capacity lines, and of the contacts of contracts, the targets of
capacity lines, the records of the capacity balance and the renewal alerts that were
seen among them, each of which holds rows before and none after, and keep the
accounts. The examples hold no line that multiplies and nobody has seen the alert, so
two records of 0.7.0 are made beside them for the reset to find: a line of tools that
multiplies the network engineers of the examples by one and a half, which counts 1.5
units more under tools, and the alert as this Admin has seen it, which is then not
shown to them again that day. The record of the balance is the one the service made
when it started.

**The capacity balance**, scenarios S39 and S40, is worked after that, where the
inventory holds four items made by hand and no capacity line, because the report is of
the whole installation and takes no filter. One more item is given the support weight
that brings the inventory to 2,400, and the eight active lines of the worked example
on the [data model](data-model.md#capacity-balance) page are entered: the report must
give 8 units of infrastructure demand and 2 of other work, a demand of 10, a supply of
9 by category, a balance of -1 and a coverage of 90%, with two thirds of the supply
the team's own. The services line is added as a draft: without the drafts nothing
moves, and with them the supply is 10, the balance zero and the coverage 100%. The
professional services line is given a last day that is past, and drops out of the
supply in both views. The lines and the item are then retired, and the report is as
it was.

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
examples hold by mistake, and not the one that two routers share. `hirdir geography
tree` must print the places of the examples, each beneath what it is in, with the
items and components that `GET /geography/tree` counts, and with `--root`,
`--no-locations` and `--include-drafts` one region with its sites, the draft among
them; `hirdir locations show` must take a room by its path and print each contact, the
shipping address and the instructions with the level they came from; `hirdir regions
list` must write the file that `POST /exports` gives; `hirdir sites move` must give a
site another region and say its new path, as one change that is audited as made
through the command line, and exit with 4 for a site that there is not; and `hirdir
report management` with no `--by` must be by site. Of what 0.6.0 added: `hirdir
agreements list`, `contracts list`, `purchases list`, `systems list`, `registrations
list` and `capacity list` must each write the file that `POST /exports` gives;
`hirdir contracts show` must take a contract by its number and mark what it has from
its agreement; `hirdir contracts cover` must say how many items a filter would put
under a contract and change nothing until `--apply`, cover them with it, and exit
with 5 when they are covered already; `hirdir contracts set` must roll the contract
that stands by itself into an agreement, as one change that is audited as made
through the command line, and take it out again; `hirdir contracts renew` must give
it a new number, period, purchase reference and cost, say how many items follow,
leave those items unwritten and keep the earlier term, and exit with 4 when it is
given neither a number nor a period; with a period that begins after today it must
keep the renewal as the next term, which `hirdir contracts show` prints, and
`--withdraw` must take it back; `hirdir agreements renew` must do the same for an
agreement; `hirdir purchases show` must print a request
with its lines and what is still to come, and `hirdir purchases receive` make the
items that arrived on a line, where and when it is told, exit with 4 for more
than is still to come, and with `--count` make the rest of a line as items named for
it; `hirdir vendors portfolio` must print what the portfolio
answers and, as CSV or JSON, write the items of the vendor with their cover; and
`hirdir report coverage`, `end-of-life`, `replacements` and `capacity` must give what
the reports of the API give at that moment, as JSON and as tables, the coverage
report with its seven counts, the lapsed contracts and each of its sections. They are pointed at
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

### Timing at scale

The response target in [requirements.md](requirements.md#qualities) is held against a
fixture of the size the target names. `make fixture` runs `scripts/seed_fixture.py`,
which fills `fixture-data/`, a folder of its own that git ignores, with a database at
the newest schema and 50,000 fictional items: 15,000 major items that are not phones,
22,000 phones, and 13,000 power supplies, modules, line cards and optics in them. Beside
them are a catalog of some three hundred models of six makers, regions, sites and their
locations, owners and operators, 360 stacks, firewall clusters and wireless controller
domains, 24 agreements and 320 contracts in every status, and the coverage of most
major items: some under two contracts, some ended, some ended because the item left
service and marked so. Some items are in Pending-Removal, Released and Archived, and
some are retired. Many of the items bought in the last two years arrived on the lines
of purchase requests, and a few of those are of another model than their line's, as
0.6.0 let in. What 0.7.0 added is there too: some of the older models are not to be
renewed, and some 470 items say otherwise of themselves; a few contracts in agreements
are marked to end with their term, and a few that share an agreement's period still
say their renewal is pending or that they have expired, so are to review; and the
operations team has 24 capacity lines, by region and by site, three of them lines that
multiply, two drafts and one that has ended, with the balance recorded for each of the
last four weeks. What 0.8.0 added is there as well: eight invented carriers, each with
an account manager and a repair desk, and 2,000 circuits across the sites, the larger
sites having more: internet, MPLS and voice with their far end in the carrier's
network, and point-to-point, dark fiber and wavelengths to another site of the same
part of the world. Most have one or two cost lines, some were repriced this year and
some have a credit for months of it; some 270 have another carrier for the local loop
or a cross-connect, which bills a line of its own; most have a router at an end; a few
are drafts on order, some were disconnected, some are to be disconnected soon, and
about a hundred are retired. Some 300 have a weight of their own, a few name a contact
of their own, and 37 groups hold them, one of them retired. Three regions, some 35
sites and some 20 main rooms have a support weight of their own, and a few models came
in without theirs. The six weights of the settings are left at their defaults: the
timing sets them in runs of their own. The fixture has an Admin account beside the
one that reads, to set them and to check what is kept. It takes about a minute and a
half. `--items` makes a smaller one of the same shape, and a folder that the script
did not make is left alone.

The fixture is for timing and bypasses the rules. What there are few of, the circuits
and their parts among them, is made through `hirdir.domain`; the items, their tags,
addresses and coverage are written in bulk, as
rows that an import of the same inventory would have written, with an audit event for
each. Dates are counted from the day it is made, so what has lapsed and what is pending
renewal is so on that day. The folder also holds `fixture.json`, which says what is in
it and the accounts to sign in with, and a `config.toml`, so that
`HIRDIR_CONFIG=fixture-data/config.toml uv run hirdir admin serve --dev` serves it on
127.0.0.1:8726.

`make time-filters` runs `scripts/time_filters.py`. It builds the application with
`create_app` on the fixture, in its own process, and asks it through a test client for
the first page the grid asks for, 100 items with the total counted, under each of the
filters and sorts that the coverage of 0.6.0 added and those of 0.6.1, the contracts
that still count an item out of service and the items on a line of another model,
beside the list with no filter; the flag not to renew in force, `effective.do_not_renew`;
the first page of the contract list, with no filter, `to_review` and `renewal_overdue`;
the coverage report, whole, narrowed to a region and a page of a section, the renewal
worklist, whole and a page of a section, and the renewal alert, each of the three
worked out anew, with every kept answer dropped (`hirdir.io.kept.drop()`) before each
run and outside what is timed, and kept, asked again unchanged. Of 0.8.0 it asks for
the first page of the circuit grid, 100 circuits with the fields the grid asks for,
their carriers and groups among them, with no filter and under `location:within:`,
`billed_by`, `effective.down_mbps:lt:`, `in_service:eq:true` and `monthly_cost:gt:`;
the circuit with the most parts, as its page reads it; the list of circuit groups, and
the largest group with a page of its members; the report of what circuits cost in the
present fiscal year by carrier, site, region and group, whole and narrowed to a region;
the capacity report anew and kept, with none of the six weights of the settings set and
with all six; a Try with a default, a minimum and two staff lines; the grid's first
page, the item list by `-effective.support_weight` and the summary, whole and by
region, with `default_item_weight` and `minimum_item_weight` set and without; and the
check of what is kept, as the Admin, with the four long reports kept and nothing else.
A request timed with settings has them set by the Admin through `PUT /settings/{key}`
before its warm-ups, as a person sets them, and returned to their defaults after its
runs. Each request is asked 15 times after 2
warm-ups, and the median and the 95th percentile are printed, each with the load
average of the host over the minute its runs ended in, because a busy host is slower
than the host can be. `--explain FILE` writes every statement of each request with how
long it took and the plan SQLite made for it, and `--url` asks a server that is running
instead, without the requests anew, whose kept answers are in the other process. The
host is shared, so the timing keeps itself to 3 GiB of memory, `--memory` to say
another, where a run takes a few hundred MB: a request that would take more fails in
its process, before the host runs out. A request that is not answered is printed as
such, with its status and after how long, the others are timed all the same, and the
run ends with the status 1.

`make time-import` runs `scripts/time_import.py`, which holds the import quality of
[requirements.md](requirements.md#qualities) against the fixture: 10,000 rows preview
in under 30 s and apply in under 60 s. It copies the fixture's database into a folder
of its own, which it throws away at the end, makes an account with the Inventory role
in the copy, and serves the copy as `hirdir admin serve` does, with uvicorn on a free
port of 127.0.0.1 and the worker that applies imports beside the requests. It makes a
file of 10,000 new switches and access points of the fixture's models, places and
owners, previews it, applies it and asks the job how far it has got until it is
applied, while a person signs in every second. The parts of the apply are timed by
wrapping, in that process only, the parts of `hirdir.io.imports.work_job`: taking the
job, working out the order of the rows, each batch, and the end; the time between two
batches is the pause in which the one writer's place is let go. A sign-in is timed
with nothing else going on first, and each sign-in during the apply is told against
it.

What the target is, and how it is read, is D-165: the median of 15 requests after 2
warm-ups under 300 ms, and the 95th percentile under 600 ms, on this fixture and an
otherwise idle host.

**Measured at 0.6.1.** On the four-core build host, page of 100 with the total
counted, median and 95th percentile in milliseconds, on a quiet host (load average 0.4
to 1.2), before and after the four changes that 0.6.1 made for it:

| Request | 0.6.0 | 0.6.1 |
|---|--:|--:|
| No filter, by name | 645 / 781 | 216 / 377 |
| The grid's first page, major items | 458 / 641 | 173 / 401 |
| `covered:eq:true`, by name | 618 / 794 | 315 / 447 |
| `covered:eq:false`, by `covered_until` | 1124 / 1175 | 473 / 522 |
| `contract_count:gt:1`, by `-contract_count` | 680 / 750 | 414 / 624 |
| No filter, by `contract.number` | 931 / 989 | 331 / 412 |
| `out_of_service_cover:eq:true` | 335 / 431 | 273 / 464 |
| `contract.status:eq:renewal_pending` | 395 / 590 | 256 / 284 |
| `GET /reports/coverage` | 2774 / 3074 | 783 / 915 |

The four changes: a list is counted from its matched rows alone,
`dialect.count_of`, because SQLite leaves out of a statement the joins that nothing in
it reads but not out of a count; a section of the coverage report is counted without
reading a page of it, `listing.count`; blank values sort last by `NULLS LAST` in one
term, so that a value worked out for each row is worked out once; and the agreements of
a page of items are read once. The list with no filter and the grid's first page meet
the target. The coverage filters and the sorts by a coverage column do not, and the
coverage report, which is not a page of the grid, takes most of a second.

**Measured at 0.7.0.** On the same host, median and 95th percentile in milliseconds of
15 runs after 2 warm-ups, with the host otherwise quiet: its load average over the
minute of each request was 1.0 to 1.3, of which about 1 is the timing itself. The
fixture holds what 0.7.0 added, which moves some totals: 1,066 items run out of cover
soon, 484 in service with no cover are not to be renewed and so no gap. The item list,
against 0.6.1:

| Request | 0.6.1 | 0.7.0 |
|---|--:|--:|
| No filter, by name | 216 / 377 | 271 / 454 |
| The grid's first page, major items | 173 / 401 | 180 / 234 |
| `covered:eq:true`, by name | 315 / 447 | 376 / 582 |
| `covered:eq:false`, by `covered_until` | 473 / 522 | 575 / 752 |
| `contract_count:gt:1`, by `-contract_count` | 414 / 624 | 488 / 714 |
| No filter, by `contract.number` | 331 / 412 | 356 / 590 |
| `out_of_service_cover:eq:true` | 273 / 464 | 280 / 487 |
| `contract.status:eq:renewal_pending` | 256 / 284 | 429 / 614 |
| `effective.do_not_renew:eq:true`, by name | | 242 / 259 |
| `covered:eq:false effective.do_not_renew:eq:true`, by name | | 462 / 670 |

The contract list, a page of 100 with the total counted: no filter 137 / 152, 314
contracts; `to_review:eq:true` 27 / 30, 6 of them; `renewal_overdue:eq:true` 35 / 39,
15 of them.

The reports, worked out anew and kept:

| Request | Anew | Kept |
|---|--:|--:|
| `GET /reports/coverage` | 4214 / 4392 | 13 / 15 |
| `GET /reports/coverage`, `location:within:Americas` | 1927 / 2216 | 14 / 16 |
| `GET /reports/coverage`, a page of `uncovered` | 4682 / 4857 | 34 / 37 |
| `GET /reports/renewals` | 203 / 239 | 14 / 15 |
| `GET /reports/renewals`, a page of `ending` | 227 / 299 | 17 / 20 |
| `GET /renewals/alert` | 189 / 467 | 10 / 14 |
| `GET /reports/capacity`, which is not kept | 2470 / 2756 | |

What meets the target: the grid's first page, the list with no filter, the flag not to
renew by itself, every page of the contract list, the renewal worklist and the alert
anew, and every kept answer, which is what each request after the first is given until
a change. The coverage filters and the sorts by a coverage column still do not, and at
0.7.0 they are 3 to 25 per cent slower than at 0.6.1, and `contract.status` by two
thirds: on the fixture as 0.6.1 made it, before what 0.7.0 added, it took 350 / 603 at
0.7.0, and the fixture of 0.7.0 has more items under a renewal pending, 2,417 against
2,048.

The coverage report worked out anew took 4.2 s with the one pass of D-184 as first
built, where 0.6.1 took 0.8 s: one statement of 140 KB that worked out every condition
of every section for each of the 50,000 items, the terms of each contract again for each
coverage of each item, 3.5 s of it. Counted section by section, as it now is, it takes
1432 / 1624 whole, 1819 / 2008 for the page of `uncovered` and 1837 / 2147 narrowed to a
region, with the same answers (load 0.8 to 1.2): still slower than at 0.6.1, for the
sections and the flag not to renew that 0.7.0 adds. What is in force for each contract,
worked out once for a request in a table of its own, which D-184 also says, is not
built: each coverage of each item reads the terms of its contract and its agreement
anew. The capacity balance took 2.5 s, summing the support weight of the inventory four
times; it now takes the whole from the demand of each region, which leaves two sums of
four, 1305 / 1564, with the same answer.

**An import at 0.7.0**, by `make time-import`: 10,000 new items, 1.9 MB of CSV, on a
copy of the fixture, the host's load average 0.9 to 1.4 throughout.

| Step | Took | Quality |
|---|--:|--:|
| Preview | 121.7 s | 30 s |
| Apply, from the request to the job applied | 167.5 s | 60 s |
| of which: taken up by the worker | 0.02 s | |
| the order of the rows worked out | 3.4 s | |
| 200 batches of 50 rows | 140.1 s | |
| 199 pauses of 0.12 s between them | 23.9 s | |
| the end of the job | 0.02 s | |

Both miss their quality. A batch takes 679 ms at the median, 831 ms at the 95th
percentile and 980 ms at the longest, the same at the end of the file as at its start:
a row costs about 13.6 ms to apply and 12.2 ms to preview, whatever has come before it.
The pauses alone are 40 per cent of the minute the apply is given. A preview's copy of
the database takes 0.2 s; the rest is the rows. Profiled over 400 rows, a row sends
about 34 statements, which take some 7 per cent of its time; the rest is Python, half
of it in reading the record back as a file would hold it, to say what the row changes,
which builds the places and the operators in force again for each row.

A sign-in takes 92 ms at the median with nothing else going on, and 124 ms at the 95th
percentile. During the apply 164 sign-ins took 467 ms at the median, 832 ms at the 95th
percentile and 970 ms at the longest: they waited beyond the idle median 374 ms, 740 ms
and 877 ms. A sign-in waits for the batch that holds the one writer to end, so how long
it waits is how long a batch takes, under a second (D-185: "a fraction of a second at
most") only while 50 rows take under a second.

**Measured at 0.8.0.** On the same host, median and 95th percentile in milliseconds of
15 runs after 2 warm-ups, with the host otherwise quiet: its load average over the
minute of each request was 0.9 to 1.5, of which about 1 is the timing itself. The
requests of 0.7.0 were timed first on the fixture as 0.7.0 made it, and then on the
fixture of 0.8.0, with its circuits and the weights of places. The item list:

| Request | 0.7.0 | 0.8.0, fixture of 0.7.0 | 0.8.0 |
|---|--:|--:|--:|
| No filter, by name | 271 / 454 | 257 / 480 | 237 / 478 |
| The grid's first page, major items | 180 / 234 | 182 / 198 | 184 / 221 |
| `covered:eq:true`, by name | 376 / 582 | 394 / 435 | 401 / 810 |
| `covered:eq:false`, by `covered_until` | 575 / 752 | 565 / 896 | 555 / 806 |
| `contract_count:gt:1`, by `-contract_count` | 488 / 714 | 496 / 596 | 493 / 720 |
| No filter, by `contract.number` | 356 / 590 | 367 / 645 | 359 / 438 |
| `out_of_service_cover:eq:true` | 280 / 487 | 334 / 523 | 308 / 369 |
| `contract.status:eq:renewal_pending` | 429 / 614 | 415 / 654 | 412 / 702 |
| `effective.do_not_renew:eq:true`, by name | 242 / 259 | 268 / 565 | 250 / 333 |
| `covered:eq:false effective.do_not_renew:eq:true`, by name | 462 / 670 | 494 / 732 | 482 / 778 |

Neither 0.8.0 nor its circuits move any of them at the median by more than a fifth, most
by less than a tenth, either way; the 95th percentile moves as the slowest of fifteen
runs does. The contract list:
no filter 144 / 192, `to_review:eq:true` 29 / 33, `renewal_overdue:eq:true` 37 / 43.
The reports that are kept, worked out anew and kept:

| Request | Anew | Kept |
|---|--:|--:|
| `GET /reports/coverage` | 1414 / 1504 | 14 / 17 |
| `GET /reports/coverage`, `location:within:Americas` | 1888 / 2006 | 14 / 15 |
| `GET /reports/coverage`, a page of `uncovered` | 1895 / 2057 | 37 / 49 |
| `GET /reports/renewals` | 199 / 220 | 16 / 17 |
| `GET /reports/renewals`, a page of `ending` | 237 / 617 | 17 / 20 |
| `GET /renewals/alert` | 208 / 251 | 10 / 11 |
| `GET /reports/capacity` | 2418 / 2683 | 11 / 12 |
| `GET /reports/capacity`, the six weights set | 2512 / 2744 | 9 / 10 |

What 0.8.0 adds, on its fixture: a page is 100 circuits with the fields the circuit grid
asks for, and the total counted.

| Request | Median / p95 | Answered |
|---|--:|--:|
| Circuits, no filter, by name | 96 / 118 | 1,831 |
| `location:within:Americas`, by name | 118 / 428 | 665 |
| `billed_by:eq:`, the carrier that bills the most, by name | 125 / 173 | 714 |
| `effective.down_mbps:lt:200`, by name | 94 / 400 | 791 |
| `in_service:eq:true`, by name | 94 / 113 | 1,785 |
| `monthly_cost:gt:2000`, by name | 111 / 151 | 922 |
| `monthly_cost:gt:2000`, by `-monthly_cost` | 129 / 203 | 922 |
| No filter, by `-monthly_cost` | 172 / 546 | 1,831 |
| `GET /circuits/{hid}`, with its parts and contacts | 23 / 27 | |
| `GET /circuit-groups` | 187 / 573 | 36 |
| `GET /circuit-groups/{hid}`, the largest | 24 / 31 | 171 circuits |
| `GET /circuit-groups/{hid}/members`, a page of it | 24 / 29 | 171 |
| `GET /reports/circuit-costs` by carrier | 269 / 679 | 8 rows |
| by site | 301 / 701 | 120 rows |
| by region | 324 / 693 | 15 rows |
| by group | 267 / 666 | 38 rows |
| any of the four, `location:within:Americas`, with the joins | 105 to 124 / 352 to 394 | 675 circuits |
| `POST /reports/capacity/try`, a default, a minimum and two staff lines, the balance in force kept | 2480 / 2961 | |
| `POST /kept-answers/check`, the four long reports kept | 4299 / 4599 | 4, none differed |

The weight in force, with `default_item_weight` and `minimum_item_weight` set against
the same requests with neither: the grid's first page 200 / 280 and 176 / 209; the item
list by `-effective.support_weight` 259 / 604 and 273 / 628; `GET /reports/summary`
2514 / 2597 and 2468 / 2576, and by region 4119 / 4386 and 3952 / 4345. The default and
the minimum cost nothing that can be told from one run to another. With all six set,
the capacity report anew takes 2512 / 2744 against 2418 / 2683, counts 1,984 items, 85
sites and 1,516 circuits at a default, and raises 17,145 items, the phones, to the
minimum.

Every page of the circuit grid meets the target, and the record of a circuit and of a
group, and the list of groups. The report of what circuits cost, whole, does not: over
300 ms at the median by site and by region, and over 600 ms at the 95th percentile by
each of the four. Narrowed by a filter that names a place, it was not answered when the
timing began: `circuit_costs` read the filter without the joins of the circuit list, so
each place the filter named was a cross join, which neither narrowed the circuits nor
counted each once. On the fixture the process grew past 6 GB before the kernel stopped
it; on a small database it answered, with each circuit counted several times over. That
was a defect and not a matter of speed, and it is put right in 0.8.0: read with the
joins, as the list of circuits reads it, the four take 105 to 124 ms at the median and
352 to 394 ms at the 95th percentile, and count the 675 circuits of the region.

The capacity report anew was slower than at 0.7.0 when the timing began, 2.4 s against
1.3 s: each of its two views read the items twice, for the sums by region, 0.6 s, and,
since 0.8.0, for the items at a default or raised to the minimum (P-155), 0.5 s. It
reads them once again, as at 0.7.0, where no default or minimum of an item's weight is
set, since none can then be either; that was not timed again. With one set it reads
them twice. It is kept now (P-157), and given in 10 ms to every request after the
first. A Try worked out the balance in force and the balance tried, eight passes over
the items, 5.0 s; the balance in force is what the report answers, and taken from the
kept answer, as 0.8.0 now takes it, a Try takes 2480 / 2961. The check of what is kept
works out the four long reports anew one after another, 4.3 s.

**Left for the timing of 1.0.0**, with what each costs now:

- The coverage report anew, 1.4 s whole and 1.9 s narrowed to a region, counted
  section by section. Under a second needs what D-184 says of the terms of each
  contract, worked out once for a request and read by every item.
- The capacity report anew with an item's default or minimum set, 2.5 s: four passes
  over the items, two of them to count what is at a default or raised, which the pass
  of the sums could count. Kept, it is 10 ms, and it is worked out at midnight and at
  start.
- A Try, 2.5 s with the balance in force taken from the kept report: the balance tried
  is worked out each time and never kept, so it costs what the report does anew.
- The check of what is kept, 4.3 s with the four long reports kept: the sum of them
  anew.
- The summary, 2.5 s whole and 4.0 s by region: four passes over the items, each 0.5 to
  0.7 s, the stacks and clusters of each worked out again.
- The report of what circuits cost, whole: 267 to 324 ms at the median and 666 to 701
  ms at the 95th percentile. Every circuit of the year and its lines are read and
  counted in Python.
- The list of circuit groups, 187 / 573 for 36 groups: three counts for each group.
- An import of 10,000 rows, not timed again at 0.8.0: 122 s to preview and 168 s to
  apply at 0.7.0, against 30 s and 60 s. The apply cannot meet the minute while a row
  costs 13.6 ms: after the pauses, 23.9 s, and the order of the rows, 3.4 s, a row
  would have to take under 3.3 ms. What a row reads, the record in its file shape and
  the places and operators in force, would have to be read for a batch at once, or for
  the file, as the order of the rows already is (P-143). A batch of 50 rows at 13.6 ms
  is also how long a sign-in waits behind it, up to 0.9 s.
- Each filter is worked out twice, once for the count and once for the page: 60 to 170
  ms each for the coverage filters at 0.6.1. Counting and paging one set of matched
  rows needs `listing.page` made anew.
- Shaping a page of 100 items in Python takes about 95 ms. A page of 100 contracts
  takes 137 ms against 27 ms for a page of 6, most of it shaping.
- The coverage columns cost much for each row: `covered` over every item takes 80 ms,
  against 14 ms for a bare test. What is in force for a contract would have to be held
  where it is read, or worked out once for a request, as for the report.
- The sort by name calls a Python function for each row; a column of the folded name,
  with an index, would not.
- About one run in fifteen is some 200 ms slower, which looks like the collector of
  Python's memory: the 95th percentile of 15 runs is the slowest of them, so it is that
  run. At 0.7.0 the alert anew shows it, 189 ms at the median and 467 ms at the 95th;
  at 0.8.0 a page of circuits in a region, 118 ms and 428 ms.

A run on a host that other work shares is not a measurement: S36 at 1.0.0 is run with
the host to itself.

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
max_megabytes = 20                   # the largest file an import takes, and any other body of a request
max_reference_megabytes = 100        # the largest reference file; hirdir-setup --renew gives nginx the larger of the two

[upgrades]
proxy = ""                           # the proxy through which hirdir-setup reaches GitHub, if any
```

Each key is named once in the code, in `config.py`, with its default and the comment
that says what it is for. The defaults of the service are read from there, and so is
the file that `hirdir admin config` writes: every key of every table, commented out at
its default. That file is `packaging/config.toml`, the one the package ships for
`hirdir-setup --settings`, and a test holds both it and the block above to what the
command writes, so the three never disagree. `--current` writes the same file with
what the file in force sets, set. `[upgrades] proxy` is read by `hirdir-setup` and not
by the service.

Installation-wide values that people change in the course of work, such as the stack
discount, are settings in the database, edited in the web UI by an Admin, each with a
default and a description in `domain/settings.py`. What a site may not change is listed
beside them by `GET /settings`, said to be fixed: what was decided, with the decision,
and the limits that protect the service. Each fixed value is read from the module that
uses it, so the value listed is the value in force, and a value that two parts of the
code use is held in one: the application's time zone in `clock.py`, the wait for the
one writer in `db/engine.py`, which is both SQLite's `busy_timeout` and the
`Retry-After` of a `503`, and the size of a page and the length of a filter in
`io/listing.py` and `io/filters.py`, which the API's parameters take.
