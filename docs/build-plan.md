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
| **0.4.0** Structure | Minor items and inheritance from the parent. Device groups: stacks, clusters, controller domains, nesting, dated membership. Replacing an item, with its place in a group. Networks and addresses, and the duplicates report. Component count, managed-node count and support weight with the stack discount. Summary report. | S18–S23 |
| **0.5.0** Places and people | Regions, sites, locations and paths. Contacts, assignments and inherited resolution. Shipping address inheritance. Owners and external-owner exceptions. Geography tree with roll-up totals. Moving a site. | S24–S28 |
| **0.6.0** Money, time and capacity | Support agreements, the contracts grouped into them, and dated coverage; a contract renewed in one place. Estimated value and annual support cost. The vendor portfolio. End-of-life and coverage reports. Replacements in reports and in files. Purchase requests, lines and receiving. External systems and registrations. Draft records. Capacity lines and the capacity report. | S29–S35, S39–S40 |
| **0.6.1** Corrections to 0.6.0 | What a contract overrides, said beside what it has in force. The dates of an earlier term of a contract that is co-termed with its agreement. The model of an item that is put on a purchase line, held to the line's. The contract that still counts an item out of service, as a field of the item list. Browser scenarios for the pages of 0.6.0 that only unit tests hold. `make upgrade` without a step the host refuses. The speed of the item filters of 0.6.0 on a large inventory, measured. | none new |
| **0.7.0** Renewals in practice, and links | The renewal worklist. An agreement renewed with new numbers for its member contracts, and a contract's history across joining and leaving one. The coverage report worked out once and kept until it changes. A renewal alert after sign-in. Settings with defaults in place of constants, and a configuration file written by the application. Imports applied in the background, in batches. A model or a device flagged as not to be renewed. Purchase lines as procurement has them. The contacts of an agreement and of a contract, linked to contact records. Capacity over time: a weekly record of the balance, a line that multiplies staff capacity, and the demand of each region beside the balance of the whole. Links, an address with its text, on regions, sites, locations and catalog entries. | S41–S46 |
| **0.8.0** Circuits | Telecommunication circuits beside the inventory: its name, description and notes, the enterprise's own circuit ID, the devices it connects, its A side and Z side, its carriers and the circuit numbers they give, billing, support and escalation contacts, the site contacts of both sides, monthly recurring cost by line, and its owner. In the API, the command line, files and the web UI, with a report of the cost by year, as support costs are reported. An optional support weight of a region, a site or a location, which the capacity report counts as demand (P-139). | S47–S50 |
| **0.9.0** Reference files | Files attached to a location: photographs, maps, sketches and floor plans. Documents attached to a catalog entry and reached from every item of that model, such as an administration guide, served by `hirdir` itself where there is no internet access. Upload, link, download, limits, roles, audit, and the files in the backup. | S51–S53 |
| **1.0.0** MVP | Timing at 50,000 items and fixes from it. Backup timer and restore. Upgrade test from every earlier release. Accessibility pass. Complete user and operator documentation. | S36–S38, and all earlier |

After the MVP, in the order currently expected: RADIUS sign-in; access-code rules; SAML;
discovery observations and reconciliation; the observed status of items and groups
written by monitoring tools, which until then is set by hand or by an import (D-92);
outward change feed and host lists for monitoring tools; planning views for draft sites and items; cell-range selection and
editing in the grid; PostgreSQL; a container image.

A release whose last number is not zero carries corrections to the one before it and
adds no scenario. One that is planned ahead has a row, as 0.6.1 has; the others came
between two rows as their releases were answered. 0.2.1 followed 0.2.0 with the answers to its proposals: one time zone
for everybody, support weight to two places, and a skipped upgrade test that says so.
0.4.1 follows 0.4.0 with the answers to its proposals, a stack that may be its master
alone among them, and with the condition of an item, what is observed of it, and the
health that follows for an item and for a stack (D-92). 0.4.2 follows 0.4.1 with the
answers to what its review found unsaid: a time that names no zone is in the
application's time zone, where it is entered and where it is filtered by (D-109,
D-110).

## From 0.6.1 to 0.9.0

What each release between 0.6.0 and the MVP is for (D-157). The requirements, the data
model and the interfaces of each are written when it is started, in the contract lane,
and what they leave to be chosen goes to [decisions.md](decisions.md) as proposals then.
What is listed here is what the release must do, not yet how.

### 0.6.1, corrections to 0.6.0

What 0.6.0 left undone, and what its two reviews and its first run in a browser
showed. It adds no scenario and no kind of record.

- A contract says, for each field it has from its agreement or overrides, what the
  agreement would give: the web UI no longer reads the agreement to show an override.
