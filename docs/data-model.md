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
| Removal | Items, device groups, sites, locations, contacts, owners, contracts and catalog entries are never deleted. They carry `record_status`. A membership of a group is ended with a date. An address, and a network or a tag that nothing uses, is removed outright, and the audit event of the removal holds what it was. |
| `record_status` | `draft`, `active` or `retired`. Draft and retired records are left out of counts and default views. |
| Dates and times | Dates are `YYYY-MM-DD`. Timestamps are stored, and travel through the API and files, as ISO 8601 in UTC. A person is shown the application's time with the name of the zone, `2026-01-31 14:05:09 EST`: the `time_zone` setting, the same for everybody whatever zone they are in. |
| Money | Decimal with two places, one currency for the installation, named in settings. |
| Decimals | Two places: money, support weight and percentages alike. In JSON a decimal is written as text, `"18000.00"`, so that nothing is lost on the way to a browser. A number is accepted on the way in. |
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
| Minor item: `location_hid`, `owner_hid` | its parent item, and that item's parent |
| Minor item: `lifecycle_state`, `disposition`, `expected_online`, taken together | the nearest item above it that has a lifecycle state |
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

In `effective` a decimal and a date are text, a reference is the HID of the record, and
`expected_online` is `true` or `false`. `source_hid` is the record the value came from:
for `parent_item`, the item above that holds it, which need not be the direct parent.

## Records

### `vendors`

A manufacturer, a support provider, or both. A name or alias belongs to one vendor only.

| Field | Type | Notes |
|---|---|---|
| `name` | text, unique | "Cisco", "Juniper", "Canonical" |
| `aliases` | list of text | Other spellings accepted on import: "Cisco Systems". An alias holds no semicolon, which separates aliases in a file |
| `notes` | text | |
| `review_status` | choice | `reviewed`, or `unreviewed` when an import created it |

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
| `parent_item_hid` | reference | set on a minor item: the item it is installed in or attached to |
| `position` | text | where in the parent: "PS-A", "Slot 3", "Bay 7". Only a minor item has one |
| `quantity` | integer, default 1 | seats or licences for software and services |
| `lifecycle_state` | choice | see below |
| `disposition` | choice | see below |
| `expected_online` | boolean | intent, not observation |
| `state_reason` | choice | "RMA", "maintenance", "lost", and so on |
| `state_changed_at` | timestamp | |
| `condition` | choice | the state of the hardware as a person knows it; see "Condition, observation and health" |
| `observed_status` | choice | `online`, `degraded` or `unreachable`: what is seen of it now. Blank until somebody says |
| `observed_at` | timestamp | when that was seen. Set with `observed_status`, to now unless another moment is given |
| `owner_hid`, `location_hid` | reference | |
| `purchase_line_hid` | reference | the request line it arrived on |
| `procured_on`, `delivered_on`, `in_service_on` | date | |
| `warranty_start`, `warranty_end` | date | |
| `est_value`, `support_weight`, `annual_support_cost` | override | blank inherits |
| `end_of_sale`, `end_of_sw_support`, `end_of_hw_support`, `ldos` | override | blank inherits |
| `record_status` | choice | see Conventions |

A **major item** is one with `parent_item_hid` blank. `is_major` is derived and is
available as a filter and a column. So is `depth`: 0 for a major item, 1 for a minor
item of it, and so on.

**Minor items.** A minor item has exactly one parent, and may have minor items of its
own: a module in a blade in a chassis. Minor items nest at most three deep beneath a
major item, and an item is never above itself. A minor item may have its own serial
number, catalog entry, name and addresses. A current member of a stack or a cluster is
a major item, so it is not given a parent, and a minor item is not made a member of
one.

