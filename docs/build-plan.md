# Build plan

The order of work, written so that several agents can build at once and every release
is something that installs and runs.

## How the work is divided

Each release is a thin slice through the whole product. Within a release there are four
lanes that touch different directories and meet at one contract:

| Lane | Owns | Starts from |
|---|---|---|
| **Contract** | the OpenAPI document, the JSON Schemas of the import envelope and the filter, `examples/` | this documentation |
| **Server** | `src/hirdir/` except `cli/`, `tests/unit`, `tests/api` | the contract |
| **Client** | `web/`, `src/hirdir/cli/`, `tests/e2e` | the contract, against a mock generated from it |
| **Ship** | `packaging/`, `scripts/`, `Makefile`, `docs/`, `.github/` | the previous release |

The contract lane goes first and is small. Server and client then run in parallel. Ship
runs throughout. A release is done when `make check`, `make package-test` and that
release's acceptance scenarios pass, and its notes are written.

A change to a field name, a route or a rule is made in the documentation and the
contract first, then in code. An agent that finds the documentation wrong or silent
proposes the change in [decisions.md](decisions.md) and carries on with the safest
reading; it does not settle a policy question in code.

## Releases

| Release | Slice | Scenarios |
|---|---|---|
| **0.1.0** Skeleton | Repository scaffold and Makefile. Health routes. SQLite, migrations. Users, groups, role grants, sign-in, session and service tokens, throttling, audit of sign-ins. Web shell with sign-in and an Admin page for accounts. `hirdir admin`. The `.deb`, `hirdir-setup`, the prefix, `make package-test`. Documentation build and its workflow. `make facts` and the first release notes. | S01–S05 |
| **0.2.0** Items | Vendors, catalog entries, items, tags, choices, settings. Inheritance from the catalog with sources. Lifecycle state, disposition, expected-online and the rules table. Audit of every change, item history. The grid with server sorting, filtering and paging; item detail and edit; stale-edit refusal. Filter grammar including bounded regex. | S06–S11 |
| **0.3.0** Files and CLI | CSV and JSON import with preview and apply, export, clipboard copy, `examples/` generated from the seed. The client CLI. Bulk edit with preview. | S12–S17 |
| **0.4.0** Structure | Minor items and inheritance from the parent. Device groups: stacks, clusters, controller domains, nesting, dated membership. Networks and addresses. Component count, managed-node count and support weight with the stack discount. Summary report. | S18–S23 |
| **0.5.0** Places and people | Regions, sites, locations and paths. Contacts, assignments and inherited resolution. Shipping address inheritance. Owners and external-owner exceptions. Geography tree with roll-up totals. Moving a site. | S24–S28 |
| **0.6.0** Money, time and capacity | Contracts and dated coverage. Estimated value and annual support cost. The vendor portfolio. End-of-life and coverage reports. Replacements. Purchase requests, lines and receiving. External systems and registrations. Draft records. Capacity lines and the capacity report. | S29–S35, S39–S40 |
| **1.0.0** MVP | Timing at 50,000 items and fixes from it. Backup timer and restore. Upgrade test from every earlier release. Accessibility pass. Complete user and operator documentation. | S36–S38, and all earlier |

After the MVP, in the order currently expected: RADIUS sign-in; access-code rules; SAML;
discovery observations and reconciliation; outward change feed and host lists for
monitoring tools; planning views for draft sites and items; cell-range selection and
editing in the grid; PostgreSQL; a container image.

## Acceptance scenarios

Each scenario is one automated test in `tests/acceptance/`, named by its number, run by
`make acceptance` against a server started from an empty database. A scenario is
written as a failing test at the start of its release.

