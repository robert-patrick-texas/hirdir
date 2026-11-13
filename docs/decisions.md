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
| D-46 | A time is shown to a person in local time, with the name of its zone: the reader's own zone where it is known, otherwise the installation's `time_zone` setting, which is America/New_York unless changed. A time is not shown in UTC. Storage and the API keep UTC. |
| D-47 | The backup taken before an upgrade is one of the rotating backups, and is removed on the same schedule as the others. |
| D-48 | Using `hirdir` should be easy and without waiting. Where a delay can be avoided or hidden, real or perceived, it is: the web UI loads only what a page needs, fetches the rest ahead of need, and a browser keeps what does not change. |

## Proposed

Each of these is the working answer. P-01 to P-04,
P-20, P-22, P-23 and P-24 were confirmed and are now D-33 to D-36 and D-40 to D-43.

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
| P-19 | Regular expressions use a linear-time engine when its binding has a production release for the Python in use, otherwise a time-limited one. | Which one is available changes with the Python version, and the dependency rule decides. | 0.2.0, with the time-limited `regex` package: RE2's own binding, `google-re2`, has no release for Python 3.15 |
| P-25 | The owner record arrives in 0.2.0 with its label, organization and external flag. Its people, and the exception recorded when an item is given to an owner outside the team, stay in 0.5.0. | S08 gives an item an owner, and an owner is a record, not free text. | 0.2.0 |
| P-26 | Lifecycle state, disposition and expected-online may all be blank on an item. Once an item has a state, the other two follow the rules table. An item with no state is in no count. | S08 creates an item from a vendor, PID, serial number and owner alone, and blanks are normal. | 0.2.0 |
| P-27 | On a move the item keeps its disposition when the new state allows it, and takes the state's "set on entry" value when it does not. The caller may name the disposition and the intent instead. | A spare that comes back from Down would otherwise become Production without anyone saying so. | 0.2.0 |
| P-28 | A lifecycle move or combination that the rules refuse is a `422` that names the field. | The API keeps `409` for a stale version and for uniqueness. | 0.2.0 |
| P-29 | `session_hours` stays in the configuration file and is not a setting in the database. | It was built there in 0.1.0 and is needed before any setting can be read. Two homes for one value would disagree. | 0.2.0 |
| P-30 | Every text comparison in a filter ignores case, regular expressions included. A regular expression matches anywhere in the value unless it is anchored. `ne` also finds blanks. | Host names and product IDs are written in mixed case, and "not Prod" is expected to include an item with no state. | 0.2.0 |
| P-31 | A list leaves out drafts, retired records and items in Archived unless `include_drafts` or `include_archived` asks for them. The `fields` parameter of a list arrives with export, and `Idempotency-Key` with import, both in 0.3.0. | The default view was described and its parameters were not named. Neither of the other two is needed before files exist. | 0.2.0 |
| P-32 | The server's tests use `httpx2`, the continuation of `httpx` under Pydantic that the test client now asks for. The CLI stays on `httpx` until the client CLI is built in 0.3.0, and moves then. | `httpx` has had no production release since 0.28.1. Changing what the package ships is a separate step from changing a test dependency. | 0.2.0 for the tests, 0.3.0 for the CLI |
| P-33 | A decimal travels as text in JSON. Money has two places, support weight three and a percentage two. | A JSON number is not exact in a browser, and a sum of weights must be. | 0.2.0 |
| P-35 | An item that is first entered in Down or Pending-Removal, and so has no disposition "from before", may be given any. Once it has one, that is the one it keeps. | An existing inventory has devices that are down today, and an item in hand is for something (R4.2). | 0.2.0 |
| P-36 | A regular expression is also bounded before it is compiled: its counted repeats, multiplied together, may come to at most 100. In the short form of a filter, a value that itself looks like `field:word:` is refused. | A seventeen-character pattern can take gigabytes to compile, which no time limit on matching catches. A mistyped operator would otherwise become part of a value and quietly find nothing. | 0.2.0 |
| P-37 | `make package-test` upgrades from the previous release's package: `PREVIOUS_DEB` when set, otherwise the highest version below the one under test in `dist/`. Once an earlier release exists, a missing package is a failure, and `--fresh` is the way to ask for the fresh install alone. | The build plan makes the upgrade part of a release's definition of done, and a skipped check that passes is not a check. | 0.2.0 |
| P-38 | The migrations of one upgrade run in one transaction. After a failed upgrade the way back is the backup, on the version installed before, and the package prints the commands. | A half-migrated database can be neither used nor migrated again. Restoring the backup works whatever went wrong. | 0.2.0 |
| P-39 | The Admin area of the web UI is shown to every role. Tags, choices and lifecycle rules are in it for all to read, and for Inventory to edit the first two. Users, groups, roles and settings show to an Admin only. | The roles table lets Inventory edit tags and choices, and the page table had put them where only an Admin could reach. | 0.2.0 |
| P-40 | A browser or a machine whose clock is set to UTC is taken as not saying where its reader is, and the installation's zone is used. The names of backup files keep their UTC stamp, marked `Z`. | D-46 asks for local time and never UTC, and a server's clock is on UTC by habit, not because its reader is. A file name must sort in order and not repeat when the clocks go back. | 0.2.0 |
| P-34 | `lifecycle_rules` has one row for each state: the dispositions it allows, which of them may and must be online, what is set on entry, and the states an item may move to. The nine states themselves cannot be added to or removed, and no row may make Excess online (D-26). | D-33 fixes the states, and R4.3 asks for the rest as data. | 0.2.0 |

## Open

| ID | Question | Needed by |
|---|---|---|
| O-01 | Which monitoring system is integrated first, and does `hirdir` send to it or read from it? | after 1.0.0 |
