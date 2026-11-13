# Data model

The records `hirdir` keeps and the rules between them. Field names here are the names
used in the database, the API, JSON and CSV. A change to a name on this page is a change
to every interface, so it is made here first.

## Conventions

| Subject | Rule |
|---|---|
| Identity | Every table has `hid`, a UUID version 7 in lower-case canonical text, assigned by the server. It is the primary key and the only thing other records reference. |
| Bookkeeping | Every editable table has `created_at`, `updated_at` (UTC), `created_by`, `updated_by` (user HID) and `row_version` (integer, starts at 1, plus one per change). |
| Stale edits | An update names the `row_version` it was made against. A mismatch is refused with `409`. The database makes the same check as it writes, so of two changes made against one version at the same moment only the first is applied. |
| Removal | Items, sites, locations, contacts, owners, contracts and catalog entries are never deleted while anything refers to them. They carry `record_status`. |
| `record_status` | `draft`, `active` or `retired`. Draft and retired records are left out of counts and default views. |
| Dates and times | Dates are `YYYY-MM-DD`. Timestamps are ISO 8601 in UTC. |
| Money | Decimal with two places, one currency for the installation, named in settings. |
| Decimals | Money has two places, support weight up to three, a percentage up to two. In JSON a decimal is written as text, `"18000.00"`, so that nothing is lost on the way to a browser. A number is accepted on the way in. |
| Blank | A blank text field is stored as nothing at all, and is `null` in JSON. |
| Text keys | Compared without regard to case or surrounding space. The text as entered is what is stored and shown. |
| History | The past value of any field is answered from `audit_events`. Only group membership and contract coverage keep their own date ranges, because reports ask about them directly. |
| Portability | Column types and constraints are limited to what SQLite and PostgreSQL both support. |

## Inheritance

One rule, used everywhere: **a blank inherits, a value overrides, and the answer says
where it came from.**

| Field on | Inherits from, nearest first |
|---|---|
| Item: `est_value`, `support_weight`, `annual_support_cost`, `end_of_sale`, `end_of_sw_support`, `end_of_hw_support`, `ldos` | its catalog entry |
| Catalog entry: `stack_discount_pct` | the global setting |
| Minor item: `location_hid`, `owner_hid`, `lifecycle_state`, `disposition`, `expected_online` | its parent item, and that item's parent |
| Location: contacts per role, shipping address, shipping instructions | its parent location, its site, then each region outward |

The API returns an inheritable field as its own stored value plus an `effective` block:

```json
{
  "est_value": null,
  "effective": {
    "est_value": { "value": "18000.00", "source": "catalog", "source_hid": "0193a1f4-6c2e-7b41-9d0a-5e3f8c1a7b22" }
  }
}
```

`source` is one of `own`, `catalog`, `parent_item`, `location`, `site`, `region`,
`setting` or `none`. Grids and exports show the effective value and offer a
`<field>_source` column. Writing a value sets the item's own. Writing `null` returns it
to inheriting.

## Records

### `vendors`

A manufacturer, a support provider, or both. A name or alias belongs to one vendor only.

| Field | Type | Notes |
|---|---|---|
| `name` | text, unique | "Cisco", "Juniper", "Canonical" |
| `aliases` | list of text | Other spellings accepted on import: "Cisco Systems" |
| `notes` | text | |

### `catalog_entries`

What is true of every item of one model. Unique on (`vendor_hid`, `pid`).

| Field | Type | Notes |
|---|---|---|
| `vendor_hid` | reference | required |
| `pid` | text | required. The product ID as the vendor writes it: `C9300-48P` |
| `model_name` | text | "Catalyst 9300 48-port PoE+" |
| `kind` | choice | `hardware`, `virtual_machine`, `software`, `service`. Left out, `hardware` |
| `type` | choice | switch, router, firewall, wireless-controller, access-point, phone, server, test-equipment, power-supply, module, application, and so on |
| `function` | choice | access, aggregation, core, edge, management, and so on |
| `description` | text | "access, 48-port" |
| `end_of_sale`, `end_of_sw_support`, `end_of_hw_support`, `ldos` | date | |
| `est_value` | money | planning estimate per unit |
| `support_weight` | decimal | relative effort to support one unit; no unit of measure |
| `annual_support_cost` | money | per unit per year; expected to be blank at first |
| `stack_discount_pct` | 0 to 100 | blank inherits the global setting |
| `successor_hid` | reference | the model that replaces this one, for refresh planning |
| `review_status` | choice | `reviewed`, or `unreviewed` when an import created it |
| `record_status` | choice | see Conventions |

