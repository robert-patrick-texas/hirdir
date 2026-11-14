import { describe, expect, it } from "vitest";
import { all, any, formatShort, itemsPath, KINDS, OPERATORS, parseShort } from "./filter";

function parsed(text: string) {
  const result = parseShort(text);
  if (!result.ok) throw new Error(result.error);
  return result.filter;
}

describe("itemsPath", () => {
  it("links to the grid of items with the filter, and asks for minor items too", () => {
    expect(itemsPath("parent_item_hid:eq:0193a1f4-0000-7000-8000-000000000001")).toBe(
      "/items?filter=parent_item_hid%3Aeq%3A0193a1f4-0000-7000-8000-000000000001&minor=1",
    );
    expect(itemsPath("hostname:prefix:site2- tags:has:core")).toBe(
      "/items?filter=hostname%3Aprefix%3Asite2-%20tags%3Ahas%3Acore&minor=1",
    );
  });
});

describe("parseShort", () => {
  it("reads one condition", () => {
    expect(parsed("lifecycle_state:eq:prod")).toEqual({
      field: "lifecycle_state",
      op: "eq",
      value: "prod",
    });
  });

  it("joins conditions with AND, as the server does", () => {
    expect(parsed("lifecycle_state:in:Test,Prod hostname:prefix:site2-")).toEqual({
      and: [
        { field: "lifecycle_state", op: "in", value: ["Test", "Prod"] },
        { field: "hostname", op: "prefix", value: "site2-" },
      ],
    });
  });

  it("lets a value run to the start of the next condition, spaces and colons included", () => {
    expect(parsed("owner.label:eq:lab team catalog.pid:glob:?X4400-48P")).toEqual({
      and: [
        { field: "owner.label", op: "eq", value: "lab team" },
        { field: "catalog.pid", op: "glob", value: "?X4400-48P" },
      ],
    });
    expect(parsed("mac_address:eq:00:00:5e:00:53:02")).toEqual({
      field: "mac_address",
      op: "eq",
      value: "00:00:5e:00:53:02",
    });
    expect(parsed("hostname:regex:^site2-sw-(core|dist)-[0-9]+$")).toEqual({
      field: "hostname",
      op: "regex",
      value: "^site2-sw-(core|dist)-[0-9]+$",
    });
  });

  it("splits the values of in and between at commas, and of nothing else", () => {
    expect(parsed("effective.est_value:between:15000, 18000")).toEqual({
      field: "effective.est_value",
      op: "between",
      value: ["15000", "18000"],
    });
    expect(parsed("comments:contains:a,b")).toEqual({
      field: "comments",
      op: "contains",
      value: "a,b",
    });
  });

  it("tells lt from lte and the like", () => {
    expect(parsed("quantity:lte:5 quantity:lt:9 quantity:gte:1")).toEqual({
      and: [
        { field: "quantity", op: "lte", value: "5" },
        { field: "quantity", op: "lt", value: "9" },
        { field: "quantity", op: "gte", value: "1" },
      ],
    });
  });

  it("keeps the same field twice", () => {
    expect(parsed("tags:has:core tags:has:refresh-2030")).toEqual({
      and: [
        { field: "tags", op: "has", value: "core" },
        { field: "tags", op: "has", value: "refresh-2030" },
      ],
    });
  });

  it("takes blank text as no filter", () => {
    expect(parseShort("")).toEqual({ ok: true, filter: null });
    expect(parseShort("   ")).toEqual({ ok: true, filter: null });
  });

  it("refuses what is not the short form, and says what the form is", () => {
    for (const text of ["just some words", "hostname:like:x", ":eq:1", "x hostname:eq:a"]) {
      const result = parseShort(text);
      expect(result.ok, text).toBe(false);
      if (!result.ok) expect(result.error).toContain("field:op:value");
    }
  });

  it("refuses a value that itself looks like a condition: a mistyped operator, most likely", () => {
    const result = parseShort("hostname:prefix:site2- lifecycle_state:is:Prod");
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error).toContain("'lifecycle_state:is:' is not a condition");
      expect(result.error).toContain("eq, ne, in");
    }
    expect(parseShort("comments:contains:see name:x: for more").ok).toBe(false);
    // A value with colons that does not look like one is taken as it is.
    expect(parsed("comments:contains:ratio 3:1: checked")).toEqual({
      field: "comments",
      op: "contains",
      value: "ratio 3:1: checked",
    });
  });

  it("reads the operator in any case, and sends it in lower case", () => {
    expect(parsed("lifecycle_state:EQ:Prod hostname:Prefix:site2-")).toEqual({
      and: [
        { field: "lifecycle_state", op: "eq", value: "Prod" },
        { field: "hostname", op: "prefix", value: "site2-" },
      ],
    });
  });

  it("leaves the field and the operator for the server to judge", () => {
    expect(parsed("nope:eq:1")).toEqual({ field: "nope", op: "eq", value: "1" });
    expect(parsed("hostname:within:Americas")).toEqual({
      field: "hostname",
      op: "within",
      value: "Americas",
    });
  });
});

describe("formatShort", () => {
  it("writes what parseShort reads", () => {
    for (const text of [
      "lifecycle_state:in:Test,Prod hostname:prefix:site2-",
      "catalog_entry_hid:eq:0193a1f4-6c2e-7b41-9d0a-5e3f8c1a7b22",
      "tags:empty:false owner_hid:empty:true",
    ]) {
      expect(formatShort(parsed(text))).toBe(text);
    }
    expect(formatShort(null)).toBe("");
  });

  it("has no way to write OR or nesting", () => {
    expect(formatShort({ or: [{ field: "a", op: "eq", value: "1" }] })).toBeNull();
    expect(formatShort({ and: [{ or: [{ field: "a", op: "eq", value: "1" }] }] })).toBeNull();
  });
});

describe("all and any", () => {
  const one = { field: "a", op: "eq", value: "1" } as const;
  const two = { field: "b", op: "eq", value: "2" } as const;
  const three = { field: "c", op: "eq", value: "3" } as const;

  it("are nothing for nothing and the part itself for one part", () => {
    expect(all()).toBeNull();
    expect(all(null, undefined)).toBeNull();
    expect(all(null, one)).toBe(one);
    expect(any(one, null)).toBe(one);
    expect(any()).toBeNull();
  });

  it("flatten an AND inside an AND, and leave an OR whole", () => {
    expect(all(one, { and: [two, three] })).toEqual({ and: [one, two, three] });
    expect(all(one, { or: [two, three] })).toEqual({ and: [one, { or: [two, three] }] });
    expect(any(one, two)).toEqual({ or: [one, two] });
  });
});

describe("KINDS", () => {
  it("names only operators of the grammar", () => {
    for (const operators of Object.values(KINDS)) {
      for (const operator of operators) expect(OPERATORS).toContain(operator);
    }
  });

  it("gives a fixed choice eq, ne, in and empty only", () => {
    expect([...KINDS.choice]).toEqual(["eq", "ne", "in", "empty"]);
    expect([...KINDS.tags]).toEqual(["has", "empty"]);
    expect(KINDS.text).toContain("regex");
    expect(KINDS.number).not.toContain("regex");
  });

  it("matches an address as it matches a MAC address: whole, or a part of it", () => {
    expect([...KINDS.address]).toEqual([...KINDS.mac]);
    expect(KINDS.address).toContain("prefix");
    expect(KINDS.address).not.toContain("glob");
  });
});
