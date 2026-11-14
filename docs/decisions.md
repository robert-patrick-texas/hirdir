# Decisions

What has been decided, and what is proposed and waiting for a yes or a correction. The
other pages are written as if every proposal here stands. When one changes, this page
changes first, then the page it affects, then the code.

A new decision takes the next number and is never renumbered. A reversed decision is
marked as replaced, not removed.

## Decided

| ID | Decision |
|---|---|
| D-01 | The product is named `hirdir` and installs under `/opt/hirdir`. |
| D-02 | Ubuntu 26.04 LTS. Python with FastAPI. SQLite now, PostgreSQL as an option later. nginx from Ubuntu terminates TLS. |
| D-03 | No cookies. The session token is kept in local browser storage. |
| D-04 | The MVP signs in with a username and an access code that an Admin sets. Length and complexity rules come after the MVP. RADIUS comes next, SAML after that. |
| D-05 | The session token is signed by the server and carries its time of issue. Each user has a start time; a token issued before it is refused. |
| D-06 | Roles are View-only, Inventory and Admin. A user group is a label by default. A role may be granted to a user or a group, and the highest wins. |
| D-07 | Automation tokens belong to service accounts, not to people. |
| D-08 | Nothing is served without signing in except the sign-in page and the health check. |
| D-09 | No compliance regime is mandated. Audit records are kept without expiry until a retention feature exists. Security controls that `hirdir` does not implement are referred to, not claimed. |
| D-10 | Python is built with uv, ty and ruff. The `.deb` carries Python and every Python dependency. Ordinary Ubuntu packages are left to apt. |
| D-11 | Every release uses the latest production release of every component. A fault not readily overcome earns a one-release hold, stated in the release notes. |
| D-12 | Release notes: a summary of one to three sentences; New, Changed, Fixes and Additional Notes as needed; a lines-of-code table from `cloc`; a versions table. |
| D-13 | Every Markdown file is published as HTML on GitHub Pages, with pictures from `images/`. |
| D-14 | The package installs nginx snippets and expects an existing site to supply TLS. A setup script edits the nginx configuration for early deployments. |
| D-15 | Tested on the build host in rootful Docker or a systemd container. A container image is a later packaging option. |
| D-16 | The inventory holds what has a recurring support contract or adds support burden, including virtual machines, software and services. |
| D-17 | Every record has an application-assigned ID, the HID. |
| D-18 | Manufacturer, PID and serial number identify an item. Serial number first, asset tag when present, name when neither exists. A blank name takes the hostname. |
| D-19 | MAC address is a first-class, searchable field and is not unique. |
| D-20 | Items are major or minor. Major items count for lifecycle and support weight. Minor items do not. |
| D-21 | A stack has one master and one or more members. Each member is counted, covered and costed on its own. The stack is one device on the network. Its serial number is read from the master and not stored. |
| D-22 | The stack discount on support weight is a global value that a model may override. It never applies to contract cost. |
| D-23 | Device groups nest and carry roles, and cover stacks, clusters and controllers with their endpoints. Registration with a cloud service or SDN controller is a link to an external-system record, not a group. |
| D-24 | The catalog holds, per manufacturer and PID: type, function, description, four end-of-life dates, estimated value, support weight and annual support cost. An item inherits them and may override. |
| D-25 | Estimated value is a planning estimate, optional. Annual support cost works the same way and is expected to be empty at first. |
| D-26 | Spare is a disposition, as Production is. Online or offline is intent, held separately from what monitoring observes. Excess is offline. |
| D-27 | A purchase request records model and quantity against an RITM and is held pending until delivery is assured. |
| D-28 | Addresses may carry a network label (a VRF, a tenant, a colour). |
| D-29 | Tags apply to most records. |
| D-30 | Phones and access points are in the inventory and in the count. |
| D-31 | The grid selects rows only in early versions, with sorting by any column. AG Grid Community is the grid. |
| D-32 | The repository is public. Examples are fictional. Nothing from a real network is committed. |
| D-33 | The nine lifecycle states stay as drawn. Disposition and expected-online are two further fields, valid in the combinations tabled in [data-model.md](data-model.md). A spare on a shelf at its site is Prod, Spare, offline. A spare still parked with the team is Assigned, Spare. (Was P-01.) |
| D-34 | Component count takes states Assigned through Pending-Removal. Support weight takes Test, Prod and Down, so an offline spare in Prod carries weight and a parked one does not. Both lists are settings. (Was P-02.) |
| D-35 | The headline component count takes hardware and virtual machines. Software and services are reported beside it, and all four kinds carry weight and cost. (Was P-03.) |
| D-36 | The web UI is React with Vite. (Was P-04.) |
| D-37 | Each endpoint carries only its own support weight. A controller gets nothing extra for the endpoints it manages. (Was O-02.) |
| D-38 | For software and services, quantity multiplies both weight and cost. (Was O-03.) |
| D-39 | Support weight is demand, balanced against resource units supplied by staff positions, professional services, smart hands, tools and add-on services including agentic AI. The sum of those lines is the capacity available, for the infrastructure and for other work. The purpose is right-sizing the team. |
| D-40 | Work that is not infrastructure, such as projects, a merger or acquisition, or an organizational transition, is entered as demand lines. The balance is supply against infrastructure plus other work. (Was P-20.) |
| D-41 | A staff line is a kind of position and a count. No capacity is attributed to a named person at this phase. View-only may read capacity lines; Inventory may edit them. (Was P-22.) |
| D-42 | Units per position are fixed numbers. Seniority is a separate staff line per level, each with its own units, with one mid-level position as 1.0 by convention. (Was P-23.) |
| D-43 | A tool or service that makes people more effective, AI among them, is a multiplier on the staff lines it amplifies, not a flat number of units standing in for staff. Until multiplier lines are built, after the MVP, such a tool is entered as a supply line with its estimated gain. The formula is in [data-model.md](data-model.md). A tool that takes work to run is an inventory item whose support weight is already demand. (Was P-24.) |
| D-44 | One resource unit, a mid-level position, carries a support weight of 300. This is a placeholder and a setting. (Was O-05.) |
| D-45 | The web UI is built with TypeScript 7. Its compiler has no programming interface, so the usual OpenAPI type generator and typescript-eslint cannot be used with it: types are generated by the project's own `web/scripts/gen-types.mjs`, and the linter is Biome. Holding TypeScript at an older version was considered and declined. |
| D-46 | A time is shown to a person in local time, with the name of its zone: the reader's own zone where it is known, otherwise the installation's `time_zone` setting, which is America/New_York unless changed. A time is not shown in UTC. Storage and the API keep UTC. **Replaced by D-61.** |
| D-47 | The backup taken before an upgrade is one of the rotating backups, and is removed on the same schedule as the others. |
| D-48 | Using `hirdir` should be easy and without waiting. Where a delay can be avoided or hidden, real or perceived, it is: the web UI loads only what a page needs, fetches the rest ahead of need, and a browser keeps what does not change. |
| D-49 | The owner record is in from 0.2.0, with its label, organization and external flag, so that ownership can be shown and tried early with mock-up examples. Its people, and the exception recorded when an item is given to an owner outside the team, come in 0.5.0. (Was P-25.) |
| D-50 | Lifecycle state, disposition and expected-online may be blank on an item. An item with no state is counted, because it may be in the team's hands and nobody has said otherwise. Once a state is given, the state decides: an item declared to be outside the team's control is not counted within it. A count is of the items in the view being looked at, whichever of drafts, active and retired records that view holds. (Was P-26, changed.) |
| D-51 | On a move an item keeps its disposition when the new state allows it, and takes the state's "set on entry" value when it does not. The caller may name the disposition and the intent instead. To be looked at again when a move may set several fields at once. (Was P-27.) |
| D-52 | `session_hours` stays in the configuration file. It moves to the database only if most of the configuration does. (Was P-29.) |
| D-53 | Every text comparison in a filter ignores case, regular expressions included: text is compared as if it were all in lower case. A regular expression matches anywhere in the value unless it is anchored. `ne` also finds blanks. (Was P-30.) |
| D-54 | A list leaves out drafts, retired records and items in Archived unless `include_drafts` or `include_archived` asks for them. The `fields` parameter of a list arrives with export, and `Idempotency-Key` with import, both in 0.3.0. (Was P-31.) |
| D-55 | A decimal has two places: money, support weight and percentages alike. It travels as text in JSON. (Was P-33, changed: support weight had three.) |
| D-56 | `lifecycle_rules` has one row for each state: the dispositions it allows, which of them may and must be online, what is set on entry, and the states an item may move to. The nine states cannot be added to or removed, and no row may make Excess online. (Was P-34.) |
| D-57 | An item that is first entered in Down or Pending-Removal, and so has no disposition "from before", may be given any. Once it has one, that is the one it keeps. (Was P-35.) |
| D-58 | `make package-test` upgrades from the previous release's package: `PREVIOUS_DEB` when set, otherwise the highest version below the one under test in `dist/`. When there is no such package the upgrade is skipped, and the run says so. (Was P-37, changed: it had failed.) |
| D-59 | The migrations of one upgrade run in one transaction. After a failed upgrade the way back is the backup, on the version installed before, and the package prints the commands. (Was P-38.) |
| D-60 | The Admin area of the web UI is shown to every role. Tags, choices and lifecycle rules are in it for all to read, and for Inventory to edit the first two. Users, groups, roles and settings show to an Admin only. (Was P-39.) |
| D-61 | Every time is shown in the application's time zone, with the zone named, so that everybody refers to the same time whatever zone they are in. It is the `time_zone` setting, America/New_York by default. This holds for the web UI, the command line and the names of backup files. Storage and the API keep UTC. (Was P-40, changed. Replaces D-46.) |
| D-62 | A lifecycle move or combination that the rules refuse is a `422` that names the field. `409` stays for a stale version and for uniqueness. (Was P-28.) |
| D-63 | The server's tests use `httpx2`, the continuation of `httpx` under Pydantic. The command line moves to it in 0.3.0, when the client commands are built. (Was P-32.) |
| D-64 | A regular expression is refused before it is compiled when the repeat counts written in it, the numbers in `{n}` and `{n,m}`, multiplied together, come to more than 100. This limits what a pattern may say, never how many records it may find. In the short form of a filter, a value that itself looks like `field:word:` is refused as a mistyped operator. (Was P-36.) |
| D-65 | An import does not turn an inherited value into an override. Where a field inherits and the record has no value of its own, a cell that holds the very value it inherits leaves it inheriting. The same holds for a catalog entry and the global stack discount, and for a row that changes an item's model while it still holds the old model's values. (Was P-43.) |
| D-66 | In an import, a different lifecycle state is a move under the rules of moves, with the row's `state_reason` as the why, and is never forced. A row that would retire a record is rejected. (Was P-45.) |
| D-67 | A preview of more than a hundred rows is worked on a copy of the database. An apply is one transaction and holds the one writer's place while it works; a change that waits more than five seconds behind it is a `503` with `Retry-After`, and was not made. (Was P-51.) |
| D-68 | The packaged nginx snippet sets `client_max_body_size 20m`, the application's own limit and no more. Through nginx a body over 20 MB is refused by nginx, with a `413` and the page of nginx, not a problem document. The application's own `413` is seen through nginx for a file of more than 100,000 rows. A site that wants to take larger files has to change nginx to allow them. (Was P-53.) |
| D-69 | A preview of an import or a bulk edit is kept, and is applied once, by anybody who holds the Inventory role, whoever made it. The job says who made it and who applied it. Apply works the file through again and applies only when every row comes out as previewed and every record a row matched is at the version previewed, rows that were `unchanged` included. (Was P-46, changed: only the one who made a preview could apply it.) |
| D-70 | The largest file `hirdir` takes is `max_megabytes` under `[files]` in the configuration file, 20 unless a site sets another. A site that wants larger files raises it there and raises `client_max_body_size` in nginx to match. The limit of 100,000 rows to a file is not changed by it. |
| D-71 | A row with neither serial number nor asset tag is matched by its name among the items that are not retired, drafts included. It was "the one active item". (Was P-52.) |
| D-72 | `/etc/nginx/snippets/hirdir.conf` is not a conffile from 0.3.0. The package ships its text as `/usr/share/hirdir/nginx/snippet.conf`, and `hirdir-setup --renew`, which postinst runs at install and at each upgrade after the migrations, writes the snippet from it under the prefix the host has, tests it with `nginx -t`, and has nginx reload when an upgrade changed it. A snippet edited by hand in more than its three prefix lines is left alone, and the upgrade says so. (Was P-54.) |
| D-73 | The CSV and JSON files of `examples/` ship in the package, in `/usr/share/doc/hirdir/examples/`. `install.md` says to load them only where a backup can be put back. (Was P-55.) |
| D-74 | `hirdir admin reset` clears the inventory, so that a site can load test data, try things out, clear it and start over with its own. It is a command on the server and nowhere else: not in the web UI, not in the API, so that nobody with Admin in the application can do it by accident. It refuses to run while the service is up, takes a backup first, and asks for the word `reset`. It removes items, catalog entries, vendors, owners, tags, stored imports and the history of those records, and keeps accounts, groups, roles, tokens, settings, choices and lifecycle rules. With `--everything` it goes back to a fresh installation, accounts and audit trail included. This is the one way anything is deleted, and the backup holds what was. |
| D-75 | `/etc/hirdir/config.toml` is not a conffile from 0.3.0, so that no upgrade stops to ask about it and an unattended upgrade always goes through. The package ships its text as `/usr/share/hirdir/config.toml`. `hirdir-setup --settings`, which postinst runs at install and at each upgrade after the migrations, writes the file on a first install, and at an upgrade puts the settings the file does not have yet into it, each commented out at its default, also where a site has edited the file. Nothing a site wrote is changed or moved, and the file as it was is kept beside it. `hirdir-setup --upgrade PACKAGE.deb` installs a newer package through apt with no question left to answer, and plain `apt install` gives the same result. The way of the `texas2step` project, taken a step further: there the file is a conffile and a merge is run after apt has asked. (Was P-59, changed: the shipped file was to stay frozen.) |
| D-76 | The package that is published is built after its release notes are written, and `make package-test` is run on that package. `make deb` builds the documentation as well as the web UI. (Was P-56.) |
| D-77 | The setup tool is part of the package, never a second file to fetch. A site downloads the one `.deb`, installs it, and from then on may let `hirdir-setup` do its upgrades: `--check` asks GitHub whether a newer release is published, `--upgrade` fetches it, compares it with the checksum published beside it and installs it, and `--proxy URL` sends both requests through an enterprise proxy. An upgrade is begun by the tool that is installed and finished by the tool the new package brings, which the old one runs once apt is done, so what a later version needs done at an upgrade is in that version. A package that is already on the host is installed with `--upgrade PACKAGE.deb`, for a host with no way out. |
| D-78 | The package ships `hirdir-upgrade.timer`, which is off unless a site turns it on. Turned on, it runs `hirdir-setup --upgrade --yes` each night at a time of its own between 21:00 and 03:00, in the host's local time, and installs a newer release from GitHub when one is published. A night that was missed is not made up for by day. The proxy it goes through is `proxy` under `[upgrades]` in the configuration file. |

