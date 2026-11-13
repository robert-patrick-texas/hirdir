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
sudo apt install ./hirdir_0.2.0_amd64.deb
```

This creates the `hirdir` user, the state directory `/var/lib/hirdir`, the database and
the key that signs sessions, and starts `hirdir.service` listening on `127.0.0.1:8715`.
The database begins with no account and no inventory, and with the lists of choices
and the lifecycle rules at their defaults. Nothing is reachable from outside the host
yet.

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
| `--self-signed` | Create a site with a throwaway certificate. For test containers only |

The prefix lives in one file, `/etc/nginx/snippets/hirdir.conf`. Running
`sudo hirdir-setup --prefix /inventory` again later moves `hirdir` and needs no
restart of the service.

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

## Configuration

`/etc/hirdir/config.toml`. Every key is optional and is shown there commented out with
its default. Restart the service after a change:

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

## Check

```bash
sudo hirdir admin check
systemctl status hirdir
journalctl -u hirdir
curl -s http://127.0.0.1:8715/api/v1/health/ready
```

## Upgrade

```bash
sudo apt install ./hirdir_<new version>_amd64.deb
```

The upgrade does four things, in this order:

1. It stops the service, so that nothing writes to the database while its schema
   changes.
2. It backs the database up into `/var/lib/hirdir/backups/` and says where:
   `hirdir: the database as it was before this upgrade is kept at
   /var/lib/hirdir/backups/hirdir-20261111T210000-0500.db`.
3. It applies the schema changes of the new version.
4. It starts the service again.

It keeps every account, user group, role grant, service token and audit event, so
access codes and service tokens go on working. It keeps the key that signs sessions,
so people who are signed in stay signed in, with the session they have. It leaves
`/etc/hirdir/config.toml` and the two nginx files as you have them, so `hirdir` stays
under the prefix it had and `hirdir-setup` is not run again.

Installing the version that is already installed does the same four things and changes
nothing in the database.

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

A purge also takes the `include` line out of the nginx site if it is still there, so
that nginx is never left pointing at a snippet that no longer exists.
