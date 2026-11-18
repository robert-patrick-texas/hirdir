// 0.9.6: what is looked for within a record that a page is about (P-208 to P-211).

import { all, type FilterNode } from "./filter";
import { locationSearch } from "./places";

/**
 * The filter of a search for a location, within a site where one is given (P-209): the
 * words typed, as `locationSearch` has them, and the site. Within a site, blank text is
 * its locations; elsewhere it is no search, and null.
 */
export function locationsWithin(typed: string, site?: string): FilterNode | null {
  const inSite: FilterNode | null = site ? { field: "site_hid", op: "eq", value: site } : null;
  return all(inSite, locationSearch(typed));
}