A minor item whose own `owner_hid` is blank has the owner of the nearest item above it
that has one. Its standing is taken as a whole: with a `lifecycle_state` of its own it
has its own disposition and intent, and with none it has all three of the nearest item
above it that has a state. A power supply is in production because its switch is, and
the one that failed is moved to Pending-Removal by itself. It is returned to inheriting
by a transition to no state. Nothing is copied down: moving the switch changes what
its minor items show, and writes to none of them.

Taking a minor item out of its parent, by clearing `parent_item_hid` or naming another
parent, keeps its record and its history. With no parent it is a major item, with
whatever is its own: what it inherited stays with the parent it left.

Release 0.4.0 has every field above except `location_hid`, which arrives in 0.5.0, and
`purchase_line_hid`, in 0.6.0.

### `item_replacements`

| Field | Type | Notes |
|---|---|---|
| `old_item_hid`, `new_item_hid` | reference | both records remain |
| `reason` | choice | a value of the `replacement_reason` list: `rma`, `refresh`, `project`, `upgrade`, `other` |
| `reference` | text | RMA, service request or ticket number |
| `replaced_on` | date | left out, today in the application's time zone |

A replacement is made by `POST /items/{hid}/replace` on the item that leaves. The item
that takes its place is one that exists, or is created by the same request. An item is
replaced once, and takes the place of one item, never of one that in the end took its
own. The new item takes over the old one's
current memberships of groups, with the same role and position: each of the old ones
ends on `replaced_on` and each of the new ones begins then, so a stack keeps its HID
and its master through an RMA. The replacement moves neither item in the lifecycle;
that is done by a transition, with its own reason.

The record arrives in release 0.4.0. Reports on replacements, and replacements in
files, arrive in 0.6.0.

### `device_groups` and `device_group_members`

| Field | Type | Notes |
|---|---|---|
| `type` | choice | `stack`, `cluster`, `controller_domain`, `custom`. Not changed once the group has had a member |
| `name` | text, unique | required |
| `hostname`, `fqdn` | text | for stacks and clusters |
| `parent_group_hid` | reference | nesting; cycles refused, and at most eight deep |
| `location_hid`, `owner_hid` | reference | optional. `location_hid` arrives in 0.5.0 |
| `managed_as` | choice | a cluster only: `one`, `members` or `members_and_cluster`. Left out, `one`. See "Counting and weight" |
| `expected_members` | integer | optional: how many members the group is meant to have |
| `observed_master_hid` | reference | a stack only: the current member that is seen to be master now. Set with `observed_at` of its own, `master_observed_at` |
| `observed_status`, `observed_at` | choice, timestamp | what is seen of the group as one device, as on an item |
| `record_status` | choice | see Conventions |

| Member field | Type | Notes |
|---|---|---|
| `group_hid` | reference | |
| `item_hid` | reference | |
| `role` | choice | stack: `master`, `member`. cluster: `active`, `standby`, `member`. controller domain: `controller`, `endpoint`. custom: `member` |
| `position` | integer | stack member number |
| `joined_on`, `left_on` | date | `joined_on` left out is today. `left_on` blank means current |

Rules, checked on every write:

- The members of a `stack` are major items. A stack may be one switch alone: it waits
  for its second in staging, and is left with one in production when a member fails
  and is taken out. A stack with no members at all is accepted, as one whose members
  are still to come.
- **The master of a stack is two facts.** The role `master` marks the master that is
  *intended*: the member given the priority in its configuration. It is optional. A
  stack has at most one, and marking another member unmarks the one that had it, in
  the same change. `observed_master_hid` is the master that is *seen*: which member
  the stack made master when it last booted. That is decided by the stack and may move
  over time, so it is an observation, set by hand or by an import and LATER by a
  monitoring tool. No rule depends on either, and neither stops a member leaving. The
  record says when the two differ, which is not a fault.
- Members may be added several at a time, by one request.
- An item is a current member of one group at most once, and of at most one stack and
  at most one cluster among the groups that are not retired. The members of a stack
  and of a cluster are major items.
