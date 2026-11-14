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
hirdir import examples/contacts.csv --entity contacts --apply
hirdir import examples/operators.csv --entity operators --apply
hirdir import examples/regions.csv --entity regions --apply
hirdir import examples/sites.csv --entity sites --apply
hirdir import examples/locations.csv --entity locations --apply
hirdir import examples/contact-assignments.csv --entity contact_assignments --apply
hirdir import examples/owners.csv --entity owners --apply
hirdir import examples/owner-members.csv --entity owner_members --apply
hirdir import examples/networks.csv --entity networks --apply
hirdir import examples/items.csv --entity items --apply
hirdir import examples/device-groups.csv --entity device_groups --apply
hirdir import examples/device-group-members.csv --entity device_group_members --apply
hirdir import examples/addresses.csv --entity addresses --apply
```

Without `--apply` a command shows what the file would do and changes nothing. Loaded a
second time, every row is `unchanged`. Four of the files are new in 0.4.0: the networks,
the device groups, which are stacks, clusters and a controller domain, their members,
and the addresses of items and of groups. So are the minor items among the items. From
0.4.1 the same nine files also show the condition of an item and what is observed of
it, a stack whose master is seen to be another switch than the one intended, clusters
that say how they are managed, and an address that two routers share, which their
cluster holds.

Seven of the files are new in 0.5.0: the contacts, the operators, which are the labels
of who looks after what, the regions, the sites and the locations within them, who is
the contact of which place in which role, and the people of each owner. The items and
the device groups say where they are and which operator they have of their own.

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

`reset` refuses while the service is running. It removes every item with its
replacements, addresses and memberships, every device group, network, catalog entry,
vendor, owner with its people, region, site, location, operator and contact with its
assignments, and tag, the stored imports, and the history of those records. It keeps
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

### Upgrades by themselves

The package ships a timer that does `hirdir-setup --upgrade --yes` each night. It is
off until a site turns it on:

```bash
sudo systemctl enable --now hirdir-upgrade.timer     # on
sudo systemctl disable --now hirdir-upgrade.timer    # off again
systemctl list-timers hirdir-upgrade.timer           # when it runs next
journalctl -u hirdir-upgrade.service                 # what it did
```

Turned on, it asks GitHub once a night, at a time of its own between 21:00 and 03:00 in
the host's local time, and installs a newer release when one has been published. Most
nights there is none, and it changes nothing. A night the host was off is skipped, not
made up for by day.

Where GitHub is reached through a proxy, name the proxy in `/etc/hirdir/config.toml`,
because the timer has nobody to give it `--proxy`:

```toml
[upgrades]
proxy = "http://proxy.example.com:2025/"
```

`hirdir-setup --check` and `--upgrade` use it too whenever `--proxy` is left out. The
file can be read by every user of the host. For a proxy that takes a name and a
password, make it readable by root and the `hirdir` group alone first:
`sudo chgrp hirdir /etc/hirdir/config.toml && sudo chmod 640 /etc/hirdir/config.toml`.

Think before turning it on. An upgrade stops the service for as long as the database
takes to back up and migrate, and people who are at work at that hour wait. If a
migration fails, the upgrade stops with the service down and the backup named, as
under [If the upgrade stops](#if-the-upgrade-stops), and it stays down until somebody
looks. `systemctl --failed` shows a night that went wrong.

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

### From 0.3.0 to 0.4.0

The schema goes from revision `0004` to `0005`. Five tables are added:
`item_replacements`, `device_groups`, `device_group_members`, `networks` and
`addresses`. They hold what is new in this release: replacements, stacks, clusters and
controller domains with their members, and the addresses of items and of groups.

The `items` table gains two columns, `parent_item_hid` and `position`, for minor items.
To add them, SQLite makes the table anew and copies every row across, inside the one
transaction that the whole upgrade runs in. Nothing you have is changed by it. Every
item is as it was, field for field, at the `row_version` it had and with its history,
and every item there is so far is a major item, as before: it has no parent. A serial
number is still unique within its model, and an asset tag among all items.

The list of reasons for a replacement, `replacement_reason`, is filled with its
defaults: `rma`, `refresh`, `project`, `upgrade` and `other`. A reason you entered in
that list yourself stays as it is, also where it has the value of a default: it keeps
your label, and the default is not added beside it.

`/etc/hirdir/config.toml` gains no setting, and `/etc/nginx/snippets/hirdir.conf` is the
one 0.3.0 wrote, so the upgrade says nothing of either and nginx is not reloaded.

The package now carries nine example files, where it carried five: see
[Try it with the examples](#try-it-with-the-examples). `hirdir admin reset` clears the
new records with the rest of the inventory.

Going back to 0.3.0 is as under
[Going back to the release before](#going-back-to-the-release-before). The backup of
this upgrade is at revision `0004`, and it holds no group, network or address, because
0.3.0 had none: whatever was entered with 0.4.0 is lost with the rest.

### From 0.4.0 to 0.4.1

The schema goes from revision `0005` to `0006`. No table is added.

The `items` table gains three columns, `condition`, `observed_status` and
`observed_at`. The `device_groups` table gains six: `managed_as`, `expected_members`,
`observed_status`, `observed_at`, `observed_master_hid` and `master_observed_at`. To
add those six, SQLite makes the table of groups anew and copies every row across,
inside the one transaction that the whole upgrade runs in. Nothing you have is changed
by it. Every item, device group, membership, network and address is as it was, field
for field and at the `row_version` it had, and every item has its history, with one
exception that is meant: the memberships of items that had left the team's hands,
below. A serial number is still unique within its model, an asset tag among all
items, and the name of a group among groups.

What is new is empty until somebody fills it in. No item has a condition and nothing
is observed of any, so the health of each is `unknown`. A stack or a cluster is
`unknown` too, unless one of its members is in Down or in Pending-Removal, which shows
it as `degraded` from the start. A stack shows the serial number of its master as
before: the master you marked is the one intended, and none is recorded as seen.

Every cluster there is counts as before. 0.4.0 counted each cluster as one managed
node, and the upgrade says so on each: `managed_as` is `one`. The managed-node count,
the component count and the support weight of a view are what 0.4.0 gave, but for a
stack that loses a member at the upgrade, below. A cluster
whose members are each managed at an address of their own, as a pair of firewalls is,
was counted as one node all the same, and still is until you say how it is managed:
`members`, or `members_and_cluster` where the cluster answers as a node of its own as
well. See "Counting and weight" on the [data model](data-model.md#counting-and-weight)
page.

The list of conditions, `item_condition`, is filled with its defaults: `untested`,
`good`, `degraded`, `suspect`, `failed` and `dead`.

The upgrade ends the memberships of items that had left the team's hands. From 0.4.1
an item that is retired, or moved to Released or to Archived, leaves its groups on
that day, and joins no group afterwards. 0.4.0 left an item that was moved to Released
or to Archived in its stack, cluster or domain. Each membership that it left standing
so is ended by the upgrade, on the day of the upgrade. The membership stays on record
with that day, at its next `row_version`, and the audit trail holds one event for
each, made by the system and not by a person. Nothing else of the item or of its group
is changed.

The numbers of such a group follow. It has one member fewer. A stack that is left
with one switch earns no stack discount for it any more, so the support weight of that
switch is whole where it was lowered, and the stack shows as `degraded`, as one switch
alone, until it is given a second switch or is told to expect one member. Before the
upgrade, `GET /api/v1/items?filter=lifecycle_state:in:Released,Archived` with
`include_archived=true` lists the items this may concern, each with the groups it is
in.

Two things answer differently from now on, for a script that reads them:

- `GET /reports/summary` and `hirdir report summary` hold no money. Estimated value
  and annual support cost are in `GET /reports/management` and `hirdir report
  management`. The summary counts the components by health and by condition instead.
- The record of an address says which `family` it is of, 4 or 6, and an item or a
  group may have a primary management address of each.

`/etc/hirdir/config.toml` gains no setting, and `/etc/nginx/snippets/hirdir.conf` is the
one 0.4.0 wrote, so the upgrade says nothing of either and nginx is not reloaded.

Going back to 0.4.0 is as under
[Going back to the release before](#going-back-to-the-release-before). The backup of
this upgrade is at revision `0005`. 0.4.0 knows no condition, no observation and no
`managed_as`, so whatever was entered of those with 0.4.1 is lost with the rest that
was entered since the upgrade.

### From 0.4.1 to 0.4.2

The schema stays at revision `0006`: 0.4.2 has no migration. Nothing that is held is
changed by the upgrade. Every item, device group, membership, network, address and
choice is as it was, at the `row_version` it had, and the upgrade writes no audit
event. It takes its backup and stops and starts the service all the same.
`/etc/hirdir/config.toml` gains no setting, and `/etc/nginx/snippets/hirdir.conf` is the
one 0.4.1 wrote, so the upgrade says nothing of either and nginx is not reloaded.

One thing answers differently from now on. **A time that names no zone is in the
application's time zone**, the `time_zone` setting, which is America/New_York until
an Admin changes it. 0.4.1 read such a time as UTC. It holds wherever a time is given:

- in a request: `observed_at` on an item or a device group, and `master_observed_at`
  on a stack;
- in a file: the columns `observed_at` and `master_observed_at`;
- in a filter: `observed_at:gte:2026-11-02T10:00`.

So `2026-11-03T09:00:00` is nine in the morning where the application is, as a person
reads it on a page, and with the zone as it is installed that is
`2026-11-03T14:00:00Z`. A time that names its zone, `2026-11-03T09:00:00Z` or
`2026-11-03T09:00:00-05:00`, is that moment, as before. **A script that means UTC
writes the `Z`.** One that has been sending times with no zone and meaning UTC adds
it, or its times are read as local ones from this release on.

The moments that are already stored are not changed. A moment that 0.4.1 took from a
time with no zone was stored as that hour in UTC, and it stays that moment: the API
gives every time in UTC with a `Z`, and a page shows it in the application's zone, as
both did. Where such a time was meant as a local one, enter it again.

Two smaller things read differently. The reason that an item gives for a health that
is not known names the condition it has: `its condition is in-repair, which says
nothing of its health, and nothing is observed` for a condition of your own, and `its
condition is untested, and nothing is observed`. The health itself is as it was. And
the item grid of the web UI shows Estimated value only when it is asked for, in the
column chooser; a layout that a person has saved is as they saved it.

In the examples, NetConfig Manager is one licence, of quantity 1, where it had 250,
which multiplied its support cost. Where the examples of 0.4.1 are loaded, loading
`examples/items.csv` again changes that one item.

Going back to 0.4.1 needs no backup, because the schema is the same and 0.4.1 reads
the database as 0.4.2 leaves it:

```bash
sudo apt install --allow-downgrades ./hirdir_0.4.1_amd64.deb
```

The command goes through and starts the service, and that is all. What was entered
with 0.4.2 stays, and a moment that 0.4.2 read from a time with no zone stays the
moment it was read as.

### From 0.4.2 to 0.5.0

The schema goes from revision `0006` to `0007`. Seven tables are added: `contacts`,
`operators`, `regions`, `sites`, `locations`, `contact_assignments` and `owner_members`. All of
them are empty after the upgrade.

The `items` table gains three columns, `location_hid`, `planned_location_hid` and
`operator_hid`, and the `device_groups` table the same three. To add a column that refers to another
table, SQLite makes each of the two tables anew and copies every row across, inside
the one transaction that the whole upgrade runs in. Nothing you have is changed by it.
Every item, device group, membership, network, address, owner and choice is as it was,
field for field and at the `row_version` it had, and every item has its history. The
audit trail holds no event of the upgrade.

What is new is empty until somebody fills it in. No item and no group has an operator:
a report by operator has one row, of what nobody is assigned to. No item and no group is anywhere:
each has no location, the tree of places is empty, and every item is counted under
"nowhere". An item or a device group that is already with an owner outside the team is
marked as an exception from now on, with the reason that owner has always had to have.
`GET /api/v1/items?filter=owner_exception:eq:true` lists the items.

The lists of contact roles and of location kinds are filled with their defaults:
`shipping`, `technical`, `federal`, `operational` and `escalation`, and `building`,
`floor`, `room`, `rack`, `warehouse` and `other`. A value that a site had entered in
either list is left as it is.

Three things answer differently from now on, for a script that reads them:

- `GET /reports/management` and `hirdir report management` with no `by` are by site:
  the answer has one row for each site, and `by` says `site` where it was `null`.
  Until items are given locations there is one row, of the items that are nowhere,
  beside the totals, which are as they were.
- The record of an owner lists its `tags` and its `members`, and the record of an item
  and of a device group the `location` it is at and its `operator`.
- A file of items or of device groups may have a `location` column, which 0.4.2
  rejected as unknown. An export of the columns that can be set writes it.

`/etc/hirdir/config.toml` gains no setting, and `/etc/nginx/snippets/hirdir.conf` is
the one 0.4.2 wrote, so the upgrade says nothing of either and nginx is not reloaded.

The package now carries sixteen example files, where it carried nine: see
[Try it with the examples](#try-it-with-the-examples).

Going back to 0.4.2 is as under
[Going back to the release before](#going-back-to-the-release-before). The backup of
this upgrade is at revision `0006`. 0.4.2 knows no region, site, location or contact,
so whatever was entered of those with 0.5.0 is lost with the rest that was entered
since the upgrade.

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

A release that changed no schema is gone back from by the first command alone: it
goes through, nothing is restored and nothing is lost. 0.4.2 is such a release. The
section of each release above says what its upgrade changed.

## Remove

```bash
sudo hirdir-setup --remove
sudo apt remove hirdir        # keeps /var/lib/hirdir and /etc/hirdir
sudo apt purge hirdir         # removes them, and the hirdir user
```

A purge also removes `/etc/nginx/snippets/hirdir.conf`, and takes the `include` line
out of the nginx site if it is still there, so that nginx is never left pointing at a
snippet that no longer exists.
