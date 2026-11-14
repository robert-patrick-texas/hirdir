# Interfaces

The API, the filter grammar, file import and export, the CLI and the web UI. All four
front doors reach the same rules on the server.

## API

Everything is under `/api/v1`. The OpenAPI document at `/api/v1/openapi.json` is the
contract: it is written and reviewed before the code behind a route, and the web UI's
and CLI's types are generated from it.

### Conventions

| Subject | Rule |
|---|---|
| Names | `snake_case` fields, plural kebab-case paths: `/catalog-entries`, `/device-groups` |
| Record routes | `GET /items`, `POST /items`, `GET /items/{hid}`, `PATCH /items/{hid}`, `POST /items/{hid}/retire` |
| Lists | `GET` with `filter`, `sort`, `limit`, `offset`, `fields`. Returns `{items, total, limit, offset}`. `limit` is at most 1000 and `offset` at most 10,000,000 |
| Fewer fields | `fields=hid,name,catalog.pid` returns only the fields named, of each record of a list. A name is a field of the record as the route returns it, or one field of a record within it, written with a dot. `hid` and `row_version` are always returned. A name the record does not have is a `422` |
| Default view | A list leaves out drafts, retired records and items in Archived. `include_drafts=true` and `include_archived=true` show them. A record is always reachable by its HID |
| Large filters | `POST /items/query` takes the same parameters as a JSON body |
| Updates | `PATCH` with only the fields to change and the `row_version` it was read at. A field left out is left alone. A field sent as `null` is cleared, and one that inherits then inherits again. A change that changes nothing leaves the version alone |
| Retiring | `POST /items/{hid}/retire` with the `row_version`. `PATCH` with `record_status` of `active` or `draft` brings a record back |
| Removing | `DELETE /addresses/{hid}`, and `DELETE` on a network or a tag that nothing uses. Nothing else is removed |
| Errors | RFC 9457 problem documents. `401` not signed in, `403` role too low, `404`, `409` stale `row_version` or uniqueness, naming the field that collides, `422` invalid input with a list of fields. A lifecycle move or combination that the rules refuse is a `422`. Two requests that collide at the same moment are answered like any other collision: `409`. A change that waited more than five seconds for another to be stored, as it may behind a large import being applied, is a `503` with `Retry-After`: nothing of it was done, and it may be sent again. An error nobody foresaw is a `500` problem document that names its request ID, and the details go to the log |
| Request ID | Every response carries `X-Request-Id`. The same value is on the audit events it caused |
| Idempotency | A `POST` that changes an inventory record, a tag or a choice, an import or a bulk edit accepts `Idempotency-Key`, a value of the caller's choosing of at most 200 characters. The answer to a request that succeeded is kept for 24 hours for that caller and key, and the same request sent again is answered with it, marked `Idempotency-Replayed: true`, and carried out no second time. The same key on a different request is a `422`. While the first request is still being worked on, a second is a `409`. An answer of more than a megabyte is not kept. Should the server stop after storing a change and before keeping its answer, the key stays taken: the request sent again is a `409`, never a second change, and what it was to change is read to see that it was. A query, which is a list asked for with a `POST`, takes no key, and a caller who no longer holds the Inventory role is given no kept answer. The routes of accounts refuse the header with a `422`: their answers may hold an access code or a token, which is shown once and kept nowhere |

### Routes