## Proposed

Each of these is the working answer. P-01 to P-04,
P-20, P-22, P-23 and P-24 were confirmed and are now D-33 to D-36 and D-40 to D-43. P-25 to P-27,
P-29 to P-31, P-33 to P-35 and P-37 to P-40 were answered on 2026-11-13 and are now
D-49 to D-61, three of them changed by the answer. P-28, P-32 and P-36 followed the same
day as D-62 to D-64. P-43, P-45, P-51 and P-53, of release 0.3.0, were confirmed on that
day too and are D-65 to D-68, and P-46 was answered with a change and is D-69. D-70 followed from D-68.

| ID | Proposal | Why | Built in |
|---|---|---|---|
| P-05 | nginx strips the prefix and names it in `X-Forwarded-Prefix`; the server writes it into the page. | Deep links and API documentation need the prefix. This is the `texas2step` way. `sunstone` and `segl` leave the server unaware. | 0.1.0 |
| P-06 | Draft, active and retired are a `record_status` on items, sites and locations from the first release that has them. Planning views come after the MVP. An item that leaves ownership is Released, then Archived, and is shown greyed when asked for; there is no separate dormant store. | Leaving drafts out of every count is cheap to build in and costly to add later. | 0.2.0 |
| P-07 | A minor item inherits lifecycle state and disposition from its parent as well as location and owner. | A power supply is in production because its switch is. | 0.4.0 |
| P-08 | Asset tag is unique when present. | It is used to match import rows. | 0.2.0 |
| P-09 | The session lasts 12 hours and is kept in `localStorage`, so it survives closing the tab. | Stood unanswered at its default. | 0.1.0 |
| P-10 | The package is built with `dpkg-deb` in a clean Ubuntu 26.04 container. The service listens on `127.0.0.1:8715`. | `dpkg-deb` needs no extra tool. A loopback port is the simplest thing nginx can reach. | 0.1.0 |
| P-11 | Release notes are files in `docs/releases/` and the same text is the GitHub release. | They are then published with the rest of the documentation. | 0.1.0 |
| P-12 | The lines-of-code table splits each language into Product, Tests and Tooling by path. | It is the table `texas2step` publishes, here produced by `cloc`. | 0.1.0 |
| P-13 | In an import a blank cell leaves the value alone and `!clear` clears it. | Blank cells are common in spreadsheets and must not erase data. | 0.3.0 |
| P-14 | A vendor or catalog entry named in an import and not yet known is created and marked unreviewed. | Imports should not stall on catalog upkeep. | 0.3.0 |
| P-15 | The same address twice under one network label is accepted and reported. | Shared and virtual addresses are real. | 0.4.0 |
| P-16 | Fiscal year starts in January unless the setting says otherwise. | Neutral default. | 0.6.0 |
| P-17 | The scale target is 50,000 items. | Phones and access points are counted. | 1.0.0 |
| P-18 | Test equipment has an owner and nothing more: no check-out, no calibration dates. | Stood unanswered at its default. | — |
| P-21 | A capacity line may be a draft, may carry an annual cost, a vendor, dates and a region or site. The report shows the balance with and without drafts. | Drafts already exist for items and sites and give what-if comparisons for free. | 0.6.0 |
| P-41 | Tags are imported and exported like any other record, and come first in the load order. Choices, settings, lifecycle rules and the access records are not carried by files. | An item names its tags, and a tag is made before it is used, so `examples/` could not otherwise be loaded into an empty database. | 0.3.0 |
| P-42 | A file is sent as the body of `POST /imports/preview`, with its entity, mode and name beside it in the URL, and not as a form upload. A file over the limit is a `413`. | The package needs nothing more for it, and the command line and a browser send a file the same way. | 0.3.0 |
| P-44 | A column that an export writes and nobody can set, such as a `_source`, a detail of the catalog entry or `updated_at`, is accepted by an import and passed over. Only a column the entity does not know rejects the file. | Any export can then be edited and imported back. | 0.3.0 |
| P-47 | A bulk edit is a preview of the same kind as an import's: `POST /items/bulk-update` previews and stores it, `POST /items/bulk-update/{hid}/apply` applies it. It sets what an import may set, except, on more than one item at once, the fields that tell one item from another, and may add and remove tags. | One mechanism and one check for a stale copy, whichever way many records are changed. | 0.3.0 |
| P-48 | `Idempotency-Key` is kept for 24 hours for each caller. The same request with the same key is answered with the first answer and not carried out again; the same key on another request is a `422`. It is taken by a `POST` on an inventory record, an import or a bulk edit, and refused on the routes of accounts. | A retry after a lost answer must not create a second record. An account route's answer may hold an access code or a token, which is kept nowhere, so it cannot be kept to be replayed. | 0.3.0 |
| P-49 | `fields` on a list names the fields of the record to return, as the route names them, with a dot for one field of a record within it. `hid` and `row_version` always come. | The command line and scripts ask for little, and a change still needs the version. | 0.3.0 |
| P-50 | A vendor carries `review_status`, as a catalog entry does. | P-14 marks a vendor that an import created as unreviewed, and there was nowhere to keep the mark. | 0.3.0 |
| P-57 | `make package-test` takes a backup before it imports `examples/` and restores it afterwards, with `hirdir admin backup` and `hirdir admin restore`. | S12 imports into an inventory that does not hold the examples, the checks that follow make records of the same names by hand, and nothing can be deleted. | 0.3.0 |
| P-58 | `/var/lib/hirdir/backups` is made with mode 0750, by postinst at install and at each upgrade and by `hirdir admin backup` when it is not there. | Its mode otherwise depended on the umask of whoever took the first backup. | 0.3.0 |
| P-19 | Regular expressions use a linear-time engine when its binding has a production release for the Python in use, otherwise a time-limited one. | Which one is available changes with the Python version, and the dependency rule decides. | 0.2.0, with the time-limited `regex` package: RE2's own binding, `google-re2`, has no release for Python 3.15 |

## Open

| ID | Question | Needed by |
|---|---|---|
| O-01 | Which monitoring system is integrated first, and does `hirdir` send to it or read from it? | after 1.0.0 |