- `serial_number` of a stack is read from the master that is seen, and when none is
  recorded from the one intended; `serial_source` says which, `observed` or
  `intended`. It is not stored, so it is right the moment either changes. A stack
  answers to the serial number of any of its current members: on the list of groups,
  `member.serial_number` finds it.
- In a `controller_domain`, a controller is an item, or a group of type `cluster`
  nested in the domain, at any depth. The controllers of an endpoint are the members
  with the role `controller` and the current members of every such cluster, each
  listed with the cluster it is in. A domain may hold several clusters, an east pair
  and a west pair of wireless LAN controllers: the access points are endpoints of the
  domain, so one that fails over from one pair to the other needs no change.
- A membership is ended by giving it `left_on`, and is never removed. An item that
  comes back joins again, with a new membership. Retiring a group ends its current
  memberships on that day. Retiring an item ends its memberships too, and so does
  moving it to Released or to Archived, when it has left the team's hands. A move to
  any other state leaves them as they are: a failed switch in Pending-Removal is still
  a member of its stack, and the stack shows as degraded.
- A change to these records is checked with no other change under way: of two requests
  that would put one item into two stacks at the same moment, the second waits, sees
  the first, and is refused.
- The group's record lists in `members_disagree` each field of its own that a current
  member contradicts: `owner_hid`, when a member has another owner in force.

A group takes tags, and addresses of its own: a stack carries the hostname and the
management address, and its members usually carry neither.

### `networks` and `addresses`

| Field | Type | Notes |
|---|---|---|
| `networks.label` | text, unique | "Red", "Black", "Tenant1" |
| `networks.kind` | choice | `vrf`, `network`, `other`. Left out, `network` |
| `addresses.item_hid` or `addresses.group_hid` | reference | exactly one of the two, and not changed afterwards |
| `addresses.address` | IPv4 or IPv6 | stored in canonical form, no prefix length |
| `addresses.network_hid` | reference | blank is the unlabelled address space |
| `addresses.role` | choice | `management`, `loopback`, `secondary`, `virtual`. Left out, `management` |
| `addresses.is_primary` | boolean | at most one primary management address of each family, IPv4 and IPv6, per item or group |

The same `address` twice under one network is allowed and is listed in the duplicates
report. The same address under two networks is two different addresses.

An address that two devices share, the virtual address of a pair of routers or
firewalls, is an address of the group they are in, with the role `virtual`, held once.
Each member keeps its own management address. The shared address is then no duplicate,
and the report is left with the repeats nobody meant.

Only an address with the role `management` may be primary. A device may be managed
over IPv4, over IPv6, over both or over neither, so there is one primary of each
family: marking an address as primary takes the mark off the one of its own family
that had it, in the same change. An address is removed
outright, and so is a network that no address is under; each removal is an audit event
that holds what was removed.

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
lists are `catalog_type`, `catalog_function`, `state_reason`, `item_condition`,
`contact_role`, `location_kind`, `replacement_reason` and `capacity_category`. A value is lower-case
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
| `time_zone` | America/New_York | the application's time zone: every time is shown in it, to everybody |
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
`sign_in_failed`, `preview`, `apply`, and so on), `record_type`, `record_hid`, and
`changes`, a list of `{field, old, new}`. One import or bulk edit shares one
`request_id`. A record changed by an import has `via` of `import`; one changed by a
bulk edit has the door the edit came through.

### `import_jobs` and `import_rows`

A preview of a change to many records, kept so that what is applied is what was shown.

