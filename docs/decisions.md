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

## Proposed

Each of these is the working answer. One marked **confirm** changes behaviour that
people will notice, and deserves a look before the release that builds it. P-01 to P-04,
P-20 and P-22 were confirmed and are now D-33 to D-36, D-40 and D-41.

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
| P-23 **confirm** | Units per position are fixed numbers. Seniority is handled by a separate staff line per level, each with its own units, with one mid-level position as 1.0 by convention. | It needs nothing beyond what 0.6.0 already builds, and the numbers stay visible and easy to argue with. | 0.6.0 |
| P-24 **confirm** | A tool or service that makes people more effective is, for now, a supply line with its estimated gain. After the MVP it may be a multiplier line on chosen staff lines, computed as in [data-model.md](data-model.md): on base units, with a share of positions using it, not compounding. A tool that takes work to run is an inventory item whose support weight is already demand. | A multiplier ties the gain to the people it amplifies, which matters when the question is how many positions. It also needs calibration that only experience with the fixed numbers will give. | after 1.0.0 |
| P-19 | Regular expressions use a linear-time engine when its binding has a production release for the Python in use, otherwise a time-limited one. | Which one is available changes with the Python version, and the dependency rule decides. | 0.2.0 |

## Open

| ID | Question | Needed by |
|---|---|---|
| O-01 | Which monitoring system is integrated first, and does `hirdir` send to it or read from it? | after 1.0.0 |
| O-05 | How much support weight does one resource unit, a mid-level position, carry? It is one setting, changeable at any time; the example uses 300 as a placeholder. | 0.6.0 |
