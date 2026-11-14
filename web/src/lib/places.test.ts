import { describe, expect, it } from "vitest";
import type { Schemas } from "../api/client";
import {
  above,
  addressLines,
  addressOf,
  contactLine,
  countRows,
  DEEPEST_DRAWN,
  drawnDepth,
  findNode,
  fromAbove,
  isLevel,
  itemsWithin,
  levelLabel,
  locationSearch,
  locationsToMoveTo,
  nameOf,
  noContactText,
  ownRoles,
  pathAbove,
  placePath,
  regionsToMoveTo,
  sourceText,
  type TreeNode,
  treeQuery,
  treeRows,
} from "./places";

const AMERICAS = "0193a1f4-0000-7000-8000-0000000000a1";
const CENTRAL = "0193a1f4-0000-7000-8000-0000000000a2";
const SITE = "0193a1f4-0000-7000-8000-0000000000a3";
const BUILDING = "0193a1f4-0000-7000-8000-0000000000a4";
const ROOM = "0193a1f4-0000-7000-8000-0000000000a5";
const EAST = "0193a1f4-0000-7000-8000-0000000000a6";

function node(
  level: TreeNode["level"],
  hid: string,
  path: string,
  items: number,
  children: TreeNode[] = [],
): TreeNode {
  return {
    level,
    hid,
    name: path.split(" > ").at(-1) ?? "",
    code: null,
    kind: null,
    path,
    record_status: "active",
    items,
    component_count: items,
    children,
  };
}

/** Americas, with Central and its site opened to the room, and East with nothing in it. */
const TREE: TreeNode[] = [
  node("region", AMERICAS, "Americas", 4, [
    node("region", CENTRAL, "Americas > Central", 4, [
      node("site", SITE, "Americas > Central > Site-2", 4, [
        node("location", BUILDING, "Americas > Central > Site-2 > Building 1", 4, [
          node("location", ROOM, "Americas > Central > Site-2 > Building 1 > Room 102", 3),
        ]),
      ]),
    ]),
    node("region", EAST, "Americas > East", 0),
  ]),
];

describe("levels and paths", () => {
  it("knows the three levels by name", () => {
    expect(isLevel("region")).toBe(true);
    expect(isLevel("location")).toBe(true);
    expect(isLevel("rack")).toBe(false);
    expect(isLevel(undefined)).toBe(false);
    expect(levelLabel("site")).toBe("Site");
    expect(levelLabel("rack")).toBe("rack");
  });

  it("names the page of a place and the grid of the items within it", () => {
    expect(placePath("site", SITE)).toBe(`/geography/site/${SITE}`);
    expect(itemsWithin(ROOM)).toBe(
      `/items?filter=${encodeURIComponent(`location:within:${ROOM}`)}&minor=1`,
    );
  });

  it("reads the name of a place off its path, and the path of what it is in", () => {
    expect(nameOf("Americas > Central > Site-2 > Building 1 > Room 102")).toBe("Room 102");
    expect(nameOf("Americas")).toBe("Americas");
    expect(nameOf(null)).toBe("");
    expect(pathAbove("Americas > Central > Site-2")).toBe("Americas > Central");
    expect(pathAbove("Americas")).toBe("");
  });
});

describe("locationSearch", () => {
  const fields = ["name", "parent.name", "site.name", "code", "site.code"];

  it("asks for nothing when nothing is typed", () => {
    expect(locationSearch("")).toBeNull();
    expect(locationSearch("  >  ")).toBeNull();
  });

  it("looks for one word in the names and codes the list of locations is filtered by", () => {
    expect(locationSearch("102")).toEqual({
      or: fields.map((field) => ({ field, op: "contains", value: "102" })),
    });
  });

  it("wants every word found, and reads the separator of a path as a space", () => {
    const found = locationSearch("Site-2 > Building  102");
    expect(found).toEqual({
      and: ["Site-2", "Building", "102"].map((value) => ({
        or: fields.map((field) => ({ field, op: "contains", value })),
      })),
    });
  });

  it("sends no more words than a filter may hold conditions for", () => {
    const found = locationSearch("a b c d e f g h i j k l");
    expect(found && "and" in found ? found.and : []).toHaveLength(8);
  });
});

describe("treeQuery", () => {
  const view = { filter: "", includeArchived: false, includeDrafts: false };

  it("asks for the regions and sites first, and leaves out what is blank or off", () => {
    expect(treeQuery(view, { locations: false })).toEqual({ locations: false });
    expect(treeQuery(view)).toEqual({});
  });

  it("asks for the inside of one site with that site as the root, in the same view", () => {
    const narrowed = {
      filter: " tags:has:refresh-2030 ",
      includeArchived: true,
      includeDrafts: true,
    };
    expect(treeQuery(narrowed, { root: SITE })).toEqual({
      filter: "tags:has:refresh-2030",
      root: SITE,
      include_archived: true,
      include_drafts: true,
    });
  });
});