| Field | Type | Notes |
|---|---|---|
| `source` | choice | `file` for an import, `bulk` for a bulk edit |
| `entity` | choice | `tags`, `vendors`, `catalog_entries`, `owners`, `networks`, `items`, `addresses`, `device_groups`, `device_group_members`, and each further record type as its release arrives |
| `mode` | choice | `create` or `upsert` for a file. A bulk edit is `update`: every row names a record that exists |
| `file_name`, `file_sha256` | text | of the file as it was sent; blank for a bulk edit |
| `status` | choice | `previewed`, `applied`, or `failed` when it could not be applied because a record had changed |
| `row_count`, `created`, `updated`, `unchanged`, `rejected` | integer | the counts of rows by what the preview found |
| `skip_rejected` | boolean | whether it was applied without its rejected rows |
| `failure` | text | why a `failed` job was not applied |
| `applied_at`, `applied_by` | timestamp, user HID | when it was applied, and by whom |

The job carries `created_at` and `created_by`, for who made the preview. Anybody who
holds the Inventory role may apply it. Its rows are kept one to a record in `import_rows`, as a row-level report in JSON:

| Field | Type | Notes |
|---|---|---|
| `job_hid`, `row` | reference, integer | rows are numbered from 1, in the order of the file |
| `outcome` | choice | `create`, `update`, `unchanged` or `rejected` |
| `record_hid` | reference | the record the row matched, or created once applied |
| `row_version` | integer | the version that record was previewed at |
| `key` | text | how the row names its record, for people |
| `values` | JSON | the row as read: a column that is absent is left alone, `null` clears |
| `changes` | JSON | a list of `{field, old, new}` in the columns of the file |
| `reasons` | JSON | for a rejected row, a list of `{field, message}` |
| `notes` | JSON | what else the row brings about, such as a catalog entry created unreviewed |

Jobs and their rows are kept without expiry, like audit events.

### `idempotency_keys`

One row for each `Idempotency-Key` a caller has sent in the last 24 hours: `user_hid`,
`key`, a hash of the request it came with, and the status and body of the answer once
there is one. Unique on the caller and the key. Rows older than a day are removed as new
ones arrive. See "Idempotency" in [interfaces.md](interfaces.md).

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
disposition and no intent, may be given any state as its first, and is counted like any
other item in the view: a blank does not take it out of a count.

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

A **minor item** may leave all three blank and then has those of the item above it;
see "Minor items" under `items`. Given a state, it follows the rules of this section
like any other item. `POST /items/{hid}/transition` with `to` as `null` returns it to
inheriting, and is recorded as the move it is. For a major item that is refused: an
item leaves a state by moving to another.

An item **should be monitored** when it is a major item in Test or Prod and
`expected_online` is true. That is an expectation for reports to compare against, not a
switch that enrols anything.

## Condition, observation and health

Three facts say how an item is doing, and they are kept apart because they are known
by different people and change at different speeds.

| Fact | Field | Who says | Values |
|---|---|---|---|
| The state of the hardware | `condition` | a person; it holds while the item is on a shelf | the `item_condition` list: `untested`, `good`, `degraded`, `suspect`, `failed`, `dead` |
| What is seen now | `observed_status`, `observed_at` | by hand or by an import; LATER a monitoring tool | `online`, `degraded`, `unreachable` |
| What is meant | `expected_online` | the lifecycle; see above | true or false |

`untested` is new and not yet tried, `good` is the last known good, `degraded` runs
with a fault such as a failed fan, `suspect` is thought to be bad, `failed` has a
hardware fault, and `dead` will not come back. The list can be edited. A condition is
an ordinary field, audited like any other, and moves the item nowhere in the
lifecycle: an item whose hardware failed is moved to Down or to Pending-Removal by a
transition, with its own reason.

`observed_status` is an observation and not a wish. Clearing it clears `observed_at`.
An import may give `observed_at` with it, for a status that was read from another tool
earlier; left out, it is the moment of the change. Minor items inherit neither the
condition nor what is observed: each is a fact about one piece of hardware.

**Health** is worked out from those three when a record is read, and is stored
nowhere. It is one of `good`, `degraded`, `failed` and `unknown`, and comes with its
reasons. For an item it is the worst of:

