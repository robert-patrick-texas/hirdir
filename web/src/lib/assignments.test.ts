// What an operator is on, as the server answers it, turned into the boxes of a tree
// (P-177). The answer has the shape of `GET /operators/{hid}/assignments`; every name in
// it is invented.

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";
import { BoxTree } from "../components/BoxTree";
import {
  type Assignments,
  assignmentColumns,
  groupNodes,
  type ItemCount,
  ownNodes,
  pathBeneath,
  placeNodes,
  totalCount,
} from "./assignments";

const OP = "0193a1f4-0000-7000-8000-0000000000f1";
const SITE = "0193a1f4-0000-7000-8000-00000000c001";
const ROOM = "0193a1f4-0000-7000-8000-00000000c002";
const STACK = "0193a1f4-0000-7000-8000-00000000d001";
const INNER = "0193a1f4-0000-7000-8000-00000000d002";

function count(value: number, source: string, hid: string | null = null): ItemCount {
  return {
    count: value,
    filter: {
      and: [
        { field: "effective.operator_hid", op: "eq", value: OP },
        { field: "effective.operator_hid.source", op: "eq", value: source },
        ...(hid ? [{ field: "effective.operator_hid.source_hid", op: "eq", value: hid }] : []),
      ],
    },
  };
}

const answer: Assignments = {
  operator_hid: OP,
  places: [
    {
      hid: SITE,
      level: "site",
      path: "Americas > Central > Site-2",
      items: count(6, "site", SITE),
      places_beneath: {
        count: 23,
        more: 3,
        shown: [{ hid: ROOM, level: "location", path: "Americas > Central > Site-2 > Room 102" }],
      },
      exceptions: count(2, "own"),
    },
  ],
  groups: [
    {
      hid: STACK,
      name: "core-stack",
      type: "stack",
      items: count(4, "device_group", STACK),
      groups_beneath: { count: 1, more: 0, shown: [{ hid: INNER, name: "inner", type: "custom" }] },
      exceptions: count(0, "own"),
    },
  ],
  own: count(1, "own"),
  from_item: count(3, "parent_item"),
  totals: count(14, "any"),
};

/** The filter a link leads to, read back from its path. */
function filterOf(href: string | null | undefined): unknown {
  const address = new URL(href ?? "", "http://example.invalid/");
  expect(address.pathname).toBe("/items");
  expect(address.searchParams.get("minor")).toBe("1");
  const text = address.searchParams.get("filter") ?? "";
  return text.startsWith("{") ? JSON.parse(text) : text;
}

describe("the places given an operator, as boxes", () => {
  const [site] = placeNodes(answer);

  it("are named by their path and lead to their page", () => {
    expect(site?.title).toBe("Americas > Central > Site-2");
    expect(site?.kind).toBe("site");
    expect(site?.href).toContain(SITE);
  });

  it("count the items that have it from there, each count a link to exactly those items", () => {
    const items = site?.counts.find((one) => one.key === "items");
    expect(items?.value).toBe(6);
    expect(items?.label).toBe("items have it from here");
    const filter = filterOf(items?.href);
    expect(JSON.stringify(filter)).toContain("effective.operator_hid.source_hid");
    expect(JSON.stringify(filter)).toContain(SITE);
  });

  it("say how many places beneath have it, and name those the server sent", () => {
    expect(site?.counts.find((one) => one.key === "places_beneath")?.value).toBe(23);
    expect(site?.beneath?.map((below) => below.title)).toEqual(["Room 102"]);
    expect(site?.more).toEqual({ count: 3, noun: "places, under Geography", href: site?.href });
  });

  it("mark what beneath is someone else's", () => {
    expect(site?.exceptions?.value).toBe(2);
    expect(site?.exceptions?.label).toBe("items beneath have another operator");
  });
});

describe("the groups given an operator, as boxes", () => {
  const [stack] = groupNodes(answer);

  it("say their type and lead to their page and to their items", () => {
    expect(stack?.title).toBe("core-stack");
    expect(stack?.kind).toBe("stack");
    expect(stack?.href).toBe(`/groups/${STACK}`);
    expect(stack?.counts[0]?.label).toBe("items have it from it");
    expect(stack?.counts[1]?.label).toBe("nested group has it");
    expect(stack?.beneath?.[0]?.href).toBe(`/groups/${INNER}`);
    expect(stack?.more).toBeNull();
  });
});

describe("the items given an operator, and the totals", () => {
  it("are a box for its own items and one for the minor items that have it from them", () => {
    const [own, fromItem] = ownNodes(answer);
    expect(own?.counts[0]?.value).toBe(1);
    expect(own?.counts[0]?.label).toBe("item");
    expect(fromItem?.counts[0]?.value).toBe(3);
  });

  it("count every item it is in force for at the top", () => {
    const total = totalCount(answer);
    expect(total.value).toBe(14);
    expect(total.label).toBe("items in force");
  });

  it("keep the drafts and the archived of the view in every link", () => {
    const total = totalCount(answer, { includeDrafts: true, includeArchived: true });
    const address = new URL(total.href ?? "", "http://example.invalid/");
    expect(address.searchParams.get("drafts")).toBe("1");
    expect(address.searchParams.get("archived")).toBe("1");
  });
});

describe("a path beneath another", () => {
  it("is what follows the path above, or the whole of it", () => {
    expect(pathBeneath("Americas > Site-2 > Room 1", "Americas > Site-2")).toBe("Room 1");
    expect(pathBeneath("Europe > Site-9", "Americas > Site-2")).toBe("Europe > Site-9");
    expect(pathBeneath("Americas > Site-2", "Americas > Site-2")).toBe("Americas > Site-2");
  });
});

describe("the tree of what an operator is on", () => {
  const markup = renderToStaticMarkup(
    createElement(
      MemoryRouter,
      null,
      createElement(BoxTree, {
        label: "What Op2 is on",
        root: { key: OP, title: "Op2", counts: [totalCount(answer)] },
        columns: assignmentColumns(answer),
      }),
    ),
  );

  it("has a column each for its places, its groups and its own items", () => {
    const heads = [...markup.matchAll(/<h3 class="tree-head">([^<]+)<\/h3>/g)].map((m) => m[1]);
    expect(heads).toEqual(["Places given it", "Groups given it", "Items given it"]);
  });

  it("marks the site with exceptions, and not the stack with none", () => {
    expect(markup.match(/data-testid="tree-exceptions"/g) ?? []).toHaveLength(1);
  });

  it("makes every count of items a link", () => {
    const links = markup.match(/<a href="\/items\?/g) ?? [];
    // The total, the site's items and its exceptions, the stack's items (it has no exceptions,
    // which are then not shown), the own items and those from the item they are in.
    expect(links).toHaveLength(6);
  });
});