### `items`

One tracked thing. At least one of `serial_number` with `catalog_entry_hid`,
`asset_tag`, `name` or `hostname` is required. Everything else may be blank, the three
lifecycle fields included.

| Field | Type | Notes |
|---|---|---|
| `catalog_entry_hid` | reference | optional, because some things arrive with only a name |
| `serial_number` | text | unique with the catalog entry when present |
| `mac_address` | text | stored as twelve lower-case hex digits; not unique |
| `asset_tag` | text | unique when present |
| `name` | text | the name the team uses. Blank shows `hostname` |
| `hostname`, `fqdn` | text | for a stack member these are usually blank; the stack holds them |
| `description`, `comments` | text | |
| `parent_item_hid` | reference | set on a minor item |
| `position` | text | where in the parent: "PS-A", "Slot 3", "Bay 7" |
| `quantity` | integer, default 1 | seats or licences for software and services |
| `lifecycle_state` | choice | see below |
| `disposition` | choice | see below |
| `expected_online` | boolean | intent, not observation |
| `state_reason` | choice | "RMA", "maintenance", "lost", and so on |
| `state_changed_at` | timestamp | |
| `owner_hid`, `location_hid` | reference | |
| `purchase_line_hid` | reference | the request line it arrived on |
| `procured_on`, `delivered_on`, `in_service_on` | date | |
| `warranty_start`, `warranty_end` | date | |
| `est_value`, `support_weight`, `annual_support_cost` | override | blank inherits |
| `end_of_sale`, `end_of_sw_support`, `end_of_hw_support`, `ldos` | override | blank inherits |
| `record_status` | choice | see Conventions |

A **major item** is one with `parent_item_hid` blank. `is_major` is derived and is
available as a filter and a column.

Release 0.2.0 has every field above except `parent_item_hid`, `position` and the
derived `is_major`, which arrive with minor items in 0.4.0, `location_hid` in 0.5.0 and
`purchase_line_hid` in 0.6.0.

### `item_replacements`

| Field | Type | Notes |
|---|---|---|
| `old_item_hid`, `new_item_hid` | reference | both records remain |
| `reason` | choice | `rma`, `refresh`, `project`, `upgrade`, `other` |
| `reference` | text | RMA, service request or ticket number |
| `replaced_on` | date | |

### `device_groups` and `device_group_members`

| Field | Type | Notes |
|---|---|---|
| `type` | choice | `stack`, `cluster`, `controller_domain`, `custom` |
| `name` | text | required |
| `hostname`, `fqdn` | text | for stacks and clusters |
| `parent_group_hid` | reference | nesting; cycles refused |
| `location_hid`, `owner_hid` | reference | optional; shown when members do not disagree |

| Member field | Type | Notes |
|---|---|---|
| `group_hid` | reference | |
| `item_hid` | reference | |
| `role` | choice | stack: `master`, `member`. cluster: `active`, `standby`, `member`. controller domain: `controller`, `endpoint` |
| `position` | integer | stack member number |
| `joined_on`, `left_on` | date | `left_on` blank means current |

Rules, checked on every write:

- A `stack` has at least two current members and exactly one `master`. All are major
  items. A stack being built may hold one member while it is `draft`.
- An item is a current member of at most one stack and at most one cluster.
- `serial_number` of a stack is read from its current master. It is not stored, so it is
  right the moment the master changes.
- In a `controller_domain`, a controller is an item, or a nested group of type `cluster`.

### `networks` and `addresses`

| Field | Type | Notes |
|---|---|---|
| `networks.label` | text, unique | "Red", "Black", "Tenant1" |
| `networks.kind` | choice | `vrf`, `network`, `other` |
| `addresses.item_hid` or `addresses.group_hid` | reference | exactly one of the two |
| `addresses.address` | IPv4 or IPv6 | stored in canonical form, no prefix length |
| `addresses.network_hid` | reference | blank is the unlabelled address space |
| `addresses.role` | choice | `management`, `loopback`, `secondary`, `virtual` |
| `addresses.is_primary` | boolean | at most one primary management address per item or group |

