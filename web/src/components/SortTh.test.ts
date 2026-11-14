import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { SortControl } from "../lib/useSorting";
import { SortTh } from "./SortTh";

const sorting = (more: Partial<SortControl> = {}): SortControl => ({
  state: null,
  by: () => undefined,
  enabled: true,
  ...more,
});

function header(sort: SortControl, column: string, className?: string): string {
  return renderToStaticMarkup(
    createElement(SortTh, { sort, column, ...(className ? { className } : {}) }, "Members"),
  );
}

describe("the header of a column that a table is sorted by", () => {
  it("is a column header with a button in it, so that the keyboard reaches it", () => {
    const html = header(sorting(), "members");
    expect(html).toMatch(/^<th scope="col"[^>]*>/);
    expect(html).toContain('<button type="button"');
    expect(html).toContain('data-sort="members"');
    expect(html).toContain("Members");
  });

  it("says that the table is not sorted by it", () => {
    const html = header(sorting({ state: { column: "name", descending: false } }), "members");
    expect(html).toContain('aria-sort="none"');
    expect(html).not.toContain("▲");
    expect(html).not.toContain("▼");
  });

  it("says which way the order runs when the table is sorted by it, in words and with a mark", () => {
    const up = header(sorting({ state: { column: "members", descending: false } }), "members");
    expect(up).toContain('aria-sort="ascending"');
    expect(up).toContain("▲");
    const down = header(sorting({ state: { column: "members", descending: true } }), "members");
    expect(down).toContain('aria-sort="descending"');
    expect(down).toContain("▼");
    // The mark is for the eye: the order is said to a screen reader by `aria-sort`.
    expect(down).toContain('aria-hidden="true"');
  });

  it("keeps the class of the column, as of a column of numbers", () => {
    expect(header(sorting(), "members", "number")).toContain('class="number"');
  });

  it("is a plain header in a table that does not hold all of its rows", () => {
    const html = header(sorting({ enabled: false }), "members");
    expect(html).toBe('<th scope="col">Members</th>');
  });
});
