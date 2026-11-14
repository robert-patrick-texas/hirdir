// The tables that the server pages and that are no grid: for each, the field of the
// route's `sort` behind each column of the table, by the name the column has on its
// page. A column that is not here is one the server does not sort by: the page composes
// its cell from a list, and its header sorts only while the table holds every row.

import type { SortFields } from "./sort";

/** `GET /users`. Kind is whether it is a service account, State whether it is disabled. */
export const USERS_SORT: SortFields = {
  username: "username",
  display_name: "display_name",
  role: "role",
  groups: "groups",
  kind: "is_service_account",
  state: "disabled",
  last_sign_in: "last_sign_in_at",
};

/** `GET /audit-events`. A record is sorted by its type and then by its HID, as it is shown. */
export const AUDIT_SORT: SortFields = {
  time: "at",
  who: "actor_name",
  via: "via",
  action: "action",
  record_type: "record_type,record_hid",
};

/** `GET /imports`: the previews of imports and of bulk edits. */
export const IMPORTS_SORT: SortFields = {
  made: "created_at",
  file: "file_name",
  records: "entity",
  mode: "mode",
  status: "status",
  rows: "row_count",
  by: "created_by_name",
};

/** `GET /imports/{hid}/rows`: the rows of one preview. */
export const PREVIEW_ROWS_SORT: SortFields = {
  row: "row",
  record: "key",
  outcome: "outcome",
};

/** `GET /reports/duplicates`. */
export const DUPLICATES_SORT: SortFields = {
  address: "address",
  network: "network",
  count: "count",
  holders: "holders",
};

/** `GET /device-groups/{hid}/members`. */
export const MEMBERS_SORT: SortFields = {
  position: "position",
  item: "item.name",
  pid: "item.pid",
  serial_number: "item.serial_number",
  role: "role",
  seen: "observed_master",
  joined_on: "joined_on",
  left_on: "left_on",
};

/** `GET /items/{hid}/children`: the minor items directly in one item. */
export const CHILDREN_SORT: SortFields = {
  position: "position",
  name: "name",
  pid: "catalog.pid",
  serial: "serial_number",
  state: "effective.lifecycle_state",
  owner: "owner.label",
  location: "location.name",
  minor: "minor_items",
};

/** `GET /items/{hid}/history`: sorted by its events, the changes of one staying together. */
export const HISTORY_SORT: SortFields = {
  at: "at",
  actor_name: "actor_name",
  action: "action",
};
