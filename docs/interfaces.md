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
| Lists | `GET` with `filter`, `sort`, `limit`, `offset`, `fields`. Returns `{items, total, limit, offset}`. `limit` is at most 1000. `fields` arrives with export in 0.3.0 |
| Default view | A list leaves out drafts, retired records and items in Archived. `include_drafts=true` and `include_archived=true` show them. A record is always reachable by its HID |
| Large filters | `POST /items/query` takes the same parameters as a JSON body |
| Updates | `PATCH` with only the fields to change and the `row_version` it was read at. A field left out is left alone. A field sent as `null` is cleared, and one that inherits then inherits again. A change that changes nothing leaves the version alone |
| Retiring | `POST /items/{hid}/retire` with the `row_version`. `PATCH` with `record_status` of `active` or `draft` brings a record back |
| Errors | RFC 9457 problem documents. `401` not signed in, `403` role too low, `404`, `409` stale `row_version` or uniqueness, `422` invalid input with a list of fields. A lifecycle move or combination that the rules refuse is a `422` |
| Request ID | Every response carries `X-Request-Id`. The same value is on the audit events it caused |
| Idempotency | `POST` routes that create accept `Idempotency-Key`, from 0.3.0 |

### Routes

| Area | Routes |
|---|---|
| Access | `POST /auth/sign-in`, `POST /auth/sign-out-everywhere`, `GET /auth/me` |
| Accounts (Admin) | `/users`, `/user-groups`, `/role-grants`, `/users/{hid}/access-code`, `/users/{hid}/service-tokens` |
| Catalog | `/vendors`, `/catalog-entries`, `GET /vendors/{hid}/portfolio` |
| Items | `/items`, `GET /items/{hid}/children`, `GET /items/{hid}/history`, `POST /items/{hid}/transition`, `POST /items/{hid}/replace` |
| Groups | `/device-groups`, `/device-groups/{hid}/members` |
| Addresses | `/networks`, `/addresses` |
| Geography | `/regions`, `/sites`, `/locations`, `GET /geography/tree`, `GET /locations/{hid}/effective` |
| People | `/contacts`, `/contact-assignments`, `/owners` |
| Contracts | `/contracts`, `/contracts/{hid}/coverage` |
| Purchases | `/purchase-requests`, `/purchase-requests/{hid}/lines`, `POST /purchase-lines/{hid}/receive` |
| External systems | `/external-systems`, `/registrations` |
| Capacity | `/capacity-lines`, `GET /reports/capacity` |
| Labels and lists | `/tags`, `/choices`, `PUT /settings/{key}`, `/lifecycle-rules` |
| Bulk | `POST /items/bulk-update` |
| Files | `POST /imports/preview`, `POST /imports/{hid}/apply`, `GET /imports`, `POST /exports` |
| Reports | `GET /reports/summary`, `/reports/end-of-life`, `/reports/coverage`, `/reports/duplicates` |
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
| `in` | any | one of a list |
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
comparison. A field or operator the route does not allow is a `422`. Every comparison
of text ignores case, a regular expression included. A field that is a fixed choice,
such as `lifecycle_state`, takes `eq`, `ne`, `in` and `empty` only.

A filter nests at most 8 deep and holds at most 100 conditions. Its JSON Schema is
`contract/filter.schema.json`.

`sort` is a list such as `["site", "-effective.ldos"]`, written `sort=site,-effective.ldos`
in a URL. Text sorts without regard to case, blank values come last in either
direction, and rows that tie keep a steady order, so paging never repeats or skips one.
On the item list, `name` filters and sorts by the hostname when the name is blank.

