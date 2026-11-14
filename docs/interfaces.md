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
| Large filters | `POST /items/query` takes the same parameters as a JSON body, and so does `/query` on catalog entries, device groups, addresses and locations |
| Updates | `PATCH` with only the fields to change and the `row_version` it was read at. A field left out is left alone. A field sent as `null` is cleared, and one that inherits then inherits again. A change that changes nothing leaves the version alone |
| Retiring | `POST /items/{hid}/retire` with the `row_version`. `PATCH` with `record_status` of `active` or `draft` brings a record back |
| Removing | `DELETE /addresses/{hid}`, `DELETE /contact-assignments/{hid}`, `DELETE /owners/{hid}/members/{member_hid}`, and `DELETE` on a network or a tag that nothing uses. Nothing else is removed |
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
| Geography | `/regions`, `/sites`, `/locations`, each with `POST .../{hid}/retire`; `GET /geography/tree`; `GET /regions/{hid}/effective`, `GET /sites/{hid}/effective`, `GET /locations/{hid}/effective` |
| People | `/contacts`, `POST /contacts/{hid}/retire`, `/operators`, `POST /operators/{hid}/retire`, `/contact-assignments`, `/owners`, `GET` and `POST /owners/{hid}/members`, `PATCH` and `DELETE /owners/{hid}/members/{member_hid}` |
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
| `lt`, `lte`, `gt`, `gte`, `between` | numbers, dates, times | A time that names no zone is in the application's time zone |
| `empty` | any | `true` for blank, `false` for not blank |
| `has` | tags | carries the tag. `empty` on `tags` finds records with none |
| `within` | a place | at or beneath the named region, site or location, by HID or path. Takes `empty` as well |

Fields are the record's own, plus dotted fields of related records that the route
allows (`catalog.pid`, `catalog.vendor`, `owner.label`, `contract.number`,
`group.name`, `address`, `network.label`) and `effective.<field>` for inherited ones.
`mac_address` and `address` accept any common notation and are normalized before
comparison. On the item list `is_major` and `depth` tell major items from minor ones,
`parent.name` is the name of the item a minor item is in, `owner.label` is the label
of the owner in force, and `group.name`, `group.type`, `group.hid`, `address` and
`network.label` find an item by any of its current groups and any of its addresses,
and `condition`, `observed_status`, `observed_at` and the derived `health` say how it
is doing. `location` is where the item is, by the location in force, and takes
`within` with a region, a site or a location, and `empty`; `planned_location` is
where it is planned to go and takes the same two; `site` and `region` are the
names of its site and of the region the site is in, `site.code` the site's code, and
`location.name` and `location.kind` those of the location; `operator.label` is the label of the operator in force and `operator.contact` the
name of the person behind it, `operator.is_open` is true where nobody is,
`effective.operator_hid` is that operator, blank for an item that nobody is assigned
to, and `operator_hid` is the item's own. `owner_exception` is true
for an item whose owner in force is outside the team, and `owner_exception_reason` is
that owner's reason; the list of device groups has `owner_exception` too. The lists of device groups and
of locations have `location` with `within` too, and the list of sites has `region`. A
device group is found and sorted by `site` and `region` as an item is. A
location is also found by `site.name`, `site.code` and `region.name`, the name of the
region its site is in. On the list of groups, `member.serial_number` finds a stack by the serial
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
far, 0.4.0 adds networks, addresses, device groups and their members, and 0.5.0
regions, sites, locations, contacts, their assignments and the members of owners. A
column of a later release, such as `contract`, is unknown until that release.