The same `address` twice under one network is allowed and is listed in the duplicates
report.

### `regions`, `sites`, `locations`

| Record | Fields | Rules |
|---|---|---|
| `regions` | `code`, `name`, `parent_region_hid`, `notes` | Any depth, no cycles. `name` unique among siblings. |
| `sites` | `code`, `name`, `region_hid`, address fields, `latitude`, `longitude`, `notes`, `record_status` | `name` unique within its region. |
| `locations` | `code`, `name`, `site_hid`, `parent_location_hid`, `kind`, address fields, `latitude`, `longitude`, `notes` | `name` unique among siblings. A parent location is in the same site. `kind` is building, floor, room, rack, warehouse or other. |

Address fields are `address1`, `address2`, `city`, `state`, `postal_code`, `country`. A
shipping address is a second set with the prefix `ship_`, plus `ship_instructions`. A
shipping address is taken whole from the nearest record that has one.

A **path** is the names from the top region down, joined with ` > `:
`Americas > Central > Site-A > Building 1 > Room 102`. A path identifies a region, site
or location in an import when no HID is given.

### `contacts` and `contact_assignments`

| Field | Type | Notes |
|---|---|---|
| `contacts.name`, `organization`, `email`, `phone`, `notes` | text | one record per person or shared mailbox |
| `contact_assignments.contact_hid` | reference | |
| `contact_assignments.region_hid`, `site_hid` or `location_hid` | reference | exactly one of the three |
| `contact_assignments.role` | choice | `shipping`, `technical`, `federal`, `operational`, `escalation` |
| `contact_assignments.priority` | integer | 1 is primary |
| `contact_assignments.stop_inheritance` | boolean | an assignment with no contact and this flag set means "none here, and do not look further up" |

Resolution for a location and a role: take the assignments on the location. If there are
none, take the parent location's, then the site's, then each region's outward. The first
level that has any supplies all of them.

### `owners` and `owner_members`

| Field | Type | Notes |
|---|---|---|
| `owners.label` | text, unique | "Network Engineering" |
| `owners.organization` | text | |
| `owners.is_external` | boolean | an owner outside the operations team |
| `owners.exception_reason` | text | required when `is_external` |
| `owners.record_status` | choice | see Conventions |
| `owner_members.contact_hid`, `role`, `priority` | | `role` is `primary` or `alternate`; exactly one primary |

The owner itself is in release 0.2.0, because an item needs one to point to. Its
members arrive with contacts in 0.5.0, and so does the marked exception on an item that
is given to an external owner.

### `contracts` and `contract_coverage`

| Field | Type | Notes |
|---|---|---|
| `contracts.number` | text | unique with the vendor |
| `contracts.vendor_hid` | reference | the provider |
| `contracts.starts_on`, `ends_on` | date | |
| `contracts.status` | choice | `active`, `expired`, `pending`, `cancelled` |
| `contracts.support_level`, `notes` | text | |
| `contracts.annual_cost` | money | the contract total, when that is all that is known |
| `contract_coverage.contract_hid`, `item_hid` | reference | |
| `contract_coverage.starts_on`, `ends_on` | date | blank takes the contract's dates |

### `purchase_requests` and `purchase_lines`

| Field | Type | Notes |
|---|---|---|
| `purchase_requests.reference` | text, unique | the RITM or other request number |
| `purchase_requests.requested_on`, `notes` | | |
| `purchase_requests.status` | choice | `draft`, `pending`, `ordered`, `received`, `cancelled` |
| `purchase_lines.catalog_entry_hid`, `quantity` | | model and how many |
| `purchase_lines.destination_site_hid`, `expected_on` | | |
| `purchase_lines.received_quantity` | integer | the number of items created from this line so far |

Receiving creates `quantity` items in state `Delivered`, each pointing back to its line.

### `external_systems` and `registrations`

