# Install and operate

How to put `hirdir` on a host, reach it through nginx, and look after it. The design
behind these steps is in [architecture.md](architecture.md).

## What you need

- Ubuntu 26.04 LTS on amd64.
- nginx from Ubuntu, with a site that already terminates TLS. `hirdir` adds itself to
  that site; it does not bring certificates of its own.
- The package, `hirdir_<version>_amd64.deb`. It carries its own Python and every Python
  dependency, so nothing is downloaded at install time except what apt needs.

## Install

```bash
sudo apt install ./hirdir_0.3.0_amd64.deb
```

This creates the `hirdir` user, the state directory `/var/lib/hirdir`, the database and
the key that signs sessions, and starts `hirdir.service` listening on `127.0.0.1:8715`.
The database begins with no account and no inventory, and with the lists of choices
and the lifecycle rules at their defaults. Nothing is reachable from outside the host
yet.

It also writes `/etc/hirdir/config.toml`, with every setting in it commented out at
its default.

On a host that already has `hirdir`, the same command upgrades it: see
[Upgrade](#upgrade).

## Create the first Admin

```bash
sudo hirdir admin create-user --role admin ada
```

The command prints an access code once. Give `--access-code` to choose the code instead.
Everyone else is created in the web UI by an Admin.

## Put it behind nginx

```bash
sudo hirdir-setup
```

`hirdir-setup` reads the running nginx configuration, lists the sites that terminate
TLS, shows the one line it will add to the site you choose, checks the result with
`nginx -t` and reloads. `hirdir` is then at `https://<your host>/hirdir/`.

| Option | Effect |
|---|---|
| `--site FILE` | Choose the site file without being asked |
| `--prefix /inventory` | Serve under another prefix. `/` serves at the root of the site |
| `--yes` | Ask nothing |
| `--remove` | Take `hirdir` out of the site again |
| `--renew` | Write the nginx snippet again as this version ships it, under the prefix it has. The package does this itself at install and at each upgrade |
| `--self-signed` | Create a site with a throwaway certificate. For test containers only |

The prefix lives in one file, `/etc/nginx/snippets/hirdir.conf`. Running
`sudo hirdir-setup --prefix /inventory` again later moves `hirdir` and needs no
restart of the service.

That file is written by the package and by `hirdir-setup`, from
`/usr/share/hirdir/nginx/snippet.conf`. Change the prefix in it with `hirdir-setup`
and leave the rest as it is: an upgrade writes the file again as the new version ships
it and keeps the prefix, but a file that was changed by hand in anything else is left
alone, and then lacks whatever the new version added.

### Uploads

An import sends its file through nginx as the body of a request. `hirdir` takes a file
of up to 20 MB, and the snippet tells nginx to let that much through, where nginx left
to itself stops at 1 MB:

```nginx
client_max_body_size 20m;
```

A larger file is refused by nginx, with `413 Request Entity Too Large` and a page of
its own, and never reaches `hirdir`. If a load balancer or another proxy stands in
front of nginx, it has to let 20 MB through as well. When an import of a file between 1
and 20 MB is answered with that page, the snippet is not the one this version ships:
`sudo hirdir-setup --renew` says why and puts it right.

A site that wants larger files raises the limit in two places, to the same figure, and
restarts both:

```toml
# /etc/hirdir/config.toml
[files]
max_megabytes = 50
```

```nginx
# /etc/nginx/snippets/hirdir.conf
client_max_body_size 50m;
```

```bash
sudo systemctl restart hirdir && sudo nginx -t && sudo systemctl reload nginx
```

Raising one alone changes nothing: the lower of the two decides. A snippet changed in
this line is one that an upgrade leaves alone from then on, and says so. A file still
holds at most 100,000 rows.

## Sign in

Open the address in a browser and sign in with the username and access code. The
session lasts 12 hours and is kept in the browser's local storage. `hirdir` sets no
cookies.

From a terminal on any machine that has the `hirdir` command:

```bash
hirdir sign-in --url https://inventory.example.net/hirdir
hirdir whoami
```

## Accounts and roles

An Admin manages accounts under **Admin** in the web UI.

| Role | May |
|---|---|
| View-only | Read everything |
| Inventory | Read and change inventory records |
| Admin | All of that, and manage users, groups, roles and tokens |

A role is granted to a user or to a user group. A user holds the highest role granted
either way. A user with no role can sign in and see nothing. A change of role takes
effect on the user's next request.

Resetting a user's access code, disabling the user or choosing "Sign out everywhere"
ends every session that user has. From the server:

```bash
sudo hirdir admin reset-access-code ada
```

## Automation

Scripts and other tools use a token that belongs to a service account, never a person's
access code. In the web UI, create a user marked as a service account, grant it a role,
and create a token for it. The token is shown once.

```bash
curl -H "Authorization: Bearer $HIRDIR_TOKEN" https://inventory.example.net/hirdir/api/v1/auth/me
```

The token acts with the role of its service account. With View-only it reads the
inventory, for example every item in production, by host name:

```bash
curl -H "Authorization: Bearer $HIRDIR_TOKEN" \
    'https://inventory.example.net/hirdir/api/v1/items?filter=lifecycle_state:eq:Prod&sort=hostname'
```

The routes and the filter grammar are on the [interfaces](interfaces.md) page. The
`hirdir` command reads the same token from `HIRDIR_TOKEN`, and the server from
`HIRDIR_URL`.

## Try it with the examples

The package carries a small, fictional inventory in `/usr/share/doc/hirdir/examples/`:
one file for each kind of record, as CSV and as JSON, the same records in both. They
are the files of [Examples](../examples/README.md). Use them to try an import, and take
the columns from them for a file of your own.

**Load them where the inventory can be cleared again.** Nothing is deleted from an
inventory in the web UI or through the API. On the server, `sudo hirdir admin reset`
clears the whole inventory, the examples and anything else in it: see
[Start over](#start-over). Where real records are already in, do not load the examples
beside them.

Sign in as a user who holds Inventory or Admin, then load the files in this order,
because a record names the ones it refers to:

```bash
cd /usr/share/doc/hirdir
hirdir import examples/tags.csv --entity tags --apply
hirdir import examples/vendors.csv --entity vendors --apply
hirdir import examples/catalog-entries.csv --entity catalog_entries --apply
hirdir import examples/owners.csv --entity owners --apply
hirdir import examples/items.csv --entity items --apply
```

Without `--apply` a command shows what the file would do and changes nothing. Loaded a
second time, every row is `unchanged`.

A script sends a file straight to the API, with a token whose service account holds
Inventory. The file is the body of the request:

```bash
curl -H "Authorization: Bearer $HIRDIR_TOKEN" -H 'Content-Type: text/csv' \
    --data-binary @/usr/share/doc/hirdir/examples/tags.csv \
    'https://inventory.example.net/hirdir/api/v1/imports/preview?entity=tags'
```

The answer is the preview: what each row would do, and the HID of the stored job.
`POST /api/v1/imports/<that HID>/apply` then loads it. The rules of an import are under
"Import and export" on the [interfaces](interfaces.md#import-and-export) page.

## Configuration

`/etc/hirdir/config.toml`. Every key is optional and is shown there commented out with
its default. An upgrade puts the settings of a new version into the file in the same
way and changes nothing you set. Restart the service after a change:

```bash
sudo systemctl restart hirdir
```

## Backup and restore

A timer backs the database up every day into `/var/lib/hirdir/backups/` and keeps the
newest 14. An upgrade puts its own backup in the same directory, and it counts as one
of the 14. A backup is named for when it was made, in the application's time zone:
`hirdir-20261111T210000-0500.db` was made at 21:00 on 11 November, five hours behind
UTC. Backups made by 0.2.0 carry a time in UTC, marked `Z`, and are kept in order with
the rest. Copying those files off the host is up to you.

```bash
sudo hirdir admin backup                   # one more backup, now; prints its path
sudo systemctl stop hirdir
sudo hirdir admin restore /var/lib/hirdir/backups/hirdir-20261111T210000-0500.db
sudo systemctl start hirdir
```

`restore` checks the file first and keeps the database as it was beside the restored
one, named `hirdir.db.before-restore`.

## Start over

A site that has loaded the examples, or test data of its own, clears the inventory and
begins again. This is done on the server and cannot be done from the web UI or the
API, whatever role a person holds.

```bash
sudo systemctl stop hirdir
sudo hirdir admin reset                    # says what goes, backs up, asks for the word "reset"
sudo systemctl start hirdir
```

`reset` refuses while the service is running. It removes every item, catalog entry,
vendor, owner and tag, the stored imports, and the history of those records. It keeps
the accounts, groups, roles and service tokens, so people sign in as before, and the
settings, choices and lifecycle rules, so the site's set-up is as it was. The backup it
takes first is one of the 14 that are kept, and its path is printed: `hirdir admin
restore` puts it back.

```bash
sudo hirdir admin reset --everything       # back to a fresh installation
sudo hirdir admin create-user --role admin NAME
```

`--everything` removes the accounts, the settings and the audit trail as well. The
signing key and the backups stay. `--yes` goes on without asking, for a script.

## Check

```bash
sudo hirdir admin check
systemctl status hirdir
journalctl -u hirdir
curl -s http://127.0.0.1:8715/api/v1/health/ready
```

## Upgrade

`hirdir-setup` is part of the package, so the tool that upgrades `hirdir` is already on
the host. Nothing but the package is ever downloaded.

```bash
sudo hirdir-setup --check        # is a newer release published?
sudo hirdir-setup --upgrade      # fetch it, check it, install it
```

`--check` asks GitHub for the latest release of `hirdir` and says whether it is newer
than the one installed. It changes nothing. `--upgrade` fetches the package of that
release and the checksum published beside it, into `/var/cache/hirdir/`, and installs
the package only when the two agree. It says what is about to happen and asks before
it goes on; `--yes` goes on without asking, for a script or a timer. When the release
installed is the latest, it says so and does nothing.

Where the way out to GitHub is through a proxy, name it:

```bash
sudo hirdir-setup --check --proxy http://proxy.example.com:2025/
sudo hirdir-setup --upgrade --proxy http://proxy.example.com:2025/
```

Both requests then go through that proxy: to `api.github.com` for the release, and to
`github.com` and the file servers it redirects to for the package. The tool fetches
from GitHub over HTTPS and from nowhere else. A name and password in the proxy's
address are used and never shown.

On a host with no way out at all, copy the package to it, with its `.sha256` file
beside it when you have it, and name the file:

```bash
sudo hirdir-setup --upgrade ./hirdir_<new version>_amd64.deb
```

Plain apt does the same upgrade, and is what a package manager or a configuration
management tool will use:

```bash
sudo apt install ./hirdir_<new version>_amd64.deb
```

Every one of these ways asks nothing once it has begun, so an upgrade with nobody at
the keyboard goes through. `hirdir-setup --upgrade` refuses a package older than the
one installed, and when apt is done it runs the `hirdir-setup` that the new package
brought, which finishes whatever that version wants done and reports how the upgrade
went: the schema revision, whether the service is running, and where the release
notes are. So a later version can add a step to an upgrade without a new tool having to
be fetched first.

The checksum shows that the package arrived as it was published. It does not show who
published it: that rests on GitHub and on HTTPS. A site that needs more verifies the
package by its own means before `--upgrade PACKAGE.deb`.

The upgrade does six things, in this order:

1. It stops the service, so that nothing writes to the database while its schema
   changes.
2. It backs the database up into `/var/lib/hirdir/backups/` and says where:
   `hirdir: the database as it was before this upgrade is kept at
   /var/lib/hirdir/backups/hirdir-20261111T210000-0500.db`.
3. It applies the schema changes of the new version.
4. It writes `/etc/nginx/snippets/hirdir.conf` again as the new version ships it, under
   the prefix the file has. When that changes the file, it reloads nginx and says so:
   `hirdir: /etc/nginx/snippets/hirdir.conf is now as this version of hirdir ships it,
   for /hirdir/. nginx was reloaded.`
5. It puts the settings that are new in this version into `/etc/hirdir/config.toml`,
   each commented out at its default, and says which: `hirdir: /etc/hirdir/config.toml
   has the new settings of this version, commented out at their defaults:
   files.max_megabytes. Nothing you set was changed.` A file you have edited is treated
   the same: every line of yours stays where it is, a new setting goes to the end of
   its table, and the file as it was is kept beside it as `config.toml.<when>.bak`.
6. It starts the service again.

It keeps every account, user group, role grant, service token and audit event, so
access codes and service tokens go on working. It keeps the key that signs sessions,
so people who are signed in stay signed in, with the session they have. It changes no
value in `/etc/hirdir/config.toml`, and leaves `/etc/nginx/conf.d/hirdir.conf` as you
have it, and the site that includes the snippet. `hirdir` stays under the prefix it had, and
`hirdir-setup` is not run again.

Step 4 is checked with `nginx -t` before nginx is reloaded, and the snippet is put back
as it was when nginx objects. A snippet that was changed by hand in more than its
prefix is not written again. The upgrade goes on and says so:

```text
hirdir-setup: /etc/nginx/snippets/hirdir.conf differs from what hirdir ships in more than its prefix, so it is left as it is. This version ships /usr/share/hirdir/nginx/snippet.conf: bring over by hand what is new there, then run: sudo nginx -t && sudo systemctl reload nginx
hirdir: /etc/nginx/snippets/hirdir.conf was left as it was, for the reason given above.
hirdir: nginx refuses an import of more than 1 MB until it is as this version
hirdir: ships it. With the cause put right, run: sudo hirdir-setup --renew
```

Installing the version that is already installed does the same six things and changes
nothing in the database, in the snippet or in the settings file.

A settings file that is not well-formed TOML is left alone, and the upgrade says so
and goes on. With the file put right, `sudo hirdir-setup --settings` brings it up to
date, and shows what it would put in before it does.

Afterwards, `sudo hirdir admin check` names the schema revision the database is at and
the one this version expects, and exits with an error when they differ.

The backup of step 2 is one of the 14 that are kept, so the daily timer removes it
about two weeks later. Copy it off the host if you want it for longer.

### From 0.1.0 to 0.2.0

The schema goes from revision `0001` to `0002`. The tables of the inventory are added:
vendors, catalog entries, owners, items, tags, choices, settings and lifecycle rules.
The lists of choices and the lifecycle rules are filled with their defaults. Nothing
that 0.1.0 stored is changed. The Inventory role, which had nothing to act on in
0.1.0, now lets its holders create and change inventory records.

### From 0.2.0 to 0.2.1

The schema goes from revision `0002` to `0003`. No table changes. Support weight is kept
to two decimal places from now on, as money is, so a weight that 0.2.0 stored with three
is rounded to the nearest hundredth: `0.125` becomes `0.13`. Nothing else that was
stored is changed.

Every time is now shown in one time zone, the same for everybody: the `time_zone`
setting, which is America/New_York until an Admin changes it under Admin, Settings.
Backups are named in that zone from now on. Those that 0.2.0 made keep their names and
their place in the order.

### From 0.2.1 to 0.3.0

The schema goes from revision `0003` to `0004`. Three tables are added: `import_jobs`
and `import_rows`, which hold the previews of imports and bulk edits, and
`idempotency_keys`, which holds the answers to requests that may be sent twice. A
vendor gains `review_status`, as a catalog entry has, and every vendor there is so far
is `reviewed`. Nothing else that 0.2.1 stored is changed.

nginx now lets a file of up to 20 MB through to `hirdir`, for imports: see
[Uploads](#uploads). The line that does it is new in `/etc/nginx/snippets/hirdir.conf`,
which this upgrade writes again and keeps under the prefix it had, and nginx is
reloaded. Up to 0.2.1 that file was a conffile of the package. It no longer is,
because `hirdir-setup --prefix` changes it, and apt would have stopped this upgrade to
ask about every such file. As it is, apt asks nothing. `dpkg --status hirdir` lists the
file as `obsolete` from now on, and that is as it should be.

`/etc/hirdir/config.toml` gains one setting, `max_megabytes` under `[files]`, commented
out at its default of 20. Up to 0.2.1 the file was a conffile of the package too. It no
longer is, for the same reason: a site that had edited it would have been asked at
this upgrade. `dpkg --status hirdir` lists it as `obsolete` as well.

The package now carries the files of `examples/` in
`/usr/share/doc/hirdir/examples/`: see
[Try it with the examples](#try-it-with-the-examples).

Going back to 0.2.1 is as under
[Going back to the release before](#going-back-to-the-release-before). The backup of
this upgrade is at revision `0003`. The snippet stays as 0.3.0 wrote it, which 0.2.1
serves under just as well, and apt asks nothing about it.

### If the upgrade stops

In both cases below the service is left stopped, apt reports an error for `hirdir`,
and the lines above the message say what went wrong.

**The backup could not be made**, for instance because the disk is full. Nothing was
changed. Put the cause right, then finish the upgrade:

```bash
sudo dpkg --configure hirdir
```

**A schema change failed.** The message names the backup and gives the way back:

```text
hirdir: the migration failed, and the service was not started.
hirdir: the database as it was before the upgrade is at /var/lib/hirdir/backups/hirdir-20261111T210000-0500.db
hirdir: A migration that fails is undone as a whole. To go back, install the
hirdir: package of version 0.1.0 again and put that backup in its place:
hirdir:     sudo apt install --allow-downgrades ./hirdir_0.1.0_amd64.deb
hirdir:     sudo systemctl stop hirdir
hirdir:     sudo hirdir admin restore /var/lib/hirdir/backups/hirdir-20261111T210000-0500.db
hirdir:     sudo systemctl start hirdir
```

Run those four commands as they are printed. `hirdir` then runs as it did before the
upgrade, with everything it held. A schema change that fails is undone as a whole, so
the database is as it was; the backup is put back all the same, so that going back
never depends on that. Once the cause is known and put right, install the new package
again.

### Going back to the release before

An older `hirdir` cannot read a database that a newer one has changed, so going back
means going back to the backup the upgrade took. Everything entered since the upgrade
is lost.

```bash
sudo apt install --allow-downgrades ./hirdir_<old version>_amd64.deb
sudo hirdir admin restore /var/lib/hirdir/backups/hirdir-<time of the upgrade>.db
sudo dpkg --configure hirdir
```

The first command stops with "the migration failed" and leaves the service stopped
and the database untouched. That is the older version meeting the newer database, and
it is expected. The second puts the backup in place, and the third finishes the
installation and starts the service.

## Remove

```bash
sudo hirdir-setup --remove
sudo apt remove hirdir        # keeps /var/lib/hirdir and /etc/hirdir
sudo apt purge hirdir         # removes them, and the hirdir user
```

A purge also removes `/etc/nginx/snippets/hirdir.conf`, and takes the `include` line
out of the nginx site if it is still there, so that nginx is never left pointing at a
snippet that no longer exists.
