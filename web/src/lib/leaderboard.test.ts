// The leaderboard of 0.9.4 (P-178, P-180): the operators with how their items have them,
// the device groups with what is under them, and the rows of the summary by group and by
// model. Every name and number here is invented.

import { describe, expect, it } from "vitest";
import { ranking } from "./rank";
import {
  groupCondition,
  groupsCsv,
  operatorsCsv,
  type ScoreRow,
  SPLIT,
  scoreColumns,
  scoreCounts,
  splitPath,
} from "./scoreboard";
import { sortRows } from "./sort";
import { rowDetail, rowLabel, rowRecordPath } from "./summary";

const OP = "0193a1f4-0000-7000-8000-0000000000f1";
const CORE = "0193a1f4-0000-7000-8000-00000000d001";
const EDGE = "0193a1f4-0000-7000-8000-00000000d002";
const MODEL = "0193a1f4-0000-7000-8000-00000000c001";

function row(key: string | null, items: number, more: Partial<ScoreRow> = {}): ScoreRow {
  return {
    key,
    label: key === null ? null : `row ${key.slice(-4)}`,
    items,
    component_count: items,
    managed_node_count: items,
    support_weight: `${items}.00`,
    by_health: { good: items, degraded: 0, failed: 0, unknown: 0 },
    operators: null,
    ...more,
  };
}

describe("how the items of an operator have it", () => {
  const operator = row(OP, 10, {
    own: 2,
    from_item: 1,
    from_group: 4,
    from_place: 3,
    groups_given: 1,
    places_given: 2,
  });
  const nobody = row(null, 5);

  it("are four counts that add up to its items, then the groups and places given it", () => {
    expect(SPLIT.map((part) => part.column)).toEqual([
      "own",
      "from_item",
      "from_group",
      "from_place",
      "groups_given",
      "places_given",
    ]);
    const parts = SPLIT.slice(0, 4).map((part) => part.value(operator) ?? 0);
    expect(parts.reduce((sum, part) => sum + part, 0)).toBe(operator.items);
  });

  it("are written blank for the row of what nobody is assigned to, which has none", () => {
    const counts = scoreCounts("15.00");
    expect(counts.own?.text(operator)).toBe("2");
    expect(counts.own?.text(nobody)).toBe("");
    expect(counts.own?.value(nobody)).toBeNull();
  });

  it("rank and sort the operators, the blank row with none", () => {
    const other = row(OP.replace("f1", "f2"), 8, { own: 5, from_group: 1 });
    const table = ranking(
      [operator, other, nobody],
      { column: "own", descending: true },
      scoreCounts("23.00"),
      {
        fallback: "weight",
        blank: (one) => one.key === null,
      },
    );
    expect(table.column).toBe("own");
    expect(table.rank(other)).toBe(1);
    expect(table.rank(operator)).toBe(2);
    expect(table.rank(nobody)).toBeNull();
    expect(table.share("own", operator)).toBeCloseTo(0.4);
    const sorted = sortRows([operator, nobody, other], scoreColumns("Nobody"), {
      column: "from_group",
      descending: true,
    });
    expect(sorted.map((one) => one.key)).toEqual([OP, other.key, null]);
  });

  it("lead to exactly their items, with the view's filter, and the groups given it to the groups", () => {
    const view = { filter: "tags:has:refresh-2030", includeArchived: false, includeDrafts: true };
    const where = (column: string) => {
      const path = splitPath(view, OP, column);
      if (path === null) return null;
      const address = new URL(path, "http://example.invalid/");
      return { address, filter: address.searchParams.get("filter") ?? "" };
    };
    const own = where("own");
    expect(own?.address.pathname).toBe("/items");
    expect(own?.address.searchParams.get("minor")).toBe("1");
    expect(own?.address.searchParams.get("drafts")).toBe("1");
    expect(own?.filter).toContain("tags");
    expect(own?.filter).toContain(`effective.operator_hid`);
    expect(own?.filter).toContain("own");
    expect(where("from_item")?.filter).toContain("parent_item");
    expect(where("from_group")?.filter).toContain("device_group");
    const place = where("from_place")?.filter ?? "";
    for (const level of ["location", "site", "region"]) expect(place).toContain(level);
    expect(splitPath(view, OP, "groups_given")).toBe(
      `/groups?filter=${encodeURIComponent(`operator_hid:eq:${OP}`)}`,
    );
    expect(splitPath(view, OP, "places_given")).toBeNull();
    expect(splitPath(view, null, "own")).toBeNull();
    expect(splitPath({ ...view, filter: "not a filter" }, OP, "own")).toBeNull();
  });

  it("follow the health in the file of the operators", () => {
    const lines = operatorsCsv([operator], "10.00").trimEnd().split("\r\n");
    expect(lines[0]).toMatch(
      /,unknown,own,from_item,from_group,from_place,groups_given,places_given$/,
    );
    expect(lines[1]).toMatch(/,10,0,0,0,2,1,4,3,1,2$/);
  });
});

