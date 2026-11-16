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
| `--renew` | Write the nginx snippet again as this version ships it, under the prefix it has, with the limit of a body that `/etc/hirdir/config.toml` gives. The package does this itself at install and at each upgrade |
| `--self-signed` | Create a site with a throwaway certificate. For test containers only |

The prefix lives in one file, `/etc/nginx/snippets/hirdir.conf`. Running
`sudo hirdir-setup --prefix /inventory` again later moves `hirdir` and needs no
restart of the service.

That file is written by the package and by `hirdir-setup`, from
`/usr/share/hirdir/nginx/snippet.conf`. Change the prefix in it with `hirdir-setup`,
the limit of a body in `/etc/hirdir/config.toml`, and leave the rest as it is: an
upgrade writes the file again as the new version ships it and keeps the prefix, but a
file that was changed by hand in anything else is left alone, and then lacks whatever
the new version added.

### Uploads

An import sends its file through nginx as the body of a request, and so does an upload
of a reference file, a photograph of a site or the administration guide of a model.
`hirdir` takes an import of up to 20 MB and a reference file of up to 100 MB, and the
snippet tells nginx to let the larger through, where nginx left to itself stops at
1 MB:

```nginx
client_max_body_size 100m;
```

A larger body is refused by nginx, with `413 Request Entity Too Large` and a page of
its own, and never reaches `hirdir`; an import between 20 and 100 MB is refused by
`hirdir` itself, with the reason. If a load balancer or another proxy stands in front
of nginx, it has to let 100 MB through as well. When an upload of a file between 1 and
100 MB is answered with the page of nginx, the snippet is not the one this version
ships: `sudo hirdir-setup --renew` says why and puts it right.

A site that wants another limit sets it in the configuration file, and `hirdir-setup
--renew` gives nginx the larger of the two:

```toml
# /etc/hirdir/config.toml
[files]
max_megabytes = 50                  # an import
max_reference_megabytes = 250       # a reference file
```

```bash
sudo hirdir-setup --renew && sudo systemctl restart hirdir
```

A file of an import still holds at most 100,000 rows. The kinds of file a reference may
be are a setting of the inventory, `reference_file_types`, that an Admin changes on the
Settings page; a web page, an SVG drawing, a script or a program is never taken.

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
hirdir import examples/vendor-contacts.csv --entity vendor_contacts --apply
hirdir import examples/operators.csv --entity operators --apply
hirdir import examples/regions.csv --entity regions --apply
hirdir import examples/sites.csv --entity sites --apply
hirdir import examples/locations.csv --entity locations --apply
hirdir import examples/contact-assignments.csv --entity contact_assignments --apply
hirdir import examples/owners.csv --entity owners --apply
hirdir import examples/owner-members.csv --entity owner_members --apply
hirdir import examples/networks.csv --entity networks --apply
hirdir import examples/external-systems.csv --entity external_systems --apply
hirdir import examples/agreements.csv --entity agreements --apply
hirdir import examples/contracts.csv --entity contracts --apply
hirdir import examples/contract-contacts.csv --entity contract_contacts --apply
hirdir import examples/purchase-requests.csv --entity purchase_requests --apply
hirdir import examples/purchase-lines.csv --entity purchase_lines --apply
hirdir import examples/items.csv --entity items --apply
hirdir import examples/device-groups.csv --entity device_groups --apply
hirdir import examples/device-group-members.csv --entity device_group_members --apply
hirdir import examples/item-replacements.csv --entity item_replacements --apply
hirdir import examples/addresses.csv --entity addresses --apply
hirdir import examples/contract-coverage.csv --entity contract_coverage --apply
hirdir import examples/registrations.csv --entity registrations --apply
hirdir import examples/capacity-lines.csv --entity capacity_lines --apply
hirdir import examples/circuit-groups.csv --entity circuit_groups --apply
hirdir import examples/circuits.csv --entity circuits --apply
hirdir import examples/circuit-carriers.csv --entity circuit_carriers --apply
hirdir import examples/circuit-costs.csv --entity circuit_costs --apply
hirdir import examples/circuit-contacts.csv --entity circuit_contacts --apply
hirdir import examples/circuit-devices.csv --entity circuit_devices --apply
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