| Area | Routes |
|---|---|
| Access | `POST /auth/sign-in`, `POST /auth/sign-out-everywhere`, `GET /auth/me` |
| Accounts (Admin) | `/users`, `/user-groups`, `/role-grants`, `/users/{hid}/access-code`, `/users/{hid}/service-tokens` |
| Catalog | `/vendors`, `/catalog-entries`, `GET /vendors/{hid}/portfolio` |
| Items | `/items`, `GET /items/{hid}/children`, `GET /items/{hid}/history`, `POST /items/{hid}/transition`, `POST /items/{hid}/replace` |
| Groups | `/device-groups`, `POST /device-groups/{hid}/retire`, `GET` and `POST /device-groups/{hid}/members`, `PATCH /device-groups/{hid}/members/{member_hid}` |
| Addresses | `/networks`, `/addresses` |
| Geography | `/regions`, `/sites`, `/locations`, `GET /geography/tree`, `GET /locations/{hid}/effective` |
| People | `/contacts`, `/contact-assignments`, `/owners` |
| Contracts | `/contracts`, `/contracts/{hid}/coverage` |
| Purchases | `/purchase-requests`, `/purchase-requests/{hid}/lines`, `POST /purchase-lines/{hid}/receive` |
| External systems | `/external-systems`, `/registrations` |
| Capacity | `/capacity-lines`, `GET /reports/capacity` |
| Labels and lists | `/tags`, `/choices`, `/settings`, `PUT /settings/{key}`, `/lifecycle-rules` |
| Bulk | `POST /items/bulk-update`, `POST /items/bulk-update/{hid}/apply` |
| Files | `POST /imports/preview`, `POST /imports/{hid}/apply`, `GET /imports`, `GET /imports/{hid}`, `GET /imports/{hid}/rows`, `POST /exports` |
| Reports | `GET /reports/summary`, `/reports/management`, `/reports/end-of-life`, `/reports/coverage`, `/reports/duplicates` |
| Audit | `GET /audit-events` |
| Health | `GET /health/live`, `GET /health/ready` (no sign-in needed) |

### Roles

| Action | View-only | Inventory | Admin |
|---|:-:|:-:|:-:|
| Read any inventory record, run reports, export | yes | yes | yes |
| Create, change, retire, import, bulk-update inventory records | | yes | yes |
| Edit choices, tags | | yes | yes |
| Edit settings and lifecycle rules, force a lifecycle move | | | yes |
| Users, groups, role grants, access codes, service tokens | | | yes |
| Read audit events | yes | yes | yes |

## Filter grammar

One grammar is used by list routes, exports, bulk updates, the CLI and the grid.

```json
{
  "and": [
    { "field": "lifecycle_state", "op": "in", "value": ["Test", "Prod"] },
    { "field": "hostname", "op": "regex", "value": "^site2-sw-(core|dist)-[0-9]+$" },
    { "or": [
        { "field": "catalog.pid", "op": "glob", "value": "C9300*" },
        { "field": "tags", "op": "has", "value": "refresh-2028" }
    ] },
    { "field": "location", "op": "within", "value": "Americas > Central" },
    { "field": "effective.ldos", "op": "lt", "value": "2029-01-01" }
  ]
}
```

| Operator | Applies to | Meaning |
|---|---|---|
| `eq`, `ne` | any | equal, ignoring case for text. `ne` also finds a blank |
| `in` | any | one of a list of at most 1000 |
| `contains`, `prefix` | text | |
| `glob` | text | `*` and `?` |
| `regex` | text | bounded; see [architecture.md](architecture.md). Matches anywhere in the value unless anchored with `^` and `$` |
| `lt`, `lte`, `gt`, `gte`, `between` | numbers, dates | |
| `empty` | any | `true` for blank, `false` for not blank |
| `has` | tags | carries the tag. `empty` on `tags` finds records with none |
| `within` | region, site, location | at or beneath the named place, by HID or path |

Fields are the record's own, plus dotted fields of related records that the route
allows (`catalog.pid`, `catalog.vendor`, `owner.label`, `contract.number`,
`group.name`, `address`, `network.label`) and `effective.<field>` for inherited ones.
`mac_address` and `address` accept any common notation and are normalized before
comparison. On the item list `is_major` and `depth` tell major items from minor ones,
`parent.name` is the name of the item a minor item is in, `owner.label` is the label
of the owner in force, and `group.name`, `group.type`, `group.hid`, `address` and
`network.label` find an item by any of its current groups and any of its addresses,
and `condition`, `observed_status`, `observed_at` and the derived `health` say how it
is doing. On the list of groups, `member.serial_number` finds a stack by the serial
number of any current member. For a field an item may have several of, `eq` is true when one of them matches, and `ne` and `empty` when none does.
A field that an item may have several of cannot be sorted by. A field or operator the route does not allow is a `422`. Every comparison
of text ignores case, a regular expression included. A field that is a fixed choice,
such as `lifecycle_state`, takes `eq`, `ne`, `in` and `empty` only.