describe("the device groups", () => {
  const core = row(CORE, 12, { type: "stack", member_count: 4, nested_groups: 0 });
  const edge = row(EDGE, 30, { type: "controller_domain", member_count: 2, nested_groups: 3 });
  const none = row(null, 7);

  it("lead each count to the items under the group at any depth, and the blank row to those under none", () => {
    expect(groupCondition(CORE)).toBe(`group:within:${CORE}`);
    expect(groupCondition(null)).toBe("group:empty:true");
  });

  it("are sorted and ranked by their members and their nested groups too", () => {
    const columns = scoreColumns("In no group");
    expect(
      sortRows([core, edge, none], columns, { column: "members", descending: true }).map(
        (one) => one.key,
      ),
    ).toEqual([CORE, EDGE, null]);
    const table = ranking(
      [core, edge, none],
      { column: "nested", descending: true },
      scoreCounts("49.00"),
      {
        fallback: "weight",
        blank: (one) => one.key === null,
      },
    );
    expect(table.rank(edge)).toBe(1);
    expect(table.rank(core)).toBe(2);
    expect(table.text("members", core)).toBe("4");
    expect(table.text("members", none)).toBe("");
  });

  it("are written to a file in the order of the table, with their type, members and nested groups", () => {
    const lines = groupsCsv([edge, core, none]).trimEnd().split("\r\n");
    expect(lines[0]).toBe(
      "group_hid,group,type,members,nested_groups,items,components,managed_nodes,support_weight,good,degraded,failed,unknown,operators: components (support weight)",
    );
    expect(lines[1]).toBe(`${EDGE},row d002,controller_domain,2,3,30,30,30,30.00,30,0,0,0,`);
    expect(lines[3]).toBe(",,,,,7,7,7,7.00,7,0,0,0,");
  });
});

describe("a row of the summary by group and by model", () => {
  it("says what a group is beneath its name, and leads to its page", () => {
    const core = row(CORE, 12, { type: "stack", member_count: 4, nested_groups: 2 });
    expect(rowDetail("group", core)).toBe("Stack · 4 members · 2 nested groups");
    expect(rowDetail("group", { ...core, nested_groups: 0, member_count: 1 })).toBe(
      "Stack · 1 member",
    );
    expect(rowRecordPath("group", CORE)).toBe(`/groups/${CORE}`);
    expect(rowLabel("group", { key: null, label: null })).toBe("In no group");
  });

  it("says what a model is beneath its vendor and PID, and leads to its catalog entry", () => {
    const model = row(MODEL, 3, {
      label: "Example Networks EN-4800",
      vendor: "Example Networks",
      pid: "EN-4800",
      model_name: "Example 48-port switch",
      kind: "hardware",
      type: "switch",
    });
    expect(rowLabel("model", model)).toBe("Example Networks EN-4800");
    expect(rowDetail("model", model)).toBe("Example 48-port switch · Hardware · switch");
    expect(rowRecordPath("model", MODEL)).toBe(`/catalog/${MODEL}`);
    expect(rowLabel("model", { key: null, label: null })).toBe("No model");
  });

  it("says nothing more of the blank row, nor of a row by anything else", () => {
    expect(rowDetail("group", row(null, 2))).toBeNull();
    expect(rowDetail("site", row(CORE, 2, { type: "stack" }))).toBeNull();
    expect(rowRecordPath("site", CORE)).toBeNull();
    expect(rowRecordPath("group", null)).toBeNull();
  });
});