Nine of the files are new in 0.6.0: the external systems and what is registered with
them; two support agreements, a Cisco one and a Juniper one, with the contracts
grouped into them, a contract that stands by itself for switches bought lately, and
what each contract covers; two purchase requests with their lines, on one of which two
switches have arrived; the capacity lines of the worked example on the
[data model](data-model.md#capacity-balance) page, one of them a draft; and one
replacement. The dates of the contracts are fixed in the files, so what the coverage
report says of them changes as the calendar moves on. The capacity report of the
examples is not the one of that page: the lines are the same, a supply of 9.0, but
the examples have a support weight of 32 where the worked example has 2,400, so the
demand is 2.11 and the balance 6.89, where the page has a demand of 10.0 and a
balance of −1.0.

One of the files is new in 0.7.0: the contacts of the contracts, by which the Cisco
agreement names two account managers, in their order, and one contract in it names an
account manager of its own in place of the agreement's, while the other has the
agreement's. The files from before say more as well. The model of the IP telephones is
marked not to be renewed, so that the one of them in Prod that no contract covers is
counted by itself on the coverage report, and not as a gap. The C9300-48P has a link to
its data sheet, Site-2 one to its page and Room 102 two, to its floor plan and its
racks. The second line of the request for Site-3 has, beside its model, the part number
of a spare power supply as procurement wrote it, and a third line,
of hook-and-loop tape, has no model: it is not tracked, takes no item and waits for
nothing. The capacity lines have the columns of a line that multiplies, though none of
them does.

Five of the files are new in 0.8.0: a group of circuits, the circuits, the carriers of a
circuit beside its primary one, the lines of what each costs a month, and the devices
each connects. An internet circuit of Site-2 has its far end in the carrier's network,
with no location and a note; a point-to-point circuit between Site-1 and Site-2 has a
local exchange carrier with a number of its own beside the carrier's; and a dark fiber
lent by a business partner has an enterprise circuit ID and no carrier's number, and
counts at its far end. Three carriers are among the vendors, and a circuit names a contact of its own.

The contacts of vendors are new in 0.8.0: Example Telecom, a fictional carrier, names
its account manager and its repair desk once, and every circuit of that carrier has them
unless it names its own.

A script sends a file straight to the API, with a token whose service account holds
Inventory. The file is the body of the request:

```bash
curl -H "Authorization: Bearer $HIRDIR_TOKEN" -H 'Content-Type: text/csv' \
    --data-binary @/usr/share/doc/hirdir/examples/tags.csv \
    'https://inventory.example.net/hirdir/api/v1/imports/preview?entity=tags'
```

The answer is the preview: what each row would do, and the HID of the stored job.
`POST /api/v1/imports/<that HID>/apply` then loads it in the background: it answers at
once, and `GET /api/v1/imports/<that HID>` says how far it has got, until its `status`
is `applied`. A script waits for that before it previews the next file of the load
order, whose rows refer to what this one makes; `hirdir import --apply` waits by
itself. The rules of an import are under "Import and export" on the
[interfaces](interfaces.md#import-and-export) page.

## Configuration

`/etc/hirdir/config.toml`. Every key is optional and is shown there commented out with
its default. An upgrade puts the settings of a new version into the file in the same
way and changes nothing you set. Restart the service after a change:

```bash
sudo systemctl restart hirdir
```

To start again from a complete file, rather than from a copy kept somewhere, ask the
application for one. `hirdir admin config` prints every key with its default and what
it is for, each commented out; `--current` sets in it what the present file sets, as
it sets it; and `--output` writes it to a file, which it does not write over without
`--force`. Written with `--current`, the file has the mode and the group of the one it
was read from, since it may hold the password of a proxy:

```bash
sudo hirdir admin config --current --output /etc/hirdir/config.toml.new
sudo diff /etc/hirdir/config.toml /etc/hirdir/config.toml.new
sudo mv /etc/hirdir/config.toml.new /etc/hirdir/config.toml && sudo systemctl restart hirdir
```

The settings of the inventory, the stack discount or the warning period of renewals,
are in the database and not in this file. An Admin lists them with their defaults and
changes them on the Settings page or by `PUT /settings/{key}`, and `null` returns one
to its default.

## Backup and restore

A timer backs the database up every day into `/var/lib/hirdir/backups/` and keeps the
newest 14. The content of the reference files, which is kept beside the database in
`/var/lib/hirdir/files/`, goes into `/var/lib/hirdir/backups/files/` with each backup,
each file once however many backups hold it. An upgrade puts its own backup in the same directory, and it counts as one
of the 14. A backup is named for when it was made, in the application's time zone:
`hirdir-20261111T210000-0500.db` was made at 21:00 on 11 November, five hours behind
UTC. Backups made by 0.2.0 carry a time in UTC, marked `Z`, and are kept in order with
the rest. Copying those files off the host is up to you: copy `backups/files/` with
them, since a backup names the reference files it holds and the content is there.
A file that is erased in the application stays in `backups/files/` until the last
backup that holds it is rotated out, 14 days unless `[backup] keep` says otherwise.

```bash
sudo hirdir admin backup                   # one more backup, now; prints its path
sudo systemctl stop hirdir
sudo hirdir admin restore /var/lib/hirdir/backups/hirdir-20261111T210000-0500.db
sudo systemctl start hirdir
```

`restore` checks the file first and keeps the database as it was beside the restored
one, named `hirdir.db.before-restore`. It takes the reference files from the `files/`
beside the backup and checks, before it changes anything, that it has every one the
backup names, byte for byte; the files the restored database does not name are set
aside in `/var/lib/hirdir/files.before-restore/`.

To restore on another host, install the package there, copy the backup and the
`files/` beside it into its `/var/lib/hirdir/backups/`, and restore as above:

```bash
sudo rsync -a /path/to/copy/hirdir-20261111T210000-0500.db /path/to/copy/files /var/lib/hirdir/backups/
sudo chown -R hirdir:hirdir /var/lib/hirdir/backups
sudo systemctl stop hirdir
sudo hirdir admin restore /var/lib/hirdir/backups/hirdir-20261111T210000-0500.db
sudo systemctl start hirdir
```

`--files DIR` names another place to take the files from. Where some are lost, the
restore refuses and says how many; `--allow-missing-files` restores all the same, and
lists them, and each says so when it is downloaded.

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
assignments, every support agreement and contract with what it covers, every purchase
request with its lines, every external system with its registrations, every capacity
line, every circuit with its parts and groups, every reference with the content of its
file, and every tag, the stored imports, and the history of those records. It keeps
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

`hirdir admin check` says which schema revision the database is at, whether it is
whole, and how many reference files there are and what they take in
`/var/lib/hirdir/files/`. It names each file whose content is not there, which is a
failure and exits with an error, and each content that no reference names, which is
not: the service removes it when it starts, a day after it was put there.

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
   the prefix the file has and with the limit of a body that `/etc/hirdir/config.toml`
   gives. When that changes the file, it reloads nginx and says so:
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
prefix and its limit is not written again. The upgrade goes on and says so:

```text
hirdir-setup: /etc/nginx/snippets/hirdir.conf differs from what hirdir ships in more than its prefix and its limit, so it is left as it is. This version ships /usr/share/hirdir/nginx/snippet.conf: bring over by hand what is new there, then run: sudo nginx -t && sudo systemctl reload nginx
hirdir: /etc/nginx/snippets/hirdir.conf was left as it was, for the reason given above.
hirdir: nginx refuses an import or a file of more than 1 MB until it is as this
hirdir: version ships it. With the cause put right, run: sudo hirdir-setup --renew
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

**The counts by owner may change.** From 0.5.0 an item with no owner of its own, and
none from an item above it, has the owner of the device group it is a member of.
Nothing that is held changes, and no item is written to, but such an item is no longer
counted as nobody's: in a report by owner it moves from the blank row to its group's
row, and where that owner is outside the team it is marked as an exception. To see
before the upgrade what will move, list the members of groups that have an owner and
have none themselves; after it,
`GET /api/v1/items?filter=owner_hid:empty:true effective.owner_hid:empty:false` lists
every item that has its owner from above.

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

### From 0.5.0 to 0.6.0

The schema goes from revision `0007` to `0008`. Eight tables are added: `agreements`,
`contracts`, `contract_coverage`, `purchase_requests`, `purchase_lines`,
`external_systems`, `registrations` and `capacity_lines`, and with them the list of
capacity categories is filled. All of the tables are empty after the upgrade.

The `items` table gains one column, `purchase_line_hid`. To add a column that refers
to another table, SQLite makes the table anew and copies every row across, inside the
one transaction that the whole upgrade runs in. Nothing you have is changed by it.
Every record is as it was, field for field and at the `row_version` it had, and every
item has its history. The audit trail holds no event of the upgrade.

What is new is empty until somebody fills it in. No item is under a contract: on the
coverage report every major item in Assigned, Test, Prod or Down is in service with no cover,
which is true until the contracts are entered, and the first page says how many. No
item arrived on a purchase line, nothing is registered with an external system, and
there is no capacity line: the capacity report shows the support weight of the
inventory as demand, and no supply.

The list of capacity categories is filled with its defaults: `staff`,
`professional_services`, `smart_hands`, `tools`, `services` and `other_work`. A value
that a site had entered in the list is left as it is.

Three things answer differently from now on, for a script that reads them:

- The record of an item has `covered`, `covered_until`, `contract_count`, `coverage`,
  `registrations`, `group_registrations`, `purchase_line_hid` and `purchase_line`, and
  the record of a device group has `registrations`.
- `GET /reports/summary` and `GET /reports/management` take `by=contract`, which 0.5.0
  refused.
- A file of items may have a `purchase_line` column, which 0.5.0 rejected as unknown.
  An export of the columns that can be set writes it.

Among the settings that an Admin changes in the application, which `GET
/api/v1/settings` lists, there is one more, `service_states`, the lifecycle states in
which an item is in service for the coverage report: Assigned, Test, Prod and Down
until it is changed. It is no setting of the configuration file:
`/etc/hirdir/config.toml` gains none, and `/etc/nginx/snippets/hirdir.conf` is the one
0.5.0 wrote, so the upgrade says nothing of either and nginx is not reloaded.

The package now carries twenty-five example files, where it carried sixteen: see
[Try it with the examples](#try-it-with-the-examples).

Going back to 0.5.0 is as under
[Going back to the release before](#going-back-to-the-release-before). The backup of
this upgrade is at revision `0007`. 0.5.0 knows no contract, purchase request,
external system or capacity line, so whatever was entered of those with 0.6.0 is lost
with the rest that was entered since the upgrade.

### From 0.6.0 to 0.6.1

The schema stays at revision `0008`: 0.6.1 has no migration. Nothing that is held is
changed by the upgrade. Every record is as it was, field for field and at the
`row_version` it had, and the upgrade writes no audit event. It takes its backup and
stops and starts the service all the same. `/etc/hirdir/config.toml` gains no setting,
and `/etc/nginx/snippets/hirdir.conf` is the one 0.6.0 wrote, so the upgrade says
nothing of either and nginx is not reloaded.

Some of what is held is said or read differently from now on, for a script that reads
it. Each is a field, a route or a column more beside what 0.6.0 gave; the one value
that reads otherwise is the dates of an earlier term:

- **An earlier term of a contract has the dates it had.** A contract with no dates of
  its own takes its period from its agreement, and 0.6.0 gave an earlier term of such
  a contract, in `GET /contracts/{hid}/terms`, with blank dates. 0.6.1 gives those of
  the agreement's term that was in force when the contract's term began, as the
  agreement stood then, read from its audit trail: a renewal of the agreement entered
  afterwards does not change them (D-163).
  Each date says where it came from, `starts_on_source` and `ends_on_source`, `own`,
  `agreement` or `none`, and the term names the agreement the contract was in,
  `agreement_hid`. This holds for the renewals entered with 0.6.0 as well.
- **An agreement lists its own earlier terms**, `GET /agreements/{hid}/terms`, which
  0.6.0 did not have: each with its number, its period, its cost, its purchase
  reference, and when the renewal that ended it was entered and by whom, read from
  the audit trail in the same way, so the agreements that were renewed with 0.6.0 have
  theirs. A renewal entered early, whose term is still to begin, has ended no term yet.
- **A contract says what its agreement gives.** Each field of `effective` on a contract
  has `from_agreement` beside its value and its source, and the reseller
  `from_agreement_label`: what the agreement gives for that field today, whether the
  contract overrides it or not. It is blank for a contract in no agreement.
- **An item on a purchase line is of the line's model.** 0.6.0 let an item be put on a
  line of another model, by hand or by a file. From 0.6.1 an item that is put on a line
  and names no model takes the line's, one that names another is refused with `422` on
  `catalog_entry_hid`, and the model of an item on a line is not changed to another
  while it is there. **What 0.6.0 let in is left as it is**, and an edit of anything
  else of such an item goes through. It is reported, to be put right: the record of an
  item and the item list have `purchase_line_mismatch`, and each purchase line counts
  its own, `mismatched_items`. `GET /api/v1/items?filter=purchase_line_mismatch:eq:true`
  lists them, and with `include_archived=true` the retired and the archived among
  them. An item is put right by giving it the line's model, or by taking it off the
  line. The `purchase_line` of an item's record names the line's model,
  `catalog_entry_hid`.
- **The contracts that still count an item out of service** are on its record,
  `out_of_service_contracts`, and are fields of the item list,
  `out_of_service_contract.number` and `out_of_service_contract.hid`, to filter and
  sort by, as `contract.number` and `contract.hid` are for the contracts that cover it
  today. They are blank for an item in service.
- A file of items has the columns `out_of_service_contracts`, the numbers of those
  contracts, and `purchase_line_mismatch`, and a file of purchase lines the column
  `mismatched_items`. An export writes them when they are asked for, and an import
  passes over them, so such a file is taken back as it is.
- `hirdir agreements show` prints an agreement with its earlier terms, and `hirdir
  contracts show` marks a date of an earlier term that was the agreement's, and says
  beside an override what the agreement gives.

Going back to 0.6.0 needs no backup, because the schema is the same and 0.6.0 reads
the database as 0.6.1 leaves it:

```bash
sudo apt install --allow-downgrades ./hirdir_0.6.0_amd64.deb
```

The command goes through and starts the service, and that is all. What was entered
with 0.6.1 stays. 0.6.0 then gives the earlier terms of a contract with no dates of its
own blank dates again, has no list of the earlier terms of an agreement, and lets an
item onto a line of another model again. It refuses a file of items with the column
`out_of_service_contracts` or `purchase_line_mismatch`, and one of purchase lines with
`mismatched_items`, as having a column it does not know.

### From 0.6.1 to 0.7.0

The schema goes from revision `0008` to `0009`. Four tables are added:
`contract_contacts`, the contacts that an agreement or a contract names;
`capacity_line_targets`, the staff lines that a line of capacity multiplies;
`renewal_alert_views`, what each person last saw of the renewal alert; and
`capacity_records`, the capacity balance kept week by week. Columns are added to what
is there, and each of them holds nothing, or says no, until somebody sets it:

- `catalog_entries` gains `do_not_renew`, false, and `links`, none, and `items`
  gains `do_not_renew`, blank, so that every item has its model's;
- `regions`, `sites` and `locations` gain `links`, none;
- `contracts` gains `ends_with_term` and `next_with_agreement`, both false;
- `purchase_lines` gains `part_number` and `description`, blank, and its model may now
  be blank. To change what a column may hold, SQLite makes the table anew and copies
  every row across, inside the one transaction that the whole upgrade runs in. Every
  line keeps its model;
- `capacity_lines` gains `effect`, `add` on every line, and `factor` and `share`,
  blank, and its `quantity` and `units_each` may now be blank. It is made anew in the
  same way, and every line keeps its quantity and its units;
- `import_jobs` gains `rows_done`, `applied` and `stale`, and `import_rows`
  `applied_outcome` and `applied_reasons`.

**One thing that is held changes, and is meant to.** A job that 0.6.1 applied was
applied whole, in one transaction: the upgrade gives it the counts that an apply keeps
from now on, `rows_done` its rows and `applied` the rows it applied, so that
`GET /api/v1/imports/<HID>` says what it was. Nothing else is changed: every other
record is as it was, field for field and at the `row_version` it had, and every item
has its history. No model or item is flagged not to be renewed, no contract is marked,
no line loses its model, and the upgrade writes no audit event.

**What the server does by itself.** From 0.7.0 the service has two things to do at
set times, by the clock of the application's time zone. Each Monday just after
midnight it records the capacity balance of the week, and it does so when it starts in
a week that has none. So the first start after the upgrade makes the first record, of
what was carried over, with one audit event that the system makes, `create` of a
`capacity_record` with `via` of `system`; somebody may record the week again by hand,
or correct its figures with a reason. Each day just after midnight, and when it starts,
it works out the renewal alert of the day, which writes nothing. A time that passed
while the service was stopped is not made up for, but the record of a week is made at
the next start.

**One server to a state directory.** While it runs, the service holds a lock on
`/var/lib/hirdir/server.lock`, a file of its own that it makes there. A second
`hirdir admin serve` on the same directory stops at once with `another hirdir server
is running on /var/lib/hirdir: stop it first`, so that it cannot take for stopped an
import that the first is applying. `systemctl restart hirdir` lets the lock go before
the service starts again.

**Imports are applied in the background.** For a script this is the change to look
at:

- `POST /api/v1/imports/<HID>/apply`, and the apply of a bulk edit, answer `202` at
  once with the job, which is `queued` or `applying`, where 0.6.1 answered `200` with
  the job applied. The server applies it in a worker of its own, 50 rows to a
  transaction. A script waits for `GET /api/v1/imports/<HID>` to say `applied`, or
  `stopped`, before it goes on; one that previews the next file of the load order
  straight away finds the records of this one not yet there. `hirdir import --apply`
  waits by itself and shows how far it has got, unless it is given `--no-wait`.
- A row whose record was changed by somebody after the preview is no longer a `409`
  for the whole file: it is left out as `stale`, with the reason, and the rest are
  applied. The job counts them, `applied` and `stale`, and each row says what the
  apply did with it, `applied_outcome`.
- A job that stopped partway, because the service stopped, is `stopped`, and the same
  `POST` resumes it from the first row it had not applied.
- A job that failed with 0.6.1 stays `failed`, and cannot be applied: preview the file
  again.

**Settings in place of what was held in the code.** Five values that were fixed in
0.6.1 are settings of the inventory, each at the value 0.6.1 used until an Admin
changes it on the Settings page or by `PUT /api/v1/settings/<key>`:
`renewal_warning_days`, 90, how far ahead a contract counts as ending soon;
`renewal_pending_overdue_days`, 60, how long a renewal may be pending before it is
overdue; `end_of_life_within_days`, 730, and `end_of_life_date`, `ldos`, what the
end-of-life report looks for unless asked; and `max_items_per_request`, 1000, how many
items one request may cover, add to a group or receive. `GET /api/v1/settings` lists
them with the rest, and then the values that stay fixed, each with `fixed` true and
the decision that fixed it. Nothing reads differently until one of them is changed.

**The configuration file is written by the application.** `hirdir admin config`
writes a complete `/etc/hirdir/config.toml`, every key at its default and commented
out, and the file the package ships is written by it; see
[Configuration](#configuration). 0.7.0 adds no setting to the file, only a line that
says what `[database] url` is for, so the upgrade leaves `/etc/hirdir/config.toml` as
it is, edited or not, keeps no copy beside it and says nothing of it, and `sudo
hirdir-setup --settings` finds nothing to change. A site that wants the new comments
writes the file afresh from the one it has, and compares the two:

```bash
sudo hirdir admin config --current --output /etc/hirdir/config.toml.new
sudo diff /etc/hirdir/config.toml /etc/hirdir/config.toml.new
```

`/etc/nginx/snippets/hirdir.conf` is the one 0.6.1 wrote, so the upgrade says nothing
of it and nginx is not reloaded.

Some of what is held is read differently from now on, for a script that reads it:

- The coverage report counts a sixth section, `not_renewed`: an item in service that
  no contract covers and is flagged not to be renewed is no gap, and is left off
  `uncovered` and `expiring`. Until something is flagged it counts nothing, and the
  other counts are those of 0.6.1.
- The capacity report lists the lines that multiply, `multiplying_lines`, and beside
  its one balance the demand of each region, `demand_by_region`.
- The earlier terms of a contract, `GET /api/v1/contracts/<HID>/terms`, are the parts
  of its history, each with when and how it began, and a contract that joined or left
  an agreement with 0.6.1 has a part more for it, read from the audit trail.
- A purchase line says whether it is `tracked`, and a request is received in full
  once every tracked line has arrived.
- The records of a catalog entry, an item, a place, an agreement and a contract have
  the fields above, and the files of them the columns, which 0.6.1 rejected as unknown.
- `GET /api/v1/reports/renewals`, `GET /api/v1/renewals/alert` and
  `/api/v1/capacity-records` are new.

The package now carries twenty-six example files, where it carried twenty-five: the
contacts of the contracts are new. See [Try it with the examples](#try-it-with-the-examples).

Going back to 0.6.1 is as under
[Going back to the release before](#going-back-to-the-release-before), with the backup
of this upgrade, which is at revision `0008`:

```bash
sudo apt install --allow-downgrades ./hirdir_0.6.1_amd64.deb
sudo hirdir admin restore /var/lib/hirdir/backups/hirdir-<time of the upgrade>.db
sudo dpkg --configure hirdir
```

The first command stops at the database, as it is meant to. 0.6.1 knows no contact of
a contract, no flag not to renew, no line that is not tracked or that multiplies, no
record of the balance and no link, so whatever was entered of those with 0.7.0 is lost
with the rest that was entered since the upgrade.

### From 0.7.0 to 0.8.0

The schema goes from revision `0009` to `0010`. Eight tables are added, for the
circuits and what is known of them:

- `circuits`, the telecommunication circuits, each with its two sides, its primary
  carrier and the number that carrier gives it;
- `circuit_carriers`, the carriers of a circuit beside its primary one, each with its
  part and its own number;
- `circuit_costs`, the lines of what a circuit costs a month, a credit among them;
- `circuit_devices`, the items and device groups that a circuit connects, each on a
  side;
- `vendor_contacts`, the account team and the support desk that a vendor names once,
  for every circuit of that carrier;
- `circuit_contacts`, the contacts that a circuit names of its own, in place of its
  carrier's or of what the location of a side gives;
- `circuit_groups` and `circuit_group_members`, the groups that circuits are looked
  at and costed in.

`regions`, `sites` and `locations` each gain `support_weight`, blank. To add it,
SQLite makes each of the three tables anew and copies every row across, with its
indexes, inside the one transaction that the whole upgrade runs in: every place keeps
its addresses, its shipping instructions, its operator, its links and the contacts
assigned there. Two lists are loaded with their defaults: `circuit_type`, seven types
from `internet` to `other`, and `carrier_role`, four parts from `local_exchange` to
`other`. 0.7.0 has neither list, and a value that a site has put into one by other
means is left as it is.

**Nothing that is held changes.** Every record is as it was, field for field and at
the `row_version` it had, and every item has its history. No place is given a weight,
no setting is set, there is no circuit and no contact of a vendor until somebody enters
one, and the upgrade writes no audit event.

**What the server does by itself.** Each day just after midnight, and when it starts,
the service works out the long reports and keeps them, for the view each page opens
with: the coverage report, the renewal worklist and the summary of the renewal alert, as
0.7.0 did, and now the capacity report as well. It writes nothing. A report so kept is
given to every person alike while nothing has changed that it is worked out of; any
change leaves it to be worked out again when it is next asked for. An Admin can see
what is kept, `GET /api/v1/kept-answers`, and have each kept answer worked out anew and
compared, `POST /api/v1/kept-answers/check`, which should find none that differs. The
record of the capacity balance of each week is made as it was.

**Settings.** Seven settings of the inventory are new. Six are the weights, each blank
until an Admin sets one, and so changing nothing until then: `default_item_weight` and
`minimum_item_weight`, for the major items, `default_site_weight` and
`minimum_site_weight`, and `default_circuit_weight` and `minimum_circuit_weight`. A
default is had by what has no weight of its own, and a minimum raises a weight below
it. `GET /api/v1/settings` lists each with a `default` of null. The seventh,
`circuit_cost_side`, is `a`: a new circuit counts its cost and its support weight at
the site of its A side unless an Admin makes it `z`, and a change of it changes no
circuit that there is. 0.8.0 adds no setting to `/etc/hirdir/config.toml`, so the
upgrade leaves the file as it is, edited or not, and says nothing of it, and
`/etc/nginx/snippets/hirdir.conf` is the one 0.7.0 wrote, so nginx is not reloaded.

Some of what is held is read differently from now on, for a script that reads it:

- The capacity report gives its `support_weight` in its parts, `items_weight`,
  `places_weight` and `circuits_weight`, with how many items, sites and circuits
  counted at a default, `defaulted`, and how many were raised to a minimum, `raised`.
  Until a place or a circuit is given a weight, or an Admin sets a default, the whole
  is the items', as it was, and the other counts are 0. A record of the capacity
  balance made before 0.8.0 has no parts, and gives them as null.
- The capacity report is kept, as above, and `POST /api/v1/reports/capacity/try`
  answers it beside what other weights and staff lines would make of it, saving
  nothing.
- A region, a site and a location have `support_weight`, and a site its weight in
  force, `effective.support_weight`; the weight in force of an item says
  `raised_from`, which is null until a minimum raises it.
- The record of an item and of a device group lists the circuits it is connected to,
  `circuits`, and that of a vendor its contacts, `contacts`: both empty until one is
  entered.
- The files of regions, sites and locations have a `support_weight` column, which
  0.7.0 rejected as unknown, and there are seven kinds of file more, of the contacts
  of vendors, circuit groups, circuits, their carriers, their cost lines, their
  contacts and their devices.
- `/api/v1/circuits`, `/api/v1/circuit-groups`, `/api/v1/vendors/<HID>/contacts`,
  `GET /api/v1/reports/circuit-costs` and `/api/v1/kept-answers` are new, and so are
  `hirdir circuits`, `hirdir circuit-groups`, `hirdir report circuit-costs` and
  `hirdir report capacity --try`.

The package now carries thirty-three example files, where it carried twenty-six: the
contacts of vendors, and six of circuits. See
[Try it with the examples](#try-it-with-the-examples).

Going back to 0.7.0 is as under
[Going back to the release before](#going-back-to-the-release-before), with the backup
of this upgrade, which is at revision `0009`:

```bash
sudo apt install --allow-downgrades ./hirdir_0.7.0_amd64.deb
sudo hirdir admin restore /var/lib/hirdir/backups/hirdir-<time of the upgrade>.db
sudo dpkg --configure hirdir
```

The first command stops at the database, as it is meant to. 0.7.0 knows no circuit, no
circuit group, no contact of a vendor, no weight of a place and none of the seven
settings, so whatever was entered of those with 0.8.0 is lost with the rest that was
entered since the upgrade.

### From 0.8.0 to 0.9.0

The schema goes from revision `0010` to `0011`. Two tables are added, for the reference
files:

- `reference_files`, the references: each a file kept by `hirdir`, with the name it
  was uploaded with, its type, its size and the checksum of its content, or a link to
  a file kept elsewhere, and each with a title, a kind and notes;
- `reference_attachments`, the records a reference is on, each a catalog entry, a
  region, a site, a location, a circuit or an item.

One list is loaded with its defaults: `reference_kind`, twelve kinds from `photograph`
to `other`. 0.8.0 has no such list, and a value that a site has put into one by other
means is left as it is.

**Nothing that is held changes.** Every record is as it was, field for field and at
the `row_version` it had, and every item has its history. There is no reference until
somebody adds one, and the upgrade writes no audit event.

**Where the files are.** The content of a reference file is kept beside the database
and never in it, in `/var/lib/hirdir/files/`, which the upgrade makes, for the `hirdir`
user alone, empty. Each backup puts the content its database names into
`/var/lib/hirdir/backups/files/`, as under [Backup and restore](#backup-and-restore);
the backup that the upgrade takes is of the database of 0.8.0, which names none. When
the service starts it removes what an upload that was cut short left behind, and
content that no reference names and that is more than a day old.

**Settings.** One setting of the inventory is new, `reference_file_types`: the
extensions of the files a reference may be, twenty-four of them, from `jpg` to `zip`,
until an Admin changes it. `GET /api/v1/settings` lists it, and beside it two values
that are fixed, `refused_file_types`, the web pages, scripts and programs that are never
taken, and `max_attachments_per_request`. The configuration file has one key more,
`max_reference_megabytes` under `[files]`, the largest reference file, 100 MB unless it
says otherwise. The upgrade puts it into `/etc/hirdir/config.toml`, commented out at its
default, and says so: `hirdir: /etc/hirdir/config.toml has the new settings of this
version, commented out at their defaults: files.max_reference_megabytes. Nothing you set
was changed.`

**nginx.** The limit of a body in `/etc/nginx/snippets/hirdir.conf` goes from `20m` to
`100m`, the larger of the two limits of the configuration file, and the upgrade writes
the snippet again and reloads nginx, and says so, as in step 4 above. From now on the
line is written from the configuration file, by every upgrade and by `sudo
hirdir-setup --renew`, and is no longer changed by hand. A site that raised it by hand
with 0.8.0, together with `max_megabytes`, as this page then said to, has its snippet
written again all the same, with the larger of its two limits: with `max_megabytes =
50` the line says `100m`, and with `max_megabytes = 250` it says `250m`. A limit
raised in the snippet alone, which 0.8.0 did not take either, and one lowered there,
come to the larger of the two of the configuration file as well: set the limits you
want there, and run `sudo hirdir-setup --renew && sudo systemctl restart hirdir`. A
snippet changed by hand in anything more is left as it is, as before, and then lets
no upload over 20 MB through: bring over the new limit by hand. A load balancer or
another proxy in front of nginx has to let 100 MB through for an upload.

Some of what is held is read differently from now on, for a script that reads it:

- A body between 20 and 100 MB that is not the upload of a reference file, an import
  among them, which nginx refused with its own page, is refused by `hirdir` itself,
  with a `413` problem document that says the limit.
- The page's `Content-Security-Policy` allows `img-src 'self' blob:`: a picture that
  the page has fetched itself, which is how it shows a photograph of a reference.
- `/api/v1/reference-files` and `GET /api/v1/<records>/<HID>/references`, for catalog
  entries, regions, sites, locations, circuits and items, are new, and so is `hirdir
  references`.
- `hirdir admin backup` puts the files into `backups/files/`; `hirdir admin restore`
  takes them back from the `files/` beside the backup or from `--files DIR`, and
  refuses, before it changes anything, where some are missing, unless
  `--allow-missing-files` is given; `hirdir admin reset` erases every reference with
  its content; and `hirdir admin check` has a line for the files, `reference files:`,
  and fails where a reference names content that is not there.

Going back to 0.8.0 is as under
[Going back to the release before](#going-back-to-the-release-before), with the backup
of this upgrade, which is at revision `0010`:

```bash
sudo apt install --allow-downgrades ./hirdir_0.8.0_amd64.deb
sudo hirdir admin restore /var/lib/hirdir/backups/hirdir-<time of the upgrade>.db
sudo dpkg --configure hirdir
```

The first command stops at the database, as it is meant to. 0.8.0 knows no reference
and no kind of file, so every file that was uploaded and every link that was made with
0.9.0 is lost with the rest that was entered since the upgrade. 0.8.0 reads neither
`/var/lib/hirdir/files/` nor `/var/lib/hirdir/backups/files/`, and leaves both as they
are, with what was uploaded in them: remove them once you are sure, or leave them for
0.9.0 to tidy when it is installed again. 0.8.0 does not know the snippet that 0.9.0
wrote either, takes it for one changed by hand, leaves it as it is and says so: nginx
then lets 100 MB through, and 0.8.0 refuses an import over 20 MB itself, or nginx
answers it with a `502`. To have the snippet of 0.8.0 back, copy
`/usr/share/hirdir/nginx/snippet.conf` over it, then give it the prefix it had with
`sudo hirdir-setup --prefix`, or, under `/hirdir/`, run `sudo nginx -t && sudo
systemctl reload nginx`.

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
goes through, nothing is restored and nothing is lost. 0.4.2 and 0.6.1 are such
releases. The section of each release above says what its upgrade changed.

## Remove

```bash
sudo hirdir-setup --remove
sudo apt remove hirdir        # keeps /var/lib/hirdir and /etc/hirdir
sudo apt purge hirdir         # removes them, and the hirdir user
```

A purge also removes `/etc/nginx/snippets/hirdir.conf`, and takes the `include` line
out of the nginx site if it is still there, so that nginx is never left pointing at a
snippet that no longer exists.