| Field | Type | Notes |
|---|---|---|
| `external_systems.name` | text, unique | the installation's own name for it |
| `external_systems.kind` | choice | `monitoring`, `config_backup`, `access_control`, `sdn_controller`, `cloud_service`, `dns`, `discovery`, `other` |
| `external_systems.url`, `notes` | text | |
| `registrations.system_hid` | reference | |
| `registrations.item_hid` or `registrations.group_hid` | reference | exactly one |
| `registrations.external_id` | text | the other system's key for it |
| `registrations.status` | choice | `registered`, `pending`, `removed` |
| `registrations.confirmed_at` | timestamp | when the other system last agreed |

### `capacity_lines`

A source of resource units, or a call on them other than the infrastructure.

| Field | Type | Notes |
|---|---|---|
| `side` | choice | `supply` or `demand` |
| `category` | choice | supply: `staff`, `professional_services`, `smart_hands`, `tools`, `services`. demand: `other_work` |
| `name` | text | "Senior network engineer", "Escalation partner", "AI assistant" |
| `quantity` | decimal, default 1 | positions, contracted blocks of hours, subscriptions |
| `units_each` | decimal | resource units that one of `quantity` provides or consumes |
| `annual_cost` | money | optional, for comparing options |
| `vendor_hid` | reference | optional; the line then appears in that vendor's portfolio |
| `region_hid` or `site_hid` | reference | optional, at most one; blank serves everywhere |
| `starts_on`, `ends_on` | date | optional; outside these dates the line is not counted |
| `notes` | text | |
| `record_status` | choice | a `draft` line is a what-if |

The resource units of a line are `quantity` × `units_each`, a fixed amount.

- **Staff.** A line names a kind of position and a number of them, never a person. Levels
  are separate lines with their own `units_each`. By convention one mid-level position
  is 1.0, and the other levels are set against it.
- **Tools and services that do work.** A supply line with the units they provide.
- **Tools and services that take work to run.** These are items in the inventory with a
  support weight, so their burden is already in the demand. It is not entered again as a
  negative supply line.
- **Tools and services that make people more effective.** For now, a supply line with the
  estimated gain in units. LATER, a multiplier line: `effect` = `multiply`, a `factor`,
  a `share` of the positions using it, and the staff lines it applies to. Its units are
  (`factor` − 1) × `share` × the base units of those lines. Multipliers each work on the
  base units and do not compound, so the result does not depend on their order, and a
  cut in the staff lines shrinks the gain with it.

### `tags` and `tag_links`

A tag is a `label` (unique), an optional `colour` written `#1f6feb`, and a
`description`. A link names the tag, the record type and the record's HID. The filter
`tags has <label>` works on every list of a record that takes tags. A tag is made before
it is used: a label that is not yet a tag is refused, not created. A tag that is on any
record cannot be removed.

### `choices` and `settings`

`choices` holds every editable list: `list`, `value`, `label`, `sort`, `active`. The
lists are `catalog_type`, `catalog_function`, `state_reason`, `contact_role`,
`location_kind`, `replacement_reason` and `capacity_category`. A value is lower-case
letters, digits, hyphens and underscores, and is what is stored on a record; the label
is what people read. A value in use cannot be removed, only made inactive, and an
inactive value is no longer offered while the records that hold it keep it.

A setting has a default, written in the code. The database has no row for a setting
that has never been changed. Setting it to nothing returns it to the default; the row
then stays, empty, and keeps its `row_version`. A number has at most two decimal places
and is refused, not rounded, when it has more.

| Setting | Default | Meaning |
|---|---|---|
| `stack_discount_pct` | 50 | applied to stack members whose model sets none |
| `currency` | USD | label only |
| `fiscal_year_start_month` | 1 | for reports grouped by fiscal year |
| `count_states` | Assigned, Test, Prod, Down, Pending-Removal | states that count toward the component count |
| `weight_states` | Test, Prod, Down | states that carry support weight |
| `count_kinds` | hardware, virtual_machine | kinds in the headline component count |
| `weight_per_resource_unit` | 300 | how much support weight one resource unit carries; a placeholder until the team sets its own |

The life of a session token, `session_hours`, is in the configuration file and not
here, because it is needed before the database can be asked. See
[architecture.md](architecture.md).