| Health | When |
|---|---|
| `failed` | the condition is `failed` or `dead`; or the item is expected online and is observed `unreachable` |
| `degraded` | the condition is `degraded` or `suspect`; or it is observed `degraded`; or it is observed `unreachable` and is not expected online |
| `good` | the condition is `good` and nothing observed says otherwise; or it is observed `online` and no condition says otherwise |
| `unknown` | nothing is said: the condition is blank or `untested`, and nothing is observed |

A **stack** and a **cluster** have a health too, from their current members and from
what is observed of the group itself:

- `failed` when the group is observed `unreachable`, or every current member is
  `failed`;
- `degraded` when it is observed `degraded`; when a member is `failed` or `degraded`;
  when a member is in Down or Pending-Removal; when it has fewer current members than
  `expected_members`; or, for a stack that names no number, when it is its master
  alone;
- `good` when it is observed `online` or every member is `good`, and nothing above
  holds;
- `unknown` otherwise, and for a group with no members.

A controller domain and a custom group have none. `expected_members` is how a stack
whose failed switch has been taken out for an RMA still shows as short of one.

A page shows health as a colour: green for `good`, amber for `degraded`, red for
`failed`, grey for `unknown`. LATER, a monitoring tool writes `observed_status`, and
the same colours then follow what it reports.

## Identity and matching

When an import row or, later, a discovery observation must be matched to an item, the
first rule that applies decides, and no later rule is tried:

1. `hid` is given: that record, or an error if there is none.
2. Vendor, PID and serial number are given: the item with that triple.
3. `asset_tag` is given: the item with that tag.
4. Neither serial number nor asset tag is given: the one item with that `name` (or
   `hostname`, when the item's name is blank) that is not retired and itself has no
   serial number.
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
| Component count | Major items of `count_kinds` in the view, whose state is one of `count_states` or is blank. The view decides whether drafts and retired records are among them; unless asked, they are not. An item with no catalog entry is counted as hardware. |
| Managed-node count | Of those: each current stack counts as one, each current cluster as its `managed_as` says, and each item in neither counts as one. |
| Support weight | Sum over major items in `weight_states` of effective `support_weight` × `quantity`, each stack member multiplied by (1 − its model's effective stack discount ÷ 100). Summed exactly, and rounded to two places once, half up. |
| Estimated value | Sum of effective `est_value` × `quantity` over all items in the set, major and minor. |
| Annual support cost | Sum of effective `annual_support_cost` × `quantity` over all items in the set. No stack discount. |

**How a cluster is managed** decides what it is on the network, and so how it is
counted. A cluster says so itself, in `managed_as`:

| `managed_as` | The cluster on the network | Managed nodes |
|---|---|--:|
| `one` | one device: its members do not appear by themselves, as a pair of wireless LAN controllers in HA with one address to manage | 1 |
| `members` | every member is managed at its own address, and virtual addresses are shared between them, as a pair of firewalls in HA | one for each member |
| `members_and_cluster` | every member is managed, and the cluster answers as a virtual node of its own as well | one for each member, and one more |

Each member is a component whichever it is, and the support weight does not depend on
it. An item in both a stack and a cluster is part of the cluster's node where the
cluster is managed as `one`, and otherwise counts through its stack. In a view that
holds only some of a cluster's members, the cluster's own virtual node is counted
where any of its members is.

A stack or a cluster is **current** for these measures when the group is `active` and
the membership has no `left_on`. The stack discount is earned by the members of a
stack that has two or more current members: one switch alone takes the full effort. A draft stack is not yet one device on the network:
its members count as the items they are, and earn no discount. In a view that includes
drafts it is counted as if active, as a draft item is.

The sums are exact however large they grow: a licence of a thousand million seats does
not round the total.

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
lifecycle state, disposition, owner, location, address, the item and the group of an
address and of a membership, contract number, each end-of-life date, `updated_at`, and
the tag links by record. Region and location
ancestry is answered with recursive queries; a stored closure is added only if a
measurement asks for it.
