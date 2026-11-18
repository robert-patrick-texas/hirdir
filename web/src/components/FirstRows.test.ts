// 0.9.6: a vendor's models in twenty with Show all, and its items before its agreements
// (P-211). Every name and number here is invented.

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";
import type { Schemas } from "../api/client";
import { FIRST_ROWS } from "./FirstRows";
import { PortfolioCounts } from "./PortfolioTables";

type Portfolio = Schemas["PortfolioOut"];

const VENDOR = "0193a1f4-0000-7000-8000-00000000f101";

const measures = {
  items: 2,
  component_count: 2,
  support_weight: "0.8",
  est_value: "5600.00",
  annual_support_cost: "380.00",
  covered: 1,
  uncovered: 1,
};

function model(n: number): Portfolio["models"][number] {
  return {
    ...measures,
    catalog_entry_hid: `0193a1f4-0000-7000-8000-${String(n).padStart(12, "0")}`,
    pid: `EX-${String(n).padStart(3, "0")}`,
    model_name: `Example ${n}`,
    kind: "hardware",
    type: null,
    function: null,
    end_of_sale: null,
    end_of_sw_support: null,
    end_of_hw_support: null,
    ldos: n % 2 === 0 ? null : "2031-06-30",
    covered_until: null,
  };
}

function portfolioOf(models: number): Portfolio {
  return {
    vendor: { hid: VENDOR, name: "Example Networks" },
    as_of: "2026-11-17",
    totals: { ...measures, items: models * 2 },
    kinds: [],
    models: Array.from({ length: models }, (_, n) => model(n + 1)),
    agreements: [],
    contracts: [],
    capacity_lines: [],
    filter: { field: "catalog.vendor_hid", op: "eq", value: VENDOR },
  };
}

function html(models: number): string {
  return renderToStaticMarkup(
    createElement(
      MemoryRouter,
      null,
      createElement(
        PortfolioCounts,
        { portfolio: portfolioOf(models), money: "", choices: undefined },
        createElement("h3", null, "Its items"),
      ),
    ),
  );
}

function modelRows(markup: string): number {
  const table = markup.split('data-testid="portfolio-models"')[1]?.split("</table>")[0] ?? "";
  return (table.split("<tbody>")[1] ?? "").split("<tr").length - 1;
}

describe("a vendor's models", () => {
  it("shows the first twenty, and a button with the number of them all", () => {
    const markup = html(25);
    expect(FIRST_ROWS).toBe(20);
    expect(modelRows(markup)).toBe(20);
    expect(markup).toContain("Show all 25<span");
    expect(markup).toContain(" models</span>");
  });

  it("shows them all where there are twenty or fewer, with no button", () => {
    const markup = html(20);
    expect(modelRows(markup)).toBe(20);
    expect(markup).not.toContain("Show all");
  });

  it("puts the vendor's items after the models and before the agreements", () => {
    const markup = html(3);
    const models = markup.indexOf('id="portfolio-models"');
    const items = markup.indexOf("<h3>Its items</h3>");
    const agreements = markup.indexOf('id="portfolio-agreements"');
    expect(models).toBeGreaterThan(-1);
    expect(items).toBeGreaterThan(models);
    expect(agreements).toBeGreaterThan(items);
  });
});