### Access records

| Record | Fields |
|---|---|
| `users` | `username` (unique), `display_name`, `email`, `is_service_account`, `access_code_hash`, `tokens_valid_after`, `disabled`, `last_sign_in_at` |
| `user_groups` | `name` (unique), `description` |
| `user_group_members` | `user_hid`, `group_hid` |
| `role_grants` | `role` (`viewer`, `inventory`, `admin`), and exactly one of `user_hid` or `group_hid` |
| `service_tokens` | `user_hid` (a service account), `name`, `token_hash`, `created_at`, `expires_at`, `last_used_at`, `revoked_at` |

A user's role is the highest of the roles granted to the user and to every group the
user is in. A user with no grant can sign in and see nothing.

### `audit_events`

Append-only. `at`, `actor_hid`, `via` (`web`, `api`, `cli`, `import`, `system`),
`request_id`, `action` (`create`, `update`, `retire`, `transition`, `sign_in`,
`sign_in_failed`, and so on), `record_type`, `record_hid`, and `changes`, a list of
`{field, old, new}`. One import or bulk edit shares one `request_id`.

### `import_jobs`

`entity`, `mode`, `file_name`, `file_sha256`, `status` (`previewed`, `applied`,
`failed`), counts of created, updated, unchanged and rejected rows, and a row-level
report kept as JSON.

## Lifecycle, disposition and intent

Three fields describe an item's standing. `lifecycle_state` is the stage. `disposition`
is what an item in hand is for. `expected_online` is the intent.

| State | Meaning | Dispositions allowed | Expected online | Set on entry |
|---|---|---|---|---|
| Purchased | ordered, not received | none | no | |
| Delivered | received, tagged, in the warehouse | none | no | |
| Assigned | handed to the operations team, parked | Staging, Spare, Excess | no | Staging |
| Test | staging or pre-production | Staging | yes or no | Staging, online |
| Prod | in operational service or ready reserve | Production, Spare | Production: yes. Spare: yes or no | Production, online |
| Down | maintenance, suspended, inactive | kept from before | no | |
| Pending-Removal | RMA, retired, powered off, lost | kept, or Excess | no | |
| Released | wiped and out of the team's hands | none | no | |
| Archived | disposed, traded in, destroyed | none | no | |

The table above, and the list of allowed moves from one state to another, are stored as
data (`lifecycle_rules`) and loaded with these defaults. Any move is allowed to an
Admin with a reason. The default moves follow the diagram left to right, plus: Test and
Prod to Down and back, any state from Assigned onward to Pending-Removal, and
Pending-Removal back to Assigned for an item that is found or returned.

### `lifecycle_rules`

One row for each of the nine states. An Admin may change a row; the states themselves
are fixed.

| Field | Type | Notes |
|---|---|---|
| `state` | text, unique | one of the nine |
| `dispositions` | list | the dispositions an item in this state may have; empty means it has none |
| `keeps_disposition` | boolean | an item keeps the disposition it came with, which is then allowed as well: Down and Pending-Removal. An item that came with none may be given any |
| `may_be_online` | list | the dispositions that may be expected online in this state. Never Excess |
| `must_be_online` | list | the dispositions that are always expected online: Production in Prod |
| `entry_disposition`, `entry_online` | choice, boolean | the "set on entry" column above |
| `next_states` | list | the states an item may move to from this one |

The three lifecycle fields of an item may all be blank: a piece of test equipment with
an owner and nothing else is a complete record. An item with no state has no
disposition and no intent, is in no count, and may be given any state as its first.

**On entry to a state**, when the caller names neither field: the item keeps its
disposition if the new state allows it, and takes `entry_disposition` if it does not.
So an item found again in Pending-Removal as Excess is still Excess in Assigned, and a
spare that went Down is still a spare when it returns to Prod. The intent is
`entry_online`, bounded by what the disposition may and must be. A caller may name the
disposition and the intent with the move, and the result must be a combination the
state allows.

**A change of state** is made by a transition, never by an edit, so that every one
records who, when, from, to and why. The why is a value of the `state_reason` list. It
is asked for on a forced move and is optional otherwise. A change of disposition or
intent within a state is an ordinary edit, checked against the same row.

