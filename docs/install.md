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
sudo apt install ./hirdir_0.1.0_amd64.deb
```

This creates the `hirdir` user, the state directory `/var/lib/hirdir`, the database and
the key that signs sessions, and starts `hirdir.service` listening on `127.0.0.1:8715`.
Nothing is reachable from outside the host yet.

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

The `hirdir` command reads the same token from `HIRDIR_TOKEN`, and the server from
`HIRDIR_URL`.

## Configuration

`/etc/hirdir/config.toml`. Every key is optional and is shown there commented out with
its default. Restart the service after a change:

```bash
sudo systemctl restart hirdir
```

## Backup and restore

A timer backs the database up every day into `/var/lib/hirdir/backups/` and keeps the
newest 14. Copying those files off the host is up to you.

```bash
sudo hirdir admin backup                   # one more backup, now; prints its path
sudo systemctl stop hirdir
sudo hirdir admin restore /var/lib/hirdir/backups/hirdir-20261112T020000Z.db
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

The upgrade backs the database up, applies any schema changes and restarts the service.
If a schema change fails the upgrade stops and names the backup it made.

## Remove

```bash
sudo hirdir-setup --remove
sudo apt remove hirdir        # keeps /var/lib/hirdir and /etc/hirdir
sudo apt purge hirdir         # removes them, and the hirdir user
```

A purge also takes the `include` line out of the nginx site if it is still there, so
that nginx is never left pointing at a snippet that no longer exists.