| Entity | Columns that can be set | Further columns an export can write |
|---|---|---|
| `tags` | `label`, `colour`, `description` | |
| `vendors` | `name`, `aliases`, `notes`, `review_status` | |
| `catalog_entries` | `vendor`, `pid`, `model_name`, `kind`, `type`, `function`, `description`, `end_of_sale`, `end_of_sw_support`, `end_of_hw_support`, `ldos`, `est_value`, `support_weight`, `annual_support_cost`, `stack_discount_pct`, `successor_vendor`, `successor_pid`, `review_status`, `record_status`, `tags` | `stack_discount_pct_source` |
| `contacts` | `name`, `organization`, `email`, `phone`, `notes`, `record_status`, `tags` | |
| `operators` | `label`, `description`, `colour`, `contact`, `record_status` | `is_open` |
| `regions` | `name`, `parent`, `code`, the shipping set, `operator`, `notes`, `record_status`, `tags` | `path` |
| `sites` | `name`, `region`, `code`, the address fields, the shipping set, `operator`, `latitude`, `longitude`, `notes`, `record_status`, `tags` | `path` |
| `locations` | `name`, `site`, `parent`, `code`, `kind`, the address fields, the shipping set, `operator`, `latitude`, `longitude`, `notes`, `record_status`, `tags` | `path` |
| `contact_assignments` | `region`, `site`, `location`, `role`, `contact`, `priority`, `stop_inheritance` | |
| `owners` | `label`, `organization`, `is_external`, `exception_reason`, `record_status`, `tags` | |
| `owner_members` | `owner`, `contact`, `role`, `priority` | |
| `networks` | `label`, `kind` | |
| `items` | `vendor`, `pid`, `serial_number`, `asset_tag`, `name`, `hostname`, `fqdn`, `mac_address`, `parent`, `position`, `description`, `comments`, `quantity`, `lifecycle_state`, `disposition`, `expected_online`, `state_reason`, `condition`, `observed_status`, `observed_at`, `owner`, `operator`, `location`, `planned_location`, `mgmt_address`, `mgmt_ipv4`, `mgmt_ipv6`, `mgmt_network`, `procured_on`, `delivered_on`, `in_service_on`, `warranty_start`, `warranty_end`, `est_value`, `support_weight`, `annual_support_cost`, `end_of_sale`, `end_of_sw_support`, `end_of_hw_support`, `ldos`, `record_status`, `tags` | `model_name`, `kind`, `type`, `function`, `state_changed_at`, `is_major`, `depth`, `health`, `site` and `region` by their names, `owner_exception` and `owner_exception_reason`, and a `_source` for each of the thirteen fields that inherit |
| `addresses` | `item`, `group`, `address`, `network`, `role`, `is_primary` | `family` |
| `device_groups` | `name`, `type`, `hostname`, `fqdn`, `parent`, `owner`, `operator`, `location`, `managed_as`, `expected_members`, `observed_status`, `observed_at`, `mgmt_address`, `mgmt_ipv4`, `mgmt_ipv6`, `mgmt_network`, `record_status`, `tags` | `serial_number`, `members`, `health` |
| `device_group_members` | `group`, `item`, `role`, `position`, `joined_on`, `left_on`, `observed_master`, `master_observed_at` | |