An item **should be monitored** when it is a major item in Test or Prod and
`expected_online` is true. That is an expectation for reports to compare against, not a
switch that enrols anything.

## Identity and matching

When an import row or, later, a discovery observation must be matched to an item, the
first rule that applies decides, and no later rule is tried:

1. `hid` is given: that record, or an error if there is none.
2. Vendor, PID and serial number are given: the item with that triple.
3. `asset_tag` is given: the item with that tag.
4. Neither serial number nor asset tag is given: the one active item with that `name`
   (or `hostname`, when the item's name is blank) that itself has no serial number.
5. Otherwise the row is a new item.

More than one candidate is an error on that row, never a guess. MAC address, hostname
and IP address are never used to match by themselves.

A row that matches by rule 2 or 3 and carries a different name updates the name. A row
with no serial number, no asset tag and a new name is a new item, which is why exports
carry the HID and why a rename is best done on the record or with the HID in the file.

## Counting and weight

For a set of items chosen by any filter:

| Measure | Definition |
|---|---|
| Component count | Major items with `record_status` active, in `count_states`, of `count_kinds`. |
| Managed-node count | Of those: each current stack or cluster counts as one, and each item in neither counts as one. |
| Support weight | Sum over major items in `weight_states` of effective `support_weight` × `quantity`, each stack member multiplied by (1 − its model's effective stack discount ÷ 100). |
| Estimated value | Sum of effective `est_value` × `quantity` over all items in the set, major and minor. |
| Annual support cost | Sum of effective `annual_support_cost` × `quantity` over all items in the set. No stack discount. |

Worked example, with a global stack discount of 50 and a per-model discount of 30 on the
second model:

| Stack | Members | Weight each | Discount | Stack weight | Counts as |
|---|--:|--:|--:|--:|---|
| `site2-sw-stack1`, Catalyst 9300 | 4 | 1.0 | 50 (inherited) | 2.0 | 4 components, 1 managed node |
| `site2-sw-stack2`, EX4400 | 4 | 1.0 | 30 (set on the model) | 2.8 | 4 components, 1 managed node |

Four standalone switches of either model weigh 4.0. Contract cost for each stack is that
of four switches.

## Capacity balance

| Measure | Definition |
|---|---|
| Infrastructure demand | Support weight of the chosen scope ÷ `weight_per_resource_unit`. |
| Demand | Infrastructure demand plus the units of every active demand line in date. |
| Supply | The units of every active supply line in date, in total and by category. |
| Balance | Supply − demand. |
| Coverage | Supply ÷ demand, as a percentage. |

With drafts included, draft lines and draft items are counted as if active, and the
report shows both results side by side.

Worked example, with `weight_per_resource_unit` at its default of 300 and a support
weight of 2,400:

| Line | Side | Category | Quantity | Units each | Units |
|---|---|---|--:|--:|--:|
| Infrastructure (computed) | demand | | | | 8.0 |
| Site consolidation project | demand | other_work | 1 | 1.5 | 1.5 |
| Organization transition | demand | other_work | 1 | 0.5 | 0.5 |
| Junior network engineer | supply | staff | 2 | 0.6 | 1.2 |
| Network engineer | supply | staff | 3 | 1.0 | 3.0 |
| Senior network engineer | supply | staff | 1 | 1.8 | 1.8 |
| Escalation partner | supply | professional_services | 1 | 1.0 | 1.0 |
| Colocation smart hands | supply | smart_hands | 1 | 0.5 | 0.5 |
| Automation and tooling | supply | tools | 1 | 1.5 | 1.5 |
| AI assistant (draft) | supply | services | 1 | 1.0 | 1.0 |

Demand is 10.0. Active supply is 9.0: a balance of −1.0 and coverage of 90%. With the
draft line, supply is 10.0 and the balance is zero. Of the active supply, 6.0 units, two
thirds, is the team's own six positions.

## Indexes

Serial number, MAC address, asset tag, name, hostname, catalog entry, parent item,
lifecycle state, disposition, owner, location, address, contract number, each
end-of-life date, `updated_at`, and the tag links by record. Region and location
ancestry is answered with recursive queries; a stored closure is added only if a
measurement asks for it.
