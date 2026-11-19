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
| A record named on another | An item that another record names, as the `item` of a coverage and of a membership, holds its `hid`, `name`, `serial_number`, `asset_tag`, `catalog_entry_hid` and `pid`; a contract so named, as the `contract` of a coverage, holds its `hid`, `number`, `vendor_hid`, `vendor`, `status` and `record_status`: each value that names a record comes with its HID, so that a list makes it a link (P-232) |
| Other paged tables | The users, the audit trail, the stored previews and their rows, the duplicates report, the members of a group, the coverage of a contract, the lines of a purchase request, the records of the capacity balance, and the minor items and the history of an item are paged with `limit` and `offset`, and take `sort` as a list does. With no `sort` each is in the order it always had. See [Sorting](#sorting) |
| Default view | A list leaves out drafts, retired records and items in Archived. `include_drafts=true` and `include_archived=true` show them. A record is always reachable by its HID |
| Large filters | `POST /items/query` takes the same parameters as a JSON body, and so does `/query` on catalog entries, device groups, addresses, locations, circuits and circuit groups |
| Updates | `PATCH` with only the fields to change and the `row_version` it was read at. A field left out is left alone. A field sent as `null` is cleared, and one that inherits then inherits again. A change that changes nothing leaves the version alone |
| Retiring | `POST /items/{hid}/retire` with the `row_version`. `PATCH` with `record_status` of `active` or `draft` brings a record back. `POST /items/retire` and `POST /device-groups/retire` retire several at once, each as its own route does (P-228): see [Retiring several, and deleting](#retiring-several-and-deleting) |
| Removing | `DELETE /addresses/{hid}`, `DELETE /contact-assignments/{hid}`, `DELETE /owners/{hid}/members/{member_hid}`, `DELETE /contracts/{hid}/coverage/{coverage_hid}`, `DELETE /agreements/{hid}/contacts/{link_hid}`, `DELETE /contracts/{hid}/contacts/{link_hid}`, `DELETE /registrations/{hid}`, `DELETE /capacity-records/{hid}`, `DELETE /vendors/{hid}/contacts/{link_hid}`, `DELETE /circuits/{hid}/contacts/{link_hid}`, `DELETE /circuits/{hid}/carriers/{link_hid}`, `DELETE /circuits/{hid}/costs/{line_hid}`, `DELETE /circuits/{hid}/devices/{link_hid}`, `DELETE /circuit-groups/{hid}/members/{member_hid}` and `DELETE /reference-files/{hid}/attachments/{attachment_hid}` for one that was a mistake, `DELETE /reference-files/{hid}`, which erases a reference with its content (P-160), and `DELETE` on a network or a tag that nothing uses. An Admin deletes an item or a device group that was a mistake and that nothing else depends on with `POST /items/delete` and `POST /device-groups/delete` (P-227), and removes a replacement that was a mistake with `POST /item-replacements/{hid}/remove` (P-238). Nothing else is removed: a coverage that was true for a time is ended with a date, a registration that ends is given the status `removed`, and a purchase line is lowered to what was received |
| Errors | RFC 9457 problem documents. `401` not signed in, `403` role too low, `404`, which for an item or a device group that was deleted holds `deleted`, when, by whom and why, read from the audit trail (P-236), `409` stale `row_version` or uniqueness, naming the field that collides and, where another record has the value, a serial number, an asset tag, a PID, a name or a label, naming that record as `existing`: its `hid`, its `record_type`, as the audit trail names a kind, and its `label`, what it is known by (P-207), `422` invalid input with a list of fields. A lifecycle move or combination that the rules refuse is a `422`. Two requests that collide at the same moment are answered like any other collision: `409`. A change that waited more than five seconds for another to be stored is a `503` with `Retry-After`: nothing of it was done, and it may be sent again. An import or a bulk edit that is being applied holds other changes up a batch at a time, a fraction of a second, and lets them in between two batches. An error nobody foresaw is a `500` problem document that names its request ID, and the details go to the log |
| Request ID | Every response carries `X-Request-Id`. The same value is on the audit events it caused |
| Idempotency | A `POST` that changes an inventory record, a tag or a choice, an import or a bulk edit accepts `Idempotency-Key`, a value of the caller's choosing of at most 200 characters. The answer to a request that succeeded is kept for 24 hours for that caller and key, and the same request sent again is answered with it, marked `Idempotency-Replayed: true`, and carried out no second time. The same key on a different request is a `422`. While the first request is still being worked on, a second is a `409`. An answer of more than a megabyte is not kept. Should the server stop after storing a change and before keeping its answer, the key stays taken: the request sent again is a `409`, never a second change, and what it was to change is read to see that it was. The answer kept for an apply of an import or a bulk edit is its `202`, the job as it was when the apply was begun: the job itself says how far it has got since. A query, which is a list asked for with a `POST`, takes no key, nor does an upload of a reference, which is refused where its content is on the record already (P-160), and a caller who no longer holds the Inventory role is given no kept answer. The routes of accounts refuse the header with a `422`: their answers may hold an access code or a token, which is shown once and kept nowhere |

### Routes

| Area | Routes |
|---|---|
| Access | `POST /auth/sign-in`, `POST /auth/sign-out-everywhere`, `GET /auth/me` |
| Accounts (Admin) | `/users`, `/user-groups`, `/role-grants`, `/users/{hid}/access-code`, `/users/{hid}/service-tokens` |
| Catalog | `/vendors`, `/catalog-entries`, `GET /vendors/{hid}/portfolio`; `GET` and `POST /vendors/{hid}/contacts`, `PATCH` and `DELETE /vendors/{hid}/contacts/{link_hid}` |
| Items | `/items`, `GET /items/{hid}/children`, `GET /items/{hid}/hosted`, `GET /items/{hid}/history`, `GET /items/{hid}/resolution`, `POST /items/{hid}/transition`, `POST /items/{hid}/replace`, `POST /items/{hid}/make-stack`; `POST /items/retire` and, for an Admin, `POST /items/delete`, of several at once; for an Admin, `POST /item-replacements/{hid}/remove` |
| Groups | `/device-groups`, `POST /device-groups/{hid}/retire`, `GET /device-groups/{hid}/hosted`, `GET /device-groups/{hid}/resolution`, `GET` and `POST /device-groups/{hid}/members`, `PATCH /device-groups/{hid}/members/{member_hid}`; `POST /device-groups/retire` and, for an Admin, `POST /device-groups/delete`, of several at once |
| Addresses | `/networks`, `/addresses` |
| Geography | `/regions`, `/sites`, `/locations`, each with `POST .../{hid}/retire`; `GET /geography/tree`; `GET /regions/{hid}/effective`, `GET /sites/{hid}/effective`, `GET /locations/{hid}/effective`; `GET /regions/{hid}/opening`, `GET /sites/{hid}/opening`, `GET /locations/{hid}/opening` |
| People | `/contacts`, `POST /contacts/{hid}/retire`, `GET /contacts/{hid}/uses`, `/operators`, `GET /operators/{hid}/assignments`, `POST /operators/{hid}/retire`, `/contact-assignments`, `/owners`, `GET` and `POST /owners/{hid}/members`, `PATCH` and `DELETE /owners/{hid}/members/{member_hid}` |
| Contracts | `/agreements`, `POST /agreements/{hid}/renew`, `POST /agreements/{hid}/retire`, `GET /agreements/{hid}/terms`, `/contracts`, `POST /contracts/{hid}/retire`, `POST /contracts/{hid}/renew`, `GET /contracts/{hid}/terms`, `GET` and `POST /contracts/{hid}/coverage`, `PATCH` and `DELETE /contracts/{hid}/coverage/{coverage_hid}`, `GET /contract-coverage`; `GET` and `POST /agreements/{hid}/contacts`, `PATCH` and `DELETE /agreements/{hid}/contacts/{link_hid}`, and the same under `/contracts/{hid}` |
| Purchases | `/purchase-requests`, `GET` and `POST /purchase-requests/{hid}/lines`, `GET /purchase-lines`, `GET` and `PATCH /purchase-lines/{hid}`, `POST /purchase-lines/{hid}/receive` |
| External systems | `/external-systems`, `POST /external-systems/{hid}/retire`, `/registrations`, `DELETE /registrations/{hid}` |
| Capacity | `/capacity-lines`, `POST /capacity-lines/{hid}/retire`, `GET /reports/capacity`, `POST /reports/capacity/try`, `GET` and `POST /capacity-records`, `GET`, `PATCH` and `DELETE /capacity-records/{hid}` |
| Circuits | `/circuits`, `POST /circuits/query`, `POST /circuits/{hid}/retire`; `GET` and `POST /circuits/{hid}/carriers`, `PATCH` and `DELETE /circuits/{hid}/carriers/{link_hid}`; `GET` and `POST /circuits/{hid}/costs`, `PATCH` and `DELETE /circuits/{hid}/costs/{line_hid}`; `GET` and `POST /circuits/{hid}/devices`, `PATCH` and `DELETE /circuits/{hid}/devices/{link_hid}`; `GET` and `POST /circuits/{hid}/contacts`, `PATCH` and `DELETE /circuits/{hid}/contacts/{link_hid}`; `/circuit-groups`, `POST /circuit-groups/query`, `POST /circuit-groups/{hid}/retire`, `GET` and `POST /circuit-groups/{hid}/members`, `DELETE /circuit-groups/{hid}/members/{member_hid}` |
| References | `GET` and `POST /reference-files`, `POST /reference-files/links`, `GET`, `PATCH` and `DELETE /reference-files/{hid}`, `GET` and `PUT /reference-files/{hid}/content`, `POST /reference-files/{hid}/attachments`, `DELETE /reference-files/{hid}/attachments/{attachment_hid}`; `GET /catalog-entries/{hid}/references`, `GET /regions/{hid}/references`, `GET /sites/{hid}/references`, `GET /locations/{hid}/references`, `GET /circuits/{hid}/references` and `GET /items/{hid}/references` |
| Labels and lists | `/tags`, `/choices`, `/settings`, `PUT /settings/{key}`, `/lifecycle-rules` |
| Bulk | `POST /items/bulk-update`, `POST /items/bulk-update/{hid}/apply` |
| Files | `POST /imports/preview`, `POST /imports/{hid}/apply`, `GET /imports`, `GET /imports/{hid}`, `GET /imports/{hid}/rows`, `GET /imports/{hid}/created`, `POST /exports` |
| Reports | `GET /reports/summary`, `/reports/management`, `/reports/end-of-life`, `/reports/coverage`, `/reports/renewals`, `/reports/replacements`, `/reports/capacity`, `/reports/circuit-costs`, `/reports/duplicates` |
| Kept answers (Admin) | `GET /kept-answers`, `POST /kept-answers/check` |
| Renewals | `GET /renewals/alert`, `POST /renewals/alert/seen` |
| Audit | `GET /audit-events` |
| About | `GET /about`: the version and what it runs on, the product name and whom to ask (P-168, P-169) |
| Health | `GET /health/live`, `GET /health/ready` (no sign-in needed) |

### Roles

| Action | View-only | Inventory | Admin |
|---|:-:|:-:|:-:|
| Read any inventory record, run reports, export | yes | yes | yes |
| Download a reference file | yes | yes | yes |
| Upload, link, change, attach, take off, replace and erase references | | yes | yes |
| Create, change, retire, import, bulk-update inventory records, and retire several at once | | yes | yes |
| Delete an item or a device group that was a mistake (P-227), and remove a replacement that was one (P-238) | | | yes |
| Edit choices, tags | | yes | yes |
| Edit settings and lifecycle rules, force a lifecycle move, and so the kinds of file a reference may be | | | yes |
| List and check the kept answers of the long reports | | | yes |
| Users, groups, role grants, access codes, service tokens | | | yes |
| Read audit events | yes | yes | yes |

### Settings

`GET /settings`, which every role reads, lists the settings of the inventory and then
the values that are fixed in the code (D-187). A setting has its `key`, `value`, which
is the value in force, `default`, `is_default`, `meaning`, which says what it is for,
`accepts`, which says what values it takes, `options`, the values to choose from where
it is one or more of a list, and `row_version`, `updated_at` and `updated_by`. A fixed
value has `fixed` true, its `key` and `value`, `meaning`, which says what it limits,
`reason`, which says why it is fixed, and `decision`, the decision that fixed it where
one did, such as `D-142`. It is always at its default, at version 0.

`PUT /settings/{key}` is for an Admin. It takes `row_version` and `value`, and is
audited; `null` returns the setting to its default. A value the setting cannot take is
a `422` that says what it takes, a fixed value refuses every change with a `422`, and a
key that is neither is a `404`. What each setting means is on the
[data model](data-model.md#choices-and-settings) page. Where a request leaves a value
out, these decide it:

| Setting | Where it decides |
|---|---|
| `renewal_warning_days` | `within_days` of `GET /reports/coverage`, how far ahead its list of what runs out soon looks; the renewal worklist and the alert after sign-in |
| `renewal_pending_overdue_days` | when a pending renewal is overdue: the renewal worklist, the alert and the coverage report |
| `end_of_life_date`, `end_of_life_within_days` | `date` and `within_days` of `GET /reports/end-of-life` |
| `circuit_cost_side` | the `cost_side` a new circuit is given where the request, or the row of a file, names none. A circuit that exists keeps its own |
| `default_item_weight`, `minimum_item_weight`, `default_site_weight`, `minimum_site_weight`, `default_circuit_weight`, `minimum_circuit_weight` | the support weight in force of a major item, a site and a circuit that gives none, and the least it counts at, wherever the weight is used; `POST /reports/capacity/try` tries others |
| `reference_file_types` | the extensions a file of `POST /reference-files` and `PUT /reference-files/{hid}/content` may have; any other is a `422` that names the setting. A file that is kept keeps its content when the list changes |
| `product_name` | `product_name` of `GET /about`, the name the page that is served shows before signing in, and the first part of the name in the `Content-Disposition` of `POST /exports`, `Example-Inventory-items-20261116T091500-0500.csv`, as P-168 forms it |
| `help_organization`, `help_email`, `help_phone`, `help_url` | `help` of `GET /about`, each `null` where it is blank |
| `help_on_sign_in` | whether the page that is served before signing in carries `help` as well; while it is false the page holds nothing of it |
| `map_link` | `map_url` of a site and of a location: the setting with the place's latitude and longitude in it, or null where it is blank or the place has none (P-229, P-236) |
| `count_kinds` | the kinds of model whose major items are components, managed nodes and carry weight in the summary and the reports. Its default holds `hardware`, `virtual_machine`, `virtual_context` and `container` from 0.9.8 (P-246); an installation that has set it itself keeps what it set, and adds the two new kinds to count them |
| `max_items_per_request` | how many items one `POST /contracts/{hid}/coverage` covers, how many members one `POST /device-groups/{hid}/members` or a new group adds, and how many items and `quantity` together one receipt takes. More is a `422` that names the setting. The API takes 5,000 at most whatever it says, and the command line and the web UI read it and send their pieces by it |

The fixed values are these. What was decided:

| Key | Value | Decision |
|---|---|---|
| `out_of_service_states` | Pending-Removal, Released, Archived: with a retired item, out of service | D-142 |
| `out_of_hands_states` | Released, Archived: the item leaves its groups and its places | D-103 |
| `received_state` | Delivered, the state of an item received on a purchase line | D-145 |
| `condition_health` | failed and dead say failed, degraded and suspect degraded, good good; any other condition says nothing of health | D-112 |
| `review_status_of_what_a_file_makes` | unreviewed | P-14 |
| `refused_file_types` | the extensions of a web page, a script or a program, which no reference may have whatever `reference_file_types` says | P-159 |

And the limits that protect the service: `default_page_size` 100 and `max_page_size`
1000, the rows of a page of a list, and `max_offset` 10,000,000; `max_filter_length`
8000, the characters of a filter in the address of a request, `max_filter_depth` 8,
`max_filter_conditions` 100, `max_filter_values` 1000 and `max_filter_value_length`
1000; `max_pattern_length` 200 and `max_pattern_repeat` 100 of a regular expression,
`pattern_match_seconds` 0.05 and `pattern_request_seconds` 1; `max_file_rows` 100,000,
of a file or a bulk edit, `max_export_hids` 10,000, and `import_batch_rows` 50 (D-185);
`max_minor_item_depth` 3, `max_group_nesting` 8, `max_location_depth` 8 and
`max_region_depth` 16; `max_request_lines` 1000 and `max_line_quantity` 100,000;
`sign_in_max_delay_seconds` 300 and `sign_in_window_seconds` 3600;
`max_attachments_per_request` 1000, the records one `POST /reference-files/{hid}/attachments` or one upload puts a reference on; `idempotency_key_hours` 24, `max_idempotency_key_length` 200 and
`max_kept_answer_bytes` 1,048,576; and `writer_wait_seconds` 5, how long a change waits
for the one writer before it is answered `503`. Each is listed with the value the code
uses, read from where it is used.

### People

Every person is a contact, and a user and an operator are each a part that a contact
plays (P-172). `GET /contacts` answers, with each contact, `is_user`, true where it is
a user's, and filters and sorts by it, and `user`, the `hid` and `username` of that
user, or nothing. Every role reads both.

`POST /users` takes `username`, `is_service_account`, `access_code` and `role` as
before, and the person: `contact_hid`, a contact that is no other user's and is not
retired, or `contact`, with `name`, `email`, `organization`, `phone` and `phone2`, a
new contact made in the same change, or neither. A service account takes neither.
`PATCH /users/{hid}` takes `username`, another name that the same rule holds
(P-173); `contact_hid`, another contact or `null` for none; and `disabled`. A user
answers `contact`, its contact's `hid`, `name`, `email`, `phone`, `phone2` and
`record_status`, and `display_name` and `email`, the contact's name and email, which
a change of the user does not take: they are changed on the contact, by
`PATCH /contacts/{hid}`. `q` on `GET /users` finds part of a username or of the
name of its contact.

An operator answers `contact` with that contact's `email`, `phone` and `phone2`;
`scope`, `internal` where the contact is a user's, `external` where it is not, and
`null` where nobody is behind the label, no contact or one that is retired; and
`user`, the user that contact is, where it is one. `GET /operators` filters and sorts
by `scope`.

`GET /contacts/{hid}/uses`, which every role reads, lists every record that names a
contact, by kind (P-205): `places`, the regions, sites and locations it is assigned to;
`owners`, those it is one of the people of; `operators`, those it stands behind; and
`agreements`, `contracts`, `vendors` and `circuits`, those that name it. Each kind has
`total` and `records`, at most 100 of them, in the order of what each is known by, a
place by its own name and not by its path. A
record has its `hid`; `record_type`, as the audit trail names a kind; `label`, a place by
its path, a contract by its number in force and its vendor, `EX-1001 (Example
Carrier)`, a circuit by its enterprise circuit ID or its name, and any other by its name
or label; `record_status`, a retired record being listed as the count counts it;
`role`, the role the contact has there, a value of `contact_role` for a place and for a
side of a circuit, `primary` or `alternate` for an owner, `account_manager` or
`support_contact` for an agreement, a contract, a vendor and the carrier of a circuit,
and null for an operator; `priority`; `side`, of a circuit, `a` or `z`, and null for its
carrier; and `colour`, of an operator. A record that names the contact in two roles is
listed twice. `total` of the answer is `uses` of the contact, and the totals of the kinds
add up to it: both are counted from one list of what names a contact.

### Why a value, and what an operator is on

`GET /items/{hid}/resolution` answers, for each value an item may have from elsewhere,
the walk that finds it (P-176): `fields`, one entry for each of `location_hid`,
`planned_location_hid`, `operator_hid` and `owner_hid`, and of the eight values of the
catalog, each with `value`, the value in force, `overrides`, the value it would have
without its own where it has its own, and `steps` in the order of the walk. A step has
`level`, one of `own`, `device_group`, `parent_item`, `catalog`, `setting`, `location`,
`site` and `region`; the record it looks at, `hid` and `name`, and for a group its
`type`, its `rank` among the item's groups from 1, and `via_hid` and `via_name`, the group
it is nested in that holds the value where the group holds none of its own; `value`, what that record
holds, with its label; and `outcome`, `decides`, `passed_over`, `nothing`, `retired`, an operator or a group
that is retired, or `raises`, the minimum of a support weight that raises the value found
(P-155), which keeps the source it was found at.
`GET /device-groups/{hid}/resolution` answers the same for a group, its own and then
each group it is nested in. Both are read by every role, and work out what they say by
the same walk as the value in force.

`GET /operators/{hid}/assignments` answers what an operator is on (P-177): `places`,
each place given it as its own, with `level`, `path`, `items`, the items that have it
from that place, `places_beneath`, the places beneath it that have it from there, and
`exceptions`, the items beneath it that have another operator; `groups`, each group given
it as its own, with `type`, `items`, `groups_beneath` and `exceptions`, the items under it,
at any depth of nesting, that have another; `own`, the items given it as
their own, and `from_item`, the minor items that have it from the item they are in; and
`totals`. Every count has `filter`, the filter of the item list that lists those items,
by `effective.operator_hid`, `effective.operator_hid.source` and
`effective.operator_hid.source_hid`. It takes `include_drafts` and `include_archived` as
the item list does, and lists at most 20 places and 20 groups beneath each, with how many
more there are.

### The members of a device group

`POST /device-groups/{hid}/members` takes `members`, each with `item_hid`, `role`,
`position` and `joined_on`, and `drop_identity`, `disposition` and `expected_online`
(P-217); `POST /device-groups` takes the same in its `members`. All of them are made, or
none: a refusal of one leaves no member added and no item changed. The answer is the
memberships made.

- `drop_identity`, true, is for a member of a stack: in the same change as the
  membership the item's own `hostname` and `fqdn` are cleared, each of its addresses is
  removed as `DELETE /addresses/{hid}` removes it, and its own `location_hid` is
  cleared, so that the stack's location is in force. Its planned location, owner and
  operator stay as they are. It is refused for a cluster, a controller domain and a
  custom group, and, with `disposition` and `expected_online`, on a row of a file that
  enters a membership that has ended already, with its `left_on`. Left out, false.
- `disposition` and `expected_online`, given, are the item's from that change, checked
  by the rule of its lifecycle state as `PATCH /items/{hid}` checks them. Left out or
  `null`, each stays as it is: nothing follows from the other, so Production for a
  spare in Prod is sent with `expected_online` true.
- A refusal of one of these names the field with the member's place in the list, from
  0: `members.0.drop_identity`, `members.0.disposition`, `members.0.expected_online`.
- Each change of the item is audited as a change of the item, and each address removed
  as the removal of that address, with the request ID of the request. Each such event
  holds among its `changes` the entry `joining_group`, with the HID of the group as
  `new`. The item's event holds the host name, the FQDN and the location it had, and
  the event of each address what it was: its item, the address, its network and its
  role (P-223).

`PATCH /device-groups/{hid}/members/{member_hid}` that gives `left_on` may carry `item`
(P-218): what the item is to have from the end, any of `hostname`, `fqdn`,
`location_hid`, `lifecycle_state`, `state_reason`, `disposition`, `expected_online` and
`condition`, a value of the `item_condition` list (P-245), which nothing sets by a rule:
a failed member is marked so where a person says it. A field left out stays as it is,
and `null` clears `hostname`, `fqdn`, `location_hid` and `condition`, as on `PATCH
/items/{hid}`. The membership is ended first and the item
is changed after, in the same change, so that the item's rules see an item that has
left: its location in force is no longer the group's. `lifecycle_state` moves the item as
`POST /items/{hid}/transition` does, by a move the rules list and never by force, with
`state_reason` as its reason and `disposition` and `expected_online` as named; a move to
Released or Archived ends the other memberships the item has, as any such move does.
Without `lifecycle_state`, or with the state the item has already, which is no move,
`disposition` and `expected_online` are checked as on `PATCH /items/{hid}`, and a
`state_reason` other than the one the item has is refused, as a file of items has it. A refusal names the field as
`item.hostname`, `item.lifecycle_state` and so on, and leaves the membership and the
item as they were. `item` without `left_on`, or on a membership that has ended, is
refused. Each change of the item is audited as its change, and holds among its
`changes` the entry `leaving_group`, with the HID of the group as `old`; what follows
from a move of the item, the end of its other memberships and of its coverage when it
is released, is audited as it always is, with no such entry. `item` is given with a
`left_on` that has come, today or before: what becomes of the item is done with the
request, so a day to come is refused with it. A membership ended with a `left_on` to
come, without `item`, is ended as the request is made, and its position is free at once.

### What runs on a host

A virtual machine, a virtual context and a container are items of a model of the kind
`virtual_machine`, `virtual_context` or `container`, and name what they run on (P-246):
"What runs on a host" under `items` on the [data model](data-model.md#items) page says
the rules, and this says how the API carries them.

- **The fields.** `POST /items` and `PATCH /items/{hid}` take `host_item_hid`, the item
  it runs on, or `host_group_hid`, a stack or a cluster, and `observed_host_hid` with
  `host_observed_at`, the item it was seen on and when; `host_observed_at` left out is
  the moment of the change, and `null` in `observed_host_hid` clears both. Each refusal
  is a `422` that names its field: `host_group_hid` given with `host_item_hid`; a host
  given to an item of another kind, or of no model, or to an item that has a parent
  (`host_item_hid`, or `host_group_hid`); a parent given to an item that has a host
  (`parent_item_hid`); a host that is not there, is retired, has left the team's
  hands, is of a kind that hosts nothing, is the item itself or runs on it, or makes a
  line of hosts longer than three; a group that is not a stack or a cluster, or is
  retired; an item seen that is the item itself; a moment seen more than a day ahead;
  and a moment given with no item seen. `PATCH /catalog-entries/{hid}` that makes a
  model a kind that runs on nothing, while an item of it names a host, is refused on
  `kind`.
- **The answer.** An item answers the four fields, and `host`, what it runs on, with
  `item_hid` or `group_hid`, its `name`, a group's `type`, an item's `pid` and its own
  `lifecycle_state`, and its `record_status`; `observed_host`, the item seen, as an item
  is named on another record; `host_differs`, true where both are known and the item
  seen is neither the host named nor a current member of the stack or the cluster
  named, false where it is, and `null` where either is not known; `hosted_count`, how
  many items not retired name it as their host; and `review`, the reasons it is to be
  looked at (P-249), each `{reason, about}`: `reason` one of `no_host`, `host_gone` and
  `not_reported`, and `about` the host (`record_type` `item` or `device_group`) or the
  external system (`external_system`) it is about, with its `hid` and `label`, `null`
  for `no_host`. A retired item has none. A device group answers `hosted_count` too.
- **What it has from its host.** `effective.location_hid`, `planned_location_hid`,
  `owner_hid` and `operator_hid` of an item that runs on a host go on through it where
  the item and its groups have none, with `source` `host` and `source_hid` the record
  it runs on, or an item that one is installed in, that holds the value; a value of a
  group of the host is `device_group` as always, and so is one the stack or the cluster
  it runs on has from a group it is nested in. `effective.serial_number`, on every item,
  is its own, or for a virtual context with none the serial number of the item it runs
  on, with `source` `host`. `GET /items/{hid}/resolution` has the steps of the host
  with `level` `host`, after those of the item and what it is installed in, each
  followed by the host's groups.
- **What runs on a record.** `GET /items/{hid}/hosted` and `GET
  /device-groups/{hid}/hosted`, which every role reads, answer `{total, items}`: each
  item that names the record as its host, and beneath each what runs on that, each as
  `{depth, host_hid, item}`, `depth` 1 for what runs on the record itself, and `item`
  as an item of a list is answered. Each comes after its host, and those of one host by
  name. Retired ones are listed with `include_retired=true`.
- **The item list** filters and sorts by `host_item_hid`, `host_group_hid`,
  `observed_host_hid`, `host.name`, the name of the item or the group it runs on,
  `observed_host.name`, `host_observed_at`, `host_differs`, `hosted_count`, and
  `review`, which holds each reason: `review:eq:no_host`, and `review:empty:false` for
  every item with one. `effective.location_hid`, `location`, `site`, `region`,
  `effective.owner_hid`, `effective.operator_hid` and `effective.planned_location_hid`
  answer through the host as the record does, and so do the geography tree and the
  summary, which count what runs on a host where its host is and with its host's owner
  and operator.
- **The items file** has `host`, the item it runs on, named as `parent` names one;
  `host_group`, a stack or a cluster by its name; `observed_host`, named as `host` is;
  and `host_observed_at`. A row may name a host that an earlier or a later row of the
  same file makes. An export writes them, and the reasons of `review`, joined, as a
  column it can write, and loads back changing nothing. A bulk edit sets `host` or
  `host_group` on the rows chosen, one clearing the other, or `null` to clear it.
- **The CLI.** `hirdir items hosted <item>` lists what runs on an item, and `hirdir
  items show` says what an item runs on and how many run on it.

A position in a stack is held by one current member (P-219). A member added at a
position that another current member of the stack holds, or moved to it, is refused
with a `409` that names that member's item as `existing`, and two members of one request
at one position with a `422`. A membership that has ended keeps its number and holds
nothing. A stack that holds two members at one position already is left as it is, and
other changes of it go through; either of the two may be moved to a free position. By
the API two members change places by way of a free position, or of none: one is given
`position` `null`, the other its place, and the first the place left. A file of members
is judged when all of its rows are in, so that it may swap two members or renumber
them all: a row that leaves its member at a position another current member still
holds is rejected then. A
member added to a stack with no position takes the lowest from 1 that no current member
holds and that no other member of the same request is given; `next_position` of the
stack, on `GET /device-groups/{hid}` and in the lists of groups, is that position, and
is `null` for a group of another type. A member of a cluster, a controller domain or a
custom group has a position only where one is given, and any. `POST
/items/{hid}/replace` ends the old item's membership and gives the new item its
position, as it is, in the same change.

### Replacing an item

`POST /items/{hid}/replace`, for the Inventory role, is sent on the item that leaves,
with its `row_version`, and records that another took its place (P-241, P-242):

```json
{ "row_version": 7, "new_item_hid": "0193a1f9-...", "reason": "rma",
  "reference": "RMA-0000001", "replaced_on": "2026-11-18",
  "drop_identity": true, "disposition": "Production", "expected_online": true,
  "old_item": { "lifecycle_state": "Pending-Removal", "state_reason": "failed",
                "condition": "failed" } }
```

- `new_item_hid` names an item that exists and is not retired, or `new_item` holds the
  fields of a new item, which this request creates, as `POST /items` takes them; one of
  the two, and not both. `reason` is a value of the `replacement_reason` list,
  `reference` an RMA, service request or ticket number, and `replaced_on`, left out,
  today. The answer, `201`, is the replacement with both of its items.
- An item is replaced, and takes another's place, as often as that happens. Two things
  are refused: an item that takes its own place, a `422` on `new_item_hid`; and a
  replacement of the same item by the same other on the day of one there is, a `409` on
  `new_item_hid` that names that replacement as `existing`, with `record_type`
  `item_replacement` and the two items as its `label`. The `row_version` of the item
  that leaves moves with the replacement, so the same request sent twice is refused the
  second time as stale, a `409`, and makes one replacement.
- The new item takes over the old one's current memberships of groups, with the same
  role and position, and its connections of circuits, on the same sides (P-147).
- `drop_identity`, true, is for the replacement of a current member of a stack: in the
  same change the item that comes gives up its own `hostname` and `fqdn`, its
  addresses, each removed as `DELETE /addresses/{hid}` removes it, and its own
  `location_hid`, as a member that joins a stack with `drop_identity` does (P-217).
  Where the item that leaves is a current member of no stack it is refused, a `422` on
  `drop_identity`. Left out, false.
- `disposition` and `expected_online`, given, are the new item's from that change,
  checked by the rule of its lifecycle state as `PATCH /items/{hid}` checks them; left
  out or `null`, each stays as it is. The new item created by the same request may be
  given the three as well.
- `old_item` is what the item that left is to have from the replacement, as `item` of
  the end of a membership is (P-218): any of `hostname`, `fqdn`, `location_hid`,
  `lifecycle_state`, `state_reason`, `disposition`, `expected_online` and `condition`,
  each meaning what it means there. It is applied once the old item's memberships have
  ended and its circuits are handed over, so that its rules see an item that has left.
  It is done with the request, so it is given with a `replaced_on` that has come, today
  or before: with a day to come it is refused, a `422` on `replaced_on`. `null` or left
  out, nothing of the old item changes but its version.
- A refusal of what the new item is to have names the field as sent, `drop_identity`,
  `disposition`, `expected_online`; of what the old item is to have, as
  `old_item.lifecycle_state`, `old_item.condition` and so on. One request does all of
  it, or nothing: a refusal of any part leaves no replacement, no membership ended or
  begun, and neither item changed.
- Each item has an event `replace` of it in its history. Each change of either item
  that the request names, and each address removed, is audited as its own change, with
  the request ID of the request, and holds among its `changes` the entry `replacing`,
  with the HID of the replacement as `new`; what follows from a move of the old item,
  the end of its other memberships and of its coverage when it is released, is audited
  as it always is, with no such entry.

An item's answer, on `GET /items/{hid}` and in the list, holds `replacements`: each
replacement the item is part of, the latest first, by `replaced_on` and then by when it
was entered. Each holds its `hid`, `part`, which is `left` where this item left and
`item` took its place, and `came` where this item took the place of `item`; `item`, the
other item as another record names it; `reason`, `reference`, `replaced_on` and
`row_version`. `replaces` and `replaced_by` are the latest of each part, or `null`, and
are what the list, its filter and an export read, so that an item replaced twice is one
row of the list and of a report.

An Admin removes a replacement that was a mistake, that a wrong file or a wrong press
recorded, with `POST /item-replacements/{hid}/remove` (P-238):

```json
{ "reason": "recorded on the wrong switch" }
```

`reason` is required, and is refused blank, a `422`. The answer is `204`, as the
removal of a coverage that was a mistake answers. The audit event of the removal,
`delete` of the replacement, holds every field of the replacement as it was, each as
`old`, and the Admin's reason as `new` of `removal_reason`; each of the two items has
an event `replacement_removed` in its history, whose `changes` hold `replaced_by` or
`replaces`, the other item, as `old`, `replacement`, the HID of the replacement, as
`old`, and `removal_reason`. Both items' versions move with it. What the replacement handed over stays as it is, the
memberships of groups and the connections of circuits, each a fact of its own that is
put right on the page of its group or its circuit; and neither item is changed but in
its version. The two items are then as any other: each is deleted by `POST
/items/delete`, or refused, by the rule of P-227, as if the replacement had never been.
Nothing else removes a replacement. A replacement that is not there, or was removed,
answers `404`.

### Making a stack of a switch that stands alone

`POST /items/{hid}/make-stack`, for the Inventory role, makes a stack of an item that
is in none, and puts the item into it as its first member, at position 1 (P-243):

```json
{ "row_version": 4, "name": "site2-sw-stack12",
  "members": [ { "item_hid": "0193a1fa-...", "drop_identity": true,
                 "disposition": "Production", "expected_online": true } ] }
```

- `name` is the stack's; left out or blank, the item's own name, and its host name where
  it has no name. A name that another group has is refused, a `409` on `name` that names
  that group as `existing`, as `POST /device-groups` refuses it.
- The stack takes from the item what a stack holds for its members: its `hostname` and
  `fqdn`; each of its addresses, moved to the stack as it is, with its HID, its network,
  its role and whether it is the primary one; and the `location_hid`,
  `planned_location_hid`, `owner_hid` and `operator_hid` that the item has of its own.
  The item gives each of them up in the same change, and has the four from the stack
  from then on, read when it is read, as any member has them: nothing is held twice.
  Its serial number, model, asset tag, state, tags, coverage, registrations and
  circuits stay its own. The stack is active, and has no parent group.
- `members` are more members, each as `POST /device-groups/{hid}/members` takes one,
  `drop_identity`, `disposition` and `expected_online` among them (P-217), added after
  the first by the rules of that route: a member given no position takes the lowest
  free one, 2 for the first. A refusal of one names its field under `members`: by its
  place in the list, from 0, where that route names it so, `members.0.disposition`,
  and otherwise as `members.item_hid`, `members.position`.
- The item is a member with the role `member`: the intended master is marked on the
  page of the stack, as for any member.
- It is refused, a `422` on `item_hid`, for a minor item, for an item that is retired,
  and for one that has left the team's hands, in Released or Archived; and, a `409` on
  `item_hid`, for one that is a current member of a stack already, naming that stack as
  `existing`; and, a `422` on `name`, where neither the request nor the item gives a
  name. A refusal of any part leaves no stack made and the item as it was.
- The answer, `201`, is the new device group, as `POST /device-groups` answers. The
  audit trail holds the stack made, the membership, the change of the item, its host
  name, its FQDN and the four it gives up, and each address moved, as an `update` of
  the address whose `item_hid` and `group_hid` change. Each of these but the stack's own
  creation holds among its `changes` the entry `joining_group`, with the HID of the
  stack as `new`. All of them share the request ID of the request: from the stack's
  `create`, found by `GET /audit-events?record_hid=` with the stack's HID, and from the
  item's history, each event leads to the others by `request_id`.

### Retiring several, and deleting

`POST /items/retire` and `POST /device-groups/retire`, for the Inventory role, retire the
records named in `hids`, at most 1,000, each as `POST /items/{hid}/retire` and `POST
/device-groups/{hid}/retire` retire one, with an audit event each (P-228, P-236). No
`row_version` is sent: what a person ticked is what is retired.

```json
{ "hids": ["0193a1f4-...", "0193a1f5-...", "0193a1f6-..."] }
```

```json
{ "retired": [ { "hid": "0193a1f4-...", "label": "site2-sw-access-01" } ],
  "already": [ { "hid": "0193a1f5-...", "label": "site2-sw-access-02" } ],
  "refused": [],
  "missing": ["0193a1f6-..."] }
```

`retired` is what this request retired; `already` what was retired before it, counted
and not refused; `refused` each that the rules did not let be retired, with why in
`detail`; and `missing` each HID that names no such record, also one that was deleted.
One that is refused leaves the others as they went, and a HID named twice counts once.
`label` is what a record is known by: an item by its name, host name, serial number or
asset tag, the first it has, and a group by its name. What is retired is hidden from a
list as before, shown again with `include_archived`, and brought back with `PATCH`.

`POST /items/delete` and `POST /device-groups/delete`, for an Admin, delete records that
should never have been, as the items a wrong file made (P-227, P-236). The body names
`hids`, at most 1,000, `reason`, which a deletion requires and a dry run does not, and
`dry_run`, false unless given:

```json
{ "hids": ["0193a1f4-...", "0193a1f7-..."], "reason": "a wrong file of 2026-11-18", "dry_run": true }
```

```json
{ "dry_run": true,
  "deleted": [ { "hid": "0193a1f4-...", "label": "site2-sw-access-01" } ],
  "refused": [ { "hid": "0193a1f7-...", "label": "site2-sw-core-01",
                 "depends_on": [ { "record_type": "contract", "hid": "0193a1f8-...",
                                   "label": "CON-2026-0001" } ] } ],
  "missing": [] }
```

Each record is judged by itself, and one that is refused leaves the others as they go.
A record is deleted where nothing depends on it but what goes with it and the records of
the same request that are deleted too: a switch named with the power supplies in it is
deleted with them, and a switch whose power supply is refused is refused, naming the
supply. What goes with an item: its addresses, its tags, its memberships of groups,
current and ended, with the role of master it had there, the mark of the master that is
seen on a stack where it was that one, and its registrations. An item is refused while
a contract covers it or has covered it, it arrived on a purchase line, an item is
installed in it, it replaced another or was replaced, a circuit is connected to it, or
a reference is attached to it. What goes with a device group: its memberships, current
and ended, its addresses, its tags and its registrations; its members stay, as items of
their own. A group is refused while a group is nested in it or a circuit is connected to
it.

`depends_on` names each record in the way, by `record_type` as the audit trail names a
kind, its `hid` and its `label`: `contract` by its number, for a coverage under it,
ended or not; `purchase_line` by its request and line, `RITM0012345/2`; `item` for an
item installed in it; `item_replacement` for a replacement, labelled with the two items;
`circuit` by its enterprise circuit ID or its name; `reference_file` by its title; and
`device_group` for a group nested in it. Each is taken away first where it can be: a
coverage that was a mistake is removed, a minor item is taken out or deleted with it,
the purchase line is cleared from the item, the circuit's device and the reference's
attachment are removed. A replacement that was a mistake is removed by an Admin, with
a reason, by `POST /item-replacements/{hid}/remove` (P-238); one that happened stays,
and an item that is part of it is retired.

With `dry_run` nothing is changed and the answer is the same: it is what the web page
shows before it asks. Without it, what `deleted` names is gone when the answer comes,
in one change. Each deletion is the audit event `delete` of its record, with who, when,
the reason, every field of the record as it was, and what went with it, as `audit_events`
on the [data model](data-model.md#audit_events) page says. A deletion removes nothing
from the audit trail: the events the record had before stay, and `GET
/audit-events?record_hid=` finds them by its HID; `hirdir admin reset`, on the server,
is the one thing that clears the trail of what it clears. A HID that was deleted is never given again. `GET` and `PATCH`
of a record that was deleted, and its other routes that read the record first, its
retire, history, members and children among them, answer `404`, whose `detail` says that
it was deleted, when and by whom, and whose `deleted` holds `at`, `actor_hid`,
`actor_name` and `reason`; a request that names it among `hids` counts it in `missing`,
and a row of a file that names it by its `hid` is rejected with the same words.
A change of the item that was under way at the same moment, its joining a group or a
contract covering it, either is stored first, and the deletion then sees it and is
refused, or comes second and is refused as a change of a record that is not there.

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
is doing. `location` is where the item is, by the location in force, its own, that of
the item above it or that of its group, and takes
`within` with a region, a site or a location, and `empty`; `planned_location` is
where it is planned to go, in force in the same way, and takes the same two, and
`planned_location.name` is the name of that location, to sort and to find by;
`effective.location_hid` and `effective.planned_location_hid` are those two as
references, `effective.owner_hid` is the owner in force, the item's own, that of the
item above it or that of its group, and `location_hid` and `planned_location_hid` the item's own; `site` and `region` are the
names of its site and of the region the site is in, `site.code` the site's code, and
`location.name` and `location.kind` those of the location; `operator.label` is the label of the operator in force and `operator.contact` the
name of the person behind it, `effective.operator_hid.source` is how the item has it, `own`,
`parent_item`, `device_group`, `location`, `site` or `region`, and
`effective.operator_hid.source_hid` the record it has it from (P-177), `group`, which takes
`within`, the HID or the name of a device group, for the items under it at any depth of
nesting with their minor items, and `empty` for the items under no group (P-181),
`operator.is_open` is true where nobody is, `operator.scope` is `internal` or
`external` as the operator in force is (P-172),
`effective.operator_hid` is that operator, blank for an item that nobody is assigned
to, and `operator_hid` is the item's own. `owner_exception` is true
for an item whose owner in force is outside the team, and `owner_exception_reason` is
that owner's reason; the list of device groups has `owner_exception` too. `covered` is true for an item that a contract covers today, `covered_until` is the
last day its cover runs to, `contract_count` how many contracts cover it today,
`contract.number`, `contract.hid` and `contract.status` find it by a contract that
covers it today, `out_of_service_cover` is true for an item that is out of service
and that a contract still counts, and `out_of_service_contract.number` and
`out_of_service_contract.hid` find it by such a contract, `catalog.vendor_hid` is the
vendor of its model, `purchase_line_hid` the line it arrived on, and
`purchase_line_mismatch` is true where that line is of another model; `do_not_renew` is
the item's own word that its support is not to be renewed, blank where it has its
model's, and `effective.do_not_renew` the flag in force, its own or its model's, blank
for an item that has neither; the list of catalog entries has `do_not_renew` too;
`registration.system` finds an item by
the name of an external system that knows it, by a registration of its own or of a
stack or a cluster it is a member of, and on the list of device groups a group by its
own. On the lists of contracts and of agreements, `number`, `starts_on`, `ends_on`,
`annual_cost`, `purchase_reference` and `status` are those of the term in force,
`next_number` and `next_starts_on` those of a term that is still to begin, and
`lapsed` is true where the period has ended and the status still says active. The lists of device groups and
of locations have `location` with `within` too, and the list of sites has `region`. A
device group is found and sorted by `site` and `region` as an item is, and by
`planned_location` with `within`, each by what the group has in force, its own or
that of the group it is nested in; `effective.operator_hid` and `effective.owner_hid`
are the operator and the owner a group has in force, and `operator.label`,
`owner.label` and `owner_exception` go by those. The list of locations has `in_use`, true for a location that is active
with everything it is in, and false for one that can be planned for. A
location is also found by `site.name`, `site.code` and `region.name`, the name of the
region its site is in. On the list of groups, `member.serial_number` finds a stack by the serial
number of any current member. On the list of circuits, `carrier.name` is the name of
its primary carrier, `carriers.vendor_hid` and `carriers.circuit_number` find it by any
of its carriers, the primary one among them, and by the number any of them gives it, `location` by a side at a
location, and takes `within` with a region, a site or a location, `a_location.name` and
`z_location.name` are the names of its two sides, `a_site.name` and `z_site.name` the
names of their sites, `cost_site_hid` is the site it counts at, `cost_site.name` its
name, and `cost_location` the location it counts at, which takes `within` as `location`
does, `groups.name` and `groups.hid` find it by any of its groups, `owner.label` and `owner_exception` go
by its owner, `effective.support_weight` is its weight in force,
`effective.down_mbps` and `effective.up_mbps` its rates in force, the port speed where
it gives none, `billed_by` finds it by its primary carrier or a carrier that bills one of
its lines,
`monthly_cost` and `annual_cost` what it costs today, nothing on a day it is not in
service, and `in_service` is true where it is in service today, a draft in a view that
includes drafts. The record of a draft, read by itself, answers both as a view of drafts
does: what it will cost. The list of circuit groups has `owner.label` and
`circuits`, how many it has, and `in_service`, `monthly_cost` and `annual_cost` as its
record has them. The lists of regions, sites and locations have
`support_weight`, the place's own, and the list of sites `effective.support_weight`, the
weight a site counts at: its own or `default_site_weight`, raised to
`minimum_site_weight`. For a field an item may have several of, `eq` is true when one of them matches, and `ne` and `empty` when none does.
A field that an item may have several of is sorted by the least of them; see [Sorting](#sorting). A field or operator the route does not allow is a `422`. A field the list does not have is refused with the nearest fields it has, at most three: the same name under a related record first, `catalog.type` for `type` on the item list, then the names spelt nearly alike, and none where nothing is near (P-207). Every comparison
of text ignores case, a regular expression included. A field that is a fixed choice,
such as `lifecycle_state`, takes `eq`, `ne`, `in` and `empty` only.

A filter nests at most 8 deep and holds at most 100 conditions, and a value is at most
1000 characters. Its JSON Schema is `contract/filter.schema.json`. A value that the
field could never hold, such as a number with more decimal places than money has, is a
`422`.

The short form used by the CLI and by `filter=` in a URL is one condition per
`field:op:value`, joined by AND: `lifecycle_state:in:Test,Prod hostname:prefix:site2-`.
A value runs to the start of the next condition, so it may hold spaces, and the values
of `in` and `between` are separated by commas. A value that itself looks like the start
of a condition, `word:word:`, is refused, because it is nearly always a mistyped
operator; the JSON form takes any value. `filter=` also takes the JSON form.

### Sorting

`sort` is a list such as `["site", "-effective.ldos"]`, written `sort=site,-effective.ldos`
in a URL. Text sorts without regard to case, blank values come last in either
direction, and rows that tie keep a steady order, so paging never repeats or skips one.
On the item list, `name` filters and sorts by the hostname when the name is blank. A
field the route is not sorted by is a `422`, which names the nearest fields it is sorted
by as a filter does: `location_hid`, `location.name` and `location.kind` for `location`
(P-207).

A list is sorted by any field it is filtered by, with two exceptions. A field that
takes `within` is a place, and a list is sorted by the name of the place and not by
the place: by `location.name`, `planned_location.name`, `site` and `region` on the
lists of items and of device groups, and by `region.name` on the list of sites. The
fields that name the records a record has several of, `group.hid`,
`member.item_hid`, `member.serial_number` and `member.contact_hid`, and on the list of
circuits `carriers.vendor_hid`, `billed_by` and `groups.hid`, have no order.

A field that a record may have several of is sorted by the least of them, in the order
of that value, and a record with none comes last in either direction, as a blank does.
`tags` is sorted by the first label without regard to case, on every list that has
tags; `group.name` by the first name and `group.type` by the first type among the
groups of an item; `network.label` by the first label; and `address` by the lowest
address, as an address and not as text: 192.0.2.9 comes before 192.0.2.10, and every
IPv4 address before any IPv6 one. Filtering by such a field is as it was: by any one of
them.

A grid that the server pages is sorted by the server, over the whole list, so every
column of such a grid has a field that it is sorted by (D-132). Where a column shows
what is worked out, the field is sorted by and not filtered by:

| List | Column | `sort` | Sorted by |
|---|---|---|---|
| Items | Groups | `group.name` | the first of its groups, by name |
| Items | Group types | `group.type` | the first type among them |
| Items, device groups | Management address | `mgmt_address` | the primary management address, the IPv4 one before the IPv6 one |
| Items, device groups | Addresses | `address` | the lowest address |
| Items, device groups | Networks | `network.label` | the first label among the networks of its addresses |
| Items | Minor items | `minor_items` | how many are directly in it; an item with none comes last |
| Device groups | Serial number | `serial_number` | the serial number the group reports: of the master that is seen, or else of the one intended |
| Device groups | Health | `health` | the worst first, as an item's is: failed, degraded, unknown, good, and a group that has no health last |
| Device groups | Intended master | `master.name` | the name that item is shown by: its name, or else its hostname, serial number or asset tag |
| Device groups | Master seen | `observed_master.name` | likewise |
| Device groups | Members | `member_count` | the number of current members |
| Contacts | Assigned | `uses` | how many records name it, as the record counts them and `GET /contacts/{hid}/uses` lists them: places, owners, operators, agreements, contracts, vendors and circuits |
| Operators | Given to | `uses` | how many items, groups and places are given it |
| Catalog | Items | `items` | how many items are of that model, as the item list counts them (P-180) |
| Vendors | Also known as | `aliases` | the first alias without regard to case |
| Owners | Primary contact | `primary.name` | the name of that contact |
| Every list with tags | Tags | `tags` | the first label |
| Items | Contracts | `contract.number` | the first number among the contracts that cover it today |
| Items | Still counted under | `out_of_service_contract.number` | the first number among the contracts that still count it while it is out of service |
| Items, device groups | Registered with | `registration.system` | the first name among the systems it is registered with |
| Agreements | Contracts | `contracts` | how many contracts that are not retired it groups |
| Contracts | Items covered | `covered_items` | how many items it covers today |
| Purchase requests | Lines, Pending | `line_count`, `pending_quantity` | how many lines it has, and how many items are still to come on them |
| Purchase lines | Received, Pending, Of another model | `received_quantity`, `pending_quantity`, `mismatched_items` | the items that name the line, what is left of its quantity, and how many of those items are of another model than the line's |
| External systems | Registrations | `registrations` | how many records are registered with it, those removed not counted |
| Capacity lines | Units | `units` | `quantity` × `units_each`, and blank on a line that multiplies |
| Circuits | Speed | `port_mbps` | the speed of the port; the rates in force are sorted by `effective.down_mbps` and `effective.up_mbps` |
| Circuits | A side, Z side | `a_location.name`, `z_location.name` | the name of that side's location, a side with none last |
| Circuits | Groups | `groups.name` | the first of its groups, by name |
| Circuit groups | Circuits, Monthly cost, Annual cost | `circuits`, `monthly_cost`, `annual_cost` | how many circuits it has, and what those in service cost today |

`mgmt_address`, `minor_items`, `serial_number` of a group, `health` of a group,
`master.name`, `observed_master.name`, `member_count`, `uses`, `aliases`,
`primary.name`, `contracts` of an agreement, `covered_items`, `line_count` and
`registrations` are sorted by and not filtered by. A contract is filtered and sorted
by `agreement_hid` and `agreement.name`, and by `effective.starts_on`,
`effective.ends_on` and the other fields in force that it may have from its agreement. `received_quantity`, `pending_quantity`, `mismatched_items` and `units` are filtered
by as well. A stack is still found by
`member.serial_number`, the serial number of any current member.

The tables that are paged and are no list of records take `sort` in the same form.
Each keeps the order it always had: that is the order with no `sort`, and what settles
the rows that a sort leaves tied.

| Route | `sort` takes | With no `sort` |
|---|---|---|
| `GET /users` | `username`, `display_name`, the name of its contact, `role`, `groups`, `is_service_account`, `disabled`, `last_sign_in_at` | by username |
| `GET /audit-events` | `at`, `actor_name`, `via`, `action`, `record_type`, `record_hid` | newest first |
| `GET /imports` | `created_at`, `file_name`, `entity`, `mode`, `status`, `row_count`, `created`, `updated`, `unchanged`, `rejected`, `created_by_name`, `rows_done`, `applied`, `stale`, `applied_at` | newest first |
| `GET /imports/{hid}/rows` | `row`, `key`, `outcome`, `applied_outcome` | the order of the file |
| `GET /reports/duplicates` | `address`, `network`, `count`, `holders` | by address and network |
| `GET /device-groups/{hid}/members` | `position`, `item.name`, `item.pid`, `item.serial_number`, `role`, `observed_master`, `joined_on`, `left_on` | the current ones first, by position |
| `GET /items/{hid}/children` | any field the item list is sorted by: `position`, `name`, `catalog.pid`, `serial_number`, `effective.lifecycle_state`, `owner.label`, `location.name` and `minor_items` are the columns of its table | by position and name |
| `GET /items/{hid}/history` | `at`, `actor_name`, `action` | newest first |
| `GET /capacity-records` | `week_of`, `recorded_at`, `active.demand`, `active.supply`, `active.balance`, `active.coverage_pct`, the same four of `with_drafts`, `adjusted`, `note` | the oldest week first |

`role` of a user is the role in force, from the lowest to the highest, and a user with
none comes last; `groups` is the first of the user's groups by name. `key` of a row is
how the row names its record, or else the HID of the record it matched. `holders` of a
duplicate is the first of its holders by name, `network` its label, and `address` is
sorted as an address. `observed_master` puts the member that is seen as master first,
whichever way round. The history of an item is sorted by its events, and the changes
of one event stay together. The balance and the coverage of a record of the capacity
balance are sorted as the record shows them, worked out from its demand and its supply,
and a coverage that is blank, with no demand, comes last. The columns that a page
composes from a list of changes are not sorted by the server: What changed in the
audit trail, and Changes and Reasons of the rows of a preview (D-136).

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
far, 0.4.0 adds networks, addresses, device groups and their members, 0.5.0
regions, sites, locations, contacts, their assignments and the members of owners,
0.6.0 contracts and their coverage, purchase requests and their lines, external
systems and registrations, capacity lines and replacements, 0.7.0 the contacts of
agreements and contracts, the flag not to renew on catalog entries and items, the links
of regions, sites, locations and catalog entries, and the lines that multiply, and 0.8.0
the circuits with their carriers, cost lines, contacts and devices, circuit groups, the
contacts of vendors, and the support weight of a place.

| Entity | Columns that can be set | Further columns an export can write |
|---|---|---|
| `tags` | `label`, `colour`, `description` | |
| `vendors` | `name`, `aliases`, `notes`, `review_status` | |
| `vendor_contacts` | `vendor`, `role`, `contact`, `priority` | |
| `catalog_entries` | `vendor`, `pid`, `model_name`, `kind`, `type`, `function`, `description`, `end_of_sale`, `end_of_sw_support`, `end_of_hw_support`, `ldos`, `est_value`, `support_weight`, `annual_support_cost`, `stack_discount_pct`, `successor_vendor`, `successor_pid`, `do_not_renew`, `links`, `review_status`, `record_status`, `tags` | `stack_discount_pct_source` |
| `contacts` | `name`, `organization`, `email`, `phone`, `phone2`, `notes`, `record_status`, `tags` | `user`, the username of the user the contact is |
| `operators` | `label`, `description`, `colour`, `contact`, `record_status` | `is_open`, `scope`, and `contact_email`, `contact_phone` and `contact_phone2`, those of its contact |
| `regions` | `name`, `parent`, `code`, the shipping set, `operator`, `support_weight`, `links`, `notes`, `record_status`, `tags` | `path` |
| `sites` | `name`, `region`, `code`, the address fields, the shipping set, `operator`, `latitude`, `longitude`, `support_weight`, `links`, `notes`, `record_status`, `tags` | `path`, `support_weight_source` |
| `locations` | `name`, `site`, `parent`, `code`, `kind`, the address fields, the shipping set, `operator`, `latitude`, `longitude`, `support_weight`, `links`, `notes`, `record_status`, `tags` | `path` |
| `contact_assignments` | `region`, `site`, `location`, `role`, `contact`, `priority`, `stop_inheritance` | |
| `owners` | `label`, `organization`, `is_external`, `exception_reason`, `record_status`, `tags` | |
| `owner_members` | `owner`, `contact`, `role`, `priority` | |
| `networks` | `label`, `kind` | |
| `items` | `vendor`, `pid`, `serial_number`, `asset_tag`, `name`, `hostname`, `fqdn`, `mac_address`, `parent`, `position`, `host`, `host_group`, `observed_host`, `host_observed_at`, `description`, `comments`, `quantity`, `lifecycle_state`, `disposition`, `expected_online`, `state_reason`, `condition`, `observed_status`, `observed_at`, `owner`, `operator`, `location`, `planned_location`, `mgmt_address`, `mgmt_ipv4`, `mgmt_ipv6`, `mgmt_network`, `procured_on`, `delivered_on`, `in_service_on`, `warranty_start`, `warranty_end`, `purchase_line`, `est_value`, `support_weight`, `annual_support_cost`, `end_of_sale`, `end_of_sw_support`, `end_of_hw_support`, `ldos`, `do_not_renew`, `record_status`, `tags` | `model_name`, `kind`, `type`, `function`, `state_changed_at`, `is_major`, `depth`, `health`, `site` and `region` by their names, `owner_exception` and `owner_exception_reason`, `covered`, `covered_until`, `contract_count` and `contracts`, the numbers of the contracts that cover it today, `out_of_service_contracts`, the numbers of those that still count it while it is out of service, `purchase_line_mismatch`, `review`, the reasons it is to be looked at, `hosted_count`, and a `_source` for each of the fourteen fields that inherit, `do_not_renew_source` among them |
| `addresses` | `item`, `group`, `address`, `network`, `role`, `is_primary` | `family` |
| `device_groups` | `name`, `type`, `hostname`, `fqdn`, `parent`, `owner`, `operator`, `location`, `planned_location`, `managed_as`, `expected_members`, `observed_status`, `observed_at`, `mgmt_address`, `mgmt_ipv4`, `mgmt_ipv6`, `mgmt_network`, `record_status`, `tags` | `serial_number`, `members`, `health` |
| `device_group_members` | `group`, `item`, `role`, `position`, `joined_on`, `left_on`, `observed_master`, `master_observed_at`, and `drop_identity`, `disposition` and `expected_online`, which an export writes only when they are asked for by name, and then blank (P-217) | |
| `item_replacements` | `old_item`, `new_item`, `reason`, `reference`, `replaced_on` | |
| `external_systems` | `name`, `kind`, `url`, `notes`, `record_status` | |
| `registrations` | `system`, `item`, `group`, `external_id`, `status`, `confirmed_at` | |
| `agreements` | `name`, `number`, `vendor`, `reseller`, `starts_on`, `ends_on`, `status`, `support_level`, `purchase_reference`, `account_manager`, `support_contact`, `support_url`, `annual_cost`, `notes`, and the term that is still to begin, `next_number`, `next_starts_on`, `next_ends_on`, `next_annual_cost` and `next_purchase_reference`, `record_status`, `tags` | `contracts` |
| `contracts` | `number`, `vendor`, `agreement`, `reseller`, `starts_on`, `ends_on`, `status`, `support_level`, `purchase_reference`, `account_manager`, `support_contact`, `support_url`, `annual_cost`, `notes`, the five `next_` columns of an agreement, `record_status`, `tags` | `covered_items`, and a `_source` for each of the seven fields a contract may have from its agreement |
| `contract_contacts` | `agreement`, `contract`, `vendor`, `role`, `contact`, `priority` | |
| `contract_coverage` | `contract`, `vendor`, `item`, `starts_on`, `ends_on`, `left_service` | `in_force`, and `effective_starts_on` and `effective_ends_on`, the dates in force |
| `purchase_requests` | `reference`, `requested_on`, `status`, `notes` | |
| `purchase_lines` | `request`, `line`, `vendor`, `pid`, `part_number`, `description`, `quantity`, `destination_site`, `expected_on`, `notes` | `tracked`, `received_quantity`, `pending_quantity`, `mismatched_items` |
| `capacity_lines` | `side`, `category`, `name`, `effect`, `quantity`, `units_each`, `factor`, `share`, `applies_to`, `annual_cost`, `vendor`, `region`, `site`, `starts_on`, `ends_on`, `notes`, `record_status` | `units` |
| `circuit_groups` | `name`, `description`, `owner`, `notes`, `record_status`, `tags` | `circuits`, `monthly_cost`, `annual_cost` |
| `circuits` | `name`, `enterprise_circuit_id`, `description`, `circuit_type`, `port_mbps`, `down_mbps`, `up_mbps`, `a_location`, `a_note`, `z_location`, `z_note`, `cost_side`, `carrier`, `carrier_circuit_number`, `billing_account`, `billing_contract`, `installed_on`, `activated_on`, `disconnected_on`, `production`, `support_weight`, `owner`, `groups`, `notes`, `record_status`, `tags` | `speed`, `monthly_cost`, `annual_cost`, `a_site`, `z_site`, `cost_site`, `owner_exception`, `owner_exception_reason`, `in_service`, `support_weight_source` |
| `circuit_carriers` | `circuit`, `vendor`, `role`, `circuit_number`, `priority`, `notes` | |
| `circuit_costs` | `circuit`, `description`, `monthly_cost`, `vendor`, `starts_on`, `ends_on`, `notes` | |
| `circuit_contacts` | `circuit`, `side`, `role`, `contact`, `priority` | |
| `circuit_devices` | `circuit`, `side`, `item`, `group`, `notes` | |

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
| Matching | By `hid` when given, otherwise by the entity's key: a tag's label, a vendor's name or alias, a catalog entry's vendor and PID, an owner's label, an operator's label, a network's label, a device group's name. A region is found by its path, which is `parent` and `name`; a site by `region` and `name`; a location by `site`, `parent` and `name`. A contact is found by its email address, and a row with none by a name that one contact alone has, retired or not; of several of one name, such a row is the one that has no email address. An assignment is found by its place, its role and its contact, or as the one that stops inheritance for its place and role; a member of an owner by the owner and the contact. An agreement is found by its name. A contract is found by its number, with `vendor` where two vendors use one number; a contact of an agreement or of a contract by that record, its role and its contact; a coverage by its contract, its item and `starts_on`, or with no `starts_on` the one that is not ended; a purchase request by its reference and a line by its request and `line`; an external system by its name; a registration by its system and its item or group; a capacity line by its side and its name; a replacement by the item that left. A
contact of a vendor is found by its vendor, its role and its contact; a circuit group by
its name; a circuit by the rules under "Circuits" below; a carrier of a circuit by its
circuit and its vendor, a cost line by its circuit and its description, a device of a
circuit by its circuit and its item or group, and a contact of a circuit by its circuit,
its side, its role and its contact. For items, the order on the data model page. An address is found by its item or group, its address and its network; a membership by its group, its item and `joined_on`, or with no `joined_on` the current one. Two rows of one file that name the same record: the second is rejected |
| References | By HID, or by the natural key: vendor name, `vendor` + `pid`, owner label, network label, contract number, geographic path, group name. A contact is named by its HID, its email address or a name that one contact alone has, and an export writes the email address when there is one. An item is named by its HID, or by a serial number, an asset tag or a name that one item alone has; an export writes the asset tag when there is one, then the serial number, then the name, and the HID when another item answers to the same text. A name that has the form of an HID is read as one, so an export writes the HID of a record so named |
| Minor items | `parent` names the item a minor item is in, and `!clear` takes it out. An item that a file creates stands before the minor items the same file puts in it: an export sorted by `depth` writes them so. Rows that change items that exist are worked an item before its minor items, wherever they stand, so that a row with the owner or the state its item would inherit anyway leaves it inheriting, also when the same file changes the item above. A bulk edit is worked in the same order |
| Management address | An item and a device group have a primary management address of each family. `mgmt_ipv4` and `mgmt_ipv6` set them, and `mgmt_address` takes an address of either family and files it under its own. A value changes the one there is or adds one; `!clear` removes it, and in `mgmt_address` removes both. `mgmt_network` is the label of the network the addresses of the row are under. It is optional: with no such column the network stays as it is, and a new address is in the unlabelled address space. An export writes it where both addresses are under one network, and leaves it blank where they are under two, so that a file loaded back moves neither. A row that names `mgmt_network` and no address is rejected. Every address of a record, these among them, is in the `addresses` entity, so an export writes these columns only when they are asked for by name |
| A first file | A file of host names, with or without addresses, loads as it is: `hostname` alone makes an item, and loading it again finds each item by its host name and changes nothing. The spellings such a file is likely to use are read as the columns they mean: `ip_address`, `ip` and `mgmt_ip` as `mgmt_address`, `ipv4_address` and `ipv4` as `mgmt_ipv4`, `ipv6_address` and `ipv6` as `mgmt_ipv6` |
| Places | `location` on an item and on a device group is the path of a location, or its HID, and so is `planned_location` on an item and on a device group, which takes a location that is not in use yet. `parent` of a region is the path of the region it is in, `region` of a site the path of its region, and `site` of a location the path of its site. `parent` of a location is the path of the location it is in, whole or from the site down: `Building 1 > Floor 2`. A row of a location that names its parent whole need not name the site. The regions of one file are worked a region before the regions within it, and the locations likewise, wherever they stand. A row that would move a location to another site is rejected. A step of any of these paths may be the code of its place, and a path may begin at the code of a region or of a site, as the [data model](data-model.md#regions-sites-locations) page says: `S2 > R102` (P-235); the name a row gives a place of its own, in `name`, finds a place by its name alone. A row of an item says where the item is and is going in force, with `location_source` and `planned_location_source`; loaded back, a value that the item has anyway from the item above it or from its group gives the item nothing of its own. |
| Contacts of a place | A row of `contact_assignments` names one place, in `region`, `site` or `location`, with a `role` and a `contact`. A row with `stop_inheritance` true and no contact is the one that stops inheritance for that place and role. An import does not remove an assignment. In a file of `owner_members` the rows that name a primary are worked first, wherever they stand, so that the first member of an owner is its primary and a change of primary comes out right |
| Contacts of contracts | A row of `contract_contacts` names one record: an `agreement` by its name, or a `contract` by its number, with `vendor` beside it where two vendors use one number. It names a `role`, `account_manager` or `support_contact`, and a `contact` as any column names one. A row with no `priority` is listed after the others of its record and role. An import does not remove one, and a row does not move one to another record |
| Not to be renewed | `do_not_renew` of a catalog entry is `true` or `false`, and `!clear` makes it `false`. `do_not_renew` of an item is its own word, and `!clear` gives it its model's again; a row that holds the very flag the item has from its model leaves it inheriting, as for every value of the catalog. An export of items in force writes the flag in force with `do_not_renew_source`, and one with `own_values` the item's own. A bulk edit sets it as a file does |
| The operator | `operator` on an item, a device group, a region, a site and a location names an operator by its label, and `!clear` returns the record to the operator it has from above. A row that names the operator an item has anyway, from the item above it, its group or its place, leaves it inheriting. The person behind a label is in the file of `operators`, in `contact`: an email address, or a name that one contact alone has, and `!clear` leaves the label open. An import does not retire an operator |
| An external owner | An item or a group that a row gives to an owner outside the team is marked as an exception by that alone. The reason is the owner's, in `exception_reason` of the file of owners; `owner_exception` and `owner_exception_reason` of an item are written by an export and passed over by an import |
| Groups | A group is loaded before its members. The groups of one file are worked a group before the groups within it, wherever they stand. A row of members with the role `master` marks the master that is intended, and takes the mark from the member that had it. `observed_master`, true on the row of one member, records on the stack that this member is seen to be master, with `master_observed_at` or else the moment of the change. One file names one intended master and one observed master of a stack at most: a second row that names one is rejected. A row that adds a member to a stack may give `drop_identity` true, and a row that adds a member `disposition` and `expected_online`, which mean what they mean on `POST /device-groups/{hid}/members`; the preview notes on each such row what is cleared and what is removed. A row of a membership that is there already is not given them again, and its notes say so (P-217). A row that adds a member to a stack with no `position` takes the lowest free one, and the rows of a file that give a stack's members their positions are worked before those that give none (P-219) |
| Observation | `observed_status` is `online`, `degraded`, `unreachable` or `present`, and `observed_at` the moment it was seen: left out, the moment of the change, and with no zone named, in the application's time zone. A row that states a status as it is, with no moment, changes nothing, where a person who does so on a page or by a bulk edit has looked again and sets the moment to now. `!clear` in `observed_status` clears both, and a moment is not cleared by itself. What a preview tells of a row leaves out a moment that the clock will set, since the apply is made later. A site that reads the status of its devices from another tool, or walks its store room, loads the result as a file of `hostname`, `observed_status` and `observed_at` |
| Missing references | A vendor or catalog entry that does not exist is created and marked `unreviewed`. Any other missing reference rejects the row. A catalog entry that a file's own later row describes is created by that row, and is then as reviewed as the row says |
| Blank cells | Leave the stored value alone. In JSON, so does a field that is left out, or one that is empty text |
| Clearing | The literal `!clear` in a cell, or `null` in JSON, clears the value so that it inherits again. In JSON an empty list clears a list |
| Inherited values | An import does not turn an inherited value into an override. Where a field inherits and the record has no value of its own, a cell that holds the very value it inherits leaves it inheriting. That is so for an item and its model, for a catalog entry and the global stack discount, for a row that gives an item another model while still holding the values of the old one, and for a minor item and the owner, the location and the standing of the item above it. It is so too for a major item and `default_item_weight` and for a site and `default_site_weight`, and a row that holds the weight a major item or a site is raised to, by `minimum_item_weight` or `minimum_site_weight`, changes nothing of it, so that an export of weights in force comes back unchanged (P-155) |
| Lifecycle | A row with a different `lifecycle_state` moves the item by a transition, under the rules of moves and never by force, with the row's `state_reason` as the why and its `disposition` and `expected_online` as named. A `state_reason` is taken with a move only. `!clear` in `lifecycle_state` returns a minor item to the standing of the item above it, and is refused for a major item |
| Retiring | An import does not retire. A row that would change `record_status` to `retired` is rejected; a row may bring a retired record back with `active` or `draft` |
| Unknown columns | Reject the file, naming the column. A column that an export writes and nobody can set is not unknown: it is passed over, so any export can be imported back |
| Preview | `POST /imports/preview` stores the parsed file and returns, per row: `create`, `update` with the changed fields, `unchanged` or `rejected` with reasons. A file that cannot be read at all is refused with a `422`, and nothing is stored. The answer holds the counts and the first hundred rows; `GET /imports/{hid}/rows` pages through all of them, `outcome=rejected` keeps to one kind, and `sort` puts them in another order than that of the file |
| Apply | `POST /imports/{hid}/apply` answers at once with `202` and the job, and the server applies it in the background, in a worker of its own beside the requests. The job is `applying`, or `queued` while another job is being applied: one is applied at a time, in the order they were asked for. The rows are worked in the order the file needs, which is worked out once for the whole file, and applied 50 at a time, each batch a transaction of its own with its audit events. Between two batches the one writer's place is let go, so a sign-in or another change waits a fraction of a second at most. A batch never splits the rows that are checked together: the members of one group are one batch, however many they are. `GET /imports/{hid}` answers how far it has got while it works: `rows_done` of `row_count`, `applied` and `stale`, beside the counts of the preview. The job is `applied` once every row has been worked. Each row says what the apply did with it, in `applied_outcome`: `create`, `update` or `unchanged` as previewed, or `stale` or `rejected` with the reasons in `applied_reasons`; it is blank until the row is worked. `GET /imports/{hid}/rows` takes `applied_outcome` to keep to one kind. Of `rows_done`, what is neither `applied` nor `stale` is `rejected`. A job that stops partway, because of an error nobody foresaw or because the server stopped, keeps the batches it applied, undoes the one it had not finished, and is `stopped`, with the reason in `failure`; a job that the server finds `applying` as it starts was stopped by the stop, and one found `queued` is applied in its turn. `POST /imports/{hid}/apply` on a stopped job resumes it from the first row it had not applied, and nothing is applied twice. A job that is `queued`, `applying` or `applied` is not applied again: `409`. A job of a release before 0.7.0 may be `failed`: it was applied as one transaction and undone, and is not applied |
| What "changed since" means | Each row is worked again as it was previewed, when its batch comes. A row whose record is not at the version it was previewed at, also when the row was `unchanged`, or that would no longer do what was previewed, with the same changes and the same notes, is not applied: it is `stale`, with the reason, and the rest go on. A row that rests on a stale one, such as a minor item in an item that was not made, is refused in its turn by the rules and is `rejected` with its reason. A stale row is applied by previewing it again |
| Whose preview | A preview is applied once, by anybody who holds the Inventory role, whoever made it: one person may prepare a file and another look it over and apply it. The job says who made it, and in `applied_by` and `applied_at` who asked for it to be applied, or resumed it, last, and when. The rows are applied as that person, who must still hold the Inventory role when the server comes to them: a job whose person no longer does is `stopped`, and anybody who does may resume it. Anybody who may read the inventory may read it |
| Rejected rows | By default any rejected row blocks the apply, with a `422`, and the preview stays good. `skip_rejected=true` applies the rest, and each row the preview rejected is then `rejected` at the apply, with the reasons of the preview. A stopped job is resumed as it was begun, and is not asked for `skip_rejected` again |
| Limits | 20 MB and 100,000 rows per file. A larger file is a `413`. A site may raise the 20 MB in its configuration file and in nginx; see [install.md](install.md#uploads). Behind the packaged nginx a body of more than 20 MB is refused by nginx itself, with a `413` that is nginx's own page and not a problem document |
| Agreements | `agreement` on a contract is the name of the support agreement it is grouped into, and `!clear` takes it out of one. A row of a contract that holds the very value the contract has from its agreement leaves it inheriting; an export with `own_values` writes only what the contract says of its own |
| Contracts and coverage | `contract` in a file of coverage is the number of a contract, and `vendor` beside it says which where two vendors use one number. A row covers one item, named as any column names an item. A row with no dates takes the contract's. An import does not remove a coverage: it is ended by a row that gives it `ends_on`. Under one contract an item has one coverage at most with no start of its own, so a row with no `starts_on` is that one; a row that finds one which has ended, and gives it nothing new, says so in its notes, since covering the item again takes a row with the day the new coverage starts. A file of contracts or of agreements holds the record as it is stored: the present term in `number`, `starts_on` and the rest, and a term that is still to begin in the `next_` columns |
| Purchases | `request` of a line is the reference of its request, and `line` its number there: left out, a new line takes the next. `part_number` and `description` are kept as procurement gave them. A row is matched to a model by its part number, `pid` where the row gives one and `part_number` where it does not, against the PIDs of the catalog without regard to case, surrounding space or the `=` that ends the part number of a spare, on either side: `PWR-C1-715WAC-P=` finds `PWR-C1-715WAC-P`. It is matched among the models of `vendor` where the row names one, and among all models where it does not. One model that answers is the line's. None, a vendor there is not, or two models or more, such as one PID of two vendors, leave a new line not tracked, and its notes in the preview say why, naming the models where there are several. A file of lines makes no vendor and no catalog entry. A row whose part number answers to no one model leaves a line the model it has, and a row that names `pid` and no part number gives a line that it cannot match that PID as its part number. A row that would give a line on which items have arrived another model is rejected: that is corrected by hand, where what becomes of the items is said. A line has a model or a part number, and a row that leaves it neither is rejected. `purchase_line` on an item names the line it arrived on, as `RITM0012345/2`, or by the HID of the line. A file of items with that column is how the serial numbers of a delivery are loaded: each new item is in whatever state its row says, and counts as received on its line. A row that would put more items on a line than its quantity is rejected, and so is one for a line of a request that is a draft or cancelled. A row with no `vendor` and `pid` that names a line takes the line's model, and one that names another model than its line's is rejected. What was received as a count is named for its line, `RITM0012345/2-003`, and a file that names it so gives it its serial number |
| Registrations | A row names a `system` and one of `item` and `group`. A registration is not removed by an import: a row gives it the status `removed` |
| Links | `links` of a region, a site, a location and a catalog entry holds the links of the record in their order, each written `text <url>`, or `<url>` where it has no text, and joined with `;`: `Data sheet <https://www.example.com/c9300.pdf>; <https://www.example.com/c9300-install.html>`. The text of a link runs to its `<`, so it may hold a `;`, and each link ends with its `>`. A JSON file holds the same text. The cell is the whole list: a row that names it changes the links whole, and `!clear` leaves the record none. An export writes them so, and a file carries them out and back unchanged. A link that is not written so, or whose address is not a web address, rejects the row, naming the link |
| Capacity lines | `effect` is `add`, as it is when left blank, or `multiply`. `applies_to` of a line that multiplies names the staff lines it works on, each by its name, joined with `;`: a line whose name holds a `;` cannot be named there, and is named on its own page or through the API instead. A line that multiplies leaves `quantity` and `units_each` blank, and is worked after the lines of the same file it may apply to, wherever it stands |
| Replacements | A row of `item_replacements` names the item that left, `old_item`, and the item that took its place, `new_item`, both of which exist. It is matched by its `hid`, or else by its two items and its `replaced_on` (P-241). A row that gives no `replaced_on` is the one replacement of those two items where there is one, and a new one, of today, where there is none; where there are several it is rejected, and asks for the day. A row that matches one changes its `reason` and `reference` alone, and one that would give it another item or another day is rejected. An export writes `replaced_on` on every row, so that a file exported loads back and changes nothing, an item replaced twice and two items that swapped places and back among them. Loaded into an inventory that has neither, it is loaded after the items and after the members of groups: what the file of members shows as handed over is then not handed over a second time |
| Circuits | A row of `circuits` finds its circuit by `hid`; then by `enterprise_circuit_id`; then by `carrier` with `carrier_circuit_number`, the primary carrier and the number it gives the circuit, which are the primary carrier's columns, so that a number a carrier gives as another of a circuit's carriers finds nothing here, and the row is refused for the number another circuit has; then by a `name` that one circuit alone has among those that are not retired; and is otherwise a new circuit. The first of these that the row gives decides, as for items: a row with an enterprise circuit ID that no circuit has is a new circuit. More than one answer is an error on the row, never a guess. So two circuits of one name with neither an enterprise circuit ID nor a primary carrier's number cannot be told apart by a file loaded without their HIDs, as two items of one name with neither a serial number nor an asset tag cannot: loaded into an empty inventory, the second row is rejected as naming the record of the first, and such circuits are given an enterprise circuit ID to travel. `down_mbps` and `up_mbps` are the circuit's own, blank being the full rate of the port, and a row that gives the port's rate to a circuit that has none of its own leaves it so. `circuit` in the other files of circuits names one by its HID, its enterprise circuit ID or a name that one circuit alone has, and an export writes the enterprise circuit ID where there is one, then the name, and the HID where another circuit answers to the same name. `a_location` and `z_location` are the path of a location or its HID, and `!clear` leaves a side with no location, which then needs its note. `groups` names the circuit's groups, joined with `;`, and is the whole list, as `tags` is. A carrier that is no vendor yet is made one, `unreviewed`. A new circuit with no `cost_side` takes the setting `circuit_cost_side`. `side` of a contact of a circuit is blank for one of the carrier's, with the role `account_manager` or `support_contact`, and `a` or `z` for a site contact, with a role of the `contact_role` list. An import removes no carrier, cost line, device or contact of a circuit |
| Load order | tags, vendors, catalog entries, contacts, vendor contacts, operators, regions, sites, locations, contact assignments, owners, owner members, networks, external systems, agreements, contracts, contract contacts, purchase requests, purchase lines, items (parents before children), device groups, members, replacements, addresses, coverage, registrations, capacity lines, circuit groups, circuits, circuit carriers, circuit costs, circuit contacts, circuit devices. Addresses come after the groups, because a group has addresses too, and the devices of circuits after the items and the groups they name |
| Audit | Each record an import creates or changes has its own audit event, with `via` of `import`, and all of them share the request ID of the apply, in whichever batch they were made; after a resume, the request ID of the resume. The preview is an event on the job, and so are `apply_started`, `apply_resumed` and `apply_stopped`, the last made by the server, and `apply` at the end, with the counts of what the apply did |

### Export

`POST /exports` takes an entity, a filter, a sort, a list of columns, a format (`csv` or
`json`) and optionally a list of at most 10,000 HIDs. The response is streamed. `hid`
is always the first column. Inheritable fields export their effective value;
`include_sources=true` adds the `_source` columns, and `own_values=true` exports stored
values instead, which is the form to use for a file that will be imported back.

A place is written as the path of its names. With `place_codes=true` each place is
written the short way, by codes (P-235): a region by its code, a site by its code, and a
location by the code of its site and its own, `S2 > R102`. Where a place has no code,
its names stand in for it, `S2 > Building 1 > Room 102` and `Americas > Central > Site-2
> R102`, and a place whose short way would find another, where a name wins over the
code, is written by its names. That holds for every column that names a place, `path`
among them, and such a file loads back to the same places.

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

### The records an import made

`GET /imports/{hid}/created`, which every role reads that reads imports, lists the
records an import made, one row of the file each, in the order of the file, and is
paged with `limit` and `offset` as the rows of an import are (P-234):

```json
{ "total": 40, "limit": 100, "offset": 0,
  "items": [ { "row": 1, "record_type": "item", "record_hid": "0193a1f4-...",
               "label": "site2-sw-access-01", "state": "retired" } ],
  "also": [ { "record_type": "catalog_entry", "record_hid": "0193a1f9-...",
              "label": "Cisco C9300-48P", "state": "active" } ] }
```

`record_type` is the kind of record, as the audit trail names it, `label` what it is
known by now, as `POST /items/retire` gives it, and for one that was deleted what it was
known by then. `state` is what it is now: `active`, `draft`, `retired` or `deleted`; a
record with no status of its own, a tag, a network, an address or a membership, is
`active` while it stands. `also` lists, after them and whole, the vendors and the
catalog entries that the import made only because a row named them and that no row of
it described. Nothing new is stored: a row that made a record keeps its HID, and the
audit trail the request that made the others. A preview that was not applied made
nothing, and lists none. A bulk edit makes no item, so its `items` are none, and its
`also` lists the models it made where it gave items one that the catalog had not.

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
it under the same rules: in the background, 50 items at a time, once, by anybody who
holds the Inventory role, with `202` at once and the job, which `GET /imports/{hid}`
follows. An item that has been changed since the preview is left as it is, and its row
is `stale`. A second person who bulk-edits rows that the first has just changed is told
which, and nothing of their change overwrites the first; the items nobody changed are
changed.

### Fixing a wrong import

A file that was wrong is put right in the way that fits what was wrong (P-234). Each
way is the Inventory role's, but deleting, which is an Admin's.

**Before it is applied.** A preview changes nothing, and is applied only when asked.
Its counts say what the file would do: a file meant to change records that are there,
whose rows come out `create`, names them otherwise than the inventory knows them, by
another serial number, another PID, or no HID; a file meant to add records, whose rows
come out `update` or `unchanged`, names records that are there. Each row says how it
names its record, in `key`, what it would change, and in `notes` what else it brings
about, such as a catalog entry made for a model nobody has entered. A preview that is
wrong is left unapplied, and the file corrected and previewed again.

**Wrong values on the right records.** Export the records with their HIDs and
`own_values`, for an import the HIDs that `GET /imports/{hid}/created` lists, or the rows
ticked in a list; correct the values in the file and import it back. Each row finds its
record by its HID and changes what was corrected, and nothing else. Or change them by a
bulk edit, `POST /items/bulk-update` or `hirdir items set`, which sets one value on many
items at once after a preview: a place, an owner, a state, and a model too, by `vendor`
and `pid`, which gives every item of the rows another model, made `unreviewed` where
the catalog has none. What tells one item from another, a serial number, an asset tag,
a name or a host name, is not set on several at once, and is corrected by the file
with HIDs.

**The kind of a model.** Whether a model is a switch or a router is its catalog
entry's, in `type`, beside `kind` and the rest of what is true of every item of it, and
each item reads it from there. One change of the catalog entry, on its page, by `PATCH
/catalog-entries/{hid}` or by a file of `catalog_entries`, changes it for every item of
the model at once, and no item is written to.

**Records that should never have been.** `GET /imports/{hid}/created`, and `hirdir
imports created`, list what an import made, each with what it is now. The Inventory
role retires those that should never have been, by `POST /items/retire` and `POST
/device-groups/retire` or `hirdir items retire`: they leave the lists and the counts,
stay found by their HIDs, and are brought back with `PATCH`. An Admin deletes them, by
`POST /items/delete` and `POST /device-groups/delete` with a reason or `hirdir items
delete --reason`, after a dry run that says which would go and what stands in the way
of the others. The vendors and catalog entries that it lists in `also` are `unreviewed`
and stay: a catalog entry that nobody needs is retired on its page, and nothing deletes
a vendor.

**A second, corrected file.** While the first file's records are only retired, a
corrected file meets them by the rules of "Identity and matching" on the
[data model](data-model.md#identity-and-matching) page. A row with the vendor, the PID
and the serial number of a retired item, or with its asset tag alone, is that item, and
changes it, which stays retired unless the row gives `record_status` `active`. A row with
another PID and the same serial number is a new item, and so is a row with a name or a
host name alone, since neither finds a retired item. A row that would make a new item
with the asset tag of a retired one is rejected, as the tag is that item's. So either
the second file names the first set by their HIDs, corrects them and brings them back,
or an Admin deletes the first set before the second file is applied, which then makes
every record anew: a record that was deleted is found by no file, and its serial number
and asset tag are free.

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
`region`, `contract`, `group`, `model`, `lifecycle_state`, `disposition`, `condition`, `health` and `tag`. By
`operator` it is by the operator in force, each row with the label, and the blank row
is what nobody is assigned to. With `operators=true` each row also lists, in
`operators`, the operators in force among its items: the label with who is behind
it, and the items, components and support weight it has in that row, the one with
the most first and what nobody is assigned to last. So a summary by `site` says who
is involved at each site, and with how much.

**The management report**, `GET /reports/management`, is for the people who pay for
the network. It holds `items`, `component_count`, `est_value` and
`annual_support_cost`, and neither condition nor health. `by` is one of `vendor`,
`kind`, `type`, `function`, `owner`, `operator`, `site`, `region`, `contract`, `group`, `model` and `tag`. With no `by` it is by
`site`, and the answer says so: the whole inventory, and each site beneath it.

In both, a row of `site` or `region` has the HID of the place as its key and its path
as its label, and the items that are nowhere are in the blank row. A row of a region
holds everything at or beneath it: an item is in the row of each region above it, as an
item with several tags is in the row of each, and the totals count it once. By
`contract` an item is in the row of each contract that covers it today, labelled with
the number of the contract and the name of its vendor, and the blank row is what no
contract covers. By `group` a row is a device group that is not retired, keyed by its HID
and labelled with its name, beside its `type`, its `member_count` and how many groups are
nested in it, `nested_groups`; it holds its current members, the current members of
every group nested in it at any depth, and the minor items of all of them, and the blank
row holds the items in no group. An item in several groups is in the row of each, and
the totals count it once (P-178). By `model` a row is a catalog entry, keyed by its HID
and labelled with its vendor and PID, `Cisco C9300-48P`, beside `vendor`, `pid`,
`model_name`, `kind` and `type`, and the blank row holds the items with no catalog entry
(P-180). By `operator` a row also answers `own`, `from_item`, `from_group` and
`from_place`, how its items have the operator, which add up to its items, and
`groups_given` and `places_given` (P-178, P-181). A row of `type` or
`function` is labelled as its list of choices labels the value. A minor item is in the
row of the owner, state and disposition in force for it. An item with several tags is
in the row of each, and the totals count it once. A stack whose members fall in two
rows is a managed node in both, and one in the totals.

**What a count lists** (P-206). In both, `totals`, each row and each entry of
`by_kind` and `by_condition` has `filter`: the filter of the item list that keeps
exactly the items its `items` counts, within the view asked for. It holds the request's
own filter and the condition of the row, and is sent to `GET /items` with the same
`include_archived` and `include_drafts`, the minor items asked for. It is written in
the short form where the short form says it, `catalog.type:eq:switch site_hid:eq:…`, and
otherwise as the filter tree in JSON, as `filter=` takes either: the row of the kind
`hardware`, which holds the items with no kind as well, has an OR. It is blank on the
totals of a view with no filter, and null where it, with a condition below joined to it,
would hold more conditions or nest deeper than a filter may. The answer has
`conditions` once, each a filter written as a `filter` is, which joined by AND to a
`filter` of the answer keeps what one of its counts counts: `component_count`, the
components; `component_count_by_kind`, for an entry of `by_kind`, the major items in
hand of whatever kind; and, in the summary, `by_health`, the components of each health.
So each count of items, of components and of health opens as the list of what it
counts, and the rule of what is counted stays here. `managed_node_count` counts devices
on the network, not items, and `support_weight`, `est_value` and `annual_support_cost`
are sums: none of them is a list. A row is kept by:

| `by` | A row | The blank row |
|---|---|---|
| `vendor`, `model`, `type`, `function` | `catalog.vendor_hid`, `catalog_entry_hid`, `catalog.type`, `catalog.function` `eq` its key | the same field `empty` |
| `kind` | `catalog.kind` `eq` its key, and for `hardware` or `catalog.kind` `empty` | none |
| `owner`, `operator` | `effective.owner_hid`, `effective.operator_hid` `eq` its key | the same field `empty` |
| `site` | `site_hid` `eq` its key | `site_hid` `empty` |
| `region` | `location` `within` its key | `region_hid` `empty` |
| `contract` | `contract.hid` `eq` its key | `covered` `eq` false |
| `group` | `group` `within` its key | `group` `empty` |
| `lifecycle_state`, `disposition` | `effective.lifecycle_state`, `effective.disposition` `eq` its key | the same field `empty` |
| `condition`, `health` | `condition`, `health` `eq` its key | the same field `empty` |
| `tag` | `tags` `has` its label | `tags` `empty` |

Every grouping can be opened. A test holds, for every row and total of the examples,
that the item list asked with its filter counts what the report says.

`GET /reports/duplicates` lists each address that is held more than once under one
network, with the unlabelled address space as one network of its own: the address, the
network, and the items and groups that hold it. A holder that a list leaves out by
default is not counted, unless `include_drafts` or `include_archived` asks for it. It
pages with `limit` and `offset`, and takes `sort`: `address`, `network`, `count` and
`holders`, which is the first of the holders by name.

**The coverage report**, `GET /reports/coverage`, is of today, and takes `filter`
and `include_drafts` as the item list does:

```json
{ "as_of": "2026-11-14", "within_days": 90,
  "service_states": ["Assigned", "Test", "Prod", "Down"],
  "totals": { "in_service": 412, "covered": 388, "uncovered": 18, "out_of_service": 3,
              "expiring": 17, "overlapping": 5, "renewal_pending": 40, "not_renewed": 6 },
  "sections": {
    "uncovered":       { "count": 18, "include_archived": false, "filter": { "and": [ "..." ] } },
    "out_of_service":  { "count": 3,  "include_archived": true,  "filter": { "...": "..." } },
    "expiring":        { "count": 17, "include_archived": false, "filter": { "and": [ "..." ] } },
    "overlapping":     { "count": 5,  "include_archived": false, "filter": { "...": "..." } },
    "renewal_pending": { "count": 40, "include_archived": false, "filter": { "...": "..." } },
    "not_renewed":     { "count": 6,  "include_archived": false, "filter": { "and": [ "..." ] },
                         "by_model": [ { "catalog_entry_hid": "0193a1f4-...", "vendor_hid": "0193a1f4-...",
                                         "vendor": "Cisco", "pid": "CP-8851-K9",
                                         "model_name": "IP Phone 8851", "count": 6,
                                         "filter": { "and": [ "..." ] } } ] } },
  "lapsed_contracts": { "count": 2, "filter": { "field": "lapsed", "op": "eq", "value": true } },
  "section": "uncovered", "items": [ "..." ], "total": 18, "limit": 100, "offset": 0 }
```

`in_service` is the major items of the view whose state in force is one of
`service_states`, and `covered`, `uncovered` and `not_renewed` split them: those a
contract covers today, and of the others those that are a gap and those that are not
to be renewed. An item whose flag not to renew is in force, its own or its model's, is
no gap: it is left off `uncovered`, and off `expiring` when its cover runs out.
`out_of_service` is every item, major or minor and whatever its status, that is out
of service and that a contract still counts: one that is retired
or in Pending-Removal, Released or Archived and whose cover goes on, and one whose
coverage was ended because it left while the term of its contract still runs. It is
the list to send the vendor: cover that is paid for and no longer needed. `expiring`
is the items in service whose cover runs out within `within_days`, the setting
`renewal_warning_days`, 90 unless changed, where it is not asked, and whose flag not
to renew is not in force. `overlapping` is the items that more than one contract
covers today: a list to look at before a renewal, and not a fault, since two contracts for one device
are usually one too many and now and then are meant. `renewal_pending` is the items
covered by a contract whose renewal is pending. `not_renewed` is the items in service
that no contract covers today and whose flag not to renew is in force: what is left
out of support on purpose. It alone has `by_model`, its items counted for each model,
by vendor and PID, each with the HID of the catalog entry, the vendor, the PID, the
model's name and the `filter` that lists those items, and the items with no model
last in a row of their own; on the other sections `by_model` is blank. `section`
names one of the six, and
the answer then holds a page of its items, as the item list returns them, by `limit`,
`offset` and `sort`: those that run out the soonest first for `expiring`. Each
section says the `filter` that lists the same items on `GET /items`, with
`include_archived` as it must be sent, so a count leads to its rows, to the grid and
to an export of them. A section's `filter` is blank only where the filter the report
was asked with is already as large as a filter may be; its items are then read with
`section`. `lapsed_contracts` is how many contracts have a period that has ended
while their status still says active, with the filter that lists them on
`GET /contracts`: with no filter all of them, and with one those that have a coverage
of an item of the view that follows the contract, as a lapsed contract covers nothing
today (D-168). Its filter is blank where they are more than a filter can name.

The coverage report, the renewal worklist and the summary of the renewal alert are
kept once they are worked out, and given again while nothing could have changed them:
each is kept with the newest audit event of a change of the inventory or its settings,
the day in the application's time zone and the request whole, so that a change, which
always writes an audit event, or the turn of the day leaves it unused. A sign-in,
seeing the alert, a preview and a change of an account leave it good. The report counts each of its sections with a count of its own
over the items. See "Answers that are kept" in
[architecture.md](architecture.md#answers-that-are-kept).

**The renewal worklist**, `GET /reports/renewals`, is what a person must act on to
keep the cover going, as of today (D-178). It takes `filter`, `include_drafts` and
`include_archived` as `GET /contracts` does, and `within_days`, how far ahead a
contract counts as ending: the `renewal_warning_days` setting, 90, unless asked
otherwise.

```json
{ "as_of": "2026-11-15", "within_days": 90, "overdue_after": 60,
  "totals": { "ending": 4, "lapsed": 1, "renewal_pending": 3, "overdue": 1,
              "ends_with_term": 1, "to_review": 2, "overlapping": 5 },
  "sections": {
    "ending":          { "count": 4, "include_archived": false, "filter": { "and": [ "..." ] } },
    "overlapping":     { "count": 5, "include_archived": false, "filter": { "...": "..." } } },
  "agreements": { "ending": { "count": 1, "filter": { "...": "..." } },
                  "lapsed": { "...": "..." }, "renewal_pending": { "...": "..." } },
  "groups": [ { "vendor_hid": "0193a1f4-...", "vendor": "Cisco",
                "agreement_hid": "0193a2c0-...", "agreement": "Cisco Enterprise Agreement",
                "counts": { "ending": 3, "lapsed": 0, "renewal_pending": 2, "overdue": 1,
                            "ends_with_term": 1, "to_review": 2, "overlapping": 4 },
                "filters": { "ending": { "...": "..." }, "overlapping": { "...": "..." } } } ],
  "section": "renewal_pending", "contracts": [ "..." ], "items": [],
  "total": 3, "limit": 100, "offset": 0 }
```

The lists are of contracts but the last. `ending`: those that cover today and whose
period in force ends from today to `within_days` ahead, that have no renewal entered
that is still to begin, their own or, for one whose end is its agreement's, the
agreement's, and that the team has not marked not to renew. `lapsed`: those whose period has ended while they still
say they are active. `renewal_pending`: those whose status in force is
`renewal_pending`; each says `renewal_pending_days`, the days since the end of the
term the renewal is for, and `overdue` is the part of them pending for longer than the
`renewal_pending_overdue_days` setting, 60 unless changed. `ends_with_term`: those the
team marked not to renew, as when a site closes, that end within `within_days` or have
ended, until a person says they have expired or retires them: shown so that a person
sees what is let go, and never in the alert. The mark changes no date, status or
coverage by itself, and is not lapsed. `to_review`: the members of an agreement that is
active and runs on that still say their renewal is pending or that they have expired,
which no renewal of an agreement changes, and that the team has not marked not to
renew, so that a person makes each active, takes it
out of the agreement or retires it. `overlapping`: the items
that more than one contract covers today, as the coverage report has them. Each list
says the `filter` that lists the same rows on `GET /contracts`, or on `GET /items` for
`overlapping`. `groups` has one entry for each vendor and agreement that has something
on a list, the contracts that stand by themselves under their vendor with no
agreement; the vendors by name, and within a vendor the agreements by name and those
standing alone last. Each counts its lists and says the filter of each. `agreements`
counts the agreements that end, have lapsed or have a renewal pending in the same way:
renewing one renews every contract that shares its period. `section` asks for a page
of one list, the soonest end first, as `GET /contracts` returns the rows, or
`GET /items` for `overlapping`; `renewal_pending_days`, `renewal_overdue`,
`renewal_waiting` and `to_review` are fields of the contract list to filter and sort
by. A filter of a section that would have to name more records than a filter takes is
blank, never wider: its rows are then read with `section`.

**The renewal alert**, `GET /renewals/alert`, answers for the person signed in
(D-179):

```json
{ "as_of": "2026-11-15", "within_days": 90, "overdue_after": 60, "show": true,
  "version": "5f1c0e9a2b7d4c31a8e6f0b2d9c4e7a1",
  "lapsed": { "count": 1, "new": 1, "section": "lapsed" },
  "renewal_pending": { "count": 3, "new": 0, "section": "renewal_pending" },
  "overdue": 1,
  "ending": { "count": 4, "new": 2, "section": "ending" },
  "agreements": { "ending": 1, "lapsed": 0, "renewal_pending": 0 } }
```

Each count leads to its list of the worklist, `section`, and `agreements` counts the
agreements on the same lists. `show` is true for a person with the Inventory or the
Admin role when a count is more than none and they have not dismissed the alert yet
that day, in the application's time zone, and for everybody else always false: it is
shown once a day to each person (the owner's answer of 2026-11-15). `new` is how many
of the contracts on a list were not on it when the person last dismissed it.
`POST /renewals/alert/seen` keeps, for the person who sends it, that they have seen it
that day, with the contracts on each list then; `version` may be sent and is not
required. It is an audit event on their own user, `alert_seen`; any role may send it,
and it changes no contract. The answer is worked out just after midnight in the
application's time zone and when the server starts, and kept as the reports are, so
that the first sign-in of the day is not kept waiting.

**An agreement renewed with its members.** `POST /agreements/{hid}/renew` takes,
beside what a contract's renewal takes, `members`: for each contract that shares the
agreement's period, a contract in it whose end is the agreement's whatever its start,
`contract_hid` and `renewal`, `same`, `new_number` or `ends`, and for `new_number` its
`number`, with `annual_cost` and `purchase_reference` where they are known; two members
are not given one number. Each may be given `status`, which it has from this change:
the operator's confirmation that it moves forward. Nothing else in the renewal changes
a member's status, a new number among them, and a number that waits keeps the member's
status when it begins. A member left out is `same`; a contract named that does not
share the period is a `422` that names it. The answer is the agreement with
`members`, what was done with each, `to_review`, the members to look at, and
`left_behind`, how many coverages of items that are not to be renewed the renewal
ended with the present term; a contract's own renewal answers `left_behind` too. No
member's status is changed by the renewal: a member that still says `renewal_pending`
or `expired`, or that the team marked not to renew, is among `to_review`, and the
agreement's record lists those that still say pending or expired in
`members_to_review` for as long as they do. A number that waits
on the agreement's next term is the member's `next_term` with `with_agreement` true,
and the agreement's dates. See "An agreement renewed with its members" on the
[data model](data-model.md#contracts-and-contract_coverage) page.

**A contract's history.** `GET /contracts/{hid}/terms` lists the parts of a
contract's history before the present one, the latest first: each with `began_on`,
`ended_on` and `began_by`, `created`, `renewal`, `joined` or `left`, beside the
number, the dates in force with their sources, the agreement it was in and when the
change that ended it was made. `GET /contracts/{hid}` answers `part_began_on` and
`part_began_by` of the present part; a list leaves them blank. `GET
/agreements/{hid}/terms` gives an agreement's earlier terms with the same days.

**The end-of-life report**, `GET /reports/end-of-life`, takes `filter`,
`include_drafts` and `include_archived`, and `date`: `end_of_sale`,
`end_of_sw_support`, `end_of_hw_support` or `ldos`: where it is not asked, the setting
`end_of_life_date`, `ldos` unless changed. A date is the one in force for the item,
its own or its model's.

```json
{ "as_of": "2026-11-14", "within_days": 730, "date": "ldos",
  "dates": { "ldos":        { "past": { "items": 6, "component_count": 6 },
                              "approaching": { "items": 40, "component_count": 38 } },
             "end_of_sale": { "...": "..." } },
  "by_fiscal_year": [ { "fiscal_year": 2027, "starts_on": "2027-01-01", "ends_on": "2027-12-31",
                        "items": 22, "component_count": 20 } ],
  "sections": { "past": { "count": 6, "filter": { "...": "..." } },
                "approaching": { "count": 40, "filter": { "...": "..." } } },
  "section": "approaching", "items": [ "..." ], "total": 40, "limit": 100, "offset": 0 }
```

`past` is before today and `approaching` from today to `within_days` ahead: where it
is not asked, the setting `end_of_life_within_days`, 730 unless changed. `dates` counts both for each of the four dates.
`by_fiscal_year` has one row for each fiscal year that the chosen date of an item of
the view falls in, past years among them: a fiscal year starts on the first day of the
`fiscal_year_start_month` setting and is named for the calendar year it ends in.
`section` asks for a page of the items, the soonest date first. The report holds no
money: the management report takes the same filter.

**Replacements**, `GET /reports/replacements`, is the list of replacements: it takes
`filter`, `sort`, `limit` and `offset` as a list does, by `reason`, `reference`,
`replaced_on`, `old.name`, `old.serial_number`, `new.name` and `new.serial_number`,
the newest first unless asked otherwise, and beside the page it answers `by_reason`,
the count of each reason among what the filter matches.

**The capacity report**, `GET /reports/capacity`, answers the balance of the whole
installation as of today, twice:

```json
{ "as_of": "2026-11-14", "weight_per_resource_unit": "300",
  "active": { "support_weight": "2400", "items_weight": "2385", "places_weight": "9",
              "circuits_weight": "6",
              "defaulted": { "items": 12, "sites": 2, "circuits": 0 },
              "raised": { "items": 3, "sites": 0, "circuits": 1 },
              "infrastructure_demand": "8", "other_demand": "2",
              "demand": "10", "supply": "9.6", "balance": "-0.4", "coverage_pct": "96",
              "own_units": "6", "own_share_pct": "62.5", "outside_units": "3.6",
              "annual_cost": "0.00",
              "by_category": [ { "category": "staff", "label": "Staff", "lines": 3,
                                 "units": "6", "annual_cost": "0.00" },
                               { "category": "services", "label": "Services", "lines": 1,
                                 "units": "0.6", "annual_cost": "0.00" } ],
              "multiplying_lines": [
                { "hid": "0193a1f4-...", "name": "AI assistant", "category": "services",
                  "factor": "1.25", "share": "0.5",
                  "applies_to": [ { "hid": "...", "name": "Network engineer",
                                    "counted": true, "units": "3" },
                                  { "hid": "...", "name": "Senior network engineer",
                                    "counted": true, "units": "1.8" } ],
                  "base_units": "4.8", "units": "0.6" } ],
              "demand_by_region": [
                { "region_hid": "0193a1f4-...", "parent_region_hid": null, "path": "Americas",
                  "support_weight": "1800", "infrastructure_demand": "6", "share_pct": "75" },
                { "region_hid": "...", "parent_region_hid": "0193a1f4-...",
                  "path": "Americas > Central", "support_weight": "600",
                  "infrastructure_demand": "2", "share_pct": "25" },
                { "region_hid": "...", "parent_region_hid": null, "path": "Europe",
                  "support_weight": "480", "infrastructure_demand": "1.6", "share_pct": "20" },
                { "region_hid": null, "parent_region_hid": null, "path": null,
                  "support_weight": "120", "infrastructure_demand": "0.4", "share_pct": "5" } ] },
  "with_drafts": { "...": "..." } }
```

`active` counts the active lines that are in date and the active items;
`with_drafts` counts the draft lines and the draft items as if they were active.
`by_category` has a row for every category of the list that supplies, also one with
no line. `coverage_pct` is blank when there is no demand. The definitions are under
"Capacity balance" on the [data model](data-model.md#capacity-balance) page.

`multiplying_lines` lists the lines that multiply and count in the view, by name: each
with its `factor` and its `share`, the staff lines it applies to, each with whether it
is `counted` in the view and its units there, `base_units`, the units of those that are
counted, and `units`, what the line adds: `factor` less 1, times `share`, times
`base_units`. A line it applies to that is retired, out of date, a draft in `active`,
or no longer a staff line that adds, is listed as not counted and gives it nothing.
Its units are in its own category, so `own_units` stays that of the team's positions.

`demand_by_region` says where the work is. A row of a region holds the support weight
of the items at or beneath it, by their location in force, as the summary by `region`
counts it, with the infrastructure demand that is and its share of the whole support
weight as a percentage, blank when there is none. Each region that holds an item of
the view has a row, by path, with the region it is in, and the last row, with no
region, is the items that are nowhere: the regions at the top and that row add up to
the whole. The report stays one balance for the whole operations team: no supply is
divided among regions, and a line's region or site narrows nothing.

**Places and circuits in the demand.** `support_weight` of each view is the weight of
the items, of the places and of the circuits together, and beside it are its parts,
`items_weight`, `places_weight` and `circuits_weight`, and `defaulted` and `raised`,
each with `items`, `sites` and `circuits`: how many counted at a default setting and how
many were raised to a minimum. A place counts its own weight in force, a site its own
or `default_site_weight`, raised to `minimum_site_weight`, and a region and a location
their own; a circuit counts its own or `default_circuit_weight`, raised to
`minimum_circuit_weight`, while it is active, or a draft in `with_drafts`, and is not
disconnected before today. A row of `demand_by_region` holds, beside the items at or
beneath the region, the weights of the places at or beneath it and of the circuits that
count at a site beneath it, at their `cost_side` (P-150, P-155), so that the regions at
the top and the row of what is nowhere still add up to the whole. A region in which a
place or a circuit has a weight in force has a row as a region that holds an item does,
and one where nothing weighs has none. A place counts by its own status: an active
location in a draft site counts in `active`.

**Try**, `POST /reports/capacity/try`, is a what-if of the balance, and saves nothing:

```json
{ "default_item_weight": "1", "minimum_item_weight": null, "default_site_weight": "5",
  "weight_per_resource_unit": "250", "stack_discount_pct": "40",
  "staff": { "add": [ { "name": "Network engineer, new", "quantity": "2", "units_each": "1" } ],
             "change": [ { "hid": "0193a1f4-...", "quantity": "4" } ],
             "leave_out": [ "0193a1f4-..." ] } }
```

It takes any of the six weights of the settings, `weight_per_resource_unit`,
`stack_discount_pct` and `staff`: a key left out is as it is in force, and `null` tries a
setting at its default, as `PUT /settings/{key}` returns it to it, which for a weight is
blank. A staff line in `add` has a `name`, a `quantity` and `units_each`, one in
`change` names a staff line that adds by its HID with another `quantity` or
`units_each`, and `leave_out` names staff lines by their HIDs, counted as if they were
not there. A staff line tried is active and in date in both views. A line that
multiplies works on a changed line as it is tried, on none that is left out, and on no
added line, since it names the lines it works on. The answer is `in_force`, the report
as `GET /reports/capacity` answers it, `tried`, the same report as the values tried
give it, and `parameters`, what was tried:

```json
{ "in_force": { "as_of": "2026-11-14", "...": "..." },
  "tried": { "as_of": "2026-11-14", "weight_per_resource_unit": "250", "...": "..." },
  "parameters": {
    "default_item_weight": "1", "minimum_item_weight": null, "default_site_weight": "5",
    "minimum_site_weight": null, "default_circuit_weight": null, "minimum_circuit_weight": null,
    "weight_per_resource_unit": "250", "stack_discount_pct": "40",
    "staff": { "add": [ { "hid": null, "name": "Network engineer, new", "quantity": "2",
                          "units_each": "1", "units": "2" } ],
               "change": [ { "hid": "0193a1f4-...", "name": "Network engineer",
                             "quantity": "4", "units_each": "1", "units": "4" } ],
               "leave_out": [ { "hid": "0193a1f4-...", "name": "Junior network engineer" } ] },
    "changed": [ "default_item_weight", "default_site_weight", "weight_per_resource_unit",
                 "stack_discount_pct" ] } }
```

`parameters` holds each of the eight figures as the balance tried was worked out with
it, those left out at their value in force, the staff lines tried by name, and
`changed`, the settings whose value tried is not the one in force: an Admin who agrees
the estimate saves each of them by `PUT /settings/{key}`, one audited change each, with
the `row_version` that `GET /settings` gives, and a staff line is saved by entering it.
A model's own stack discount still overrides the global one tried. Nothing is saved,
nothing is written to the audit trail, and the answer is never kept; any role may Try.
A value a setting would refuse, or a line that is no staff line that adds, is retired,
or is named twice, is a `422` that names it.

**The records of the balance**, `GET /capacity-records`, keep the balance week by week,
to show the trend. Each record is of one week, `week_of`, the Monday that begins it in
the application's time zone, with `recorded_at`, `weight_per_resource_unit`, and for
`active` and `with_drafts` the figures as the report answered them: `support_weight`,
`items_weight`, `places_weight`, `circuits_weight`, `defaulted`, `raised`,
`infrastructure_demand`, `other_demand`, `demand`, `supply`, `own_units`,
`outside_units` and `by_category`. A week recorded before 0.8.0 kept no parts of the
support weight, and answers them blank. `balance` and `coverage_pct` are worked out from
the record's own demand and supply when it is read. The list is paged with `limit` and
`offset`, the oldest week first, and takes `sort` (see [Sorting](#sorting)); any role
reads it.

The server records the balance by itself each Monday just after midnight in the
application's time zone, and when it starts in a week that has no record, with `via`
of `system` in the audit trail; a week that somebody has recorded already keeps what
they recorded. `POST /capacity-records`, with an optional `note`, records the balance
as it is now, on any day, by hand, and replaces the record of this week: a contractor
added on a Wednesday is in that week's point once somebody records again, and the audit
event of the change holds what the record was. `PATCH /capacity-records/{hid}` corrects
the `demand` and the `supply` of `active` and of `with_drafts` of a saved week, either
or both, with a `note` that says why, which is required; the record is then
`adjusted`, and the change is audited. A correction changes the two totals and
nothing else: the parts, `infrastructure_demand` and `other_demand` of the demand and
`by_category` of the supply, stay as they were recorded, so a corrected week shows its
corrected totals beside its parts as recorded. A record that is recorded again is
worked out anew and is no longer adjusted. `DELETE /capacity-records/{hid}` removes a
record that was a mistake, with an audit event that holds what it was. Recording,
correcting and removing take the Inventory role.

**The portfolio of a vendor**, `GET /vendors/{hid}/portfolio`, is everything from one
vendor in one place, for the view that `include_drafts` and `include_archived`
choose:

```json
{ "vendor": { "hid": "0193a1f4-...", "name": "Cisco" }, "as_of": "2026-11-14",
  "totals": { "items": 61, "component_count": 40, "support_weight": "38.5",
              "est_value": "412000.00", "annual_support_cost": "38400.00",
              "covered": 36, "uncovered": 12 },
  "kinds": [ { "kind": "hardware", "items": 58, "...": "..." },
             { "kind": "virtual_machine", "...": "..." },
             { "kind": "software", "...": "..." }, { "kind": "service", "...": "..." } ],
  "models": [ { "catalog_entry_hid": "...", "pid": "C9300-48P", "model_name": "...",
                "kind": "hardware", "type": "switch", "ldos": "2031-10-31",
                "end_of_sale": null, "end_of_sw_support": null, "end_of_hw_support": null,
                "items": 12, "component_count": 12, "support_weight": "9",
                "est_value": "216000.00", "annual_support_cost": "14400.00",
                "covered": 12, "uncovered": 0, "covered_until": "2027-06-30" } ],
  "agreements": [ "..." ], "contracts": [ "..." ], "capacity_lines": [ "..." ],
  "filter": { "field": "catalog.vendor_hid", "op": "eq", "value": "0193a1f4-..." } }
```

All four kinds are there, also one the vendor has nothing of. `covered` and
`uncovered` are of the major items, since a power supply is covered with its switch,
so the two do not add up to `items` where minor items are among them. A row of `models` is
one catalog entry of the vendor that has items in the view, with the dates of the
model; `covered_until` is the soonest day the cover of one of its covered items runs
out. `agreements` is the support agreements with the vendor, and `contracts` the
contracts the vendor provides or that were bought through it, as `GET /contracts`
returns them, and `capacity_lines` the lines that name it. The items are the item list with
`filter`, and an export of them is the working list for a renewal.

**What circuits cost**, `GET /reports/circuit-costs`, is of one fiscal year,
`fiscal_year`, the one today is in unless asked, which begins on the first day of the
`fiscal_year_start_month` setting and is named for the calendar year it ends in. It takes
`filter` and `include_drafts` as the list of circuits does, and `by`: `carrier`, which
it is unless asked, `site`, `region`, `group`, `circuit_type`, `owner` or `tag`.

```json
{ "fiscal_year": 2027, "starts_on": "2027-01-01", "ends_on": "2027-12-31",
  "as_of": "2027-12-31", "by": "carrier", "currency": "USD",
  "include_archived": true, "include_drafts": false,
  "totals": { "circuits": 12, "cost": "141300.00", "monthly_cost": "12450.00",
              "annual_cost": "149400.00" },
  "rows": [ { "key": "0193a1f4-...", "label": "Example Telecom", "circuits": 9,
              "cost": "108700.00", "monthly_cost": "9550.00", "annual_cost": "114600.00",
              "filter": { "...": "..." } } ] }
```

`include_archived` is always true and `include_drafts` is the report's own: the view the
rows' filters are of, since a retired circuit that was disconnected in the year ran for
part of it. `circuits` is how many were in service on any day of the year, `cost` what the year
costs, `monthly_cost` what is billed for a month on `as_of`, today for the present
year, the last day of a past one and the first day of one to come, and `annual_cost`
twelve times that. A line counts its `monthly_cost` for each month of the year in which
it is billed: a whole month in full, and a month that the line's dates and the circuit's
service share only in part for the days they share, the monthly cost times those days
over the days of the month, as the carrier bills it. A circuit of 1,000 a month activated
on 10 April 2027 costs 8,700 in 2027. Every sum is exact, and rounded to two places once,
half up. By `carrier` a line counts under the vendor that bills it, its own or the
circuit's primary carrier, and a circuit is in the row of each carrier that bills any of
it in the year: a line billed on no day of the year's service puts no carrier in a row,
and a circuit with no such line is in the row of its primary carrier; by `site` it is in the row of the site it counts at; by `region` in that of each
region at or above that site; by `group` in the row of each group it is in, a retired
group among them, since retiring a group ends no membership, and by `tag`
of each tag; by `circuit_type` and `owner` in one row. The blank row is what has none,
and the totals count each circuit once. A row's `filter` lists its circuits on `GET
/circuits`, with the report's filter, the year's window of service (activated by its last
day, not disconnected before its first, and, retired, with a disconnection) and the
row's own condition: by `billed_by`, the circuits that carrier provides or bills a line
of, whatever the dates of the line, so that it may list a circuit more than the row
counts where the carrier's only line on it was billed before or after the year, and by
`carrier_hid` empty for the blank row, the circuits with no primary carrier; by
`cost_site_hid`, by `cost_location` `within` the region, by `groups.hid`, by
`circuit_type`, by `owner_hid` or by `tags`; the totals' filter is the report's with the
window. A row whose filter, or the totals whose filter, would be more than the grammar
takes has none (P-151).

## Kept answers

The coverage report, the renewal worklist, the summary of the renewal alert and the
capacity report are kept as D-184 has it, and each is worked out just after midnight in
the application's time zone and when the server starts, for the view its page opens
with. `GET /kept-answers`, for an Admin, lists what is kept: `report`, `request`, the
request whole, `kept_at`, when it was worked out, and `uses`, how many times it has been
given since. `POST /kept-answers/check`, for an Admin, works out each kept answer anew,
compares it with what was kept, and keeps the new one:

```json
{ "checked_at": "2027-03-02T14:05:09Z", "checked": 7, "differed": [] }
```

`differed` lists, for each answer that was not the same, its `report` and its
`request`. None should differ: one that did is a defect to report. The check is an audit
event, `kept_answers_checked`, with what it found, and it leaves the kept answers good,
as a sign-in does (P-157).

## Geography

A region, a site and a location take a `code`, unique among regions, among sites, and
within its site for a location. A code that a site has is refused for a region, and a
region's for a site, a `409` on `code` that names the record that has it as `existing`,
by `POST` and `PATCH`, by the page and by a file alike (P-237), so that a path that
begins with a code leads to one place. A region and a site that hold one code from
before stay so: a change of anything else of either goes through, and a path that
begins with that code finds neither, as the [data model](data-model.md#regions-sites-locations)
page says.

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
beneath it, and are not there yet, by the plan in force: the members of a group that
is planned for it are among them. `planned_groups` is how many device groups are, and
is of every group whatever the filter, which is a filter of items; the two are not
added together. `items` is every item whose location in force is at or beneath the node, major and
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

`GET /sites/{hid}/opening`, and the same for a region and a location, says what
making the place active would bring about, and changes nothing:

```json
{ "level": "site", "hid": "0193a1f4-...", "path": "Americas > Central > Site-3",
  "record_status": "draft", "moves_now": true, "waits_for": null, "waits_for_level": null,
  "items": 4, "device_groups": 1, "records_changed": 3 }
```

`items` and `device_groups` are what would be there: by a plan of their own, or with
the item or the group they are in. `records_changed` is how many of them are written
to, each with an entry of its own in the audit trail: what has no location of its own
is where its group is and is not written to. While a place above is not active,
`moves_now` is false and `waits_for` names the nearest such place: the numbers are
then what moves once that place is active too. The preview of a file that makes a
place active says the same in the `notes` of its row. The web UI asks this before a
place is made active, and makes one active in no other way.

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

**The support weight of a place** is `support_weight` on the record of a region, a site
and a location, its own, set by `POST` and `PATCH` and audited as any field. The record
of a site also answers the weight it counts at, which a place beneath does not take:

```json
{ "support_weight": "0.5",
  "effective": { "support_weight": { "value": "1", "source": "own", "source_hid": "0193a1f4-...",
                                     "raised_from": "0.5" } } }
```

`source` is `own`, `setting` where the site gives none and `default_site_weight` is
set, or `none`; `raised_from` is the weight before `minimum_site_weight` raised it, and
blank where it was not raised. A region and a location count their own alone. An item
answers `effective.support_weight` in the same form, with `catalog` for its model's
weight and `setting` for `default_item_weight`, and so does a circuit (P-155).

**The map of a place** is `map_url` on the answer of a site and of a location, in a list
as on its own: the setting `map_link` with `{latitude}` and `{longitude}` each replaced
by the place's coordinates, as the answer writes them, six places of decimal degrees
(P-229, P-236):

```json
{ "latitude": "41.878100", "longitude": "-87.629800",
  "map_url": "https://www.google.com/maps/search/?api=1&query=41.878100,-87.629800" }
```

It is null where the place has no coordinates of its own, which are not inherited, and
where the setting is blank, as an installation with no access to the internet sets it,
or holds a value stored before its rule was what it is, which the rule now refuses.
Nothing else of the place is in it. A region has no coordinates and no `map_url`.

## Contacts of agreements and contracts

`GET /agreements/{hid}/contacts` lists the contact records an agreement names, by role
and then by priority, and `GET /contracts/{hid}/contacts` those a contract names of its
own. Each is a naming: its HID, the record it is of in `agreement_hid` or
`contract_hid`, its `role`, `account_manager` or `support_contact`, its `priority`, and
the contact as its record is now, with its name, organization, email address,
telephone number and record status.

`POST` names a contact with a `contact_hid`, a `role` and, if it is wanted, a
`priority`: left out, one more than the highest there is for that record and role. A
contact is named once for one record and one role, and a second time is a `409` that
names `contact_hid`. A retired agreement or contract takes no new contact, and a
retired contact is not newly named: both are a `422`. A contact that is retired later
stays where it is named, marked so. `PATCH` changes the role, the priority or the
contact of a naming, which stays with its record, and `DELETE` removes one that was a
mistake: the audit event of the removal holds what it was. Each is a change of the
Inventory role, audited as `contract_contact`.

The record of an agreement and of a contract answers its own namings in `contacts`,
and in `effective` the lists in force, `account_managers` and `support_contacts`, each
as `{ "value": [ ... ], "source": ..., "source_hid": ... }` with the namings in the
order they are listed. For each role by itself a contract has its own where it names
any, with the source `own`, else those of the agreement it is grouped into, with the
source `agreement`, else none, with the source `none`. An agreement has its own or
none. Nothing is copied: a change of a contact record shows on every record that names
it and on every contract that has it from its agreement, and no agreement or contract
is written to. The free text of `account_manager` and `support_contact` stays beside
them, and is inherited by itself as before.

## Circuits

`GET /circuits/{hid}` answers the circuit's own fields, as the [data
model](data-model.md#circuits) page names them, and what is worked out when it is read:

```json
{ "hid": "0193a1f4-...", "name": "Site-2 internet", "enterprise_circuit_id": "EC-0042",
  "circuit_type": "internet", "port_mbps": "1000.00", "down_mbps": "200.00", "up_mbps": "20.00",
  "speed": "1G / 200M / 20M",
  "a_location_hid": null, "a_note": "carrier network",
  "z_location_hid": "0193a1f4-...", "z_note": null, "cost_side": "a",
  "cost_site_hid": "0193a1f4-...", "cost_site_path": "Americas > Central > Site-2",
  "carrier_hid": "0193a1f4-...", "carrier_circuit_number": "EXT/12345/000/EXTL",
  "monthly_cost": "1000.00", "annual_cost": "12000.00", "in_service": true,
  "a_side": null,
  "z_side": { "location_hid": "0193a1f4-...", "name": "Building 1",
              "path": "Americas > Central > Site-2 > Building 1",
              "site_hid": "0193a1f4-...", "site_path": "Americas > Central > Site-2",
              "region_hid": "0193a1f4-...", "record_status": "active" },
  "carriers": [ { "hid": "...", "vendor_hid": "...", "vendor": "Example Local Exchange",
                  "role": "local_exchange", "circuit_number": "LEC-778-0001", "priority": 1 } ],
  "costs": [ { "hid": "...", "description": "Port", "monthly_cost": "850.00", "vendor_hid": null,
               "vendor": null, "starts_on": null, "ends_on": null, "in_date": true } ],
  "devices": [ { "hid": "...", "side": "z", "item_hid": "...", "group_hid": null,
                 "name": "site2-rtr-01", "record_status": "active" } ],
  "groups": [ { "hid": "...", "name": "Internet access" } ],
  "effective": {
    "support_weight": { "value": "2.00", "source": "setting", "source_hid": null },
    "down_mbps": { "value": "200.00", "source": "own", "source_hid": null },
    "up_mbps": { "value": "20.00", "source": "own", "source_hid": null },
    "account_managers": { "value": [ "..." ], "source": "vendor", "source_hid": "0193a1f4-..." },
    "support_contacts": { "value": [ "..." ], "source": "vendor", "source_hid": "0193a1f4-..." },
    "site_contacts": { "a": [], "z": [ { "role": "technical", "value": [ "..." ],
                                         "source": "site", "source_hid": "0193a1f4-..." } ] } } }
```

A side with no location is `null` in `a_side` or `z_side`. A list leaves `carriers`,
`costs`, `devices`, `groups` and the contacts out of each row, as `null`, which its own
routes and the record answer; `fields` may ask for them. The record also answers
`owner_exception` and `owner_exception_reason`, as an item does. A new circuit with no `cost_side` takes
the setting `circuit_cost_side`. A request that leaves both sides with no location,
gives a side with no location no note, gives a rate with no port speed or above it,
puts an activation before the installation or a disconnection before the activation,
or gives a carrier's number with no carrier, is a `422` that names the field; an
enterprise circuit ID or a carrier's number that another circuit has is a `409` that
names it.

**Its parts.** `GET /circuits/{hid}/carriers`, `/costs`, `/devices` and `/contacts`
list the carriers beside its primary one, its cost lines, the devices it connects and
the contacts it names of its own. `POST` adds one, `PATCH` changes one, and `DELETE`
removes one that was a mistake, the audit event of the removal holding what it was;
each takes the Inventory role. A part has a `row_version` of its own, which a `PATCH`
names, and the circuit's is not asked for, as a contact of a contract does not ask for
its contract's. A carrier is a vendor named once
on the circuit; a device is an `item_hid` or a `group_hid` on a `side`, once; a contact
is a `contact_hid` with a `side`, blank for one of the carrier's, and a `role`, once for
one side and role. A retired circuit takes no new part, and a retired item, group,
vendor or contact is not newly named: each is a `422`. `POST /circuits/{hid}/devices`
takes several devices at once, as `members` of a group does: `devices`, each an
`item_hid` or a `group_hid` with its `side`. A cost line's `vendor_hid` is the circuit's
primary carrier or one of its other carriers, blank being the primary, and any other
vendor is a `422` that names it; a carrier that a line names is not removed, a `409`,
and the primary carrier is not replaced while a line names it by name, a `422`.

**Its contacts.** `GET /circuits/{hid}/contacts` lists the carrier's first, then those of
the A side and of the Z side, each by role and then by priority. A contact named once
more for the same side and role is a `409` that names `contact_hid`. Left out, the
`priority` is one more than the highest there is for the circuit, the side and the
role. With no side the role is `account_manager` or `support_contact`, and with a side
a value of the `contact_role` list. A `PATCH` may change the side, the role, the
priority or the contact of a naming, which stays with its circuit, and its role is then
one that its side takes. The contacts are audited as `circuit_contact`.

**Its contacts in force.** `effective.account_managers` and `effective.support_contacts`
are each the list in force for the role: with the source `own` and the circuit in
`source_hid` where the circuit names any of its own in the role, with `vendor` and its
primary carrier where it has the carrier's, and otherwise `none`. `effective.site_contacts`
has, for `a` and for `z`, one entry for each role that has contacts on that side, in the
order of the `contact_role` list: its `role`, its `value`, and `source` with
`source_hid`, which are `own` and the circuit for those the circuit names for that side,
or else the level they came from as the location of the side resolves them, `location`
for that location or one above it, `site` or `region`, with that place. Each entry of a
`value` is the naming it comes by, a contact of the circuit, of its carrier or, among
the site contacts, an assignment of the place: its `hid`, its `role`, its `priority`
and `contact_hid`, with the contact as its record is when it is read, its name,
organization, email address, telephone number and record status.

**The contacts of a vendor.** `GET /vendors/{hid}/contacts` lists the contacts a vendor
names, `account_manager` or `support_contact`, by role and then by priority, and `POST`,
`PATCH` and `DELETE` work as they do for a contract (see "Contacts of agreements and
contracts"), audited as `vendor_contact`. The record of a vendor, in the list of
vendors as well, answers them in `contacts`.

**Where a circuit is.** The record of an item and of a device group answers `circuits`,
each with its HID, name, enterprise circuit ID and side, the HID of the connection,
`link_hid`, and the circuit's `record_status`, to be read only. The list of
circuits finds those with a side at a location, or at or beneath a site or a region, by
`location:within:`, which a location's page asks for.

**Circuit groups.** `GET /circuit-groups/{hid}` answers the group's fields, `circuits`,
how many it has, `in_service`, how many of them are in service today, and their
`monthly_cost` and `annual_cost`, each circuit once. `GET /circuit-groups/{hid}/members`
lists its circuits by name, paged, each with its `circuit`; `POST` adds circuits,
`circuit_hids`, several at a time, each once, a circuit already in the group being a
`409`, and
`DELETE /circuit-groups/{hid}/members/{member_hid}` takes one out, the audit event
holding what it was. A retired group takes no circuit, and a retired circuit is added
to none.

## Reference files

A reference is a file that `hirdir` keeps, or a link to one kept elsewhere, with a
title and a kind, on one record or more: a region, a site, a location, a catalog entry,
a circuit or an item ([data model](data-model.md#reference_files-and-reference_attachments),
P-158 to P-162).

**Uploading.** `POST /reference-files` takes the file itself as the body of the
request, as an import does (D-80), and in the address `title`, `kind`, `file_name`,
which gives its extension, and `attach_to`, the HID of a record it goes on,
given once for each record, at least once and at most 100: the address of a request
holds no more, and more records are given the reference afterwards with `POST
/reference-files/{hid}/attachments`. Notes, which may be long, are given afterwards
with `PATCH`, since nginx holds the address of a request to a few kilobytes. A body over
`max_reference_megabytes`
is a `413`; an extension that `reference_file_types` does not take, or content that is
not what the extension says, a `422` with the reason; a record that is not one of the
six kinds, a `422` naming it; and content that a record has already, under any
reference, a `409` that names that reference. The answer is `201` with the reference.
`POST /reference-files/links` makes a link from a JSON body of `title`, `kind`, `url`,
`notes` and `attach_to`, a list of HIDs.

```json
{ "hid": "0193a1f4-...", "title": "Building 1, second floor", "kind": "floor_plan",
  "form": "file", "file_name": "b1-floor-2.pdf", "media_type": "application/pdf",
  "size_bytes": 4718592, "sha256": "9f86d081...", "url": null, "notes": null,
  "shown_in_page": false, "content_missing": false,
  "attachments": [ { "hid": "...", "record_type": "location", "record_hid": "...",
                     "label": "Americas > Central > Site-2 > Building 1 > Floor 2" } ],
  "attachment_count": 1, "row_version": 1,
  "created_at": "2026-11-16T15:04:05Z", "created_by": "...", "updated_at": "...", "updated_by": "..." }
```

`shown_in_page` is true for a JPEG, PNG, GIF or WebP picture, which the web UI shows;
every other file is downloaded. `content_missing` is true only after a restore that was
told to go on without some content (P-161).

**Reading and downloading.** `GET /reference-files/{hid}` answers one, with the
records it is on. `GET /reference-files/{hid}/content` answers the content, byte for
byte, as `Content-Type` its `media_type`, with `Content-Disposition: attachment` and
its file name, `X-Content-Type-Options: nosniff`, `Content-Security-Policy: sandbox;
default-src 'none'` and `Cache-Control: no-store`, and is an audit event, `download`.
It is not compressed again, but for a text file, which is compressed on the way as any
answer of more than a kilobyte is, and arrives as it was. A link has no content, and asking for it is a `422`; content missing
after a restore is a `404` that says so. `GET /reference-files` lists every reference,
paged with `limit` and `offset`, sorted by `sort` over `title`, `kind`, `form`,
`file_name`, `size_bytes`, `attachment_count`, `created_at` and `updated_at`, title
first unless asked, and narrowed by `kind`, by `form`, `file` or `link`, and by
`title`, which the title contains without regard to case.

**What a record has.** `GET /locations/{hid}/references`, and the same under
`/regions`, `/sites`, `/catalog-entries`, `/circuits` and `/items`, lists what the
record has, paged with `limit` and `offset`: its own first, then each level it stands
under, nearest first, as the data model tables, and within a level by title. Each entry
is the reference, as above, with `attachment_hid`, the attachment it is listed by,
`source`, `own`, `catalog`, `location`, `site` or `region`, `source_hid` and
`source_label`, the path or name of the record it is attached to. A reference attached
at two levels is listed at the nearer.

**Changing.** `PATCH /reference-files/{hid}` changes `title`, `kind`, `notes`, and the
`url` of a link, with `row_version`. `PUT /reference-files/{hid}/content` takes a new
edition as its body, with `file_name` and `row_version` in the address, and is checked
as an upload is; the reference keeps its HID, title, kind and attachments, and the
content it had is erased unless another reference holds it too. `POST
/reference-files/{hid}/attachments` takes `records`, a list of up to 1,000 HIDs, and
puts the reference on each; a record that has it already is passed over, and the
answer is the reference. `DELETE /reference-files/{hid}/attachments/{attachment_hid}`
takes it off one record and answers `{ "erased": false }`, or `true` when that was
the last record and the reference was erased with it. `DELETE /reference-files/{hid}`
erases it from every record at once. Each of these is an audit event of the reference,
`create`, `update`, `replace_content`, `attach`, `detach` or `erase`, and an erasure's
event holds the title, kind, file name, size, checksum and the records it was on.

The body of any other request stays at the limit of an import, `max_megabytes`: one that
says a larger length is refused by the application itself, whatever nginx lets through,
and the rest of it is read and thrown away first. An upload and an import also hold a
body that does not say its length to their limits as they read it; nginx, which reads a
body whole before it passes it on, always says it.

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
hirdir operators list                            # the labels, who is behind each, internal or external, which are open
hirdir operators assign LM robin.achterberg@example.net   # hand over what LM looks after
hirdir operators assign LM --open                # nobody behind it for now
hirdir operators release LM                      # the label stands for nothing: the next level up decides
hirdir items set --filter 'group.name:eq:site2-sw-core' operator=LM --apply
hirdir items list --filter 'effective.operator_hid:empty:true'    # what nobody is assigned to
hirdir report summary --by operator              # who looks after how much
hirdir report summary --by site --operators      # and who is involved at each site
hirdir vendors portfolio Cisco --format csv --output cisco-renewal.csv
hirdir import items.csv --entity items                 # preview only
hirdir import items.csv --entity items --apply         # waits for the end, saying how far it has got
hirdir import items.csv --entity items --apply --skip-rejected
hirdir import items.csv --entity items --apply --no-wait   # leaves it to the server
hirdir imports show <hid> --wait                       # how far an apply has got, until it ends
hirdir imports apply <hid>                             # a stored preview, or one that stopped, resumed
hirdir imports created <hid>                           # the records it made, and what each is now
hirdir items retire <hid> <hid> <hid>                  # several at once, for the Inventory role
hirdir items delete <hid> <hid> --reason 'a wrong file'    # an Admin: says what it would do, and asks
hirdir groups retire site2-sw-stack9
hirdir groups delete <hid> --reason 'a wrong file' --yes
hirdir items make-stack site2-sw-access-07 --name site2-sw-stack12 --member FCW0000X008
hirdir replacements remove <hid> --reason 'recorded on the wrong switch'   # an Admin: asks first
hirdir export items --filter 'tags:has:refresh-2030' --format json --output refresh.json
hirdir export items --own-values --place-codes --output items.csv   # places as S2 > R102
hirdir report summary --by health --format json
hirdir report management                         # by site
hirdir report management --by owner
hirdir report duplicates
hirdir report coverage --section uncovered       # in service, and under no contract
hirdir report end-of-life --date ldos --section approaching
hirdir report replacements --filter 'reason:eq:rma'
hirdir report capacity                           # the balance, with and without the drafts
hirdir agreements list                           # the support agreements, and how many contracts each groups
hirdir contracts list --filter 'status:eq:active'
hirdir contracts list --filter 'agreement.name:eq:Cisco Enterprise Agreement'
hirdir contracts set CON-2026-0107 agreement='Cisco Enterprise Agreement'   # roll it in
hirdir contracts show CON-2026-0001              # the contract, and what it covers
hirdir contracts cover CON-2026-0001 --filter 'tags:has:refresh-2030' --apply
hirdir contracts renew CON-2026-0001 --number CON-2027-0001 --from 2027-01-01 --to 2027-12-31
hirdir contracts renew CON-2026-0001 --withdraw   # the term that was still to begin
hirdir agreements renew 'Cisco Enterprise Agreement' --from 2028-01-01 --to 2030-12-31 \
hirdir agreements add-contact 'Cisco Enterprise Agreement' jordan.reyes@example.com --role account_manager
hirdir contracts add-contact CON-2025-0002 casey.lund@example.com --role account_manager
hirdir contracts remove-contact CON-2025-0002 casey.lund@example.com --role account_manager
    --member CON-2026-0002=new:CON-2028-0002 --member CON-2026-0005=ends
hirdir renewals                                   # the worklist, by vendor and agreement
hirdir renewals --section renewal_pending --format csv --output pending.csv
hirdir report coverage --section overlapping     # under more than one contract
hirdir purchases list
hirdir purchases show RITM0012345                # the request and its lines, with what is still to come
hirdir purchases receive RITM0012345/1 --serial FCW0000X101 --serial FCW0000X102
hirdir purchases receive RITM0012345/1 --count 4 # arrived, with nothing to know them by yet
hirdir systems list                              # the external systems
hirdir registrations list --filter 'system.name:eq:NetWatch'
hirdir capacity list                             # the lines of supply and of other work
hirdir capacity record --note 'a contractor started'   # this week's balance, recorded again now
hirdir capacity records                          # the balance week by week, the oldest first
hirdir report capacity --try default_item_weight=1 --try weight_per_resource_unit=250 \
    --try-staff-add 'Network engineer, new=2x1' --try-staff-leave-out 'Junior network engineer'
hirdir circuits list --filter 'circuit_type:eq:internet effective.down_mbps:lt:100'
hirdir circuits show EC-0042                     # by HID, enterprise circuit ID or name
hirdir circuits set EC-0042 cost_side=z          # count it at the far end
hirdir circuits add-contact EC-0042 noc@example.net --role support_contact
hirdir circuit-groups show 'Internet access'     # its circuits, and what they cost
hirdir circuit-groups add 'Internet access' EC-0042 EC-0043
hirdir vendors add-contact 'Example Telecom' jordan.reyes@example.com --role account_manager
hirdir report circuit-costs --year 2027 --by site
hirdir references add b1-floor-2.pdf --to 'location:Americas > Central > Site-2 > Building 1 > Floor 2' \
    --kind floor_plan --title 'Building 1, second floor'
hirdir references add rack-*.jpg --to 'location:Americas > Central > Site-2 > Building 1 > Room 102' \
    --kind photograph                            # several at once, each titled by its file name
hirdir references add c9300-admin.pdf --to 'model:Cisco C9300-24P' --to 'model:Cisco C9300-48P' \
    --kind administration_guide
hirdir references link https://docs.example.com/c9300 --to 'model:Cisco C9300-48P' \
    --kind data_sheet --title 'Data sheet'
hirdir references list --of 'location:Americas > Central > Site-2 > Building 1 > Room 102'
hirdir references list --of item:FCW0000X001    # its own, its model's, and those of where it is
hirdir references get <hid> --output b1-floor-2.pdf
hirdir references replace <hid> c9300-admin-2027.pdf  # a new edition, on every model at once
hirdir references attach <hid> --to 'model:Cisco C9300-24UX'
hirdir references detach <hid> --from 'model:Cisco C9300-24P'
hirdir references remove <hid>                   # erases it from every record, after asking
```

A record is named for `--to`, `--from` and `--of` as its kind and the text the other
commands take for it, `location:`, `site:` and `region:` with a path, `model:` with the
vendor and the PID, `item:` with a serial number, an asset tag or a name, and
`circuit:` with an enterprise circuit ID or a name; or by its HID alone. `add` of
several files uploads them one after another and says what became of each; one that is
refused leaves the others as they went.

| Subject | Rule |
|---|---|
| Server and token | `--url` and `--token`, or `HIRDIR_URL` and `HIRDIR_TOKEN`, or `~/.config/hirdir/config.toml`, in that order |
| Output | A table on a terminal. `--format json` or `csv` for scripts. Data on stdout, messages on stderr |
| Lists | `hirdir items list`, and `vendors`, `catalog`, `owners`, `tags`, `networks`, `addresses`, `groups`, `regions`, `sites`, `locations`, `contacts`, `operators`, `agreements`, `contracts`, `purchases`, `systems`, `registrations`, `circuits`, `circuit-groups` and `capacity` in its place, take `--filter`, `--sort` and `--columns`. A table shows the first 50 rows, or as many as `--limit` says. As `csv` or `json` a list is every row, and is the very file that `hirdir export` writes for the same filter, sort and columns |
| Times | In a message or a table, the application's time with the name of the zone, as the web UI shows it. `--format json` and `csv` carry what the API sends, in UTC |
| Exit codes | `0` done, `2` usage, `3` not signed in or not allowed, `4` validation or rejected rows, `5` conflict, a row left out as stale among them, `6` server or network, or an apply that stopped |
| Changes | Anything that changes more than one record previews first and needs `--apply` |
| An apply | `hirdir import --apply` and `hirdir items set` wait for the server to apply the change in the background, and say how far it has got, unless `--no-wait` is given. Stopping the command does not stop the apply. The rows the apply left out as stale are listed with why, and the command exits `5`; rows the rules refused at the apply exit `4`; a job that stopped exits `6` and says how to resume it. `hirdir imports show HID` prints a stored preview of an import or a bulk edit and how far its apply has got, and with `--wait` waits for its end as an apply does. `hirdir imports apply HID` applies a stored preview, or resumes one that stopped, and waits likewise |
| An item, by what it is known | Where a command takes an item, it takes the HID, or a serial number, an asset tag or a name that one item alone has. More than one is listed, and nothing is done. `hirdir items show` prints the item with the links of its model, and each of its replacements, the latest first, with the other item, which of the two it was, the reason, the reference and the day (P-241) |
| A stack of one switch | `hirdir items make-stack ITEM [--name NAME] [--member ITEM]...` makes a stack of an item that is in none, by `POST /items/{hid}/make-stack`, and prints the stack; each `--member` is one more member, added as a member that joins with its name and place given up, `drop_identity` (P-243) |
| A replacement that was a mistake | `hirdir replacements remove HID --reason TEXT`, for an Admin, prints the replacement, its two items and its day, asks `Remove this replacement?`, and goes on only when it is answered yes, or `--yes` is given by a script; it then removes it by `POST /item-replacements/{hid}/remove` (P-238) |
| Retiring and deleting several | `hirdir items retire ITEM...` and `hirdir groups retire GROUP...` retire the records named, each named as the commands name one, by one request of `POST /items/retire` or `POST /device-groups/retire`, and print what was retired, what was retired already, what was refused with why and what was not found; anything refused or not found exits `4`, after the rest is done. `hirdir items delete ITEM... --reason TEXT` and `hirdir groups delete GROUP... --reason TEXT`, for an Admin, first ask the server what the deletion would do, with `dry_run`, and print it: what would be deleted, and each that would be refused with what depends on it. They then ask `Delete N items?`, and go on only when it is answered yes, or `--yes` is given by a script; `--dry-run` prints what would be done and stops there. A record named twice counts once. One command takes 1,000 records at most, which one request judges together, a switch with its power supplies: more is refused with how many were given, exit `2`, and nothing is done (P-227, P-228) |
| The records an import made | `hirdir imports created HID` lists, for a past import, each record it made with its row, its kind, its name, what it is now and its HID, and then the vendors and catalog entries it made for a row that named them; `--format json` writes the answer of `GET /imports/{hid}/created` whole, every page of it (P-234) |
| Places by code | `hirdir export ENTITY --place-codes` writes each place the short way, as `place_codes` of `POST /exports` does (P-235). A path that a command takes, `--root` and `--filter` among them, may hold codes as a file's may |
| A group | `hirdir groups show` takes the HID or the name, and prints the group with its health, its current members and their roles, and for a stack the master that is intended, the one that is seen, the serial number that follows, and the position a member added with none takes (P-219). No command adds a member by itself: a file of `device_group_members` does, by `hirdir import`, with `drop_identity`, `disposition` and `expected_online` among its columns (P-217) |
| A place | Where a command takes a region, a site or a location, it takes the HID or the path. `hirdir regions show`, `hirdir sites show` and `hirdir locations show` print the place with what it has in force: the contacts of each role and the shipping address and instructions, each with the level it came from, its links, each as its text and its address, and its support weight: a region's and a location's own, and a site's in force, marked where it is the default of the setting or was raised to the minimum. `hirdir sites move SITE REGION` gives a site another region, and `hirdir regions move REGION PARENT` a region another parent, `top` for none: one change, after which the paths and the totals follow |
| The geography | `hirdir geography tree` prints the regions, their sites and the locations within them, indented, each with its items and components, and the items that are nowhere beneath. `--root` starts from one place, `--no-locations` stops at the sites, and `--filter`, `--include-drafts` and `--include-archived` choose the view as they do for a list |
| Reports | `hirdir report summary` and `hirdir report management` take `--filter`, `--by`, `--include-drafts` and `--include-archived`, and print the totals and one row for each value. The management report is by site unless `--by` says otherwise. The table leaves out the filter of each row; `--format json` holds it, with the conditions of the counts, to give to `hirdir items list --filter` (P-206). `hirdir report duplicates` lists the addresses held more than once. `hirdir report coverage` and `hirdir report end-of-life` print the counts, and with `--section` the items of one of them; `hirdir report replacements` lists the replacements; `hirdir renewals` prints the renewal worklist, the counts of each list by vendor and agreement, and with `--section` the rows of one list; `hirdir report capacity` prints demand beside supply by category, the balance and the coverage, with and without the drafts, then what each line that multiplies adds and the lines it works on, and the demand and the share of each region and of what is nowhere; the support weight is printed with its parts, the items, the places and the circuits, and how many of each counted at a default and were raised to a minimum |
| The balance over time | `hirdir capacity record` records the balance as it is now, in place of this week's record, with `--note` to say why. `hirdir capacity records` lists the records, one week to a row, the oldest first, each with the demand, the supply, the balance and the coverage of both views, whether it was corrected, and its note; `--format csv` and `json` write all of them |
| A contract | `hirdir contracts show` takes the HID or the number, and prints the contract with the items it covers. `hirdir contracts cover CONTRACT` covers the items of a `--filter`, or the items named after it, from `--from` to `--to` or for the contract's own dates: a preview unless `--apply` is given. It sends them as many at a time as the setting `max_items_per_request` says. `hirdir contracts renew CONTRACT` gives it a new `--number` and a new period, `--from` and `--to`, in one change, and says how many items follow; a period that begins after today is kept as the next term, which `--withdraw` withdraws. `hirdir agreements renew AGREEMENT` does the same for a support agreement, with `--member CONTRACT=same`, `CONTRACT=new:NUMBER` or `CONTRACT=ends` for each contract that shares its period and is to do other than keep its number, and `hirdir agreements show AGREEMENT` prints it with the terms it had before. An earlier term of a contract marks a date that was its agreement's |
| Contacts of a contract | `hirdir contracts show` and `hirdir agreements show` print the account managers and the support contacts in force, each with how to reach them, a retired one marked so, and on a contract those it has from its agreement marked `(agreement)`. `hirdir contracts add-contact CONTRACT CONTACT --role ROLE` names a contact, with `--priority` for its place in the list, and `hirdir contracts remove-contact CONTRACT CONTACT --role ROLE` removes one; `hirdir agreements add-contact` and `remove-contact` do the same for an agreement. A contact is named by its email address, a name that one contact alone has, or its HID |
| A purchase | `hirdir purchases show` takes the HID or the reference of a request, and prints each line with its model, or as not tracked, and the part number procurement gave it. `hirdir purchases receive LINE` takes a line as `RITM0012345/2` and one `--serial`, `--asset-tag` or `--name` for each item that arrived, and `--count` for those that nothing is known of yet, with `--location` and `--on` for where and when |
| A vendor | `hirdir vendors portfolio VENDOR` prints the totals, the four kinds and the models. With `--format csv` or `json` and `--output` it writes the items of the vendor, one row each, with their coverage |
| A value | `field=value` sets, `field=` clears. A field is named as a column of an import |
| A circuit | `hirdir circuits show` takes the HID, the enterprise circuit ID or a name that one circuit alone has, and prints the circuit with its sides and their site contacts, each with the level it came from, its carriers and their numbers, the account team and the support desk in force, marked `(vendor)` where they are the carrier's, its devices, its cost lines with the monthly and annual totals, and its groups. `hirdir circuits set CIRCUIT field=value` changes the fields of one circuit, each named as a column of its file names it (`carrier`, `owner`, `a_location`), as a change on its page does: a value given is the circuit's own, also one that is the default it has, and its groups are changed with `hirdir circuit-groups`. `hirdir circuits retire` retires it. `hirdir circuits add-contact CIRCUIT CONTACT --role ROLE`, with `--side a` or `--side z` for a site contact, names a contact, and `remove-contact` removes one; `hirdir vendors add-contact` and `remove-contact` do the same for a carrier. Carriers, cost lines and devices are given by a file or on the circuit's page |
| Circuit groups | `hirdir circuit-groups list` and `show GROUP`, by HID or name, the group with its circuits and their cost; `hirdir circuit-groups add GROUP CIRCUIT...` and `remove GROUP CIRCUIT...`, which change the group's memberships at once, with no preview, as members are added to a device group by one request: what changes is named on the command line |
| Circuit costs | `hirdir report circuit-costs` prints the totals and one row for each value of `--by`, for `--year`, the present fiscal year unless given |
| Try | `hirdir report capacity --try KEY=VALUE`, as often as needed, for the six weights, `weight_per_resource_unit` and `stack_discount_pct`, `KEY=` to try a weight blank, and `--try-staff-add NAME=QUANTITYxUNITS`, `--try-staff-change LINE=QUANTITYxUNITS` and `--try-staff-leave-out LINE`, a line by its name or HID, prints the balance in force beside the one tried, a column for each view in force and tried. A part of `QUANTITYxUNITS` left blank in a change is as it is, `LINE=4x` changing the quantity alone, and a line added with no quantity has 1. Nothing is saved |
| Secrets | Never echoed, never in logs |

**`hirdir admin`** runs on the server as root or the service user and works on the
database directly, because it must work before any account exists:

```bash
hirdir admin create-user --role admin NAME       # prints a new access code once
hirdir admin create-user --role admin --name 'Ada Example' --email ada@example.org NAME   # and its contact
hirdir admin reset-access-code NAME
hirdir admin migrate
hirdir admin backup
hirdir admin restore FILE
hirdir admin reset                               # clear the inventory; --everything for all
hirdir admin load-examples                       # the examples, into an empty inventory
hirdir admin check                               # schema version, integrity, settings
hirdir admin config                              # a complete configuration file, every key at its default
hirdir admin config --current --output config.toml.new   # with what the present file sets, set
hirdir admin serve                               # what the service runs
```

`hirdir admin config` writes a complete configuration file from the application
itself: every key of every table, each with its default and the comment that says what
it is for, commented out at its default. It is the file the package ships for
`hirdir-setup --settings`. With `--current` each key that the file in force sets
(`/etc/hirdir/config.toml`, or `HIRDIR_CONFIG`) is set as it sets it, and what it sets
that this version does not read is kept at the end of its table under a comment that
says so. It writes to standard output, or to `--output PATH`, which it does not write
over without `--force`; with `--current` that file has the mode and the group of the
file in force, since it may hold the password of a proxy. It reads no database and
changes nothing else.

Run as root, an admin command first steps down to the user that owns the state
directory, so it never leaves behind a file the service cannot write.

`hirdir admin reset` is for a site that has loaded test data and wants to start over.
It is on the server and nowhere else: no page and no route of the API clears anything.
It refuses while the service is running, says what it will remove and how many, takes a
backup, and goes on only when the word `reset` is typed, or `--yes` is given by a
script. It removes the items with their replacements, addresses and memberships, the
device groups, networks, catalog entries, vendors, owners with their people, regions,
sites, locations, operators, contacts with their assignments, agreements and contracts with
their coverage and their contacts, purchase requests with their lines, external systems with their
registrations, capacity lines and the records of the balance, tags and stored imports,
and the audit events of those records, and writes one audit event that says so and
names the backup. Accounts, groups, roles, service tokens, settings, choices and
lifecycle rules stay, and so does the contact each user is, with its history (P-174). `--everything` removes those too and leaves the database as a
fresh installation has it, with no account and an empty audit trail.

`hirdir admin load-examples` loads the fictional inventory of `examples/`, which the
application carries inside itself, so that a site can try `hirdir` and clear it again
with `hirdir admin reset` (P-166). It is on the server and nowhere else, and refuses
while the service is running, where the inventory holds any record that a reset clears,
and where an import is queued or being applied: what a reset clears afterwards is then
the examples, with whatever was added beside them, and nothing of the site's own. A
stored preview, a renewal alert that was seen and the weekly record of the capacity
balance do not count, nor does the contact a user is, which a reset keeps; the examples
may change such a contact where its email is one of theirs (P-174). Each CSV file is
imported in the load order, a preview and an
apply as any import is, kept as a stored import named for its file and audited as
`system`, under a request ID of its own, which the records it made share. A file with a rejected row stops it there and names the rows; what the files
before it made stays, for a reset to clear. It prints how many records each file made.
Accounts and settings are not touched.

## Web UI

### Pages

| Page | Content |
|---|---|
| Sign in | Username, access code, a Sign in button, under the product name: `Sign in to Example Inventory` where `product_name` is `Example Inventory`. Where `help_on_sign_in` is true and one of whom to ask is set, it says under the form that someone who cannot sign in should ask them, and lists them as About does |
| Home | The headline of the summary: component count beside managed-node count, support weight, and the components by health. No money. The number of components that nobody is assigned to as operator, and of those under a label with nobody behind it, each as a link to its list. The items in service that no contract covers, those whose cover runs out within ninety days, and those past and approaching their last day of support, each as a link to its list |
| Items | The main grid, with a health mark on each row, and minor items left out until "Include minor items" is turned on. Location and Site are shown from the start, and Region, Operator and Expected online are in the column chooser (P-193): Location shows the name of the location in force, with its path on hover and in an export. An item whose owner in force is outside the team is marked, with the reason that owner has. It shows no money until a column of it is asked for: Estimated value, Annual support cost and Support weight are in the column chooser. Still counted under, the contracts that still count an item out of service, and Of another model than its line, an item on a purchase line of another model, are in the column chooser too, each filtered, sorted and exported by the server. Detail page: identity, catalog and effective values with sources, and under Values in force the walk of each, a row of boxes joined by arrows, the one that decides marked and those passed over struck through, with the same as a table (P-176), parent and minor items, groups, addresses, coverage, with the contracts that still count it while it is out of service, registrations, the purchase line it arrived on, history, and the circuits it is connected to, each with its side. Naming its purchase line shows its model beside the line, and a line of another model is refused under that model; a change of its model while it is on a line is refused under the model in its form. An item on a line of another model, which 0.6.0 let in, is marked there, with how to put it right. An item's page shows the links of its model, and Files and links: its own references, its model's and those of where it is. Retire, for the Inventory role, retires the rows ticked at once by `POST /items/retire` (P-228): it is for particular rows, and is not pressed while all that match are chosen, nor while more than 1,000 are ticked, the most one request takes: the list then says so, with how many are ticked, before anything is sent, and the web never splits a request (so for Delete, and for the list of what an import made); it asks first, `Retire 3 items?`, and then says what the answer did, how many were retired, how many were retired already, and each refused, as a link with why, which stays ticked when the list is read again. What is retired is hidden as before, and shown again with Include archived. Delete, for an Admin, deletes the rows ticked that were a mistake (P-227): it too is for particular rows only. It asks first with what the server answers to the same request with `dry_run`: how many will be deleted, and each that is refused, as a link, with what depends on it, each a link to its page where its kind has one. A reason is typed, and only then is the request sent again without `dry_run`; the page then says what was deleted and what was refused, which stays ticked. An item's page has Delete too, for an Admin, which asks the same way; once the item is deleted the list of items is shown, saying `Item <name> was deleted.`, and one that is refused stays, the page saying what is in its way. A page opened for an item that was deleted says what the server's `404` says, that it was deleted, when and by whom, and the reason given 0.9.8, a thing that runs on another (P-250, P-249): among the first facts of an item of a kind that runs on a host, where a member of a stack says it is one, Runs on names the host as a link, an item or a stack or a cluster, said to be which, with the PID of an item; and where one was seen, Seen on, as a link, with when, and `not the host named` where `host_differs` is true, in a plain word that is no fault. An item that names none says `It names no host.` marked To be looked at, with Name its host, which goes to Host in its form; one whose host is gone (`host_gone`) says that its host is retired or out of the team's hands, with the host still a link, and how to put it right. A mark of what is to be looked at is a word, never the colour of a fault. The location, the planned location, the owner and the operator it has from its host say `Inherited from the host <name>`, a link to the host, as they say it of a group, and the walk of Why it has each value has the step of the host. A virtual context with no serial number of its own shows its host's, inherited from the host. The form of an item, New item and Details, has Host while the model chosen is of a kind that runs on a host: one field that searches by name, offering the items of a kind that may host, or of no model, and the stacks and the clusters, each said to be which, sent as `host_item_hid` or `host_group_hid`, the other cleared; a refusal of either is shown at Host, and nothing typed is lost. Seen on, an item searched for, fills Seen at with now as it is chosen, which may be changed; Create and add another like it keeps the host. A model chosen of a kind that runs on none clears the host in the same save. An item or a stack or a cluster that something runs on has What runs on it, with the count in its heading: each as a link, with its kind, its state and its primary address, and what runs on those indented beneath them, read from `GET /items/{hid}/hosted` and `GET /device-groups/{hid}/hosted`, and beneath its heading, there before the list has come, a link to them in the item list (`host_item_hid:eq:<hid>` or `host_group_hid:eq:<hid>`), to tick and change together; one that nothing runs on shows nothing of it. The item list has Runs on as a column to turn on, a link to the host, filtered and sorted by `host.name`, and To be looked at, the reasons in words, filtered by `review`. Bulk edit has Host, searched for as in the form, which gives the rows ticked another host, an item by its HID as `host` or a stack or a cluster by its name as `host_group`, or clears it |
| Catalog | Entries by vendor, each with how many items are of it, sorted by it as by any column, a link to them (P-180); the items of each entry; an entry's links, each opening in a new tab, edited as a list; its flag not to renew; and Files and links, the documents of the model |
| Vendors | The list of vendors. A vendor has a page of its own, the portfolio: the totals, the four kinds, the models with their dates and their cover, its items as a grid that is exported like any other, with the filter box of the item list, and the agreements, the contracts and the capacity lines of the vendor (0.9.6, P-211). A carrier's page also lists its account team and its support desk, named and removed there, and its circuits |
| Groups | Stacks, clusters and controller domains, with members and roles, and the circuits a group is connected to. A group's page shows, under Values in force, the walk of its location, planned location, operator and owner as a row of boxes (P-176). The rows ticked are retired at once, and deleted by an Admin, and a group's page has Delete for an Admin, as the list and the page of an item have them (P-227, P-228) A stack's or a cluster's page has What runs on it where something does, as an item's page has it (P-250) |
| Circuits | The grid of circuits, with Name, Enterprise ID, Type, Speed, Carrier, Carrier's number, A side, Z side, Monthly cost, Annual cost, Owner and Tags shown at first and the rest in the column chooser, filtered, sorted and exported by the server. A circuit has a page of its own: its fields, each side with its location's path, or its note where it has none, and its site contacts with the level each came from; its carriers with their numbers; the carrier's account team and support desk with where they came from, and those it names of its own; the devices on each side; its cost lines, with the monthly and annual totals; its groups; Files and links, its own references; and the forms to change it, to switch the side it counts at, and to retire it. A speed is entered as the port, and the rates down and up left blank for the full rate, and shown short, `1G / 200M / 20M`. Circuit groups have a list, with how many circuits each has and what they cost, and a page each, with its circuits to add and take out |
| Addresses | Every address, with the item or group that has it; the networks |
| Geography | The tree of regions, sites and locations with the items and components at or beneath each, and what is planned for each, for a filter of the item list; the inside of a site is fetched when it is opened. A place has a page of its own: its path, fields and tags, what it has in force with the level each thing came from, the contacts assigned to it, and the forms to change, move and retire it. A draft place lists what is planned for it, and making it active says first how many items that moves in. A region, a site and a location show their own links, each opening in a new tab, edited as a list; a place shows none of the places above it. Files and links lists a place's own references and then those of the places above it, each under the place it is on. A place shows its own support weight, a site the default where it has none and the minimum where it was raised, and a location's page lists the circuits that have a side there. The coordinates of a site and of a location, among its facts, are a link to `map_url` where the place's answer has one, opening in a new tab with `rel="noopener noreferrer"`, so that the map's site is sent the coordinates and nothing else; where `map_url` is null, as where the setting `map_link` is blank, they are plain numbers, and a place with none shows none (P-229) |
| Contacts, Owners | Contacts: the list of people, each marked where it is a user by its username, which every role reads and which is a link to the user's page for an Admin alone (P-239), and a contact with the user it is and, under Where it is named, every record that names it, by kind under a heading of each, each record a link with the role the contact has there: the places, owners, operators it stands behind, agreements, contracts, vendors and circuits (P-205). Owners: the list, and an owner with its people, the primary first |
| Operators | The labels, each with its colour, the person behind it, internal where that person is a user and external where not, the person's email and two numbers, and how much it is on. An operator's page draws what it is on as a tree of boxes: the operator, then its places, its groups and its own items, each box with its counts and the exceptions within it, joined by lines, every count a link (P-177). Hand a label over to another person, a contact that is a user, another contact or a new person, leave it open, release it and bring it back. The email and the numbers are changed there, on the person's contact. Wherever an operator is shown, in a grid, on a page or in a report, it is the label in its colour, as a link to this page, with the person's name beside it or on hover and a mark when it is open |
| Contracts | The support agreements, each with the contracts grouped into it, and the contracts that stand by themselves. An agreement has a page of its own: its fields, its contracts with what each has from it and what each overrides, shown as an inherited value is shown everywhere, and the terms it had before, its purchase history, as a contract has its own. An override says what the agreement gives in its place, as the server answers it, and where the two are the same it says so: it stays as it is when the agreement's changes. A contract is put into an agreement, and taken out of one, on its own page. The list of contracts with how many items each covers. A contract has a page of its own: its fields and tags, and the items it covers, each with its dates, to add to several at a time and to end. **Renew** asks for the new number and the new period, says how many items follow, and changes the one record; a renewal that is still to begin is shown as the next term, and can be withdrawn; the terms it had before are listed beneath, each with the dates it had in force, a date it had from its agreement shown as inherited. Renewing an agreement is the same, and lists every contract that shares its period, each with a choice: keep its number, the default, take a new number that begins with the new term, or end with this term, and with the status it is to have, which the operator confirms there for the members that move forward: one, some or all of them are selected and given a choice and a status at once, and nothing else in the renewal changes a member's status. The answer says what was done with each, which members are to review, and how many items not to be renewed were left behind. An agreement's page lists its contracts, to select one, some or all and change them at once: their status, taken out of the agreement, or retired; and its members to review. A number that waits on the agreement's next term is shown as the contract's next term, with the agreement's dates. A contract may be marked not to be renewed, the team's note, which changes nothing by itself and is shown as such. The earlier terms of a contract are the parts of its history, each with its days and what began it: a renewal, joining an agreement or leaving one. **Renewals**, under Contracts, is the worklist: the counts of each list first, by vendor and agreement, each count leading to its rows when it is opened, and the rows of a list with their end, how long a renewal has been pending, marked when overdue, and how many items each covers. A change of a contract or an agreement that is refused as stale says, where it has a next term, that the term may have begun since the page was read. A contract that has lapsed is marked, and so is one whose renewal is pending, with the account manager to go through. A coverage that was a mistake is removed, and one that was ended because its item left is marked until the vendor has been told. The gaps and the expiries are the coverage report |
| Purchases | The requests, each with its lines and what is still to come. A request has a page of its own: its lines, and for each the items that arrived on it, and where some of them are of another model than the line's, which 0.6.0 let in, how many, leading to them in the item grid. The list of lines has Of another model in its column chooser. Receiving a line asks for the serial numbers, the asset tags or the names of what arrived, or how many arrived that nothing is known of yet, the day and the location |
| External systems | The systems, each with how many records are registered with it, and the registrations of each. An item and a device group show what they are registered with, and are registered from their own page; a member of a stack or a cluster also shows, to be read only, what that group is registered with. A registration that was a mistake is removed |
| Import | Upload, preview, apply, past jobs. An apply goes on in the background: the page shows how far it has got, from `rows_done` of `row_count`, and may be left and come back to. Once applied, the rows left out as stale and those refused are listed, each with why, and a job that stopped says why and is resumed from there. A past import of a file that was applied, or stopped, lists under What it made the records it made, from `GET /imports/{hid}/created`, a hundred to a page: the row of the file, the kind, the name as a link to the record's page, in plain words where the record was deleted, and what it is now, Active, Draft, Retired or Deleted (P-234). The vendors and the catalog entries it made because a row named them follow, each a link. For an import of items or of device groups, a person who may retire them ticks the rows, one by one or every row of the page by the box in the heading, and the rows ticked are retired by Retire, for the Inventory role, and deleted by Delete, for an Admin, which ask and answer as they do on the lists of items and of groups; the list is then read again, and those refused stay ticked. A View-only person reads the list, with no box and no button |
| Capacity | Demand beside supply by category, the balance and the coverage, with and without drafts, and the share of the supply that is the team's own positions; the lines, editable. The lines that multiply, each with its gain and the staff lines it works on; the demand of each region beside the balance, with no supply divided; and the trend, a graph of one point a week, demand and supply as two lines with the balance between them shaded and a switch that stacks the supply by category and splits the demand into the infrastructure and other work, a corrected week marked; a week recorded now, corrected with a note, and removed. The support weight is shown in its parts, the items, the places and the circuits, with how many counted at a default and were raised to a minimum. **Try** sets other defaults and minimums, another weight per engineer and another stack discount, adds, changes and leaves out staff lines, and shows the balance tried beside the one in force, saving nothing; an Admin is offered to save the settings tried |
| Reports | Every table of a report has a rank by the column it is sorted by, and a bar beside each count (P-178, P-180). Scoreboard: the operators, each with its rank, the items, components, managed nodes and support weight it looks after and their health in one column, a bar in four parts with its numbers, the most first, each count with a bar beside it; beneath them, how each operator's items have it and how many groups and places are given it, a table of its own (P-181); with what nobody is assigned to and what is under an open label; the device groups, ranked in the same way, each with its type, members, nested groups and the items, components, managed nodes, support weight and health of what is under it (P-178); and the sites likewise, each with the operators involved there. Summary: components, managed nodes, support weight and health, whole and by owner, state, vendor and the rest. Management: estimated value and annual support cost, whole and by site unless another grouping is chosen. In both, the name of a row of a record opens its page: a vendor, a model, an owner, an operator, a group, a site, a region and a contract (P-240); a row of a tag, which has no page, of a value or of what has none is its name alone. Duplicates. Coverage: the items in service with no cover, the items out of service that a contract still counts, each with those contracts, Still counted under, as a column of the item list, what runs out soon, what more than one contract covers, what is covered while a renewal is pending, and the contracts that have lapsed. End of life: past and approaching, for each of the four dates, and by fiscal year. Replacements. Circuit costs: the year and the grouping to choose, by carrier unless another is chosen, each row with its circuits, the year's cost, and the monthly and annual figures, leading to its circuits |
| The renewal alert | After signing in, a person with the Inventory or the Admin role is shown a banner under the header of every page, once a day while `GET /renewals/alert` says to show it: how many contracts have lapsed, have a renewal pending, of which overdue, and end within the warning period, and the agreements on the same lists, each leading to its list on the Renewals page. Dismissing it sends `POST /renewals/alert/seen`, and it is not shown again until the next day |
| Files and links | A section of the page of a catalog entry, an item, a region, a site, a location and a circuit (P-162). The record's links of 0.7.0 come first, where it has them; then its references, grouped by where each comes from, its own first, each with its title, kind, size or address, and who added it and when. A picture is opened in a viewer within the page, and every other file is downloaded with its name; a link opens in a new tab, as the links of 0.7.0 do. With the Inventory role: Add files, one or several at once, chosen or dropped on the section, each given a title, which starts as its file name, and a kind, with a bar for how far each upload has got; Add a link; and on each reference Edit, New edition, Put on other records, Take off this record, and Erase. Taking off the last record, and Erase, say first that the content is erased at once and that the backups on the server keep a copy until they rotate out, 14 days unless the server is set otherwise. A file that is refused says why, and the others go on. A file chosen before the page has read the kinds of file is given its first kind when they are read, a picture a photograph, unless the person has chosen one |
| Admin | Users, each with its contact, whose email and numbers it shows and changes, and a username that an Admin changes; groups, role grants, service tokens, settings, choices, lifecycle rules, tags, and Files: every reference, with its kind, its size and how many records it is on, sorted and narrowed by the server, each leading to the records it is on. On the Settings page an Admin's Change opens the form of that setting directly beneath its row, and the table fits a window 1280 pixels wide (P-171); Edit on Tags and Lifecycle rules and Change on Files open their forms beneath their row too. It has, for an Admin, a button, Check kept reports, which says how many kept answers were checked and names any that differed. Every role sees this area: tags, choices and lifecycle rules are there for all to read and for Inventory to edit, and the rest shows to an Admin only |
| About | The product, by the name the site gives it, and that the software is hirdir with its version; what it runs on, Python, SQLite and the revision of the schema. Whom to ask: the organization, the email address to write to, the number to call, its link dialling the number without its extension, and the address to open, each that is set and none that is not, or that nobody has been named, with a link to Admin › Settings for an Admin |

What 0.9.5 adds to these pages, for the work of each day:

- **Home.** The totals come from the plain summary and do not wait for the summary by
  operator, which is asked for apart for the one line that needs it; each total of
  health is a link to the items with that health (P-195).
- **Items.** Site and Location are shown from the start and Expected online is in the
  column chooser. The columns shown from the start stand as Name, PID, Serial number,
  State, Health, Site and Location, which fit a window 1280 pixels wide, then Operator,
  Owner, Vendor, Disposition, Tags and LDoS. A layout kept before 0.9.5 stays as it
  was: Reset layout and filters brings the new one (P-193). New item has a second button, Create and add another like it:
  the page says the item was made, with a link to it, and the form stays open with what
  the next one shares, and with the serial number, asset tag, name, host name and MAC
  address blank (P-192). Once an item has been made so, Enter in a box of the form makes
  the next one as that button does, so that a scanner's Enter after a serial number
  does not end the run; a box that takes Enter for itself, as a picker that searches,
  keeps it.
- **An item.** Under its name, links to the sections of the page. Among its first
  facts, its lifecycle state, disposition and intent, with Change, and Change beside its
  comments; beside its location and its site, a link, items here, to the list of items
  filtered to that place (P-189). Where its disposition and intent are changed, only
  what the lifecycle rule of its state allows is offered (P-191).
- **Geography.** A box, Find a place, searches the sites as a site is searched for
  elsewhere, each word in its name, its code or its region's name, and the locations as
  the Location field of an item searches them, each word in the name or the code of the
  location, the name of the location it is in, the name or the code of its site or the
  name of its region, so that the site named with a room narrows it; it lists up to ten
  of each by their path, each a link. Drafts are found, and a retired place is found
  when the view of the tree has Retired places on; both are marked (P-188). On the page
  of a place, what is in force there, its contacts first, stands above its files and
  links, and the email and the number of a contact are links that write to it and call
  it (P-194).
- **Reports.** The Scoreboard begins with links to its tables; a table of more than
  twenty rows shows twenty and a button, Show all; the operators involved with a group
  or a site are a number with the list behind it (P-196). A link to a table writes the
  address as every link of the app does, under the path the site is served at, and
  brings the window to the table with the keyboard on its heading; the page opened at an
  address that names a table stands at it once the tables have come. The totals of health on the
  summary are links to the items, within the view asked for (P-195).
- **Contacts.** A contact that the server counts uses of, with no place, owner or
  operator to list, is said to be named in agreements, contracts, vendors or circuits,
  with the number, and not to be assigned nowhere (P-197).

What 0.9.6 changes:

- **An item, a device group.** Under Values in force, the walks of why the record has
  each value stand behind a line, Why it has each value, closed when the page opens;
  a press opens them, and they are read from the server then (P-198). The table of
  the values in force and the source of each stays open.
- **Every form.** A field that offered every record of a kind as one list, where
  there can be many, is searched as it is typed in, as the Location field is: the
  catalog entry of New item and of an item's details, and the successor of a catalog
  entry, among them: each word typed is looked for in the PID, the model name and the
  vendor's name, those with the most items first, each offered with its vendor beside its
  PID. A list that stays a list is read to its end, past the first 1,000 (P-200). New item offers to add a model that the search does not
  find, within the page, and keeps what was typed (P-201). What is typed into a form
  after its Save, while the page reads the record again, stays; where the record read
  again has a new value in a field kept so, from someone else, the field says so beneath
  it, "Changed meanwhile to …; saving replaces it", and a field not typed in takes the
  new value without a word (P-202). A page that has
  made a record says so, with a link to it (P-204).
- **Every grid.** Coming back to a list from a record shows the page it was on, where
  it was scrolled to, with the row that was opened marked; a new filter or sort begins
  at the top (P-203). The preview of a bulk edit speaks of the bulk edit, and the export
  of the item list as it first stands holds the host name (P-204).
- **Contacts.** A contact's page lists, under Where it is named, every record that names
  the contact, by kind under a heading of each, each a link, with the role the contact
  has there, from `GET /contacts/{hid}/uses`, in place of the sentence of P-197 (P-205).
  Where a kind names it more than 100 times, the page says how many of how many it lists.
- **Reports.** Every count of items, of components and of health of the summary and
  of the management report, in the totals and in each row, is a link to the items it
  counts, by the filter the server gives with it and the condition it gives for the
  count; Home's totals use the same, and the page builds no such filter of its own
  (P-206). A count of none is no link, and neither is a count of managed nodes, a support
  weight or a sum of money.
- **A refusal.** Where a record is refused because another has its serial number, asset
  tag, PID or name, the page names that record as a link; a filter refused for a field
  its list does not have names the nearest one it has (P-207).
- **Purchases.** Add a line has a second button, Add and add another like it, which
  keeps the destination site and the expected date; a line's destination site offers
  the draft sites, marked; the table of a request's lines fits the window, with the
  part number and description as procurement gave them beneath the model where a line
  has them, and one link, Every item it brought, beside what was received, opens the
  items that arrived on its lines, retired and draft ones among them, by
  `purchase_line_hid:in:` the lines received on; a
  request received on in more than 100 lines is given in links of 100 lines each, so
  that no address is too long to send (P-208).
  Receive opens its form in the window with the keyboard in the box of what arrived,
  and its location is searched within the line's destination site from the start, the
  site's first locations offered before anything is typed and its one location chosen
  where it has only one; Only at the site, cleared, searches every site (P-209). The
  plain words of the list of lines look in the name of the destination site (`site`;
  the list of lines has no field of the site's code), and Destination site and Expected
  are in view, with Part number and Tracked in the column chooser; a layout a person
  kept stays until Reset layout and filters. Still to come is whole in the list of
  requests (P-210).
- **A vendor.** The table of models shows twenty, as it is sorted, and a button, Show
  all, with the number; sorted by a date, the models with none come last, whichever
  way. The vendor's items stand above its agreements and contracts, with the filter box
  of the item list and its plain words, which narrow within the vendor's items; what is
  typed there is not remembered, so that it is never in force on another vendor's page,
  and the same holds of the items a contract covers (P-211).
- **Contracts.** The grid of every contract comes first, with the contracts that have
  lapsed counted above it, and the tables by agreement after it, folded closed behind a
  line that says how many agreements there are and read when it is opened; on Renewals
  the rows of a count that is opened come into the window, with the keyboard on their
  heading; the list of agreements shows the account manager, beside the vendor (P-212). The items a
  contract covers have the filter box, its plain words looking in the item's name,
  serial number and asset tag; ending a coverage on the contract's last day is said to
  change nothing before it is sent, with how to leave an item out of a renewal, and
  after an End the page says what the server kept, never that a coverage it kept open
  was ended (P-213). Renew begins with the dates
  that follow the present term, from the day after it ends for a year whatever its
  length, with a button, Keep the present period, for a new number alone; a record whose
  end is its agreement's, or that has a term to come, begins with its dates as they are.
  The purchase reference begins blank. Under the button of a contract's renewal, each
  counted by the server: the coverages that have the contract's period and follow, the
  items it covers today that are marked not to be renewed, as a link to them, with the
  rule the renewal keeps (it leaves behind those whose coverage runs to the last day of
  the present term), the coverages that begin after the present term, with the new one,
  and those that end on a day of their own by then; for a term that names no end, the
  items in scope and those marked. The counts are read again when a coverage is changed
  on the page (P-214). On the grid of the items a contract covers, Leave out of the
  renewal sets the item's own mark Not to be renewed on the items of the rows selected,
  after a line that says the mark holds for every contract that covers the item, and
  says how many were marked; Renew after all takes the item's own mark off, so that each
  has what its model says. Both take particular rows, not all that match, and the counts
  under the renewal form are read again after them (P-224). An agreement's page has the
  annual cost of each of its contracts, which is always the contract's own, and a row
  of their total, beside the agreement's own figure and not in place of it: a contract
  with no cost counts as none, and the row says how many have none; a draft is not
  counted, nor is a contract cancelled or expired, and the row says how many were left
  out for that (P-215).
- **A minor item.** Under its heading, one line: its type and model, its position in
  the item it is in, that item as a link, and the site it has in force; and a link,
  Spares of this model here, to the item list filtered to its catalog entry, that site
  and the disposition Spare in force, minor items included (P-216).
- **Stacks.** Add members on a stack's page has a box, ticked from the start: the
  switch takes the stack's name and place, which sends `drop_identity` with the member,
  and Production for a spare (P-217). The box stands under the members chosen, one for
  each with its name, and under it one line of exactly what it removes from that switch,
  read from the switch as it was chosen: its host name, its FQDN, each address and its own
  location; unticked, the line says that nothing of it is changed, and nothing of the
  item is sent. A switch whose disposition is Spare is offered Production and expected
  online, as Disposition and Expected online, each with As it is, among what the rule of
  its state allows. New group has the same box under each member chosen for a stack,
  ticked from the start, with Production for a spare, sent on each of its `members`
  (P-244); a member chosen while the type was another keeps what the box needs, so the
  box is there when the type is made a stack, and the other types have none. Join a
  stack on a switch's page has the same box, and the position the stack offers. After the
  add, the answer at the top of the page says for each member its position, what was
  removed and what it is now.
  Ending a membership of a stack asks What becomes
  of it: to the spare pool with a new name and place, to be returned to the
  manufacturer, excess, or nothing now, saved with the end (P-218). Nothing now is
  chosen when the form opens, and sends nothing of the item. The item is read when the
  form opens, for its state and disposition; each other choice fills Hostname, FQDN,
  Location, Lifecycle state (As it is, or a state its rule lets it move to), Reason (the
  published reasons, for a move), Disposition and Expected online (as the rule of the
  state allows), which the person may change, and a field left blank or As it is is not
  sent: to the spare pool fills Spare and not expected online, the state as it is, and
  leaves the name and the place to be typed; to be returned fills Pending-Removal for the
  reason RMA, not expected online, and the Condition Failed, a field of the
  `item_condition` list beside them that the others leave as it is, sent as
  `item.condition` with the end and said in the answer as marked Failed (P-245); excess fills Pending-Removal for the reason Retired,
  Excess, not expected online. The ended row stays among the members, marked Ended,
  until the page is left, and the answer says what was sent and names the item as a link. The position offered
  is the lowest that is free, and one that a current member holds is refused (P-219):
  the first member added is offered the stack's `next_position`, and each further one of
  the same request the next that neither a current member nor another row holds; a
  position refused is said beside its row, with the member that holds it as a link, from
  the refusal's `existing`.
  Find an item and the item list find the members of a stack by the stack's name, and
  say above the rows that the words name a device group, with a link to it; the list of
  groups finds a stack by a member's serial number; a member's row names its stack and
  position (P-220). The plain words of the item list look in `group.name`, the names of
  the groups an item is a current member of (the item list has no field of a group's host
  name); a word that is the name or the host name of a device group, ignoring case, is
  named beside the heading Items, at most three groups, each with its number of members,
  from one request to the list of groups sent beside the list's own. The line stands
  beside the heading, so that it moves no row when it comes. The column Stack, beside
  Name from the start, shows a member's stack and position, as `cw07-idf03-acc1 #2`,
  from the groups every row of the list carries; it is filtered and sorted by the names
  of the item's groups, as Groups is. The plain words of the list of groups look in
  `name`, `hostname` and `member.serial_number`. The picker of members shows each switch's state, disposition and
  place and the stack it is in, offers the spares first, and does not let one that is in
  a stack be chosen for another (P-221): it is shown, with why, as is one in a cluster
  for another cluster and one in Released or Archived. The spares are a second search
  sent beside the first, since the server sorts by no field that puts them first; the
  search is not narrowed to switches, since a member may be any major item, one with no
  model yet among them. A member's page says among its first facts that
  it is a member, with its position and its stack as a link, and shows the stack's host
  name, FQDN and addresses as the stack's; an item in no stack has Join a stack (P-222).
  They stand under Name: Stack, "Member 2 of" the stack as a link, then the stack's
  hostname, FQDN and addresses, read from `GET /device-groups/{hid}` when the page is
  read, their lines there from the start. Join a stack is offered to a person who may
  change the item, on a major item that is not retired, not in Released or Archived and
  in no stack: the stack is searched for by its name among the stacks, the next position
  is offered, and the answer is said at the top of the page, which reads the item again.
  The row of a current member of any group has Replace beside End, for the Inventory
  role (P-242), and each of the three forms of a member's row, Change, End and Replace,
  opens under its row, across the table, as the forms of rows do since 0.9.3 (P-171).
  Replace reads the item that leaves when it opens, for its version and its groups, and
  asks: what takes its place, an item in the inventory, searched for by the picker of
  members of P-221 (the spares first, each with where it stands; in a stack, major items,
  one in another stack shown and not to be chosen), or a new item created there; in a
  stack, under it, the box of the stack's name and place with the line of what it
  removes, ticked from the start, and Disposition and Expected online for a spare, as
  Add members has them, sending `drop_identity`, `disposition` and `expected_online`;
  Reason, of the `replacement_reason` list, Reference and Replaced on; and What becomes
  of it for the item that leaves, the four choices of End with the same fields and a
  Condition, of the `item_condition` list, which To be returned to the manufacturer starts
  at Failed (P-245), sent as `old_item`. What becomes of it is asked of every
  replacement, in a group or not, since the item that leaves is the one a person moves
  next; Nothing now is chosen when it opens and sends nothing. It is one request, `POST
  /items/{hid}/replace`; a refusal is said beside the field it names, as
  `old_item.condition`, and what was typed stays. The answer at the top of the page names
  the item that left and the one that came, each as a link, the position and the stack,
  what the box removed, what the one that came is now and what became of the one that
  left; the members are read again, and the new member's row stands at the position
  that was the old one's. Replace this item on an item's page is the same form, offered
  whether or not the item was replaced before (P-241). Above it, the section Replacement
  lists the item's `replacements`, the latest first, one line each: Replaced by, where
  this item left, or Took the place of, where it came, the other item as a link, the day,
  the reason and the reference. For an Admin each line has Remove (P-238), which opens
  under the line a question that says the removal is for a replacement that never
  happened and that what it handed over stays, with a Reason that must be typed before
  Remove replacement may be pressed; it calls `POST /item-replacements/{hid}/remove`, and
  the page says the replacement was removed and reads the item again. Beside Join a
  stack, an item that may join one has Make it a stack (P-243), for the same people:
  its form, in the same place, has Name of the stack, the item's own name, or its host
  name, from the start, which the person may change; one sentence of what goes to the
  stack, each only where the item has it of its own, its host name, its FQDN, its
  address or how many addresses, its location, planned location, owner and operator,
  and of what stays its own; and More members, the picker of members with the item as
  member 1 and the next offered 2, each chosen with the box of P-217 and Production for
  a spare. Make the stack sends `POST /items/{hid}/make-stack`, the name left out when
  blank; a refusal of the name, of the item or of a member is said beside it, by its row
  for a member. Afterwards the stack's page is shown, which says at the top that the
  stack was made of the item, member 1, and how many more members it has. No other page
  reads `replaces` or `replaced_by` of an item: the report of replacements has a row for
  each replacement.

### The grid

One grid component is used on every list page.

- Sort by one or more columns, filter per column, resize, reorder, show and hide
  columns. Sorting, filtering and paging are done by the server.
- Every column of every grid is sorted by its header, by the server and over the
  whole list: [Sorting](#sorting) names the field of each column that is worked out.
  A table that the server pages and that is no grid, the users, the audit trail, the
  past imports and the rows of a preview, the duplicates, the members of a group, the
  minor items and the history of an item, is sorted by the server too, by the `sort`
  of its route. Every other table a page shows, the scoreboard, the people of an
  owner, the contacts of a place, is sorted by its headers in the browser, since it
  holds all of its rows: text without regard to case, numbers as numbers, dates as
  dates, and blanks last.
- Select whole rows: one, a range with Shift, several one by one, or "all that match the
  filter", which is shown as a count and sent to the server as the filter, not as a list
  of rows. Pressing a row ticks it or unticks it, and unticks nothing else, so that a
  stray press costs one tick and not forty. Shift with a press, on a row or on its box,
  or with Space, ticks the rows from the one last pressed without Shift to this one, and
  unticks nothing, whether the row last pressed was ticked or unticked by that press;
  the web takes the gesture itself, since the grid's own would untick the rest. Rows of
  the range that the grid has not read yet, as when the list was scrolled to its end at
  once, cannot be ticked unread: the rows read and the row pressed are ticked, and the
  status beside the count says how many rows between were not read and so not ticked,
  until the next press.
  A press on a link in a row follows the link and changes no tick; Ctrl or the middle
  button on a link opens it in a new tab, as a browser does.
- Rows are ticked (P-233). Every list whose rows are selected has a column of boxes at
  its left, one to a row, as narrow as a box, 24 px, so that the columns the owner asked
  to see at 1280 px stay in view: ticking one adds its row to those selected, and clearing it
  takes the row out, whatever else is ticked. The box in the heading ticks the rows the
  grid has read from the server so far, a hundred at a time as the list is scrolled,
  and clears every row ticked when every one of those is ticked; its name says which,
  with their number, `Tick the 100 rows read so far`, or `Clear the 150 rows ticked`,
  which after a sort may be more than the rows read again. It shows itself ticked only when every row
  of the list is read and ticked, and the half mark while some are ticked, as when the
  first 100 of 260 are; it waits, not to be pressed, until the first rows have come. All that match the filter stays the
  button Select all that match, since it is a count and not a list of rows. Pressing a
  row ticks its box or clears it, as the box itself does. Each button that acts on the rows
  chosen says how many, as `Copy (3)`, or `Bulk edit (all 1,204)` for all that match:
  Copy, Export CSV, Export JSON, Bulk edit, and each action a page adds, as Cover with
  a contract. A button that takes particular rows only, offered while all that match
  are chosen, is not pressed then and says no count. Export with nothing chosen takes
  every row that matches, as before, and says no count.
- **Copy** puts the selected rows on the clipboard as tab-separated text with a header
  row. **Export** sends the current filter, sort and columns to `POST /exports`. With
  particular rows selected, copy, export and bulk edit all act on exactly those rows,
  named by their HIDs, also when one of them no longer matches the filter. Beside them,
  on a list whose records name a place, items, groups, regions, sites, locations, the
  contacts of places, capacity lines and circuits, a box **Places by code**, off when
  the list is opened, sends `place_codes` with Copy and with Export while it is ticked,
  so that each place is written the short way, `S2 > R102` (P-235). It is not
  remembered.
- **Edit** opens the record's form. **Bulk edit** opens a form for the selected rows,
  shows a before-and-after preview, and applies on confirmation, in the background as
  an import is: it shows how far the apply has got, and the rows left out as stale.
- An inherited value is shown in a lighter style with its source on hover. Editing it
  creates an override; clearing an override returns it to inheriting.
- Archived and retired records are hidden until "Include archived" is on, then greyed.
- Column layout and the last filter are remembered per user in `localStorage`.
- Where a list was left, how far it was scrolled and the row opened from it, is kept
  for the tab in `sessionStorage`, by the grid. Coming back to the list by Back or by a
  link, under the same filter, sort and switches, shows the same rows with that row
  marked; a new filter or sort begins at the top, and a link that brings a filter of
  its own shows it from the top. A browser that refuses the storage shows the list from
  its top (P-203).

- Every value of a list that names another record is a link to that record's page
  (P-232): in the item list the stack, the groups, the location, the planned location,
  the site, the region, the owner, the operator, the vendor, the PID and the model, the
  item a minor item is in, the contracts, the systems it is registered with and the
  purchase request of its line; in the list of groups the masters, the owner, the
  operator, the group it is in, the places and the systems; in the list of circuits the
  carrier, the places of the two sides, the owner, the site its cost is of and its
  groups; and likewise in the other lists. Such a link is in the colour of the text
  around it, a lighter inherited value lighter, with no underline but while the pointer is
  on it and while its cell has the keyboard's focus. The name that opens the row's own
  record stays the link it is. A cell that names several records, as the groups of an
  item, has a link for each, parted by commas. A press on a link opens its page and does
  not select the row; a press with Ctrl, Shift or the middle button is the browser's, as a
  new tab, and selects nothing either. Enter on such a cell opens the page of the first
  record it names, as Enter on any other cell opens the row's own. A value that names a
  record with no page, a tag or a network, stays text. What is copied and exported is
  unchanged: the same text as the cell's. The tables of pages follow the same rule: the
  name in the heading of a row, which opens the row's own record, is the link it is, and a
  value in another cell that names a record is a link in the style of its text, as the
  vendor of a contract, the agreement of a term or a contract, the system of a
  registration, the model of a minor item and of a member of a group, the vendor of a
  contract that covers an item, the carrier or the place a contact is inherited from, the
  contact of a place and the user groups of a user, for an Admin. In the grid of the items
  a contract covers, the PID is a link to the model.

Cell-range selection and editing in the grid are LATER.

### The frame of every page

The menu bar is at the top of every page, with the product name at its upper left:
`product_name`, `hirdir` unless an Admin gives another (P-168). The title of the
browser's tab is the page and that name, `Items · Example Inventory`, and what the pages
say of the product, as "ask an administrator of Example Inventory", say it by that name
too. A downloaded file
is named with it: an export as the server names it, and a file the page makes itself,
such as the scoreboard's `Example-Inventory-scoreboard-sites.csv`. An import guesses the kind of
record of a file so named as it does of one named `hirdir-`.

A page opened from the menu bar, or from a link on another page, begins at its top with
the menu bar in view, and focus moves to its content without scrolling it, so that a
keyboard or a screen reader starts there (P-167). Back and Forward leave the window
where the browser puts it, and a change that keeps the page's address, such as a
filter, does not move it.

What a page answers to a change, that it was done or why it was refused, stays in view
(P-182): it is shown at its place near the top of the page, and while the window is
scrolled past that place it stays at the top of the window, over the page. It is part
of the page and does not go away by itself; a message that something was done is taken
away when the next change on that page is sent, stays away if that change is refused,
and once it is done the page says what it says of it, the same words again after a
second save of the same record. Room is kept for it at the top of the window, so
that a field the keyboard moves to, or a row a form opens under, does not come to rest
beneath it. A change refused because another record has the value says, under the
server's sentence, which record that is, "The item that has it:", with the record as a
link to its page by what it is known by (P-207); a record whose kind has no page, a tag,
a choice, a network or a reference file, is named without a link, and so is a user or a user group to anyone but an
Admin.

A field that finds a record by what is typed searches again when Enter is pressed, when
the same text is typed again, and when the person comes back to the tab with a search
on show; a list of choices that a page read whole when it opened is read again when the
person comes back to the tab, though not twice within five seconds (P-183). So a record made a moment before in another tab
is found without loading the page again.

Where a location is searched for and none matches, the field also looks for sites by
the same words and names up to three of those found, saying of each that it has no
location that matches, with a link to its page, where a location is made, and says how
many more match (P-184). An item is put at a location, never at a site, and the page of
a site with no location says so. Where a planned location is searched for, no site is
named: only a place not yet in use is offered there, so a site in use with every
location it has would be named wrongly.

On the page of an item, the catalog entry, the owner, the operator and the location
among its first facts each have Change beside them, for a person who may change the
item: a button that reads as a link, it moves to that field of the form of details and
puts the keyboard there, and leaves the page's address as it is (P-185). Where the parts
of the page above the field come after, on a busy server, the window follows the field,
so that it stays where Change put it.

A table wider than the page scrolls sideways within its own box and the page does not;
a form opened under a row of a table is brought wholly into the window when it fits there
with the row it changes, and otherwise moves no further than keeps that row in view; and
the audit trail links each change to the page of its record, where it has one (P-186).
A record that an event on show deleted is named as text, by each of its events, and said
to be deleted; one deleted in an event not on show is a link, to a page that says it was
deleted, when, by whom and why. The user who made the change is a link to the user's
page for an Admin, and text for everyone else (P-240); so is Who in the History of an
item, where the event was made by a user.

The menu bar has a box, Find an item, on every page: what is typed there opens the list
of items with those words, minor items among them (P-187). Text the list cannot read is
not sent there: what is wrong with it is said under the box, which keeps it. The same
words asked again make the list anew, its own filter box with them. In the filter box above any
list, text that holds no condition of the short form is taken as words: a record matches
when each word is held by one of the fields its list is known by, as an item's name,
host name, serial number, asset tag and address. The words are sent as a tree of the
filter grammar; a condition of the short form is sent as it always was. Text that is
neither, as words with a condition after them, is answered with how that list's own short
form reads. A word of hex digits and the colons, dots or hyphens that part them, as a MAC
address or an IPv6 address, is a word whatever its first group is, and the double quotes
round a word are dropped. An item is found by its MAC address too, `mac_address`, for a
word that can be one or a part of one: pairs of hex digits parted by colons or hyphens,
groups of four parted by dots, or the twelve digits alone; the server refuses any other
text there. A list opened with text in its box that it cannot read, from a link or as it
was remembered, says why under the box at once, and while that text is in force asks for
no row: the count, Select all that match, Copy, Export, Bulk edit and Cover with a
contract have nothing to act on. Up to eight words are taken at once. What a list is known by: an item by its
`name`, `hostname`, `serial_number`, `asset_tag` and `address`; a contact by `name` and
`email`; a catalog entry by `pid` and `model_name`; a vendor, a capacity line, an external
system and a circuit group by `name`; an operator by `label`; an owner by `label` and
`organization`; an agreement by `name` and `number`; a contract, on Contracts and on
Renewals, by `number` and `agreement.name`; a device group by `name` and `hostname`; a
circuit by `name`, `enterprise_circuit_id` and `carrier_circuit_number`; an address by
`address`, `item.name` and `group.name`; a purchase request by `reference`, a purchase
line by `request.reference`, `catalog.pid` and `catalog.model_name`; and a replacement
by `old.name`, `old.serial_number`, `new.name` and `new.serial_number`. The words stay
as typed in the box and in what the grid remembers, and each thing the grid does with
its rows, the count, Select all that match, Copy, Export, Bulk edit and Cover with a
contract, sends the same tree. The filter of a view of the items, on the summary, the
management report, the scoreboard, Geography, coverage and end of life, takes words as
the item list does: they stay as typed in the page's address and are sent as their tree,
and a link from such a view to the item list carries them. The filter boxes of the
renewals report and of circuit costs take the short form only, as before.

A form that changes a record keeps its buttons, Save and Undo, at the foot of the window
while the form is in the window and its own foot is below it, and a form opened by a
button New comes into the window with the keyboard in its first field (P-190). What a
field that searches finds is brought into the window as it comes, above those buttons.

A count written in a sentence has the separator of thousands, as "34,778 items" (P-195).

A page that cannot be drawn says so (P-230): "This page could not be drawn", with the
text of the fault in a box that is read and selected as any text, a button Copy the text,
and two ways on, Load again, which loads the page at its present address, and The first
page, at the prefix the page is served under. A fault in what is beneath the menu bar
leaves the menu bar where it is, and any move clears it, to another page or to the same
one again, as Items in the menu bar on the list of items, or Find an item; a fault in the
frame itself, the menu bar or what stands with it, stands over the whole page, and Back or
Forward clears it. A part of the web page that cannot be fetched, the file of one of its
pages, says the same, and that a new version may have been installed since the page was
loaded; it is fetched again the next time the page is opened after a move, once for each
opening, so that a file put back is drawn without loading the page again. The fault is written to the browser's console and sent nowhere. The text of the
fault holds what was thrown, the address of the page, the version of the web page, the
time, and where in the page it happened. Before its script runs the page holds words:
the product's name, written into it by the server as it writes the tab's title, and
Loading…; after six seconds, and at once where the stylesheet did not arrive either, "If
the page stays like this, load the page again."

A page older than the server says that a new version is installed (P-231). The page
knows the version it was built as, that of `web/package.json`. It asks `GET /about`, as
the person signed in, on coming back to its tab, at a change of page where it last asked
more than five minutes before (or was loaded then), and when a page could not be drawn.
Where the version the server answers is another, a notice stands under the menu bar of
every page until the page is loaded again: that a new version of the product has been
installed, the two versions, and a button, Load again. It is no dialog, takes no focus
and is announced politely; the page never loads again by itself, so that what is typed
into a form is not lost. A request that fails, or an answer without a version, says
nothing, and nothing is asked while nobody is signed in.

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
