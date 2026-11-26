# Integrations

`hirdir`, [vakr](https://github.com/robert-patrick-texas/vakr) and
[sunstone](https://github.com/robert-patrick-texas/sunstone) are three projects for one
network operations team. `hirdir` keeps what the team has and what it intends for each
thing. vakr watches the network: interface traffic, reachability and latency, the way MRTG
and SmokePing do. sunstone draws the network: maps, topology, live state, problems,
on-call and the shift handover.

This page says how the three projects move toward one another:
- who owns each fact;
- the keys they share;
- the fields that have the same name and content in each;
- how data moves between them.

It is the one page that describes the three together. Each project's own decisions say
what that project will change, and the [tracking table](#tracking) at the end says where
each change stands.

The owner, on 2026-11-26: "The goal is to shape these projects to move toward one
another to enable integration and move to common approaches where it makes sense,
ultimately toward a common reference keys for a device, a site, an operator. Circuit ID
in all its forms should be shared across each project, carrier/provider circuit ID,
enterprise circuit ID, same fields with same content across the tools/projects."

Everything on this page is proposed unless the tracking table says it is built:
- P-329 to P-341 and O-04 in hirdir's [Decisions](decisions.md#proposed);
- ADR-037 and ADR-038 in vakr;
- SI-01 to SI-10 in sunstone's Decisions.

## Who owns what

Each fact has one owner. Another project holds a copy only where it needs one to work
on its own, and that copy is read-only and carries the owner's key. Otherwise it links
to the owner.

| Fact | Owner | What the others hold |
|---|---|---|
| Regions, sites and locations: names, codes, coordinates, time zone | hirdir | vakr: its sites, read-only. sunstone: regions, sites and locations, generated |
| Devices, stacks and clusters: name, host name, model, serial number, lifecycle, whether each is meant to be online | hirdir | vakr: what it polls. sunstone: what it draws |
| The catalog: vendors and models, and each model's kind, type and function | hirdir | vakr and sunstone: a read-only copy |
| Operators, owners, contacts, and the carriers' account teams and support desks | hirdir | the operator's key and label; a link to hirdir for the rest |
| Circuits: their IDs, carriers, rates, sides, and the carrier networks they reach | hirdir | vakr: on the interface where the circuit lands. sunstone: on the link it draws |
| Interfaces as a device reports them: ifIndex and ifName, MAC address, speed | vakr | not copied. hirdir names a port only where a circuit lands |
| What is seen: reachability from each monitoring position, traffic, errors, history, how fresh each reading is, and the hardware a device reports | vakr | hirdir: the observed fields, kept apart from the record. sunstone: live state |
| Cables and links, layers (VLAN, VNI, VRF), expected neighbours | sunstone, with discovery | hirdir: none for now (see [Cabling](#cabling-if-hirdir-takes-it-later)) |
| Layouts, overrides, priorities, maintenance windows, on-call rotations, incidents, the handover | sunstone | nothing |

A copy cannot be changed where it lands. vakr already refuses, through its web UI, a
change to a record that comes from a file (`409 managed_by_file`). sunstone never writes
its topology file. A change is made in the owner, and reaches the copies from there.

## The common keys

**In every project, a record's key is its HID in hirdir.** An HID is a UUID version 7,
written in lower-case canonical text. hirdir assigns it and never reuses it. A record
carries its own HID as `hid`. A reference to another record is `<name>_hid`, for example
`site_hid`, `operator_hid`, `circuit_hid`, `catalog_entry_hid` or `carrier_hid`.

Each project also keeps its own ID, for its own history: vakr's `id` for a device's
graphs, and sunstone's link IDs for its problems and incidents.

| Key | In hirdir | In vakr and sunstone |
|---|---|---|
| A device | The HID of an item that stands alone, or of a stack or cluster that is managed as one device | `hid` on the device. It names the managed node: a stack is one device, whatever its members |
| A site | The HID of a site, with its `code` and `name` | `hid` on the site, with hirdir's `code` and `name` |
| A location | The HID of a location | `hid` on sunstone's location |
| An operator | The HID of an operator, with its `label` | `operator_hid`, with the label as `operator`, on a device, a site or a circuit |
| A circuit | The HID of a circuit, with its IDs ([below](#circuit-ids-in-all-their-forms)) | `circuit_hid`, with the circuit's block of fields |
| A model | The HID of a catalog entry, with its vendor and PID | `catalog_entry_hid`, with the model's fields ([below](#one-catalog-for-the-three)) |
| A person, a team | The HID of a contact or of an owner | sunstone's on-call people carry `contact_hid`, and its teams `owner_hid` |

**A device is the managed node, and its hardware may change.** When a switch that stands
alone is replaced, hirdir records a new item with a new HID. From then on that new HID is
the `hid` that vakr's and sunstone's device carries. vakr's device keeps its own `id`,
and its history with it, so a replacement changes the device's `hid` but not its graphs.

A stack keeps its own HID when one of its members is replaced, so nothing changes
outside hirdir. hirdir moves a registration that follows the node over to the new item
(P-332).

**Names are for people, and for the first match.** A device's `name` in vakr and sunstone
is hirdir's name in force: its name, or its host name where it has no name. A rename in
hirdir renames it in the others.

Matching by name, host name or address is only for the first time two records are
joined, before either carries the other's key. A match that is not certain is reported,
never guessed. vakr requires its device names to be unique and hirdir does not. When two
hirdir records share a name, neither is sent to vakr until one is renamed, and the
mismatch is reported.

## Shared fields: one name, hirdir's

A field that two projects hold for the same fact has the same name and the same content
in each. The name is hirdir's, and it is used in each project's model, files and API. A
field that only one project has keeps that project's own name.

| Fact | hirdir | vakr now → proposed | sunstone now → proposed |
|---|---|---|---|
| The record's key | `hid` | nothing → `hid` | nothing → `hid` |
| A site's code and name | `code`, `name` | `code`, `name` | `code`, `name` |
| A site's region | its region, by name and path | `region` (free text) → `region`, hirdir's name for it | `region` → `region` |
| A site's coordinates | `latitude`, `longitude` | none | `lat`, `lon` (required) → `latitude`, `longitude` (optional) |
| A site's time zone | `time_zone` (P-339) | `timezone` → `time_zone` | nothing → `time_zone` |
| A device's name, host name and FQDN | `name`, `hostname`, `fqdn` | `name` → `name`, and adds `hostname` and `fqdn` | `name` → `name` |
| A device's site | the site of its location | `site` (by name) → `site_hid` | `site` (by code) → `site_hid` |
| A device's operator | `operator_hid` and its label | nothing → `operator_hid`, `operator` | nothing → `operator_hid`, `operator` |
| A device's model | `catalog_entry_hid`, vendor, `pid`, `model_name`, `kind`, `type`, `function` | nothing → the same | `platform` → the same, keeping `platform` as sunstone's own label |
| A device's management address | its primary address of the role `management` | `address`, what vakr polls (vakr's own field), filled from it | `mgmt_ip`, shown (sunstone's own field), filled from it |
| A circuit | [below](#circuit-ids-in-all-their-forms) | [below](#circuit-ids-in-all-their-forms) | [below](#circuit-ids-in-all-their-forms) |

Times that pass between the projects are written in ISO 8601, in UTC, ending in `Z`. A
blank means nothing is known. It is never read as zero, and never as down.

## Circuit IDs in all their forms

A circuit has the same block of fields in all three projects, under hirdir's names.

| Field | What it holds |
|---|---|
| `circuit_hid` | the circuit's HID |
| `name` | hirdir's name for the circuit |
| `enterprise_circuit_id` | the enterprise's own ID for it: one value for the whole circuit |
| `circuit_type` | from hirdir's list: `internet`, `mpls`, `point_to_point`, `dark_fiber`, `wavelength`, `voice`, `other` |
| `carrier`, `carrier_hid` | the primary carrier, by its vendor's name and HID |
| `carrier_circuit_id` | the ID the primary carrier gives the circuit, as the carrier writes it (P-340) |
| `carriers` | each of the other carriers: `carrier`, `carrier_hid`, `role` (`local_exchange`, `cross_connect`, `last_mile`, `other`), `side` (`a`, `z`, or blank for the whole circuit; P-338) and `carrier_circuit_id` |
| `port_mbps`, `down_mbps`, `up_mbps` | the speed of the port, and the download and upload rates the circuit is limited to, in Mbps. A blank rate means the port's speed |
| `side` | on vakr's interface and on sunstone's link end: whether this device is on the `a` or `z` side of the circuit |
| `interface` | the port where the circuit lands (P-330) |

What each project changes:
- **hirdir.** `carrier_circuit_number` becomes `carrier_circuit_id`, and so does the
  other carriers' `circuit_number` (P-340). It is an ID, not a number to count with.
  `enterprise_circuit_id` stays a single value for the whole circuit, as the owner
  confirmed on 2026-11-26.
- **vakr.** `provider` becomes `carrier`. `circuit_id` becomes `carrier_circuit_id`.
  `contracted_bps` becomes `down_mbps` and `up_mbps`, in Mbps as hirdir writes them.
  `circuit_hid`, `enterprise_circuit_id`, `carriers`, `circuit_type`, `port_mbps` and
  `side` are added. `capacity_override_bps` stays, as vakr's own. The filter `provider`
  becomes `carrier`.
- **sunstone.** `enterprise_cid`, which holds a value for each side, becomes the single
  `enterprise_circuit_id`. `circuit.provider` becomes `carrier`. `circuit.circuit_id`,
  which also holds a value for each side, becomes `carrier_circuit_id`, and an ID
  that belongs to one side alone goes in `carriers`, with its `side`. `circuit_hid`,
  `circuit_type` and the rates are added. `type` (`carrier`, `cross-connect`), `service`
  and `technology` stay sunstone's own until hirdir holds them.
- **sunstone references.** A resource's `circuits` name a circuit by its
  `enterprise_circuit_id`, as they do now, or by its `circuit_hid`. On-call's
  `carriers[].provider` becomes `carrier`.

**Which way is down** (P-330). `down_mbps` is the rate toward the A side, and `up_mbps`
the rate away from it. vakr compares an interface's incoming traffic with `down_mbps`
when the interface is on the A side, and with `up_mbps` when it is on the Z side.
Outgoing traffic is compared the other way round. A circuit with no rates of its own
runs at the port's speed both ways.

## One catalog for the three

hirdir's catalog has vendors and catalog entries.
- A **vendor** has its `name`, its `aliases`, and its `enterprise_number` (P-337).
- A **catalog entry** has its vendor, `pid`, `pid_aliases`, `model_name`, `kind`,
  `type`, `function` and `sys_object_ids` (P-337).

vakr and sunstone each keep a read-only copy, read from `GET /vendors`,
`GET /catalog-entries` and `GET /choices`. The lists of types and functions are read
from `GET /choices`, because a site may change them, so neither project hard-codes them.

**How a model is recognized.** vakr takes the model name that the chassis reports in
ENTITY-MIB (`entPhysicalModelName`) and looks for a catalog entry of that vendor with
that PID or one of its aliases. Failing that, it looks for the device's `sysObjectID`
among the entries' `sys_object_ids`. The vendor is found from the enterprise arc of the
`sysObjectID`: `1.3.6.1.4.1.`, then the vendor's `enterprise_number`.

A model that matches neither is reported to hirdir as the vendor and PID that were
seen. hirdir shows them beside the record. The catalog gains the model only when a
person adds it.

**Device type stays matched.** A device carries its `catalog_entry_hid`, and hirdir's
`kind`, `type` and `function` with it.
- sunstone's `role` (`wan-edge`, `core`, `distribution`, `access`) places a device in a
  row of its hierarchy view. It is worked out from hirdir's `function` by a table in
  sunstone's settings, and `sunstone check` names any function the table does not map.
- vakr's collection policies and object sets match on the same fields
  ([below](#observed-hardware-and-what-vakr-polls-by-model)).

**What a tool sees is compared, never written.** vakr's observed model is shown beside
hirdir's intended model, and a difference is marked in both projects. hirdir keeps the
observed model apart from the record (P-336).

## Stacks and clusters in each project

| In hirdir | In vakr | In sunstone |
|---|---|---|
| A **stack** | One device, with the stack's `hid`, name and address, `form` `stack` and `expected_members`. The members are entries within that device: switch number, role, state, serial number and model, read by the stack's object set. The active switch it sees becomes hirdir's observed master | One node, named for the stack. Its panel lists the members, with switch number, role, serial number and state. It is marked when fewer members are seen than are expected, or when one is not ready. On Cisco, an interface's first number is its member's switch number: `Gi2/0/1` is on member 2 |
| A **cluster** managed as `one` | One device, at the cluster's address, with the group's `hid` | One node |
| A **cluster** managed as `members` | Each member is a device with its own item's `hid`, in a vakr group of the type `cluster` that carries the cluster's `hid` | Each member is a node, inside a frame named for the cluster. The frame shows the cluster's state: degraded while a member is down, failed when all of them are |
| A **cluster** managed as `members_and_cluster` | Both: a device for each member, and one more for the cluster's own (virtual) address | The member nodes, inside a frame whose state is read from the cluster's own address |
| A **controller domain** | The controller is a device. Its endpoints, the access points, are not polled unless an object set reads their state from the controller | The controller is a node. Its endpoints are counted at each site, for example "access points 42 of 44 up", and are not drawn one by one |
| A **custom group** | A vakr group, with the group's `hid`, whose members are named by their `hid` | A tag on each of its members |

hirdir works out the health of a stack and of a cluster from their members and from what
is observed of each group. Once vakr reports, hirdir's colours follow what vakr sees.

## Observed hardware and what vakr polls by model

This is vakr's ADR-038, and hirdir's P-336 and P-337.

**What discovery keeps.** vakr already reads `sysName`, `sysDescr`, `sysObjectID`,
`sysContact` and `sysLocation`, and will keep them. It also reads ENTITY-MIB's physical
table, `entPhysicalTable` (`1.3.6.1.2.1.47.1.1.1`). For each entry of the class
chassis(3) or stack(11), it keeps:
- the class, name and description;
- the model name (`entPhysicalModelName`);
- the serial number (`entPhysicalSerialNum`);
- the software revision;
- the entry's position within its parent.

vakr keeps each value as it is now, with a history of its changes.

**Object sets.** An object set is a named list of SNMP objects. Each object is a scalar
or a table, of text or of numbers, and is either inventory or a metric. A rule of vakr's
collection policy adds an object set to every device that matches its facts:
- the vendor or its `enterprise_number`;
- the `pid`, or the `catalog_entry_hid`;
- the model's `kind`, `type` or `function`;
- the device's `form`: `single`, `stack`, `cluster_member` or `cluster`;
- the `sysObjectID`;
- and the facts vakr's policies already match: site, tags and groups.

The sets that match a device add up. A set may name an object that has to answer before
the set is polled. That way a stack is found even where hirdir has not said that the
device is one.

vakr ships two sets:
- `entity-physical`, for every device;
- `cisco-stackwise`, for a device of the form `stack` or one where CISCO-STACKWISE-MIB's
  switch table answers. It reads each switch's number, role and state, and the state of
  its stack ports.

An operator adds more sets in a file of their own. A switch stack then answers more
objects than a router of the same vendor, because the router matches neither the form
`stack` nor the stack set's required object.

An inventory object is read at the discovery interval, and kept as its current value
with a history of its changes. A metric object is read at the poll interval and kept as
a time series, which comes in a second phase.

**In hirdir.** An item keeps the serial number and model that were seen, and a stack
keeps the members that were seen at each switch number, apart from the record (P-336).
A difference is marked for review. Nothing in the record changes by itself: a person
takes in what was seen, or records the replacement.

## Interface names

The three projects compare an interface's name by one rule (P-331):
1. Take out the spaces around the name, and between its type and its number.
2. Write it in lower case.
3. Where its type is a short form in the table below, write that type out in full.
4. Keep the rest of the name as it is.

A type that is not in the table is compared as it is, in lower case. Prefixes are never
guessed: `Tw` and `Twe` are two different types.

| Short form | Full type |
|---|---|
| `Fa` | `FastEthernet` |
| `Gi` | `GigabitEthernet` |
| `Tw` | `TwoGigabitEthernet` |
| `Fi` | `FiveGigabitEthernet` |
| `Te` | `TenGigabitEthernet` |
| `Twe` | `TwentyFiveGigE` |
| `Fo` | `FortyGigabitEthernet` |
| `Hu` | `HundredGigE` |
| `Ap` | `AppGigabitEthernet` |
| `Eth` | `Ethernet` |
| `Po` | `Port-channel` |
| `Lo` | `Loopback` |
| `Vl` | `Vlan` |
| `Tu` | `Tunnel` |
| `Nu` | `Null` |

Each project tests its implementation against these vectors:

| As given | Compared as |
|---|---|
| `Gi1/0/1` | `gigabitethernet1/0/1` |
| `GigabitEthernet1/0/1` | `gigabitethernet1/0/1` |
| ` gi1/0/1 ` | `gigabitethernet1/0/1` |
| `GigabitEthernet 1/0/1` | `gigabitethernet1/0/1` |
| `Gi0/0/0.100` | `gigabitethernet0/0/0.100` |
| `Tw1/0/1` | `twogigabitethernet1/0/1` |
| `Twe1/0/1` | `twentyfivegige1/0/1` |
| `Te1/1/1` | `tengigabitethernet1/1/1` |
| `Hu1/0/49` | `hundredgige1/0/49` |
| `Po10` | `port-channel10` |
| `Port-channel10` | `port-channel10` |
| `Eth1/1` | `ethernet1/1` |
| `ge-0/0/0` | `ge-0/0/0` |

The table is a starting point, written from Cisco IOS XE and NX-OS. Before code relies on
it, it is checked against walks of real devices, run through vakr's SNMP simulator. A new
short form is added here first, and then to each project's tests.

## What is seen, and what is not known

From vakr's report to hirdir's `observed_status`:

| vakr sees | hirdir's `observed_status` |
|---|---|
| reachable from every monitoring position | `online` |
| reachable from some positions only, or with loss or latency over its threshold | `degraded` |
| unreachable from every position, with readings that are fresh | `unreachable` |
| readings that are stale, a device never polled, or one in maintenance | a row that names the device and gives no status. It confirms the registration, so that `complete` does not mark the device as no longer reported. hirdir's value stays as it is, and its `observed_at` shows its age |

From hirdir's intent to what vakr polls and what sunstone counts:

| hirdir says | vakr's `admin_state` | sunstone |
|---|---|---|
| expected online | `enabled` | counted as usual |
| not expected online, with the reason `maintenance` | `maintenance` | `priority: ignored` |
| not expected online, for any other reason | `disabled` | `priority: ignored` |
| Released, Archived, or retired | `retired` | left out |

None of the three projects deletes a record. Each one retires or disables it, and keeps
its history.

## How data moves

**Rules:**
- Each project reads what it needs from the owner's API, with an account of its own.
- What a tool sees goes back to hirdir as a file of what that tool reports (P-248).
  hirdir previews the file and applies it, as it does any import.
- No project writes into another's records by any other route.
- Nothing is sent at the moment of a change. hirdir is read in batches, as P-223 asks.

| From → to | What | How | Account |
|---|---|---|---|
| hirdir → vakr | the devices whose box is ticked for vakr (P-341), with their sites, models and operators, and circuits on interfaces | vakr reads hirdir's API on a timer and writes its inventory file from what it reads. `vakr inventory plan` shows each change before it is applied | a hirdir service account, View-only |
| vakr → hirdir | observed status, observed hardware, registrations | vakr writes what it reports under the shared names, as two JSON files, one of items and one of device groups, each row leaving out what it does not say. It sends them as two imports: `system` vakr, mode `update` (P-334), `complete` | a hirdir service account, Inventory |
| hirdir → sunstone | regions, sites, locations, devices, groups, circuits, carrier networks, operators | sunstone's import adapter writes the generated part of its topology (SI-09) | a hirdir service account, View-only |
| vakr → sunstone | live state and history | sunstone's live-state source for vakr (SI-08) | vakr's integration reader |
| sunstone → hirdir | fixes to what hirdir owns, such as a circuit's ends | a file that a person previews and applies in hirdir. sunstone has no sign-in, so it never writes with an account of its own | the person's |
| hirdir → others, later | what changes add, remove and alter, read from the audit trail | P-223, after 1.0.0 | — |

Because the fields share their names, a file from one project needs little translation
before another can load it.

**In order:**
1. **Now, with nothing changed in any project.**
   - A vakr export is turned into a hirdir file of items, matched by host name and
     loaded with `--system vakr`. The rows that would make new items are left out at
     the preview.
   - A stack is registered by hand.
   - A file is generated from a hirdir export for `vakr inventory plan`.
2. **With hirdir 0.9.20, vakr's ADR-037 and sunstone's SI-01 to SI-09.** vakr's ADR-037 goes
   in before vakr's production install, so that production starts on the shared names
   (the owner, 2026-11-26). It brings:
   - the keys, the shared fields and the circuit block;
   - the mode `update`, and files of device groups from a tool;
   - the copy of the catalog;
   - the generated topology, and live state from vakr.
3. **With vakr's ADR-038, after vakr's 14-day parallel run:** observed hardware and object
   sets, and hirdir showing what differs.
4. **After 1.0.0:**
   - hirdir's sync from the audit trail (P-223), read in the order of each event's HID,
     so that a batch resumes where the last one ended;
   - vakr's feed of events, and Server-Sent Events;
   - object sets of metrics.

## External systems in hirdir: general, linked, registered

hirdir knows every system the team uses, at one of three levels (P-341). Each level has
all that the level before it has.

| Level | What it does | Examples |
|---|---|---|
| **general** | Named and kept with its kind, home address and notes. It shows on no other page | a ticketing system, a wiki |
| **linked** | Shows as a link on the records it relates to: the kinds named in `shows_on`, and only a vendor's records where the system belongs to a vendor | sunstone on items, sites and circuits; a building system on locations; a carrier's portal on that carrier's circuits; a maker's support portal on its items |
| **registered** | Items and device groups are registered with it. Each one's page has a box that asks the system to take it | vakr |

**The link.** A link is built from the system's `link_template`, which may hold:
- `{hid}`, `{name}` and `{external_id}`, for any record;
- `{hostname}` and `{fqdn}`, for an item or a group;
- `{serial_number}`, `{asset_tag}` and `{pid}`, for an item;
- `{code}`, for a place;
- `{enterprise_circuit_id}` and `{carrier_circuit_id}`, for a circuit.

A record with no value for a placeholder in the template shows no link, rather than a
broken one.

| System | Its template |
|---|---|
| vakr, which keeps hirdir's keys | `https://vakr.example.net/devices?hid={hid}` |
| A building system | `https://building.example/detail/{external_id}`, where the ID is the one a person enters on the building |
| A carrier's portal | `https://carrier.example/portal/`, or `https://carrier.example/portal/circuits/{carrier_circuit_id}` where the portal takes the carrier's ID |

**The box.** Ticking the box makes a registration `pending`. The system takes it at its
next exchange (its pull from hirdir's API, an export, or a file of its own) and confirms
it, and the registration becomes `registered`. Clearing the box makes it `removed`, which
for vakr disables the device. With no registered system, a page shows no box.

## Access between the projects

- **hirdir** gives each project a service account of its own, which holds tokens and
  never Admin. A reader has View-only. vakr's report needs Inventory, to apply its
  imports.
- **vakr** gives sunstone its integration reader, the read-only role its design calls
  for (API-003). Until that role exists, a kiosk token (`vkk_`) reads what an operator
  reads. Nothing writes to vakr except its inventory file.
- **sunstone** has no sign-in. It keeps its tokens for hirdir and vakr in its settings
  file, reads with them from its own server and never from the browser, and stays
  behind nginx's password.

## Cabling, if hirdir takes it later

For now, hirdir holds no cables. sunstone's own file and discovery hold them. If hirdir
takes cabling after 1.0.0 (O-04), it could look like this.

- **Ports, from the catalog.** A catalog entry gets a template of its ports, a pattern
  for each row of them, for example 48 × `GigabitEthernet{member}/0/{1-48}` and 8 ×
  `TenGigabitEthernet{member}/1/{1-8}`. A module's catalog entry adds its own ports, in
  the slot where the module is installed.
- **Ports are worked out, not stored.** An item's ports are worked out from its model
  and its minor items when it is read, and stored nowhere, as every inherited value is.
  A port gets a row of its own only where the team has recorded something on it: a
  cable, an address, a circuit or a note. 50,000 items do not become two million rows.
- **Cables.** A cable has an A end and a B end. Each end is a port of an item (the
  item's HID and the port's name, in the form of P-331), a front or rear port of a patch
  panel, or a side of a circuit. A cable also has a label (its tag), a kind (`patch`,
  `trunk`, `dac`, `aoc`, `cross_connect`), its media, colour and length, and the dates
  it was installed and removed. It is retired, never deleted, and every change to it is
  audited.
- **Patch panels.** A patch panel is an item whose model's template pairs each front
  port with a rear port. The path from a port, through the panels, to the far port is
  worked out when it is read.
- **Stacks and replacements.** A port belongs to the member that has it. A replacement
  hands that member's cables to the item that takes its place, as it hands over circuit
  connections now.
- **Circuits.** Where a circuit's `interface` names one of a device's ports, it becomes
  a reference to that port, in the migration that brings ports.
- **What is seen.** LLDP and CDP neighbours, from vakr (an object set on LLDP-MIB) or
  from sunstone's discovery, are compared with the cables on record. A difference is a
  finding for review and never a change, as with a registration that is `not_reported`.
- **sunstone.** sunstone's fixes to cables become files for hirdir. sunstone draws
  hirdir's cables, and keeps its own layers, expectations and layouts.

The work is about the size of 0.8.0, circuits. The catalog's port templates would come
first, since vakr and sunstone could use them on their own, for example to know how many
ports a model has.

## Example data for testing the three together

A test of what moves between the projects needs one fictional network, written in each
project's own files:
- a hirdir export;
- a vakr inventory file and its SNMP simulator's walks;
- a sunstone topology.

It follows hirdir's rule for example data: no name of a real place or organization, host
names under `.example`, and addresses from `192.0.2.0/24`, `198.51.100.0/24`,
`203.0.113.0/24` and `2001:db8::/32`. sunstone's own samples use real city names and
coordinates and addresses in `10.0.0.0/8`. They stay sunstone's, and are not this
fixture.

## Tracking

| What | hirdir | vakr | sunstone |
|---|---|---|---|
| The common keys: `hid` and `<name>_hid` | P-329; HIDs exist already | ADR-037 (1), proposed, before vakr's production install | SI-01, proposed |
| Shared fields under hirdir's names, operators on devices | P-329, 0.9.20 | ADR-037 (2), proposed | SI-02, SI-07, proposed |
| The circuit block, and which way is down | P-330, P-338, P-340, 0.9.20 | ADR-037 (3), proposed | SI-03, proposed |
| One rule for an interface's name | P-331, 0.9.20 | ADR-037 (6), proposed | SI-05, proposed |
| Registrations follow the node through a replacement | P-332, 0.9.20 | none | none |
| What a tool reports: files of device groups, the mode `update` | P-333, P-334, 0.9.20 | ADR-037 (4), proposed | none |
| External systems that are general, linked or registered, and the box | P-341, 0.9.20 | ADR-037 (2) and (4), proposed | none |
| The hardware a tool sees | P-336, 0.9.20 | ADR-038 (1), proposed, after vakr's parallel run | none |
| How a model is recognized; one catalog | P-337, 0.9.20 | ADR-038 (2), proposed | SI-04, proposed |
| A site's time zone | P-339, 0.9.20 | ADR-037 (2), proposed | SI-02, proposed |
| Stacks and clusters | held already | ADR-038 (3), proposed | SI-06, proposed |
| Object sets by model and form | none | ADR-038 (4), proposed | none |
| Access for each project's own account | held already | ADR-037 (5), API-003, proposed | SI-08, proposed |
| Topology generated from hirdir; coordinates optional | none | none | SI-09, proposed |
| Fixes back to hirdir as a file | none | none | SI-10, proposed |
| Sync from the audit trail | P-223, after 1.0.0 | none | none |
| Cabling | O-04, after 1.0.0 | none | none |