- An earlier term of a contract that took its dates from its agreement shows the
  dates it had, and not blanks.
- An item that is put on a purchase line, by hand or by a file, is of the line's
  model, or the answer says that it is not.
- The contract that still counts an item which is out of service is a field of the
  item list, to sort, filter and export by. The page works it out for itself today.
- Browser scenarios for what only unit tests hold: renewing an agreement, the marks
  of a lapsed contract and of a renewal that is pending, removing a coverage and
  telling the vendor for several at once, opening a coverage again, covering more
  than a thousand items, and the answer to an edit that went stale when a term began.
- `make upgrade` moves every dependency without the step that the host's permissions
  refuse.
- The item filters that 0.6.0 added, how many contracts cover an item and what is
  out of service and still counted among them, are timed on a large inventory. What
  is slow is put right here where that is small, and otherwise goes to the timing of
  1.0.0 with the numbers.

### 0.7.0, renewals in practice, and links

- **The renewal worklist.** One page, one report and one command for what a person
  must act on: the contracts that end within a horizon, those that have lapsed,
  those whose renewal is pending and for how long, and the items that more than one
  contract covers, each under its vendor and its agreement, and each count leading
  to its rows. Its horizon is the site's warning period, 90 days unless changed, and a
  renewal pending for longer than 60 days, unless changed, is flagged as overdue
  (P-125).
- **A renewal alert after sign-in.** A person with the Inventory or the Admin role is
  shown, once until something new comes onto it, how many contracts have lapsed, are
  pending renewal, or end within the warning period, each leading to the worklist.
  The coverage report's count of lapsed contracts follows its filter (P-117).
- **An agreement renewed with its members.** Where the contracts of an agreement share
  its period, renewing the agreement gives each member contract its new number in the
  same change, as a replacement of the old numbers by new ones, each waiting as the
  member's next term and beginning with the agreement's new term. An earlier term of a
  contract that joined or left the agreement partway through is dated by the days it
  was a member (D-164).
- **Not to be renewed.** A model, or a single device, is flagged as one whose coverage
  is not renewed, such as an access point or a telephone whose support came with its
  purchase; a device inherits the flag from its model and may override it. A renewal
  leaves it behind, its lack of cover is no gap, and a list and a count by model show
  what is left out on purpose (P-118). Until then an item is left out by ending its
  coverage on an earlier day (D-156).
- **Contacts of an agreement and of a contract.** The account managers and the support
  contacts, any number of each, may be contact records, as the contacts of a place are
  since 0.5.0, and are inherited from the agreement as the text is. Free text stays
  possible (P-119).
- **The coverage report at speed.** Counted in one pass, what is in force for each
  contract worked out once for a request, and the answer kept until a change or the
  turn of the day makes it stale (P-115). The coverage filters of the grid gain from
  the same work.
- **Imports in the background.** Applying a file is a job that shows its progress and
  applies a few dozen rows at a time, so that sign-ins and other changes go on beside
  it; one that fails partway says what was applied and is resumed (P-116).
- **Purchase requests as procurement has them.** A line's model is corrected at any
  time, and the items that arrived on it with it when the operator says so (P-120). A
  line that is not network equipment, cable ties or a printer, is not tracked, keeps
  the part number procurement gave it, and does not hold the request open; a file of
  a request's lines matches each part number to the catalog and makes no catalog entry
  (P-121).
- **Settings rather than constants.** Every value of a business rule held in the code
  that a site could reasonably want otherwise becomes a setting with a default built
  in, and one that protects the service is said to be fixed. A command writes a
  complete configuration file from the application, every key with its default and a
  description, and the settings of the inventory are listed with their defaults and
  returned to them by one change (P-126).
- **Capacity over time.** A record of the balance each week, to show the trend as a
  graph, taken by the server each Monday and again by hand, with a week's figures
  correctable (R14.7). A line that multiplies the capacity of chosen staff lines, for
  tools and services that make people more effective (R14.8). The report stays one
  balance for the whole operations team, whose tools and services are shared by
  every region, and shows beside it how the demand splits by region; the report for
  one region or one site, which D-147 left until the report of the whole had been
  used, is not built (P-137).
- **Links.** A location and a catalog entry take one link or more, each an address
  and the text to show for it: the web page of a site, the data sheet of a model.
  They are optional, are shown where the record is shown, an item shows those of its
  model, and they travel in files. A site and a region take them too (P-138).

### 0.8.0, circuits

Beside the circuits, 0.8.0 gives a region, a site and a location an optional support
weight of its own, which is not inherited by the places beneath and is added to the
demand of the capacity report (P-139).

A first way to track telecommunication circuits beside the device inventory. A
circuit is a record of its own, referenced by HID, audited, role-checked, retired and
never deleted, and may be a draft, as every record is. It holds:

- a name, a description and notes;
- the enterprise's own circuit ID, assigned locally, as an item has an asset tag
  beside its serial number. Every circuit can have one, also one that no carrier
  numbers: dark fiber between two buildings that a business partner lets the
  enterprise use has no carrier's circuit number, and is still a circuit to track.
  It is unique where it is given, as an asset tag is;
- the device or devices it connects, matched from the inventory, and shown on each
  of them;
- its A side, the source, and its Z side, the destination, each a location;
- its primary carrier, or the other party that provides it, and any number of
  additional carriers, each with its part: a local exchange carrier, the provider
  of a cross-connect in a co-location, and the like;
- the circuit numbers the carriers give it, one for each carrier that gives one,
  and none where none is given;
- the billing account number and the reference of the billing contract;
- the number and the address of technical support;
- the contacts of the carrier's account team, for escalation;
- the site contacts of the A side and of the Z side, which follow from the two
  locations as 0.5.0 resolves them, with any that are the circuit's own;
- its monthly recurring cost, as lines that add up, which is how a carrier bills
  it, and its annual cost, twelve times that, worked out when it is read;
- its owner, and what every record has: status, dates, notes and tags.

Circuits are listed, filtered, sorted and exported as items are, and load from
files, where a row finds its circuit by the enterprise's circuit ID. The report of
their cost is by year, by carrier and by site, with the monthly figure beside it:
support agreements, renewals and support costs are tracked as annual numbers, and
the cost of circuits is read beside them in the same terms. What is not in scope
stays so: cabling inside a building, the interfaces of a device, and the accounting
of what was paid.

### 0.9.0, reference files

Optional reference material, kept with the record it is about.

- **For a location:** photographs of the site, maps, sketches and floor plans.
- **For a catalog entry:** the documents of a vendor or a manufacturer for that
  model, an administration guide for one, reached from every item of the model. On
  a closed network with no internet access the link of 0.7.0 leads nowhere, so the
  file itself is kept and served by `hirdir`.
- A reference is a file that is uploaded, or a link to one that is kept elsewhere:
  both are listed together, with a title and what kind of thing each is.
- Limits on size and on the kinds of file, role checks on every upload, download
  and removal, an audit event for each, and no file is served in a way that lets
  it run in the browser as part of the application.