| ID | Scenario | Passes when |
|---|---|---|
| S01 | Install the package in a clean container and run `hirdir-setup --self-signed --prefix /hirdir` | The health probe answers through nginx under the prefix |
| S02 | Create the first Admin with `hirdir admin`, sign in on the web page | A session token is in `localStorage`; no response in the whole run set a cookie |
| S03 | A user in a View-only group is also granted Admin directly | The user can create an account; with the direct grant removed, the next request is refused without signing in again |
| S04 | An Admin resets a user's access code while that user is signed in | The user's existing token is refused; a new sign-in works |
| S05 | Six wrong access codes in a row | The sixth is delayed, and each failure is an audit event |
| S06 | Create a catalog entry with value, weight and LDoS; create two items of it; override the value on one | One item shows the catalog value with source `catalog`, the other its own with source `own` |
| S07 | Change the LDoS date on the catalog entry | Both items show the new date; neither item's `row_version` changed |
| S08 | Create an item with only vendor, PID, serial number and owner | Accepted; every other field is blank |
| S09 | Create a second item with the same vendor, PID and serial number; a second with the same MAC address | The first is refused with `409`; the second is accepted |
| S10 | Move an item Delivered → Assigned → Test → Prod, set it to Spare and offline, then try Excess and online | Each move is in the history with who and why; the last is refused |
| S11 | Filter the grid by state, a PID glob, a hostname regex and a tag; then send a pattern that is too long | The right rows; the bad pattern is a `422` and the server stays responsive |
| S12 | Import `examples/` in load order into an empty database | Every row is created; the summary counts match the seed |
| S13 | Import the same files again | Every row is `unchanged` |
| S14 | Import a CSV with one blank cell, one `!clear` cell and one unknown vendor and PID | The blank leaves the value, `!clear` returns the field to inheriting, the catalog entry is created `unreviewed` |
| S15 | Preview an import, change one of its rows in the web UI, then apply | Nothing is applied and a new preview is asked for |
| S16 | Filter the grid, select rows, copy, and export CSV and JSON from the UI and the CLI with the same filter | Clipboard, both exports and the CLI output hold the same rows and columns, each with `hid` |
| S17 | Two people bulk-edit overlapping rows | The second is shown the conflict and nothing of theirs overwrites the first |
| S18 | Add two power supplies and a module to a switch; move the switch to another location | The minor items show the new location with source `parent_item`; the component count rose by one, not four |
| S19 | Build a stack of four switches with one master | The stack shows the master's serial number; making another member master changes it at once |
| S20 | Take the same stack with a global discount of 50, then set 30 on its model | Weight is 2.0, then 2.8; component count 4 and managed-node count 1 throughout; annual support cost is four times one switch |
| S21 | Replace the stack's master for an RMA | Two item records linked by a replacement; the departed switch's membership has an end date; the stack's HID is unchanged |
| S22 | A controller domain: a cluster of two controllers and forty access points | Forty-two components; the cluster is one managed node; each access point lists its controllers |
| S23 | The same address under networks Red and Black, then twice under Red | All are accepted; only the pair under Red is in the duplicates report |
| S24 | Create `Americas > Central`, Site-2, Building 1 and Room 102 within it | Paths and roll-up counts are right at every level |
| S25 | A technical contact on Americas, a shipping contact on Site-2 | Room 102 shows both, each with the level it came from |
| S26 | Override the technical contact on Building 1, then change the one on Americas | Room 102 keeps Building 1's; a room in another building shows the new one |
| S27 | Move Site-2 to another region | Paths, inherited contacts and roll-ups change; item HIDs do not; the move is one audit event |
| S28 | Assign an item to an external owner with no reason, then with one | Refused, then accepted and marked as an exception |
| S29 | One contract covering items in two regions, one of them archived | The coverage report lists the archived item as covered but out of service |
| S30 | An item in Prod with no coverage; an item whose model's LDoS is next year | Each is on its report |
| S31 | A vendor with switches, a virtual machine template, a software application and a service | The portfolio lists all four kinds with cost and weight totals, and exports |
| S32 | A purchase request with a line of ten switches | Not in the component count; receiving six creates six Delivered items linked to the line, four still pending |
| S33 | Register a stack with a monitoring system and an SDN controller | Both registrations are on the stack, not on its members |
| S34 | Create a draft site with draft items | Left out of every count until made active |
| S35 | Archive an item | Hidden by default, greyed when included, still reachable by HID, history intact |
| S36 | `make fixture`, then page, sort and filter the item grid | Each request is within the response target in [requirements.md](requirements.md) |
| S37 | Back up, install on a clean container, restore | Counts, history and audit events match |
| S38 | Install the first release, load the examples, upgrade through each release in turn | Every migration applies and the summary is unchanged |
| S39 | Enter the lines of the worked example in [data-model.md](data-model.md) against a seeded support weight of 2,400 | Demand 10.0, supply 9.0 by category, balance −1.0, coverage 90% |
| S40 | Add the draft services line, then set an end date in the past on the professional services line | With drafts the balance is zero; the ended line drops out of supply in both views |

## Definition of done

For a task:

- the behaviour is in the documentation and the contract, and matches them;
- it has tests at the level where it can fail, and they pass;
- `make check` is clean, with no ignored rule added to make it so;
- every write path it adds is audited and role-checked on the server;
- no example or fixture holds anything real.

For a release, add: its scenarios pass, `make package-test` passes including the
upgrade, and its notes are written from `make facts`.