The short form used by the CLI and by `filter=` in a URL is one condition per
`field:op:value`, joined by AND: `lifecycle_state:in:Test,Prod hostname:prefix:site2-`.
A value runs to the start of the next condition, so it may hold spaces, and the values
of `in` and `between` are separated by commas. `filter=` also takes the JSON form.

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
      "addresses": [ { "address": "192.0.2.10", "role": "management", "network": "Red" } ],
      "tags": ["refresh-2030"]
    }
  ]
}
```

**CSV** is the same record flattened, one header row, UTF-8. Lists are joined with `;`.
The entity and mode are given beside the file, not in it.

```csv
hid,vendor,pid,serial_number,asset_tag,name,lifecycle_state,disposition,expected_online,owner,location,mgmt_address,mgmt_network,tags
,Cisco,C9300-48P,FCW0000X001,AT-000123,site2-sw-access-01,Prod,Production,true,Network Engineering,Americas > Central > Site-2 > Building 1 > Room 102,192.0.2.10,Red,refresh-2030
```

### Rules

| Subject | Rule |
|---|---|
| Entities | Every record type on the data model page, including memberships, coverage, assignments and registrations |
| Modes | `create` refuses a row that matches an existing record. `upsert` creates or updates. There is no mode that deletes |
| Matching | By `hid` when given, otherwise by the entity's key. For items, the order on the data model page |
| References | By HID, or by the natural key: vendor name, `vendor` + `pid`, owner label, contract number, geographic path, group name |
| Missing references | A vendor or catalog entry that does not exist is created and marked `unreviewed`. Any other missing reference rejects the row |
| Blank cells | Leave the stored value alone |
| Clearing | The literal `!clear` in a cell, or `null` in JSON, clears the value so that it inherits again |
| Unknown columns | Reject the file, naming the column |
| Preview | `POST /imports/preview` stores the parsed file and returns, per row: `create`, `update` with the changed fields, `unchanged` or `rejected` with reasons |
| Apply | `POST /imports/{hid}/apply` applies exactly what was previewed, in one transaction. If any record it would touch has changed since, nothing is applied and a new preview is asked for |
| Rejected rows | By default any rejected row blocks the apply. `skip_rejected=true` applies the rest |
| Limits | 20 MB and 100,000 rows per file |
| Load order | vendors, catalog entries, regions, sites, locations, contacts, contact assignments, owners, networks, contracts, purchase requests, items (parents before children), addresses, device groups, members, coverage, registrations, capacity lines |

### Export

`POST /exports` takes an entity, a filter, a sort, a list of columns, a format (`csv` or
`json`) and optionally a list of HIDs. The response is streamed. `hid` is always the
first column. Inheritable fields export their effective value; `include_sources=true`
adds the `_source` columns, and `own_values=true` exports stored values instead, which
is the form to use for a file that will be imported back.

A CSV cell that begins with `=`, `+`, `-` or `@` is written with a leading apostrophe so
a spreadsheet does not run it as a formula. Import removes that apostrophe again.

Every template in `examples/` is produced by exporting the seeded example database, so
the templates can never drift from the importer.

## CLI

`hirdir` is one command with two halves.

**Client commands** talk to the API and work from any machine:

```bash
hirdir sign-in                                   # asks for username and access code
hirdir items list --filter 'lifecycle_state:eq:Prod location:within:Americas > Central'
hirdir items show FCW0000X001                    # by HID, serial number, asset tag or name
hirdir items set <hid> disposition=Spare expected_online=false
hirdir items transition <hid> Down --reason maintenance
hirdir groups show site2-sw-stack1
hirdir vendors portfolio Cisco --format csv --output cisco-renewal.csv
hirdir import items.csv --entity items                 # preview only
hirdir import items.csv --entity items --apply
hirdir export items --filter 'tags:has:refresh-2030' --format json --output refresh.json
hirdir report summary --by site --format json
hirdir report capacity --include-drafts
```

| Subject | Rule |
|---|---|
| Server and token | `--url` and `--token`, or `HIRDIR_URL` and `HIRDIR_TOKEN`, or `~/.config/hirdir/config.toml`, in that order |
| Output | A table on a terminal. `--format json` or `csv` for scripts. Data on stdout, messages on stderr |
| Exit codes | `0` done, `2` usage, `3` not signed in or not allowed, `4` validation or rejected rows, `5` conflict, `6` server or network |
| Changes | Anything that changes more than one record previews first and needs `--apply` |
| Secrets | Never echoed, never in logs |

**`hirdir admin`** runs on the server as root or the service user and works on the
database directly, because it must work before any account exists:

```bash
hirdir admin create-user --role admin NAME       # prints a new access code once
hirdir admin reset-access-code NAME
hirdir admin migrate
hirdir admin backup
hirdir admin restore FILE
hirdir admin check                               # schema version, integrity, settings
hirdir admin serve                               # what the service runs
```

Run as root, an admin command first steps down to the user that owns the state
directory, so it never leaves behind a file the service cannot write.

## Web UI

### Pages

| Page | Content |
|---|---|
| Sign in | Username, access code, a Sign in button |
| Summary | Component count beside managed-node count, weight, value, by state and by site; end-of-life and coverage warnings |
| Items | The main grid. Detail page: identity, catalog and effective values with sources, parent and minor items, groups, addresses, coverage, registrations, history |
| Catalog | Entries by vendor; the items of each entry |
| Vendors | The portfolio: everything from one vendor |
| Groups | Stacks, clusters and controller domains, with members and roles |
| Geography | The region tree, sites, locations, effective contacts with their source |
| Contacts, Owners | |
| Contracts | Coverage lists, gaps, expiries |
| Purchases | Requests and lines; receive a line |
| Import | Upload, preview, apply, past jobs |
| Capacity | Demand beside supply by category, the balance and coverage, with and without drafts; the lines, editable |
| Reports | Summary, end of life, coverage, duplicates |
| Admin | Users, groups, role grants, service tokens, settings, choices, lifecycle rules |
| About | Version, the versions table, release notes |

### The grid

One grid component is used on every list page.

- Sort by one or more columns, filter per column, resize, reorder, show and hide
  columns. Sorting, filtering and paging are done by the server.
- Select whole rows: one, a range with Shift, several with Ctrl, or "all that match the
  filter", which is shown as a count and sent to the server as the filter, not as a list
  of rows.
- **Copy** puts the selected rows on the clipboard as tab-separated text with a header
  row. **Export** sends the current filter, sort and columns to `POST /exports`.
- **Edit** opens the record's form. **Bulk edit** opens a form for the selected rows,
  shows a before-and-after preview, and applies on confirmation.
- An inherited value is shown in a lighter style with its source on hover. Editing it
  creates an override; clearing an override returns it to inheriting.
- Archived and retired records are hidden until "Include archived" is on, then greyed.
- Column layout and the last filter are remembered per user in `localStorage`.

Cell-range selection and editing in the grid are LATER.
