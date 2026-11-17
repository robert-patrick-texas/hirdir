// The health of a row of the scoreboard in one cell (P-178): a bar in four parts, the
// numbers beside it, and the four counts in words for a screen reader, once.

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { healthParts, healthWeight, healthWords, scoreColumns } from "../lib/scoreboard";
import { nextSort, sortRows } from "../lib/sort";
import { HealthSplit } from "./HealthSplit";

const counts = { good: 12, degraded: 1, failed: 0, unknown: 3 };

describe("the four counts of health", () => {
  it("are said in words, once, in their order", () => {
    expect(healthWords(counts)).toBe("12 good, 1 degraded, 0 failed, 3 unknown");
    expect(healthWords({ good: 1200, degraded: 0, failed: 0, unknown: 0 })).toBe(
      "1,200 good, 0 degraded, 0 failed, 0 unknown",
    );
  });

  it("are parts of one bar, each as long as its share of the row's components", () => {
    expect(healthParts(counts)).toEqual([
      { health: "good", share: 0.75 },
      { health: "degraded", share: 0.0625 },
      { health: "unknown", share: 0.1875 },
    ]);
    expect(healthParts({ good: 0, degraded: 0, failed: 0, unknown: 0 })).toEqual([]);
  });

  it("sort by what failed, then by what is degraded, the worst first at the first click", () => {
    const calm = { key: "a", by_health: { good: 9, degraded: 0, failed: 0, unknown: 9 } };
    const worn = { key: "b", by_health: { good: 1, degraded: 4, failed: 0, unknown: 0 } };
    const broken = { key: "c", by_health: { good: 0, degraded: 0, failed: 1, unknown: 0 } };
    expect(healthWeight(broken.by_health)).toBeGreaterThan(healthWeight(worn.by_health));
    expect(healthWeight(worn.by_health)).toBeGreaterThan(healthWeight(calm.by_health));
    const first = nextSort(null, "health", true);
    expect(first).toEqual({ column: "health", descending: true });
    const columns = scoreColumns("Nobody");
    const rows = [calm, worn, broken].map((row) => ({
      ...row,
      label: row.key,
      items: 1,
      component_count: 1,
      managed_node_count: 1,
      support_weight: "1.00",
      operators: null,
    }));
    expect(sortRows(rows, columns, first).map((row) => row.key)).toEqual(["c", "b", "a"]);
    // Another column still starts with the least, as every header does.
    expect(nextSort(null, "items")).toEqual({ column: "items", descending: false });
  });
});

describe("the cell of health", () => {
  const markup = renderToStaticMarkup(createElement(HealthSplit, { counts }));

  it("hides the bar and the marked numbers from a screen reader, which hears the words once", () => {
    expect(markup).toContain('<span class="health-bar" aria-hidden="true">');
    expect(markup).toContain('<span class="health-figures" aria-hidden="true">');
    expect(markup).toContain(
      '<span class="visually-hidden">12 good, 1 degraded, 0 failed, 3 unknown</span>',
    );
    expect(markup.match(/12 good/g)).toHaveLength(1);
  });

  it("draws each part in the colour of its health, as long as its share", () => {
    expect(markup).toContain(
      'class="health-part health-part-good" data-health="good" style="inline-size:75.00%"',
    );
    expect(markup).toContain('class="health-part health-part-unknown"');
    // What has none has no part.
    expect(markup).not.toContain("health-part-failed");
  });

  it("writes the four numbers beside the bar, each with its mark", () => {
    const figures = markup.match(/class="health health-[a-z]+ health-figure"/g) ?? [];
    expect(figures).toHaveLength(4);
    expect(markup).toContain(
      'data-health="failed" title="Failed"><span class="health-dot"></span>0</span>',
    );
  });
});
