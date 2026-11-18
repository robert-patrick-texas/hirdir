// 0.9.6 (P-216): what the line under the heading of a minor item says, and where its
// link to the spares of its model leads. Nothing is worked out here but the words and
// the filter: the site is the one the server resolves for the item, from the item it
// is in where it has no location of its own.

import { itemsPath } from "./filter";

/** What of an item the line reads: its model, its position, the item it is in, its site. */
export interface MinorOf {
  catalog_entry_hid: string | null;
  catalog: { pid: string; model_name: string | null; type: string | null } | null;
  position: string | null;
  parent: { hid: string } | null;
  effective: { location_hid: { site: string | null; site_hid: string | null } };
}

/** Its type and model, as the line begins: "Power supply · EX-PSU-650, Example 650 W". */
export function minorWhat(item: Pick<MinorOf, "catalog">, typeLabel: string): string {
  const catalog = item.catalog;
  if (!catalog) return "";
  const model = catalog.model_name ? `${catalog.pid}, ${catalog.model_name}` : catalog.pid;
  return [typeLabel, model].filter(Boolean).join(" · ");
}

/**
 * The item list of the spares of an item's model at its site: the items of that catalog
 * entry at that site whose disposition in force is Spare, minor items among them. Null
 * for an item with no model or no site, which has no such list.
 */
export function sparesPath(item: Pick<MinorOf, "catalog_entry_hid" | "effective">): string | null {
  const site = item.effective.location_hid.site_hid;
  if (!item.catalog_entry_hid || !site) return null;
  return itemsPath(
    `catalog_entry_hid:eq:${item.catalog_entry_hid} site_hid:eq:${site} effective.disposition:eq:Spare`,
  );
}
