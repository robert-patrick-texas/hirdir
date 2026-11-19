// 0.9.8: the fields of an item's form for what it runs on (P-250). Host is one field that
// searches by name, as a member is searched for (P-221): the items that may host and the
// stacks and clusters together, each said to be which. What the form holds is
// `item:<hid>` or `group:<hid>`, which the form sends as `host_item_hid` or
// `host_group_hid`. What it was seen on is an item, searched for in the same way.

import { api } from "../api";
import { all, type FilterNode } from "../lib/filter";
import { itemName } from "../lib/format";
import { queryBody } from "../lib/gridQuery";
import {
  HOSTING_GROUPS,
  hostGroupOption,
  hostItemOption,
  hostItemSearch,
  sawHosts,
} from "../lib/hosting";
import { itemSearch, PICK_LIMIT, pickLabel } from "../lib/pick";
import { type Found, PickField, type PickFieldProps } from "./PickField";

async function findItems(filter: FilterNode | null, signal: AbortSignal) {
  if (filter === null) return null;
  return api.request("post", "/api/v1/items/query", {
    body: queryBody({
      filter,
      sort: ["name"],
      limit: PICK_LIMIT,
      offset: 0,
      include_archived: false,
      include_drafts: true,
    }),
    signal,
  });
}

/** The items that may host and the stacks and clusters whose name holds what was typed. */
async function findHosts(
  typed: string,
  signal: AbortSignal,
  exclude: readonly string[],
): Promise<Found | null> {
  const value = typed.trim().slice(0, 200);
  const items = hostItemSearch(itemSearch(value));
  if (items === null) return null;
  const groups: FilterNode | null = all(
    { field: "type", op: "in", value: [...HOSTING_GROUPS] },
    { field: "name", op: "contains", value },
  );
  const [itemPage, groupPage] = await Promise.all([
    findItems(items, signal),
    api.request("post", "/api/v1/device-groups/query", {
      body: {
        ...queryBody({
          filter: groups,
          sort: ["name"],
          limit: PICK_LIMIT,
          offset: 0,
          include_archived: false,
          include_drafts: true,
        }),
        fields: ["name", "type", "record_status"],
      },
      signal,
    }),
  ]);
  // 0.9.8: the stack of a member found by its own name is offered beside it (P-252).
  const named = new Set(groupPage.items.map((group) => group.hid));
  const stacks: Array<{ hid: string; name: string; type: string }> = [];
  for (const item of itemPage?.items ?? []) {
    for (const group of item.groups) {
      if (group.type !== "stack" || named.has(group.group_hid)) continue;
      named.add(group.group_hid);
      stacks.push({ hid: group.group_hid, name: group.name, type: group.type });
    }
  }
  sawHosts([
    ...groupPage.items.map((group) => ({ value: `group:${group.hid}`, name: group.name })),
    ...stacks.map((group) => ({ value: `group:${group.hid}`, name: group.name })),
    ...(itemPage?.items ?? []).map((item) => ({ value: `item:${item.hid}`, name: itemName(item) })),
  ]);
  const options = [
    ...groupPage.items.map((group) => ({
      ...hostGroupOption(group),
      draft: group.record_status === "draft",
    })),
    ...stacks.map((group) => hostGroupOption(group)),
    ...(itemPage?.items ?? [])
      .filter((item) => !exclude.includes(item.hid))
      .map((item) => ({ ...hostItemOption(item), draft: item.record_status === "draft" })),
  ].sort((one, other) => one.label.localeCompare(other.label));
  // Those of both lists that match, the first few of them by name.
  return { options: options.slice(0, PICK_LIMIT), total: groupPage.total + (itemPage?.total ?? 0) };
}

/** Host: an item, a stack or a cluster, searched for by name. */
export function HostField(props: PickFieldProps & { exclude?: readonly string[] }) {
  const { exclude = [], ...field } = props;
  return (
    <PickField
      {...field}
      noun={["host", "hosts"]}
      how="To choose one, type a part of its name: a server, a switch, a virtual machine, or a stack or a cluster."
      find={(typed, signal) => findHosts(typed, signal, exclude)}
    />
  );
}

/** The items whose name, serial number or asset tag holds what was typed. */
async function findAnyItem(
  typed: string,
  signal: AbortSignal,
  exclude: readonly string[],
): Promise<Found | null> {
  const page = await findItems(itemSearch(typed), signal);
  if (page === null) return null;
  return {
    options: page.items
      .filter((item) => !exclude.includes(item.hid))
      .map((item) => ({
        value: item.hid,
        label: pickLabel(item),
        draft: item.record_status === "draft",
      })),
    total: page.total,
  };
}

/** An item, searched for by its name, serial number or asset tag. */
export function ItemField(props: PickFieldProps & { exclude?: readonly string[] }) {
  const { exclude = [], ...field } = props;
  return (
    <PickField
      {...field}
      noun={["item", "items"]}
      how="To choose one, type a part of its name, serial number or asset tag."
      find={(typed, signal) => findAnyItem(typed, signal, exclude)}
    />
  );
}
