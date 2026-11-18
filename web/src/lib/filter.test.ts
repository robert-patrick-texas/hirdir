import { describe, expect, it } from "vitest";
import {
  all,
  any,
  canBeMac,
  type FilterNode,
  filterText,
  formatShort,
  ITEM_WORDS,
  isWords,
  itemsAndCondition,
  itemsPath,
  itemsViewPath,
  KINDS,
  OPERATORS,
  parseFilter,
  parseShort,
  sentFilter,
  viewFilter,
  wordsFilter,
  wordsOf,
} from "./filter";

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

describe("a filter as a link or the filter box holds it", () => {
  // What the coverage report gives for the cover on items that are out of service.
  const outOfService: FilterNode = {
    and: [
      { field: "covered", op: "eq", value: true },
      {
        or: [
          { field: "record_status", op: "eq", value: "retired" },
          {
            field: "effective.lifecycle_state",
            op: "in",
            value: ["Pending-Removal", "Released", "Archived"],
          },
        ],
      },
    ],
  };
  // And for the items in service that no contract covers: ANDs within an AND.
  const uncovered: FilterNode = {
    and: [
      {
        and: [
          { field: "effective.lifecycle_state", op: "in", value: ["Test", "Prod", "Down"] },
          { field: "is_major", op: "eq", value: true },
        ],
      },
      { field: "covered", op: "eq", value: false },
    ],
  };

  it("reads the short form as before", () => {
    expect(parseFilter("covered:eq:false is_major:eq:true")).toEqual(
      parseShort("covered:eq:false is_major:eq:true"),
    );
    expect(parseFilter("  ")).toEqual({ ok: true, filter: null });
    expect(parseFilter("covered").ok).toBe(false);
  });

  it("reads a filter tree written as JSON, an OR in it and all", () => {
    expect(parseFilter(JSON.stringify(outOfService))).toEqual({ ok: true, filter: outOfService });
    expect(parseFilter(` ${JSON.stringify({ field: "covered", op: "eq", value: true })} `)).toEqual(
      { ok: true, filter: { field: "covered", op: "eq", value: true } },
    );
  });

  it("refuses what begins as a tree and is none", () => {
    expect(parseFilter("{not json").ok).toBe(false);
    expect(parseFilter('{"field": "covered"}').ok).toBe(false);
    expect(parseFilter('{"field": "covered", "op": "is", "value": true}').ok).toBe(false);
    expect(parseFilter('{"and": {"field": "covered", "op": "eq"}}').ok).toBe(false);
    expect(parseFilter('{"or": [{"and": ["covered"]}]}').ok).toBe(false);
  });

  it("writes a filter in the short form where it reads back as the same conditions", () => {
    expect(filterText(null)).toBe("");
    expect(filterText({ field: "contract.hid", op: "eq", value: "c-1" })).toBe(
      "contract.hid:eq:c-1",
    );
    // ANDs within an AND are one AND, which the short form can write.
    expect(filterText(uncovered)).toBe(
      "effective.lifecycle_state:in:Test,Prod,Down is_major:eq:true covered:eq:false",
    );
    expect(parsed(filterText(uncovered))).toEqual({
      and: [
        { field: "effective.lifecycle_state", op: "in", value: ["Test", "Prod", "Down"] },
        { field: "is_major", op: "eq", value: "true" },
        { field: "covered", op: "eq", value: "false" },
      ],
    });
  });

  it("writes the tree as JSON where the short form cannot say it", () => {
    expect(filterText(outOfService)).toBe(JSON.stringify(outOfService));
    // A value that would be read as the start of another condition.
    const awkward: FilterNode = { field: "name", op: "eq", value: "core a:eq:b" };
    expect(filterText(awkward)).toBe(JSON.stringify(awkward));
    // One of a list that holds a comma would be read as two.
    const listed: FilterNode = { field: "name", op: "in", value: ["a,b", "c"] };
    expect(filterText(listed)).toBe(JSON.stringify(listed));
  });

  it("takes what a report gives as a filter, and nothing that is none", () => {
    expect(viewFilter(outOfService)).toBe(outOfService);
    expect(viewFilter(null)).toBeNull();
    expect(viewFilter({ count: 3 })).toBeNull();
    expect(viewFilter("covered:eq:true")).toBeNull();
  });

  it("links to the items a report counted, with the switches as the report says to send them", () => {
    const link = new URL(
      itemsViewPath({ filter: outOfService, include_archived: true, include_drafts: false }),
      "http://localhost",
    );
    expect(link.pathname).toBe("/items");
    expect(parseFilter(link.searchParams.get("filter") ?? "")).toEqual({
      ok: true,
      filter: outOfService,
    });
    // Archived items are among them: the grid is asked to include them.
    expect(link.searchParams.get("archived")).toBe("1");
    expect(link.searchParams.get("drafts")).toBeNull();
    // The filter says itself where only major items count.
    expect(link.searchParams.get("minor")).toBe("1");
  });

  it("links to the list of a report that has no filter of its own as to every item", () => {
    const link = new URL(itemsViewPath({ filter: null }), "http://localhost");
    expect(link.searchParams.get("filter")).toBe("");
    expect(link.searchParams.get("archived")).toBeNull();
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

describe("plain words in a filter box (P-187)", () => {
  const CONTACTS = { fields: ["name", "email"], example: "tags:has:on-call" };

  it("are each held by one of the fields a list is known by", () => {
    expect(wordsFilter("  sw-01274 ", ITEM_WORDS.fields)).toEqual({
      or: [
        { field: "name", op: "contains", value: "sw-01274" },
        { field: "hostname", op: "contains", value: "sw-01274" },
        { field: "serial_number", op: "contains", value: "sw-01274" },
        { field: "asset_tag", op: "contains", value: "sw-01274" },
        { field: "address", op: "contains", value: "sw-01274" },
        // 0.9.6: and the name of a group it is in, as a stack's (P-220).
        { field: "group.name", op: "contains", value: "sw-01274" },
      ],
    });
    expect(parseFilter("rowan example.org", CONTACTS)).toEqual({
      ok: true,
      filter: {
        and: [
          {
            or: [
              { field: "name", op: "contains", value: "rowan" },
              { field: "email", op: "contains", value: "rowan" },
            ],
          },
          {
            or: [
              { field: "name", op: "contains", value: "example.org" },
              { field: "email", op: "contains", value: "example.org" },
            ],
          },
        ],
      },
    });
  });

  it("leave a condition of the short form and a tree as they always were", () => {
    expect(parseFilter("hostname:prefix:site2-", ITEM_WORDS)).toEqual(
      parseFilter("hostname:prefix:site2-"),
    );
    const tree = '{"field":"tags","op":"has","value":"core"}';
    expect(parseFilter(tree, ITEM_WORDS)).toEqual(parseFilter(tree));
    expect(parseFilter("   ", ITEM_WORDS)).toEqual({ ok: true, filter: null });
  });

  it("are refused where a list is known by nothing, as before", () => {
    const result = parseFilter("sw-01274");
    expect(result.ok).toBe(false);
  });

  it("with a condition after them are neither, and the help is the list's own", () => {
    const result = parseFilter("rowan tags:has:on-call", CONTACTS);
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error).toContain("name or email");
      expect(result.error).toContain("as in tags:has:on-call");
      expect(result.error).not.toContain("lifecycle_state");
    }
    const mistyped = parseFilter("name:contans:rowan", CONTACTS);
    expect(mistyped.ok).toBe(false);
    if (!mistyped.ok) expect(mistyped.error).toContain("as in tags:has:on-call");
  });

  it("are at most eight", () => {
    expect(parseFilter("a b c d e f g h", CONTACTS).ok).toBe(true);
    expect(parseFilter("a b c d e f g h i", CONTACTS).ok).toBe(false);
  });

  it("tell words from conditions", () => {
    expect(isWords("sw-01274 192.0.2.1")).toBe(true);
    expect(isWords("2001:db8::1")).toBe(true);
    expect(isWords("hostname:prefix:sw")).toBe(false);
    expect(isWords('{"field":"name"}')).toBe(false);
    expect(isWords("")).toBe(false);
  });

  it("take a MAC address or an IPv6 address as words, whatever its first group is", () => {
    for (const text of [
      "aa:bb:cc:dd:ee:ff",
      "AA-BB-CC-DD-EE-FF",
      "fd00:abcd:1::5",
      "db8:beef::1",
      "2001:db8::1",
      "fe80::1",
      "00:00:5e:00:53:02",
      "sw-01274 aa:bb:cc:dd:ee:ff",
    ]) {
      expect(isWords(text), text).toBe(true);
      expect(parseFilter(text, ITEM_WORDS).ok, text).toBe(true);
    }
    // A condition, or a mistyped one, is still neither.
    expect(isWords("hostname:contains:aa:bb")).toBe(false);
    expect(isWords("core:sw:01")).toBe(false);
    expect(parseFilter("core:sw:01", ITEM_WORDS).ok).toBe(false);
  });

  it("find an item by a MAC address, and only by a word that can be one", () => {
    expect(wordsFilter("00:00:5e:00:53:02", ITEM_WORDS.fields, ITEM_WORDS.mac)).toEqual({
      or: [
        ...ITEM_WORDS.fields.map((field) => ({
          field,
          op: "contains",
          value: "00:00:5e:00:53:02",
        })),
        { field: "mac_address", op: "contains", value: "00:00:5e:00:53:02" },
      ],
    });
    for (const mac of ["00:00:5e", "00-00-5E-00-53-02", "0000.5e00.5302", "00005e005302"]) {
      expect(canBeMac(mac), mac).toBe(true);
    }
    for (const other of ["site2", "2030", "192.0.2.10", "2001:db8::1", "17.9.4", "-", "a:b"]) {
      expect(canBeMac(other), other).toBe(false);
    }
    // The server refuses any other text there: a word that cannot be one is not sent.
    expect(parseFilter("site2", ITEM_WORDS)).toEqual({
      ok: true,
      filter: wordsFilter("site2", ITEM_WORDS.fields),
    });
    // A list with no MAC address is as it was.
    expect(wordsFilter("00:00:5e", ["name"])).toEqual({
      field: "name",
      op: "contains",
      value: "00:00:5e",
    });
  });

  it("drop the double quotes round a word", () => {
    expect(wordsOf('"core switch" "sw-01274"')).toEqual(["core", "switch", "sw-01274"]);
    expect(wordsOf('"" lab')).toEqual(["lab"]);
    expect(parseFilter('"sw-01274"', ITEM_WORDS)).toEqual(parseFilter("sw-01274", ITEM_WORDS));
  });

  it("go to the server of a view as the tree of them, and a condition as typed", () => {
    expect(JSON.parse(sentFilter("sw-01274"))).toEqual(wordsFilter("sw-01274", ITEM_WORDS.fields));
    expect(sentFilter(" tags:has:core ")).toBe("tags:has:core");
    expect(sentFilter("")).toBe("");
  });

  it("are added to with a row's condition, as the tree of both", () => {
    const path = itemsAndCondition("sw-01274", "location:empty:true");
    const filter = new URLSearchParams((path ?? "").split("?")[1]).get("filter") ?? "";
    expect(JSON.parse(filter)).toEqual({
      and: [
        wordsFilter("sw-01274", ITEM_WORDS.fields),
        { field: "location", op: "empty", value: "true" },
      ],
    });
    expect(itemsAndCondition("tags:has:core", "location:empty:true")).toBe(
      itemsPath("tags:has:core location:empty:true"),
    );
    expect(itemsAndCondition('{"field":"tags","op":"has","value":"x"}', "a:eq:b")).toBeNull();
  });
});