The address fields are `address1`, `address2`, `city`, `state`, `postal_code` and
`country`, and the shipping set is the same six with `ship_` before them, and
`ship_instructions`. For a site and a location the shipping set has
`ship_same_as_address` as well, true or false.

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
| Matching | By `hid` when given, otherwise by the entity's key: a tag's label, a vendor's name or alias, a catalog entry's vendor and PID, an owner's label, an operator's label, a network's label, a device group's name. A region is found by its path, which is `parent` and `name`; a site by `region` and `name`; a location by `site`, `parent` and `name`. A contact is found by its email address, and a row with none by a name that one contact alone has, retired or not; of several of one name, such a row is the one that has no email address. An assignment is found by its place, its role and its contact, or as the one that stops inheritance for its place and role; a member of an owner by the owner and the contact. For items, the order on the data model page. An address is found by its item or group, its address and its network; a membership by its group, its item and `joined_on`, or with no `joined_on` the current one. Two rows of one file that name the same record: the second is rejected |
| References | By HID, or by the natural key: vendor name, `vendor` + `pid`, owner label, network label, contract number, geographic path, group name. A contact is named by its HID, its email address or a name that one contact alone has, and an export writes the email address when there is one. An item is named by its HID, or by a serial number, an asset tag or a name that one item alone has; an export writes the asset tag when there is one, then the serial number, then the name, and the HID when another item answers to the same text. A name that has the form of an HID is read as one, so an export writes the HID of a record so named |
| Minor items | `parent` names the item a minor item is in, and `!clear` takes it out. An item that a file creates stands before the minor items the same file puts in it: an export sorted by `depth` writes them so. Rows that change items that exist are worked an item before its minor items, wherever they stand, so that a row with the owner or the state its item would inherit anyway leaves it inheriting, also when the same file changes the item above. A bulk edit is worked in the same order |
| Management address | An item and a device group have a primary management address of each family. `mgmt_ipv4` and `mgmt_ipv6` set them, and `mgmt_address` takes an address of either family and files it under its own. A value changes the one there is or adds one; `!clear` removes it, and in `mgmt_address` removes both. `mgmt_network` is the label of the network the addresses of the row are under. It is optional: with no such column the network stays as it is, and a new address is in the unlabelled address space. An export writes it where both addresses are under one network, and leaves it blank where they are under two, so that a file loaded back moves neither. A row that names `mgmt_network` and no address is rejected. Every address of a record, these among them, is in the `addresses` entity, so an export writes these columns only when they are asked for by name |
| A first file | A file of host names, with or without addresses, loads as it is: `hostname` alone makes an item, and loading it again finds each item by its host name and changes nothing. The spellings such a file is likely to use are read as the columns they mean: `ip_address`, `ip` and `mgmt_ip` as `mgmt_address`, `ipv4_address` and `ipv4` as `mgmt_ipv4`, `ipv6_address` and `ipv6` as `mgmt_ipv6` |
| Places | `location` on an item and on a device group is the path of a location, or its HID, and so is `planned_location` on an item, which takes a location that is not in use yet. `parent` of a region is the path of the region it is in, `region` of a site the path of its region, and `site` of a location the path of its site. `parent` of a location is the path of the location it is in, whole or from the site down: `Building 1 > Floor 2`. A row of a location that names its parent whole need not name the site. The regions of one file are worked a region before the regions within it, and the locations likewise, wherever they stand. A row that would move a location to another site is rejected |
| Contacts of a place | A row of `contact_assignments` names one place, in `region`, `site` or `location`, with a `role` and a `contact`. A row with `stop_inheritance` true and no contact is the one that stops inheritance for that place and role. An import does not remove an assignment. In a file of `owner_members` the rows that name a primary are worked first, wherever they stand, so that the first member of an owner is its primary and a change of primary comes out right |
| The operator | `operator` on an item, a device group, a region, a site and a location names an operator by its label, and `!clear` returns the record to the operator it has from above. A row that names the operator an item has anyway, from the item above it, its group or its place, leaves it inheriting. The person behind a label is in the file of `operators`, in `contact`: an email address, or a name that one contact alone has, and `!clear` leaves the label open. An import does not retire an operator |
| An external owner | An item or a group that a row gives to an owner outside the team is marked as an exception by that alone. The reason is the owner's, in `exception_reason` of the file of owners; `owner_exception` and `owner_exception_reason` of an item are written by an export and passed over by an import |
| Groups | A group is loaded before its members. The groups of one file are worked a group before the groups within it, wherever they stand. A row of members with the role `master` marks the master that is intended, and takes the mark from the member that had it. `observed_master`, true on the row of one member, records on the stack that this member is seen to be master, with `master_observed_at` or else the moment of the change. One file names one intended master and one observed master of a stack at most: a second row that names one is rejected |
| Observation | `observed_status` is `online`, `degraded`, `unreachable` or `present`, and `observed_at` the moment it was seen: left out, the moment of the change, and with no zone named, in the application's time zone. A row that states a status as it is, with no moment, changes nothing, where a person who does so on a page or by a bulk edit has looked again and sets the moment to now. `!clear` in `observed_status` clears both, and a moment is not cleared by itself. What a preview tells of a row leaves out a moment that the clock will set, since the apply is made later. A site that reads the status of its devices from another tool, or walks its store room, loads the result as a file of `hostname`, `observed_status` and `observed_at` |
| Missing references | A vendor or catalog entry that does not exist is created and marked `unreviewed`. Any other missing reference rejects the row. A catalog entry that a file's own later row describes is created by that row, and is then as reviewed as the row says |
| Blank cells | Leave the stored value alone. In JSON, so does a field that is left out, or one that is empty text |
| Clearing | The literal `!clear` in a cell, or `null` in JSON, clears the value so that it inherits again. In JSON an empty list clears a list |
| Inherited values | An import does not turn an inherited value into an override. Where a field inherits and the record has no value of its own, a cell that holds the very value it inherits leaves it inheriting. That is so for an item and its model, for a catalog entry and the global stack discount, for a row that gives an item another model while still holding the values of the old one, and for a minor item and the owner, the location and the standing of the item above it |
| Lifecycle | A row with a different `lifecycle_state` moves the item by a transition, under the rules of moves and never by force, with the row's `state_reason` as the why and its `disposition` and `expected_online` as named. A `state_reason` is taken with a move only. `!clear` in `lifecycle_state` returns a minor item to the standing of the item above it, and is refused for a major item |
| Retiring | An import does not retire. A row that would change `record_status` to `retired` is rejected; a row may bring a retired record back with `active` or `draft` |
| Unknown columns | Reject the file, naming the column. A column that an export writes and nobody can set is not unknown: it is passed over, so any export can be imported back |
| Preview | `POST /imports/preview` stores the parsed file and returns, per row: `create`, `update` with the changed fields, `unchanged` or `rejected` with reasons. A file that cannot be read at all is refused with a `422`, and nothing is stored. The answer holds the counts and the first hundred rows; `GET /imports/{hid}/rows` pages through all of them, and `outcome=rejected` keeps to one kind |
| Apply | `POST /imports/{hid}/apply` applies exactly what was previewed, in one transaction. If any record it would touch has changed since, nothing is applied and a new preview is asked for |
| What "changed since" means | Apply works the file through again. Every row must come out as it was previewed, with the same changes and the same notes, and every record a row matched must be at the version it was previewed at, also when the row was `unchanged`. Otherwise the answer is a `409` that names the rows, the first fifty of them, and the job is `failed` |
| Whose preview | A preview is applied once, by anybody who holds the Inventory role, whoever made it: one person may prepare a file and another look it over and apply it. The job says who made it and who applied it. Anybody who may read the inventory may read it |
| Rejected rows | By default any rejected row blocks the apply, with a `422`, and the preview stays good. `skip_rejected=true` applies the rest |
| Limits | 20 MB and 100,000 rows per file. A larger file is a `413`. A site may raise the 20 MB in its configuration file and in nginx; see [install.md](install.md#uploads). Behind the packaged nginx a body of more than 20 MB is refused by nginx itself, with a `413` that is nginx's own page and not a problem document |
| Load order | tags, vendors, catalog entries, contacts, operators, regions, sites, locations, contact assignments, owners, owner members, networks, contracts, purchase requests, items (parents before children), device groups, members, addresses, coverage, registrations, capacity lines. Addresses come after the groups, because a group has addresses too |
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
`asset_tag`, `mac_address`, `name`, `hostname`, `fqdn` and `mgmt_address`. `location`
and `owner` are set on many at once like any other column. A change that names a single
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

`by` is one of `vendor`, `kind`, `type`, `function`, `owner`, `operator`, `site`,
`region`, `lifecycle_state`, `disposition`, `condition`, `health` and `tag`. By
`operator` it is by the operator in force, each row with the label, and the blank row
is what nobody is assigned to. With `operators=true` each row also lists, in
`operators`, the operators in force among its items: the label with who is behind
it, and the items, components and support weight it has in that row, the one with
the most first and what nobody is assigned to last. So a summary by `site` says who
is involved at each site, and with how much.

**The management report**, `GET /reports/management`, is for the people who pay for
the network. It holds `items`, `component_count`, `est_value` and
`annual_support_cost`, and neither condition nor health. `by` is one of `vendor`,
`kind`, `type`, `function`, `owner`, `operator`, `site`, `region` and `tag`. With no `by` it is by
`site`, and the answer says so: the whole inventory, and each site beneath it.

In both, a row of `site` or `region` has the HID of the place as its key and its path
as its label, and the items that are nowhere are in the blank row. A row of a region
holds everything at or beneath it: an item is in the row of each region above it, as an
item with several tags is in the row of each, and the totals count it once. `contract`
joins `by` when that record arrives. A row of `type` or
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

## Geography

`GET /geography/tree` answers the regions, their sites and the locations within them
as one tree, each node with what is at or beneath it:

```json
{
  "totals":   { "items": 61, "component_count": 40 },
  "unplaced": { "items": 4, "component_count": 3 },
  "hidden":   { "items": 0, "component_count": 0 },
  "roots": [
    { "level": "region", "hid": "0193a1f4-...", "name": "Americas", "code": "AMER",
      "kind": null, "path": "Americas", "record_status": "active",
      "items": 57, "component_count": 37,
      "children": [
        { "level": "region", "name": "Central", "path": "Americas > Central", "...": "...",
          "children": [
            { "level": "site", "name": "Site-2", "path": "Americas > Central > Site-2", "...": "...",
              "children": [ { "level": "location", "name": "Building 1", "kind": "building", "...": "..." } ] } ] } ] }
  ]
}
```

`planned` on a node is how many items of the view are planned for it or for a place
beneath it, and are not there yet. `items` is every item whose location in force is at or beneath the node, major and
minor, and `component_count` the components among them, as defined under "Counting
and weight" on the [data model](data-model.md#counting-and-weight) page. The view is
the one the item list shows: `filter`, `include_drafts` and `include_archived` mean
what they mean there, and a place that is a draft or retired is in the tree only when
it is asked for in the same way. `unplaced` counts the items with no location in
force, and `hidden` those in a place the view leaves out, so that the roots, `unplaced`
and `hidden` add up to `totals`. Within a node the regions come first, then the
sites, each by name; locations are by name.

`root` is the HID or the path of one region, site or location: the tree is then that
node alone with what is beneath it, and the counts beside it are still those of the
whole view, so they no longer add up to it. A place that is asked for so is shown
with what is in it, also when the view would leave it out. `locations=false` stops at the sites, whose counts hold their locations
all the same, so a page can show the regions and sites at once and fetch the inside of
a site when it is opened.

`GET /locations/{hid}/effective` answers what a location has in force, and
`GET /sites/{hid}/effective` and `GET /regions/{hid}/effective` the same for a site and
a region:

```json
{
  "level": "location", "hid": "0193a1f4-...", "path": "Americas > Central > Site-2 > Building 1 > Room 102",
  "contacts": [
    { "role": "technical", "label": "Technical", "source": "region", "source_hid": "0193a1f4-...",
      "source_path": "Americas", "stopped": false, "overrides_hid": null, "overrides_path": null,
      "contacts": [ { "assignment_hid": "...", "contact_hid": "...", "name": "Dana Whitfield",
                      "organization": null, "email": "dana.whitfield@example.net",
                      "phone": "+1 555 0100", "priority": 1, "record_status": "active" } ] },
    { "role": "shipping", "label": "Shipping", "source": "site", "source_hid": "...",
      "source_path": "Americas > Central > Site-2", "stopped": false, "contacts": [ "..." ] },
    { "role": "federal", "label": "Federal", "source": "none", "source_hid": null,
      "source_path": null, "stopped": false, "contacts": [] }
  ],
  "ship_address": { "value": { "address1": "100 Example Way", "address2": null, "city": "Springfield",
                               "state": "IL", "postal_code": "00000", "country": "US" },
                    "same_as_address": true,
                    "source": "site", "source_hid": "...", "source_path": "Americas > Central > Site-2",
                    "overrides_hid": "...", "overrides_path": "Americas > Central" },
  "ship_instructions": { "value": "Dock B, weekdays 08:00 to 15:00", "source": "region",
                         "source_hid": "...", "source_path": "Americas",
                         "overrides_hid": null, "overrides_path": null }
}
```

There is one entry for each role of the `contact_role` list. `source` is `own` for
what the place itself has, `location` for a location above it, `site`, `region`, or
`none`. `stopped` is true where a level said "none here, and do not look further up",
and `source` then names that level. `same_as_address` says that the shipping address
is the street address of the level it came from. `overrides_hid` and
`overrides_path`, on the shipping address, the instructions and each role, name the
nearest level above the source that has one too: what the value in force overrides,
and what would be in force without it. `operator` is the operator of what is at the
place and has none from elsewhere, with its level and what it overrides in the same
way: `value` is the label with who is behind it. A page shows what is inherited in a lighter
style with the level it came from, and marks a value that overrides one from above.

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
hirdir geography tree                            # regions, sites and locations, with what is in each
hirdir geography tree --root 'Americas > Central' --no-locations
hirdir locations show 'Americas > Central > Site-2 > Building 1 > Room 102'
hirdir sites move 'Americas > Central > Site-2' 'Americas > East'
hirdir items set <hid> location='Americas > Central > Site-2 > Building 1 > Room 102'
hirdir items set --filter 'tags:has:for-site-3' planned_location='Americas > Central > Site-3 > Suite 300' --apply
hirdir contacts list --filter 'organization:contains:Operations'
hirdir operators list                            # the labels, who is behind each, which are open
hirdir operators assign LM robin.achterberg@example.net   # hand over what LM looks after
hirdir operators assign LM --open                # nobody behind it for now
hirdir operators release LM                      # the label stands for nothing: the next level up decides
hirdir items set --filter 'group.name:eq:site2-sw-core' operator=LM --apply
hirdir items list --filter 'effective.operator_hid:empty:true'    # what nobody is assigned to
hirdir report summary --by operator              # who looks after how much
hirdir report summary --by site --operators      # and who is involved at each site
hirdir vendors portfolio Cisco --format csv --output cisco-renewal.csv
hirdir import items.csv --entity items                 # preview only
hirdir import items.csv --entity items --apply
hirdir import items.csv --entity items --apply --skip-rejected
hirdir export items --filter 'tags:has:refresh-2030' --format json --output refresh.json
hirdir report summary --by health --format json
hirdir report management                         # by site
hirdir report management --by owner
hirdir report duplicates
hirdir report capacity --include-drafts
```

| Subject | Rule |
|---|---|
| Server and token | `--url` and `--token`, or `HIRDIR_URL` and `HIRDIR_TOKEN`, or `~/.config/hirdir/config.toml`, in that order |
| Output | A table on a terminal. `--format json` or `csv` for scripts. Data on stdout, messages on stderr |
| Lists | `hirdir items list`, and `vendors`, `catalog`, `owners`, `tags`, `networks`, `addresses`, `groups`, `regions`, `sites`, `locations`, `contacts` and `operators` in its place, take `--filter`, `--sort` and `--columns`. A table shows the first 50 rows, or as many as `--limit` says. As `csv` or `json` a list is every row, and is the very file that `hirdir export` writes for the same filter, sort and columns |
| Times | In a message or a table, the application's time with the name of the zone, as the web UI shows it. `--format json` and `csv` carry what the API sends, in UTC |
| Exit codes | `0` done, `2` usage, `3` not signed in or not allowed, `4` validation or rejected rows, `5` conflict, `6` server or network |
| Changes | Anything that changes more than one record previews first and needs `--apply` |
| An item, by what it is known | Where a command takes an item, it takes the HID, or a serial number, an asset tag or a name that one item alone has. More than one is listed, and nothing is done |
| A group | `hirdir groups show` takes the HID or the name, and prints the group with its health, its current members and their roles, and for a stack the master that is intended, the one that is seen, and the serial number that follows |
| A place | Where a command takes a region, a site or a location, it takes the HID or the path. `hirdir regions show`, `hirdir sites show` and `hirdir locations show` print the place with what it has in force: the contacts of each role and the shipping address and instructions, each with the level it came from. `hirdir sites move SITE REGION` gives a site another region, and `hirdir regions move REGION PARENT` a region another parent, `top` for none: one change, after which the paths and the totals follow |
| The geography | `hirdir geography tree` prints the regions, their sites and the locations within them, indented, each with its items and components, and the items that are nowhere beneath. `--root` starts from one place, `--no-locations` stops at the sites, and `--filter`, `--include-drafts` and `--include-archived` choose the view as they do for a list |
| Reports | `hirdir report summary` and `hirdir report management` take `--filter`, `--by`, `--include-drafts` and `--include-archived`, and print the totals and one row for each value. The management report is by site unless `--by` says otherwise. `hirdir report duplicates` lists the addresses held more than once |
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
device groups, networks, catalog entries, vendors, owners with their people, regions,
sites, locations, operators, contacts with their assignments, tags and stored imports, and the
audit events of those records, and writes one audit event that says so and
names the backup. Accounts, groups, roles, service tokens, settings, choices and
lifecycle rules stay. `--everything` removes those too and leaves the database as a
fresh installation has it, with no account and an empty audit trail.

## Web UI

### Pages

| Page | Content |
|---|---|
| Sign in | Username, access code, a Sign in button |
| Home | The headline of the summary: component count beside managed-node count, support weight, and the components by health. No money. The number of components that nobody is assigned to as operator, and of those under a label with nobody behind it, each as a link to its list. End-of-life and coverage warnings from 0.6.0 |
| Items | The main grid, with a health mark on each row, and minor items left out until "Include minor items" is turned on. Location, Site, Region and Operator are in the column chooser: Location shows the name of the location in force, with its path on hover and in an export. An item whose owner in force is outside the team is marked, with the reason that owner has. It shows no money until a column of it is asked for: Estimated value, Annual support cost and Support weight are in the column chooser. Detail page: identity, catalog and effective values with sources, parent and minor items, groups, addresses, coverage, registrations, history |
| Catalog | Entries by vendor; the items of each entry |
| Vendors | The portfolio: everything from one vendor |
| Groups | Stacks, clusters and controller domains, with members and roles |
| Addresses | Every address, with the item or group that has it; the networks |
| Geography | The tree of regions, sites and locations with the items and components at or beneath each, and what is planned for each, for a filter of the item list; the inside of a site is fetched when it is opened. A place has a page of its own: its path, fields and tags, what it has in force with the level each thing came from, the contacts assigned to it, and the forms to change, move and retire it. A draft place lists what is planned for it, and making it active says first how many items that moves in |
| Contacts, Owners | Contacts: the list, and a contact with where it is assigned. Owners: the list, and an owner with its people, the primary first |
| Operators | The labels, each with its colour, the person behind it and how much it is on. Hand a label over to another person, leave it open, release it and bring it back. Wherever an operator is shown, in a grid, on a page or in a report, it is the label in its colour, as a link to this page, with the person's name beside it or on hover and a mark when it is open |
| Contracts | Coverage lists, gaps, expiries |
| Purchases | Requests and lines; receive a line |
| Import | Upload, preview, apply, past jobs |
| Capacity | Demand beside supply by category, the balance and coverage, with and without drafts; the lines, editable |
| Reports | Scoreboard: the operators, each with the components, managed nodes and support weight it looks after, the most first, with what nobody is assigned to and what is under an open label; and the sites likewise, each with the operators involved there. Summary: components, managed nodes, support weight and health, whole and by owner, state, vendor and the rest. Management: estimated value and annual support cost, whole and by site unless another grouping is chosen. Duplicates. End of life and coverage from 0.6.0 |
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
