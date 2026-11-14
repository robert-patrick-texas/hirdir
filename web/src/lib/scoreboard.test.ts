import { describe, expect, it } from "vitest";
import {
  byLoad,
  fromHundredths,
  hundredths,
  involvedText,
  operatorCondition,
  operatorOfRow,
  operatorsCsv,
  type RowOperator,
  ranked,
  rowItemsPath,
  type ScoreRow,
  share,
  shareText,
  siteCondition,
  sitesCsv,
  toCsv,
  underOpenLabels,
} from "./scoreboard";

const OP1 = "0193a1f4-0000-7000-8000-0000000000f1";
const OP2 = "0193a1f4-0000-7000-8000-0000000000f2";
const OP3 = "0193a1f4-0000-7000-8000-0000000000f3";
const SITE = "0193a1f4-0000-7000-8000-0000000000f4";

function involved(
  hid: string | null,
  label: string | null,
  components: number,
  weight: string,
  open = false,
): RowOperator {
  return {
    hid,
    label,
    colour: hid ? "#1f6feb" : null,
    contact: hid && !open ? "Lee Marchetti" : null,
    is_open: open,
    items: components,
    component_count: components,
    support_weight: weight,
  };
}

function row(
  key: string | null,
  label: string | null,
  components: number,
  weight: string,
  operators: RowOperator[] | null = null,
): ScoreRow {
  return {
    key,
    label,
    items: components + 1,
    component_count: components,
    managed_node_count: components,
    support_weight: weight,
    by_health: { good: components, degraded: 0, failed: 0, unknown: 0 },
    operators,
  };
}

describe("support weight as hundredths", () => {
  it("reads a decimal exactly, with none, one or two places", () => {
    expect(hundredths("12.50")).toBe(1250);
    expect(hundredths("12.5")).toBe(1250);
    expect(hundredths("12")).toBe(1200);
    expect(hundredths("0.07")).toBe(7);
    // What a floating-point number would get wrong.
    expect(hundredths("0.1") + hundredths("0.2")).toBe(30);
    expect(hundredths("")).toBe(0);
    expect(hundredths(null)).toBe(0);
    expect(hundredths("a lot")).toBe(0);
  });

  it("writes it back with two places", () => {
    expect(fromHundredths(1250)).toBe("12.50");
    expect(fromHundredths(7)).toBe("0.07");
    expect(fromHundredths(0)).toBe("0.00");
    expect(fromHundredths(123456)).toBe("1234.56");
  });
});

describe("the order of a scoreboard", () => {
  const light = row(OP1, "NE1", 9, "2.00");
  const heavy = row(OP2, "NE2", 3, "10.50");
  const nobody = row(null, null, 2, "40.00");

  it("puts the most support weight first, whatever the counts", () => {
    expect([light, heavy].sort(byLoad).map((one) => one.label)).toEqual(["NE2", "NE1"]);
    // 10.50 is more than 9.75: compared as numbers, not as text.
    expect([row(OP1, "NE1", 1, "9.75"), heavy].sort(byLoad).map((one) => one.label)).toEqual([
      "NE2",
      "NE1",
    ]);
  });

  it("breaks a tie by components, then by items, then by name, so that it is steady", () => {
    const more = row(OP1, "NE1", 5, "3.00");
    const fewer = row(OP2, "NE2", 4, "3.00");
    expect([fewer, more].sort(byLoad).map((one) => one.label)).toEqual(["NE1", "NE2"]);
    const same = [row(OP3, "NE3", 4, "3.00"), row(OP2, "NE2", 4, "3.00")];
    expect(same.sort(byLoad).map((one) => one.label)).toEqual(["NE2", "NE3"]);
  });

  it("sets the blank row apart, however much it holds", () => {
    const board = ranked([nobody, light, heavy]);
    expect(board.rows.map((one) => one.label)).toEqual(["NE2", "NE1"]);
    expect(board.blank).toBe(nobody);
    expect(ranked([light]).blank).toBeNull();
    expect(ranked(undefined)).toEqual({ rows: [], blank: null });
  });
});

describe("a share of the view's support weight", () => {
  it("is exact to a hundredth of a per cent", () => {
    expect(share("10.50", "42.00")).toBe(2500);
    expect(share("42.00", "42.00")).toBe(10000);
    expect(share("0", "42.00")).toBe(0);
    // Nothing of nothing is no share.
    expect(share("0", "0")).toBe(0);
    expect(share("5.00", "0.00")).toBe(0);
  });

  it("is said as a per cent, with one place where it has one", () => {
    expect(shareText("10.50", "42.00")).toBe("25%");
    expect(shareText("1.00", "3.00")).toBe("33.3%");
    expect(shareText("42.00", "42.00")).toBe("100%");
    expect(shareText("0", "42.00")).toBe("0%");
    expect(shareText("0.01", "500.00")).toBe("under 0.1%");
    expect(shareText("0", "0")).toBe("0%");
  });
});