describe("treeRows", () => {
  it("lists each place before what is in it, with how far in it stands", () => {
    const rows = treeRows(TREE);
    expect(rows.map((row) => [row.node.name, row.depth])).toEqual([
      ["Americas", 0],
      ["Central", 1],
      ["Site-2", 2],
      ["Building 1", 3],
      ["Room 102", 4],
      ["East", 1],
    ]);
    expect(rows[0]?.hasChildren).toBe(true);
    expect(rows.at(-1)?.hasChildren).toBe(false);
  });

  it("leaves out what is in a place that is closed, and keeps the place", () => {
    const rows = treeRows(TREE, new Set([CENTRAL]));
    expect(rows.map((row) => row.node.name)).toEqual(["Americas", "Central", "East"]);
    expect(rows[1]?.open).toBe(false);
    expect(treeRows(TREE, new Set([AMERICAS])).map((row) => row.node.name)).toEqual(["Americas"]);
  });

  it("starts deeper for the inside of a site", () => {
    const site = findNode(TREE, SITE);
    expect(treeRows(site?.children ?? [], new Set(), 3).map((row) => row.depth)).toEqual([3, 4]);
  });

  it("draws no row further in than the page has room for", () => {
    expect(drawnDepth(3)).toBe(3);
    expect(drawnDepth(40)).toBe(DEEPEST_DRAWN);
    expect(drawnDepth(-1)).toBe(0);
  });
});

describe("finding a place in a tree", () => {
  it("finds a node by its HID, at any depth", () => {
    expect(findNode(TREE, ROOM)?.name).toBe("Room 102");
    expect(findNode(TREE, "no-such")).toBeNull();
  });

  it("names the places a place is in, outermost first", () => {
    expect(above(TREE, ROOM)).toEqual([AMERICAS, CENTRAL, SITE, BUILDING]);
    expect(above(TREE, AMERICAS)).toEqual([]);
    expect(above(TREE, "no-such")).toBeNull();
  });
});

describe("countRows", () => {
  const counts = (items: number) => ({ items, component_count: items });

  it("shows the items that are nowhere and the whole view, so that the numbers add up", () => {
    const rows = countRows({ unplaced: counts(1), hidden: counts(0), totals: counts(5) });
    expect(rows.map((row) => [row.key, row.count.items])).toEqual([
      ["unplaced", 1],
      ["totals", 5],
    ]);
  });

  it("shows the items in places the view leaves out when there are any", () => {
    const rows = countRows({ unplaced: counts(0), hidden: counts(2), totals: counts(6) });
    expect(rows.map((row) => row.key)).toEqual(["unplaced", "hidden", "totals"]);
    // The row of the items that are nowhere is always there, also at nought.
    expect(rows[0]?.count.items).toBe(0);
  });
});

describe("where what is in force came from", () => {
  it("tells what a place has itself from what it has from above", () => {
    expect(fromAbove("own")).toBe(false);
    expect(fromAbove("none")).toBe(false);
    expect(fromAbove("location")).toBe(true);
    expect(fromAbove("site")).toBe(true);
    expect(fromAbove("region")).toBe(true);
  });

  it("names the level and the path of the place it came from", () => {
    expect(sourceText("own", "Americas")).toBe("Set here");
    expect(sourceText("none", null)).toBe("Not set");
    expect(sourceText("region", "Americas")).toBe("From the region Americas");
    expect(sourceText("site", "Americas > Central > Site-2")).toBe(
      "From the site Americas > Central > Site-2",
    );
    expect(sourceText("location", null)).toBe("From the location");
  });

  it("says of a role nobody is in whether a level stopped the looking further up", () => {
    expect(noContactText({ source: "none", source_path: null, stopped: false })).toBe("Nobody");
    expect(noContactText({ source: "own", source_path: "Americas", stopped: true })).toBe(
      "None here, and nothing further up is looked at",
    );
    expect(
      noContactText({
        source: "location",
        source_path: "Americas > Central > Site-2 > Building 2",
        stopped: true,
      }),
    ).toBe(
      "None: the location Americas > Central > Site-2 > Building 2 says so, and nothing further up is looked at",
    );
  });
});

describe("addresses", () => {
  const address = {
    address1: "100 Example Way",
    address2: null,
    city: "Springfield",
    state: "IL",
    postal_code: "00000",
    country: "US",
  };

  it("writes an address as lines, leaving out what is blank", () => {
    expect(addressLines(address)).toEqual(["100 Example Way", "Springfield, IL 00000", "US"]);
    expect(addressLines({ ...address, state: null, postal_code: null })).toEqual([
      "100 Example Way",
      "Springfield",
      "US",
    ]);
    expect(addressLines(null)).toEqual([]);
    expect(addressLines({})).toEqual([]);
  });

  it("reads the street address and the shipping address of a place apart", () => {
    const place = {
      address1: "1 Example Plaza",
      city: "Springfield",
      ship_address1: "100 Example Way",
      ship_city: "",
      ship_country: "US",
    };
    expect(addressLines(addressOf(place))).toEqual(["1 Example Plaza", "Springfield"]);
    expect(addressLines(addressOf(place, "ship_"))).toEqual(["100 Example Way", "US"]);
  });
});