A filter nests at most 8 deep and holds at most 100 conditions, and a value is at most
1000 characters. Its JSON Schema is `contract/filter.schema.json`. A value that the
field could never hold, such as a number with more decimal places than money has, is a
`422`.

`sort` is a list such as `["site", "-effective.ldos"]`, written `sort=site,-effective.ldos`
in a URL. Text sorts without regard to case, blank values come last in either
direction, and rows that tie keep a steady order, so paging never repeats or skips one.
On the item list, `name` filters and sorts by the hostname when the name is blank.

The short form used by the CLI and by `filter=` in a URL is one condition per
`field:op:value`, joined by AND: `lifecycle_state:in:Test,Prod hostname:prefix:site2-`.
A value runs to the start of the next condition, so it may hold spaces, and the values
of `in` and `between` are separated by commas. A value that itself looks like the start
of a condition, `word:word:`, is refused, because it is nearly always a mistyped
operator; the JSON form takes any value. `filter=` also takes the JSON form.

## Import and export

### Formats

**JSON** has an envelope:

```json
{
  "schema": "hirdir/1",
  "entity": "items",
  "mode": "upsert",
  "records": [
    {
      "vendor": "Cisco",
      "pid": "C9300-48P",
      "serial_number": "FCW0000X001",
      "asset_tag": "AT-000123",
      "name": "site2-sw-access-01",
      "lifecycle_state": "Prod",
      "disposition": "Production",
      "expected_online": true,
      "owner": "Network Engineering",
      "location": "Americas > Central > Site-2 > Building 1 > Room 102",
      "mgmt_address": "192.0.2.10",
      "mgmt_network": "Red",
      "tags": ["refresh-2030"]
    }
  ]
}
```

**CSV** holds the same columns, one header row, UTF-8. Lists are joined with `;`.
The entity and mode are given beside the file, not in it.

```csv
hid,vendor,pid,serial_number,asset_tag,name,lifecycle_state,disposition,expected_online,owner,location,mgmt_address,mgmt_network,tags
,Cisco,C9300-48P,FCW0000X001,AT-000123,site2-sw-access-01,Prod,Production,true,Network Engineering,Americas > Central > Site-2 > Building 1 > Room 102,192.0.2.10,Red,refresh-2030
```

### Columns

A file names its columns as the fields are named on the [data model](data-model.md)
page, with a reference written as people write it: `vendor` and `pid` for a catalog
entry, `owner` for an owner's label. Release 0.3.0 carries the records that exist so
far, and 0.4.0 adds networks, addresses, device groups and their members. A column of
a later release, such as `location`, is unknown until that release.

| Entity | Columns that can be set | Further columns an export can write |
|---|---|---|
| `tags` | `label`, `colour`, `description` | |
| `vendors` | `name`, `aliases`, `notes`, `review_status` | |
| `catalog_entries` | `vendor`, `pid`, `model_name`, `kind`, `type`, `function`, `description`, `end_of_sale`, `end_of_sw_support`, `end_of_hw_support`, `ldos`, `est_value`, `support_weight`, `annual_support_cost`, `stack_discount_pct`, `successor_vendor`, `successor_pid`, `review_status`, `record_status`, `tags` | `stack_discount_pct_source` |
| `owners` | `label`, `organization`, `is_external`, `exception_reason`, `record_status` | |
| `networks` | `label`, `kind` | |
| `items` | `vendor`, `pid`, `serial_number`, `asset_tag`, `name`, `hostname`, `fqdn`, `mac_address`, `parent`, `position`, `description`, `comments`, `quantity`, `lifecycle_state`, `disposition`, `expected_online`, `state_reason`, `condition`, `observed_status`, `observed_at`, `owner`, `mgmt_address`, `mgmt_ipv4`, `mgmt_ipv6`, `mgmt_network`, `procured_on`, `delivered_on`, `in_service_on`, `warranty_start`, `warranty_end`, `est_value`, `support_weight`, `annual_support_cost`, `end_of_sale`, `end_of_sw_support`, `end_of_hw_support`, `ldos`, `record_status`, `tags` | `model_name`, `kind`, `type`, `function`, `state_changed_at`, `is_major`, `depth`, `health`, and a `_source` for each of the eleven fields that inherit |
| `addresses` | `item`, `group`, `address`, `network`, `role`, `is_primary` | `family` |
| `device_groups` | `name`, `type`, `hostname`, `fqdn`, `parent`, `owner`, `managed_as`, `expected_members`, `observed_status`, `observed_at`, `mgmt_address`, `mgmt_ipv4`, `mgmt_ipv6`, `mgmt_network`, `record_status`, `tags` | `serial_number`, `members`, `health` |
| `device_group_members` | `group`, `item`, `role`, `position`, `joined_on`, `left_on`, `observed_master`, `master_observed_at` | |