describe("the operator of a row", () => {
  it("is read off what the row lists, with its colour and the person behind it", () => {
    const listed = row(OP1, "NE1", 3, "4.50", [involved(OP1, "NE1", 3, "4.50")]);
    expect(operatorOfRow(listed)).toMatchObject({
      hid: OP1,
      label: "NE1",
      colour: "#1f6feb",
      person: "Lee Marchetti",
      open: false,
    });
  });

  it("is still the label and the link when the row lists nothing", () => {
    expect(operatorOfRow(row(OP1, "NE1", 3, "4.50"))).toMatchObject({
      hid: OP1,
      label: "NE1",
      colour: null,
      open: false,
    });
    expect(operatorOfRow(row(null, null, 2, "1.00"))).toBeNull();
  });

  it("adds up what is under labels that nobody is behind", () => {
    const rows = [
      row(OP1, "NE1", 3, "4.50", [involved(OP1, "NE1", 3, "4.50", true)]),
      row(OP2, "NE2", 2, "0.10", [involved(OP2, "NE2", 2, "0.10", true)]),
      row(OP3, "NE3", 9, "9.00", [involved(OP3, "NE3", 9, "9.00")]),
    ];
    expect(underOpenLabels(rows)).toEqual({
      labels: 2,
      items: 7,
      components: 5,
      support_weight: "4.60",
    });
    expect(underOpenLabels([])).toEqual({
      labels: 0,
      items: 0,
      components: 0,
      support_weight: "0.00",
    });
  });
});

describe("the links of a row", () => {
  it("keeps the items of one operator, or those nobody is assigned to", () => {
    expect(operatorCondition(OP1)).toBe(`effective.operator_hid:eq:${OP1}`);
    expect(operatorCondition(null)).toBe("effective.operator_hid:empty:true");
  });

  it("keeps the items at or beneath one site, or those that are nowhere", () => {
    expect(siteCondition(SITE)).toBe(`location:within:${SITE}`);
    expect(siteCondition(null)).toBe("location:empty:true");
  });

  it("adds the condition of the row to the filter of the view, minor items among them", () => {
    expect(rowItemsPath("", operatorCondition(OP1))).toBe(
      `/items?filter=${encodeURIComponent(`effective.operator_hid:eq:${OP1}`)}&minor=1`,
    );
    expect(rowItemsPath(" tags:has:refresh-2030 ", siteCondition(SITE))).toBe(
      `/items?filter=${encodeURIComponent(`tags:has:refresh-2030 location:within:${SITE}`)}&minor=1`,
    );
  });

  it("offers no link where the view was asked for with a filter tree", () => {
    expect(rowItemsPath('{"field":"tags","op":"has","value":"x"}', siteCondition(SITE))).toBeNull();
  });
});

describe("the tables as files", () => {
  it("writes CSV as RFC 4180 has it", () => {
    expect(
      toCsv([
        ["a", "b"],
        ["1", 2],
      ]),
    ).toBe("a,b\r\n1,2\r\n");
    expect(toCsv([["Building 1, Room 102", 'the "core"', "two\nlines"]])).toBe(
      '"Building 1, Room 102","the ""core""","two\nlines"\r\n',
    );
  });

  it("keeps a spreadsheet from running a cell as a formula", () => {
    expect(toCsv([["=SUM(A1)", "+1", "-OP", "@x", "NE1-east"]])).toBe(
      "'=SUM(A1),'+1,'-OP,'@x,NE1-east\r\n",
    );
    // A number is a number: a count is not text that could be a formula.
    expect(toCsv([[-1, 0]])).toBe("-1,0\r\n");
  });

  it("writes the operators in the order of the table, what nobody is assigned to last", () => {
    const rows = [row(OP2, "NE2", 3, "10.50", [involved(OP2, "NE2", 3, "10.50", true)])];
    const text = operatorsCsv(rows, row(null, null, 2, "31.50"), "42.00");
    const lines = text.trimEnd().split("\r\n");
    expect(lines).toHaveLength(3);
    expect(lines[0]).toContain("operator_hid,operator,person,open,components");
    expect(lines[1]).toBe(`${OP2},NE2,,true,3,3,4,10.50,25%,3,0,0,0`);
    expect(lines[2]).toBe(",,,,2,2,3,31.50,75%,2,0,0,0");
  });

  it("writes the sites with the operators involved in one cell", () => {
    const here = [involved(OP1, "NE1", 3, "4.50"), involved(null, null, 1, "1.00")];
    expect(involvedText(here)).toBe("NE1 3 (4.50); nobody 1 (1.00)");
    expect(involvedText(null)).toBe("");
    const text = sitesCsv([row(SITE, "Americas > Central > Site-2", 4, "5.50", here)], null);
    expect(text.trimEnd().split("\r\n")[1]).toBe(
      `${SITE},Americas > Central > Site-2,4,4,5,5.50,NE1 3 (4.50); nobody 1 (1.00)`,
    );
  });
});
