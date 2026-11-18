// 0.9.6: what is looked for within a record that a page is about (P-208 to P-211).

import { all, type FilterNode } from "./filter";
import { locationSearch } from "./places";

/** A site a form offers, by path, and marked where it is a draft (P-208). */
export function siteOption(site: { hid: string; path: string; record_status: string }): {
  value: string;
  label: string;
} {
  return {
    value: site.hid,
    label: site.record_status === "draft" ? `${site.path} (draft)` : site.path,
  };
}

// The most lines one address of the item list names (P-208): a HID is 36 characters,
// and 100 of them keep the address under 4,000, well within what a server takes.
export const LINES_IN_ONE_PATH = 100;

/** One address of the items that arrived on lines of a request: lines `from` to `to`. */
export interface BroughtPath {
  path: string;
  from: number;
  to: number;
}

/**
 * The item list filtered to the items that arrived on the lines of a request (P-208):
 * the lines on which something was received, by their HIDs. A request of more lines
 * than one address may name is given in parts, each of at most `most` lines, in the
 * order of the lines. No line received on is no address.
 */
export function broughtPaths(
  lines: ReadonlyArray<{ hid: string; line: number; received_quantity: number }>,
  most: number = LINES_IN_ONE_PATH,
): BroughtPath[] {
  const received = lines
    .filter((line) => line.received_quantity > 0)
    .sort((one, other) => one.line - other.line);
  const paths: BroughtPath[] = [];
  for (let start = 0; start < received.length; start += Math.max(1, most)) {
    const part = received.slice(start, start + Math.max(1, most));
    const first = part[0];
    const last = part[part.length - 1];
    if (!first || !last) continue;
    const filter =
      part.length === 1
        ? `purchase_line_hid:eq:${first.hid}`
        : `purchase_line_hid:in:${part.map((line) => line.hid).join(",")}`;
    paths.push({
      path: `/items?filter=${encodeURIComponent(filter)}&minor=1`,
      from: first.line,
      to: last.line,
    });
  }
  return paths;
}

/**
 * The filter of a search for a location, within a site where one is given (P-209): the
 * words typed, as `locationSearch` has them, and the site. Within a site, blank text is
 * its locations; elsewhere it is no search, and null.
 */
export function locationsWithin(typed: string, site?: string): FilterNode | null {
  const inSite: FilterNode | null = site ? { field: "site_hid", op: "eq", value: site } : null;
  return all(inSite, locationSearch(typed));
}