describe("ownRoles", () => {
  const role = (
    value: string,
    label: string,
    sort: number,
    active = true,
  ): Schemas["ChoiceOut"] => ({
    hid: `c-${value}`,
    list: "contact_role",
    value,
    label,
    sort,
    active,
    row_version: 1,
    created_at: "2026-01-31T19:05:09Z",
    updated_at: "2026-01-31T19:05:09Z",
  });
  const CHOICES = [
    role("shipping", "Shipping", 1),
    role("technical", "Technical", 2),
    role("legacy", "Legacy", 3, false),
    { ...role("room", "Room", 1), list: "location_kind" },
  ];
  const assignment = (
    hid: string,
    roleOf: string,
    priority: number,
    name: string | null,
  ): Schemas["AssignmentOut"] => ({
    hid,
    role: roleOf,
    priority,
    contact_hid: name ? `k-${hid}` : null,
    contact: name
      ? {
          hid: `k-${hid}`,
          name,
          organization: null,
          email: null,
          phone: null,
          record_status: "active",
        }
      : null,
    stop_inheritance: name === null,
    region_hid: AMERICAS,
    site_hid: null,
    location_hid: null,
    place: { hid: AMERICAS, level: "region", name: "Americas", path: "Americas" },
    row_version: 1,
    created_at: "2026-01-31T19:05:09Z",
    updated_at: "2026-01-31T19:05:09Z",
  });

  it("lists every active role, in the order of the list, also with nobody in it", () => {
    const roles = ownRoles([], CHOICES);
    expect(roles.map((one) => [one.role, one.label])).toEqual([
      ["shipping", "Shipping"],
      ["technical", "Technical"],
    ]);
    expect(roles.every((one) => one.assigned.length === 0 && one.stop === null)).toBe(true);
  });

  it("puts the contacts of a role in the order of their priority", () => {
    const roles = ownRoles(
      [
        assignment("a-1", "technical", 3, "Dana Whitfield"),
        assignment("a-2", "technical", 2, "Priya Raman"),
      ],
      CHOICES,
    );
    const technical = roles.find((one) => one.role === "technical");
    expect(technical?.assigned.map((one) => one.contact?.name)).toEqual([
      "Priya Raman",
      "Dana Whitfield",
    ]);
  });

  it("keeps the word that a place has none apart from its contacts", () => {
    const roles = ownRoles([assignment("a-3", "shipping", 1, null)], CHOICES);
    const shipping = roles.find((one) => one.role === "shipping");
    expect(shipping?.stop?.hid).toBe("a-3");
    expect(shipping?.assigned).toEqual([]);
  });

  it("still shows a role that is no longer active, or not in the list, while it is used", () => {
    const roles = ownRoles(
      [
        assignment("a-4", "legacy", 1, "Lee Okafor"),
        assignment("a-5", "facilities", 1, "Site-2 Receiving"),
      ],
      CHOICES,
    );
    expect(roles.map((one) => one.label)).toEqual([
      "Shipping",
      "Technical",
      "Legacy",
      "facilities",
    ]);
  });
});

describe("where a place may be moved to", () => {
  const regions = [
    { hid: AMERICAS, path: "Americas" },
    { hid: CENTRAL, path: "Americas > Central" },
    { hid: EAST, path: "Americas > East" },
    { hid: "r-4", path: "Americas > Central > Lakes" },
    { hid: "r-5", path: "Americas > Central Plains" },
  ];

  it("offers a region every region but itself and the ones within it", () => {
    const central = { hid: CENTRAL, path: "Americas > Central" };
    expect(regionsToMoveTo(regions, central).map((option) => option.label)).toEqual([
      "Americas",
      "Americas > East",
      // A region whose name only begins the same is not within it.
      "Americas > Central Plains",
    ]);
  });

  it("offers a location the other locations of its site, but not those within it", () => {
    const first = { hid: BUILDING, path: "Americas > Central > Site-2 > Building 1" };
    const locations = [
      first,
      { hid: ROOM, path: "Americas > Central > Site-2 > Building 1 > Room 102" },
      { hid: "l-3", path: "Americas > Central > Site-2 > Building 2" },
    ];
    expect(locationsToMoveTo(locations, first).map((option) => option.value)).toEqual(["l-3"]);
  });
});

describe("contactLine", () => {
  it("writes a contact on one line, leaving out what it does not have", () => {
    expect(
      contactLine({
        name: "Dana Whitfield",
        organization: null,
        email: "dana.whitfield@example.net",
        phone: "+1 555 0100",
      }),
    ).toBe("Dana Whitfield · dana.whitfield@example.net · +1 555 0100");
    expect(contactLine({ name: "", organization: null, email: null, phone: null })).toBe("");
  });
});