Every entity has `hid` as its first column, and an export can also write `row_version`,
`created_at` and `updated_at`. In CSV, `true` and `false` are written so, `yes`, `no`,
`1` and `0` are read as well, and a list is joined with `;`. In JSON a list is a list, a
truth value is `true` or `false`, and a decimal is text; the words a CSV file may use
are read there too.

### Rules

| Subject | Rule |
|---|---|
| Entities | Every record type on the data model page, including memberships, coverage, assignments and registrations. Tags are among them. Choices, settings, lifecycle rules and the access records are not carried by files |
| Sending a file | The file is the body of `POST /imports/preview`, as `text/csv` or `application/json`, with `entity`, `mode` and `file_name` beside it in the URL. A JSON file names its entity and mode in its envelope, and the URL may leave them out; the two must not disagree |
| Modes | `create` refuses a row that matches an existing record. `upsert` creates or updates. There is no mode that deletes |
| Matching | By `hid` when given, otherwise by the entity's key: a tag's label, a vendor's name or alias, a catalog entry's vendor and PID, an owner's label, a network's label, a device group's name. For items, the order on the data model page. An address is found by its item or group, its address and its network; a membership by its group, its item and `joined_on`, or with no `joined_on` the current one. Two rows of one file that name the same record: the second is rejected |
| References | By HID, or by the natural key: vendor name, `vendor` + `pid`, owner label, network label, contract number, geographic path, group name. An item is named by its HID, or by a serial number, an asset tag or a name that one item alone has; an export writes the asset tag when there is one, then the serial number, then the name, and the HID when another item answers to the same text. A name that has the form of an HID is read as one, so an export writes the HID of a record so named |
| Minor items | `parent` names the item a minor item is in, and `!clear` takes it out. An item that a file creates stands before the minor items the same file puts in it: an export sorted by `depth` writes them so. Rows that change items that exist are worked an item before its minor items, wherever they stand, so that a row with the owner or the state its item would inherit anyway leaves it inheriting, also when the same file changes the item above. A bulk edit is worked in the same order |
| Management address | An item and a device group have a primary management address of each family. `mgmt_ipv4` and `mgmt_ipv6` set them, and `mgmt_address` takes an address of either family and files it under its own. A value changes the one there is or adds one; `!clear` removes it, and in `mgmt_address` removes both. `mgmt_network` is the label of the network the addresses of the row are under. It is optional: with no such column the network stays as it is, and a new address is in the unlabelled address space. An export writes it where both addresses are under one network, and leaves it blank where they are under two, so that a file loaded back moves neither. A row that names `mgmt_network` and no address is rejected. Every address of a record, these among them, is in the `addresses` entity, so an export writes these columns only when they are asked for by name |
| A first file | A file of host names, with or without addresses, loads as it is: `hostname` alone makes an item, and loading it again finds each item by its host name and changes nothing. The spellings such a file is likely to use are read as the columns they mean: `ip_address`, `ip` and `mgmt_ip` as `mgmt_address`, `ipv4_address` and `ipv4` as `mgmt_ipv4`, `ipv6_address` and `ipv6` as `mgmt_ipv6` |
| Groups | A group is loaded before its members. The groups of one file are worked a group before the groups within it, wherever they stand. A row of members with the role `master` marks the master that is intended, and takes the mark from the member that had it. `observed_master`, true on the row of one member, records on the stack that this member is seen to be master, with `master_observed_at` or else the moment of the change. One file names one intended master and one observed master of a stack at most: a second row that names one is rejected |
| Observation | `observed_status` is `online`, `degraded`, `unreachable` or `present`, and `observed_at` the moment it was seen: left out, the moment of the change. A row that states a status as it is, with no moment, changes nothing, where a person who does so on a page or by a bulk edit has looked again and sets the moment to now. `!clear` in `observed_status` clears both, and a moment is not cleared by itself. What a preview tells of a row leaves out a moment that the clock will set, since the apply is made later. A site that reads the status of its devices from another tool, or walks its store room, loads the result as a file of `hostname`, `observed_status` and `observed_at` |
| Missing references | A vendor or catalog entry that does not exist is created and marked `unreviewed`. Any other missing reference rejects the row. A catalog entry that a file's own later row describes is created by that row, and is then as reviewed as the row says |
| Blank cells | Leave the stored value alone. In JSON, so does a field that is left out, or one that is empty text |
| Clearing | The literal `!clear` in a cell, or `null` in JSON, clears the value so that it inherits again. In JSON an empty list clears a list |
| Inherited values | An import does not turn an inherited value into an override. Where a field inherits and the record has no value of its own, a cell that holds the very value it inherits leaves it inheriting. That is so for an item and its model, for a catalog entry and the global stack discount, for a row that gives an item another model while still holding the values of the old one, and for a minor item and the owner and standing of the item above it |
| Lifecycle | A row with a different `lifecycle_state` moves the item by a transition, under the rules of moves and never by force, with the row's `state_reason` as the why and its `disposition` and `expected_online` as named. A `state_reason` is taken with a move only. `!clear` in `lifecycle_state` returns a minor item to the standing of the item above it, and is refused for a major item |
| Retiring | An import does not retire. A row that would change `record_status` to `retired` is rejected; a row may bring a retired record back with `active` or `draft` |
| Unknown columns | Reject the file, naming the column. A column that an export writes and nobody can set is not unknown: it is passed over, so any export can be imported back |
| Preview | `POST /imports/preview` stores the parsed file and returns, per row: `create`, `update` with the changed fields, `unchanged` or `rejected` with reasons. A file that cannot be read at all is refused with a `422`, and nothing is stored. The answer holds the counts and the first hundred rows; `GET /imports/{hid}/rows` pages through all of them, and `outcome=rejected` keeps to one kind |
| Apply | `POST /imports/{hid}/apply` applies exactly what was previewed, in one transaction. If any record it would touch has changed since, nothing is applied and a new preview is asked for |
| What "changed since" means | Apply works the file through again. Every row must come out as it was previewed, with the same changes and the same notes, and every record a row matched must be at the version it was previewed at, also when the row was `unchanged`. Otherwise the answer is a `409` that names the rows, the first fifty of them, and the job is `failed` |
| Whose preview | A preview is applied once, by anybody who holds the Inventory role, whoever made it: one person may prepare a file and another look it over and apply it. The job says who made it and who applied it. Anybody who may read the inventory may read it |
| Rejected rows | By default any rejected row blocks the apply, with a `422`, and the preview stays good. `skip_rejected=true` applies the rest |
| Limits | 20 MB and 100,000 rows per file. A larger file is a `413`. A site may raise the 20 MB in its configuration file and in nginx; see [install.md](install.md#uploads). Behind the packaged nginx a body of more than 20 MB is refused by nginx itself, with a `413` that is nginx's own page and not a problem document |
| Load order | tags, vendors, catalog entries, regions, sites, locations, contacts, contact assignments, owners, networks, contracts, purchase requests, items (parents before children), device groups, members, addresses, coverage, registrations, capacity lines. Addresses come after the groups, because a group has addresses too |
| Audit | Each record an import creates or changes has its own audit event, with `via` of `import`, and all of them share the request ID of the apply. The preview and the apply are events on the job |

### Export

`POST /exports` takes an entity, a filter, a sort, a list of columns, a format (`csv` or
`json`) and optionally a list of at most 10,000 HIDs. The response is streamed. `hid`
is always the first column. Inheritable fields export their effective value;
`include_sources=true` adds the `_source` columns, and `own_values=true` exports stored
values instead, which is the form to use for a file that will be imported back.

Left out, the columns are the ones that can be set. A column may also be named as a
filter names it: `catalog.pid` is `pid`, `owner.label` is `owner` and `effective.ldos`
is `ldos`. Left out, the sort is the list's own. `include_archived` and
`include_drafts` mean what they mean on a list. Records named by their HIDs are
exported whatever their status, as a bulk edit changes them: what a person selected is
what the file holds. A filter sent beside the HIDs still narrows them; the grid sends
the HIDs alone. A JSON export is the envelope above, so
it can be imported as it is.

A CSV cell that begins with `=`, `+`, `-` or `@` is written with a leading apostrophe so
a spreadsheet does not run it as a formula. Import removes that apostrophe again. A
value that itself begins with an apostrophe before such a character is written with one
more, so that it comes back as it was.

Device groups export `serial_number`, which for a stack is that of the master seen or
else of the one intended, `members`, the number of current ones, and `health`. None
of them can be set.

Every template in `examples/` is produced by exporting the seeded example database, so
the templates can never drift from the importer. `make examples` writes them, and a
test fails when they are out of date.

### Bulk edit

`POST /items/bulk-update` takes the rows, as a filter or as a list of at most 10,000
HIDs, and the change: `set`, which names columns of an import and their new values,
with `null` to clear one, and `add_tags` and `remove_tags`. The fields that tell one
item from another cannot be set on more than one item at once: `serial_number`,
`asset_tag`, `mac_address`, `name`, `hostname`, `fqdn` and `mgmt_address`. A change that names a single
item by its HID may set them. A filter leaves out what a list leaves out, unless
`include_archived` or `include_drafts` says otherwise; items named by their HIDs are
changed whatever their status. One bulk edit changes at most 100,000 items, and more is
a `413`.

The answer is a preview of the same kind as an import's, with before and after for each
row, and it is stored in the same way. `POST /items/bulk-update/{hid}/apply` applies
it under the same rules: in one transaction, once, by anybody who holds the Inventory
role, and not at all when any of its records has changed since. A second person who bulk-edits rows that the
first has just changed is told which, and none of their change is applied.

## Reports

Two reports count a view of the items. Each takes `filter`, `include_drafts` and
`include_archived` as the item list does, and `by`. The answer holds `totals` and, when
`by` is given, `rows`, one for each value, the blank among them.

**The summary**, `GET /reports/summary`, is for the people who run the network. It
holds no money.

| Measure | |
|---|---|
| `items` | every item of the view, major and minor |
| `component_count`, `managed_node_count`, `support_weight` | as defined under "Counting and weight" on the [data model](data-model.md#counting-and-weight) page |
| `by_health` | the components that are `good`, `degraded`, `failed` and `unknown`; see "Condition, observation and health" |
| `by_condition` | on `totals` only: the components of each condition, and those with none |
| `by_kind` | on `totals` only: items and components of each kind, so that software and services stand beside the headline count |

`by` is one of `vendor`, `kind`, `type`, `function`, `owner`, `lifecycle_state`,
`disposition`, `condition`, `health` and `tag`.

**The management report**, `GET /reports/management`, is for the people who pay for
the network. It holds `items`, `component_count`, `est_value` and
`annual_support_cost`, and neither condition nor health. `by` is one of `vendor`,
`kind`, `type`, `function`, `owner` and `tag`. From 0.5.0, which has sites, it is also
by `site`, and that is what it shows when no `by` is given: the whole inventory, and
each site beneath it.

In both, `region` and `contract` join `by` as those records arrive. A row of `type` or
`function` is labelled as its list of choices labels the value. A minor item is in the
row of the owner, state and disposition in force for it. An item with several tags is
in the row of each, and the totals count it once. A stack whose members fall in two
rows is a managed node in both, and one in the totals.

`GET /reports/duplicates` lists each address that is held more than once under one
network, with the unlabelled address space as one network of its own: the address, the
network, and the items and groups that hold it. A holder that a list leaves out by
default is not counted, unless `include_drafts` or `include_archived` asks for it. It
pages with `limit` and `offset`.

The end-of-life and coverage reports arrive in 0.6.0.

## CLI

`hirdir` is one command with two halves.

**Client commands** talk to the API and work from any machine:

```bash
hirdir sign-in                                   # asks for username and access code
hirdir items list --filter 'lifecycle_state:eq:Prod location:within:Americas > Central'
hirdir items show FCW0000X001                    # by HID, serial number, asset tag or name
hirdir items set <hid> disposition=Spare expected_online=false
hirdir items set --filter 'tags:has:refresh-2030' owner='Voice Services'          # preview
hirdir items set --filter 'tags:has:refresh-2030' owner='Voice Services' --apply
hirdir items transition <hid> Down --reason maintenance
hirdir items transition PS-A inherit             # a minor item: the standing of the item it is in
hirdir items set PS-A parent=FCW0000X002 position=PS-B
hirdir groups list --filter 'type:eq:stack'
hirdir groups show site2-sw-stack1               # by HID or name; --include-past for who has left
hirdir addresses list --filter 'network.label:eq:Red'
hirdir vendors portfolio Cisco --format csv --output cisco-renewal.csv
hirdir import items.csv --entity items                 # preview only
hirdir import items.csv --entity items --apply
hirdir import items.csv --entity items --apply --skip-rejected
hirdir export items --filter 'tags:has:refresh-2030' --format json --output refresh.json
hirdir report summary --by health --format json
hirdir report management --by owner
hirdir report duplicates
hirdir report capacity --include-drafts
```

| Subject | Rule |
|---|---|
| Server and token | `--url` and `--token`, or `HIRDIR_URL` and `HIRDIR_TOKEN`, or `~/.config/hirdir/config.toml`, in that order |
| Output | A table on a terminal. `--format json` or `csv` for scripts. Data on stdout, messages on stderr |
| Lists | `hirdir items list`, and `vendors`, `catalog`, `owners`, `tags`, `networks`, `addresses` and `groups` in its place, take `--filter`, `--sort` and `--columns`. A table shows the first 50 rows, or as many as `--limit` says. As `csv` or `json` a list is every row, and is the very file that `hirdir export` writes for the same filter, sort and columns |
| Times | In a message or a table, the application's time with the name of the zone, as the web UI shows it. `--format json` and `csv` carry what the API sends, in UTC |
| Exit codes | `0` done, `2` usage, `3` not signed in or not allowed, `4` validation or rejected rows, `5` conflict, `6` server or network |
| Changes | Anything that changes more than one record previews first and needs `--apply` |
| An item, by what it is known | Where a command takes an item, it takes the HID, or a serial number, an asset tag or a name that one item alone has. More than one is listed, and nothing is done |
| A group | `hirdir groups show` takes the HID or the name, and prints the group with its health, its current members and their roles, and for a stack the master that is intended, the one that is seen, and the serial number that follows |
| Reports | `hirdir report summary` and `hirdir report management` take `--filter`, `--by`, `--include-drafts` and `--include-archived`, and print the totals and one row for each value. `hirdir report duplicates` lists the addresses held more than once |
| A value | `field=value` sets, `field=` clears. A field is named as a column of an import |
| Secrets | Never echoed, never in logs |

**`hirdir admin`** runs on the server as root or the service user and works on the
database directly, because it must work before any account exists:

```bash
hirdir admin create-user --role admin NAME       # prints a new access code once
hirdir admin reset-access-code NAME
hirdir admin migrate
hirdir admin backup
hirdir admin restore FILE
hirdir admin reset                               # clear the inventory; --everything for all
hirdir admin check                               # schema version, integrity, settings
hirdir admin serve                               # what the service runs
```

Run as root, an admin command first steps down to the user that owns the state
directory, so it never leaves behind a file the service cannot write.

`hirdir admin reset` is for a site that has loaded test data and wants to start over.
It is on the server and nowhere else: no page and no route of the API clears anything.
It refuses while the service is running, says what it will remove and how many, takes a
backup, and goes on only when the word `reset` is typed, or `--yes` is given by a
script. It removes the items with their replacements, addresses and memberships, the
device groups, networks, catalog entries, vendors, owners, tags and stored imports,
and the audit events of those records, and writes one audit event that says so and
names the backup. Accounts, groups, roles, service tokens, settings, choices and
lifecycle rules stay. `--everything` removes those too and leaves the database as a
fresh installation has it, with no account and an empty audit trail.

## Web UI

### Pages

| Page | Content |
|---|---|
| Sign in | Username, access code, a Sign in button |
| Home | The headline of the summary: component count beside managed-node count, support weight, and the components by health. No money. End-of-life and coverage warnings from 0.6.0 |
| Items | The main grid, with a health mark on each row, and minor items left out until "Include minor items" is turned on. Detail page: identity, catalog and effective values with sources, parent and minor items, groups, addresses, coverage, registrations, history |
| Catalog | Entries by vendor; the items of each entry |
| Vendors | The portfolio: everything from one vendor |
| Groups | Stacks, clusters and controller domains, with members and roles |
| Addresses | Every address, with the item or group that has it; the networks |
| Geography | The region tree, sites, locations, effective contacts with their source |
| Contacts, Owners | |
| Contracts | Coverage lists, gaps, expiries |
| Purchases | Requests and lines; receive a line |
| Import | Upload, preview, apply, past jobs |
| Capacity | Demand beside supply by category, the balance and coverage, with and without drafts; the lines, editable |
| Reports | Summary: components, managed nodes, support weight and health, whole and by owner, state, vendor and the rest. Management: estimated value and annual support cost, whole and by site. Duplicates. End of life and coverage from 0.6.0 |
| Admin | Users, groups, role grants, service tokens, settings, choices, lifecycle rules, tags. Every role sees this area: tags, choices and lifecycle rules are there for all to read and for Inventory to edit, and the rest shows to an Admin only |
| About | Version, the versions table, release notes |

### The grid

One grid component is used on every list page.

- Sort by one or more columns, filter per column, resize, reorder, show and hide
  columns. Sorting, filtering and paging are done by the server.
- Select whole rows: one, a range with Shift, several with Ctrl, or "all that match the
  filter", which is shown as a count and sent to the server as the filter, not as a list
  of rows.
- **Copy** puts the selected rows on the clipboard as tab-separated text with a header
  row. **Export** sends the current filter, sort and columns to `POST /exports`. With
  particular rows selected, copy, export and bulk edit all act on exactly those rows,
  named by their HIDs, also when one of them no longer matches the filter.
- **Edit** opens the record's form. **Bulk edit** opens a form for the selected rows,
  shows a before-and-after preview, and applies on confirmation.
- An inherited value is shown in a lighter style with its source on hover. Editing it
  creates an override; clearing an override returns it to inheriting.
- Archived and retired records are hidden until "Include archived" is on, then greyed.
- Column layout and the last filter are remembered per user in `localStorage`.

Cell-range selection and editing in the grid are LATER.

### Times

Every time on a page is in the application's time zone, the `time_zone` setting, and
carries the zone's short name. It is the same for everybody, whatever zone their own
machine is in, so two people who speak of a time mean the same moment. Pointing at a
time shows it written out in full with the name of the zone. A filter on a time is in
the days of that zone, and so is a time that is typed in.

### Waiting

The page that is loaded first holds sign-in and the first page and nothing else. Each
other page is a file of its own, fetched when it is opened, and all of them are fetched
in the background a moment after signing in, so opening the grid does not wait for its
code. A message that something is loading shows only when that takes more than a
moment.