- The files are in the backup and come back with a restore, and an upgrade leaves
  them as they were.

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
| S15 | Preview an import, change the record of one of its rows in the web UI, then apply | That row is not applied and is reported as changed since the preview; every other row is applied. Until 0.7.0: nothing is applied and a new preview is asked for |
| S16 | Filter the grid, select rows, copy, and export CSV and JSON from the UI and the CLI with the same filter | Clipboard, both exports and the CLI output hold the same rows and columns, each with `hid` |
| S17 | Two people bulk-edit overlapping rows | The second is shown the conflict and nothing of theirs overwrites the first |
| S18 | Add two power supplies and a module to a switch; give the switch another owner and move it to Prod. From 0.5.0, also move it to another location | The minor items show the new owner and the new state with source `parent_item`, and from 0.5.0 the new location; the component count rose by one, not four |
| S19 | Build a stack of four switches with one marked as the intended master; then record another member as the master that is seen | The stack shows the intended master's serial number, then the observed one's, at once; it is found by the serial number of any member |
| S20 | Take the same stack with a global discount of 50, then set 30 on its model | Weight is 2.0, then 2.8; component count 4 and managed-node count 1 throughout; annual support cost is four times one switch |
| S21 | Replace the stack's master for an RMA | Two item records linked by a replacement; the departed switch's membership has an end date; the stack's HID is unchanged |
| S22 | A controller domain: a cluster of two controllers and forty access points | Forty-two components; the cluster is one managed node; each access point lists its controllers |
| S23 | The same address under networks Red and Black, then twice under Red | All are accepted; only the pair under Red is in the duplicates report |
| S24 | Create `Americas > Central`, Site-2, Building 1 and Room 102 within it | Paths and roll-up counts are right at every level |
| S25 | A technical contact on Americas, a shipping contact on Site-2 | Room 102 shows both, each with the level it came from |
| S26 | Override the technical contact on Building 1, then change the one on Americas | Room 102 keeps Building 1's; a room in another building shows the new one |
| S27 | Move Site-2 to another region | Paths, inherited contacts and roll-ups change; item HIDs do not; the move is one audit event |
| S28 | Make an owner outside the team with no reason, then with one, and give it an item | Refused, then accepted, and the item is marked as an exception with the owner's reason |
| S29 | One contract covering items in two regions, one of them archived | The archived item's coverage ended on the day it was archived, and the coverage report lists it as out of service under a contract that still runs |
| S30 | An item in Prod with no coverage; an item whose model's LDoS is next year | Each is on its report |
| S31 | A vendor with switches, a virtual machine template, a software application and a service | The portfolio lists all four kinds with cost and weight totals, and exports |
| S32 | A purchase request with a line of ten switches | Not in the component count; receiving six creates six Delivered items linked to the line, four still pending; the other four, received as a count, are named for the line, and the request is then received |
| S33 | Register a stack with a monitoring system and an SDN controller | Both registrations are on the stack, not on its members, each of which says what its stack is registered with |
| S34 | Create a draft site with draft items | Left out of every count until made active |
| S35 | Archive an item | Hidden by default, greyed when included, still reachable by HID, history intact |
| S36 | `make fixture`, then page, sort and filter the item grid | Each request is within the response target in [requirements.md](requirements.md) |
| S37 | Back up, install on a clean container, restore | Counts, history and audit events match |
| S38 | Install the first release, load the examples, upgrade through each release in turn | Every migration applies and the summary is unchanged |
| S39 | Enter the lines of the worked example in [data-model.md](data-model.md) against a seeded support weight of 2,400 | Demand 10.0, supply 9.0 by category, balance −1.0, coverage 90% |
| S40 | Add the draft services line, then set an end date in the past on the professional services line | With drafts the balance is zero; the ended line drops out of supply in both views |
| S41 | Under one agreement: a contract that ends next month, one that has lapsed, one whose renewal has been pending for longer than the overdue period, and an item under two contracts; then sign in as Inventory | The renewal worklist lists each under its vendor and agreement, the pending one as overdue, and each count leads to its rows; the alert after sign-in counts them, is not shown again that day once it is dismissed, also when another contract lapses, and is shown again the next day |
| S42 | Two items of one model and one of another under one contract; flag the first model as not to be renewed, give one of its two items its own flag of false, then renew the contract | The flagged item's coverage ends with the old term and the other two follow into the new one; once its cover has ended, the flagged item is on no list of what is uncovered and is counted as not to be renewed |
| S43 | The account manager of an agreement is a contact record; one contract in it names another | Each contract shows the contact in force with its source, and a change of the agreement's contact's telephone number shows on the agreement and on the contract that has it from there |
| S44 | Record the capacity balance in one week and again in the next, with a line added between them; correct the figures of the first week; then add a line that multiplies two staff lines | The trend shows both weeks, the first marked as corrected; the supply of the two staff lines is multiplied and no other is |
| S45 | Capacity lines and items in two regions | The report is one balance for the whole team; beside it each region's share of the support weight, which with what is nowhere adds up to the whole, and no supply is divided |
| S46 | Give a location two links, a site one and a catalog entry one, each an address and its text | Each shows on its record, an item shows the link of its model, a file carries them out and back unchanged, and an address that is no web address is refused |
| S47 | Enter a circuit between two locations with a name, an enterprise circuit ID, a primary carrier, a local exchange carrier, a circuit number for each, and a router at each end; then a dark fiber between two buildings that has an enterprise circuit ID and no carrier's number | The first shows both sides, both carriers and both devices, and each router and each location shows it; the second is accepted, is found by its enterprise circuit ID, and that ID is refused for another circuit |
| S48 | Give the circuit three monthly cost lines; enter a second circuit of the same carrier | The monthly cost of each is the sum of its lines and its annual cost twelve times that; the report totals the annual cost of both by carrier and by site, with the monthly figure beside it |
| S49 | The A side's site has a site contact; the circuit has a carrier account manager | The circuit shows the site contacts of each side, resolved from its locations with their source, and the carrier's escalation contacts |
| S50 | Export the circuits to a file, load it into an empty inventory, and load it again | Every circuit is created with its sides, carriers, numbers and cost lines, and the second load changes nothing |
| S51 | Upload a photograph and a floor plan to a location, and download each | Each is listed with its title and kind, comes back byte for byte, and a View-only user downloads and cannot upload |
| S52 | Upload an administration guide to a catalog entry | Every item of that model reaches it, with no request leaving the server |
| S53 | Upload a file over the limit and one of a kind that is not allowed; then back up, restore on a clean install | Both uploads are refused with the reason; the restored inventory has every file, byte for byte |

## Definition of done

For a task:

- the behaviour is in the documentation and the contract, and matches them;
- it has tests at the level where it can fail, and they pass;
- `make check` is clean, with no ignored rule added to make it so;
- every write path it adds is audited and role-checked on the server;
- no example or fixture holds anything real.

For a release, add: its scenarios pass, `make package-test` passes including the
upgrade, and its notes are written from `make facts`.
