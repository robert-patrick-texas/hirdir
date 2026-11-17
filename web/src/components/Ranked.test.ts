import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ranking } from "../lib/rank";
import { Bar, Counted, RankCell, RankHead, RankNote } from "./Ranked";

interface Row {
  key: string | null;
  items: number;
}

const rows: Row[] = [
  { key: "a", items: 3 },
  { key: "b", items: 12 },
  { key: null, items: 6 },
];
const counts = {
  items: { value: (row: Row) => row.items, text: (row: Row) => String(row.items), label: "items" },
};
const ranked = ranking(rows, null, counts, { fallback: "items", blank: (row) => row.key === null });

describe("a count with its bar", () => {
  it("writes the number once, and hides the bar from a screen reader", () => {
    const markup = renderToStaticMarkup(createElement(Bar, { share: 0.25, text: "3", figure: 2 }));
    expect(markup).toContain('<span class="bar" aria-hidden="true">');
    expect(markup.match(/>3</g)).toHaveLength(1);
    expect(markup).toContain("inline-size:25.00%");
    expect(markup).toContain("min-inline-size:2ch");
  });

  it("draws nothing for nothing, and never more than the whole", () => {
    expect(renderToStaticMarkup(createElement(Bar, { share: 0, text: "0", figure: 1 }))).toContain(
      'class="bar-fill" style="inline-size:0.00%"',
    );
    expect(renderToStaticMarkup(createElement(Bar, { share: 3, text: "9", figure: 1 }))).toContain(
      'class="bar-fill bar-some" style="inline-size:100.00%"',
    );
  });

  it("is as long as the count is to the largest of its column", () => {
    const markup = renderToStaticMarkup(
      createElement(Counted<Row>, { ranking: ranked, column: "items", row: rows[0] as Row }),
    );
    expect(markup).toContain("inline-size:25.00%");
    expect(markup).toContain(">3<");
  });
});

describe("the Rank column", () => {
  it("is named Rank, and keeps what it is by beside, apart from the name", () => {
    const markup = renderToStaticMarkup(createElement(RankHead<Row>, { ranking: ranked }));
    expect(markup).toBe('<th scope="col" class="number rank" data-rank-by="items">Rank</th>');
  });

  it("is 1 for the most, and blank for the blank row", () => {
    const cell = (row: Row) =>
      renderToStaticMarkup(createElement(RankCell<Row>, { ranking: ranked, row }));
    expect(cell(rows[1] as Row)).toBe('<td class="number rank" data-measure="rank">1</td>');
    expect(cell(rows[0] as Row)).toBe('<td class="number rank" data-measure="rank">2</td>');
    expect(cell(rows[2] as Row)).toBe('<td class="number rank" data-measure="rank"></td>');
  });

  it("is said beneath the table, with the row that has none", () => {
    const markup = renderToStaticMarkup(
      createElement(RankNote<Row>, { ranking: ranked, fallback: "items", blank: "No owner" }),
    );
    expect(markup).toContain('data-rank-by="items"');
    expect(markup).toContain("Ranked by items, 1 for the most");
    expect(markup).toContain("the row “No owner” has none");
  });
});
