// 0.8.0: the tables and the facts of the support weight, rendered from answers of the
// shape the server gives (P-155, P-156). Every name and number here is invented.

import { createElement, type ReactElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";
import type { CapacityReport, CapacityView } from "../lib/capacity";
import { TriedBeside, WeightParts } from "./CapacityParts";
import { PlaceWeightFacts, WeightInForce } from "./Weight";

function html(element: ReactElement): string {
  return renderToStaticMarkup(createElement(MemoryRouter, null, element));
}

function view(more: Partial<CapacityView> = {}): CapacityView {
  return {
    support_weight: "2409",
    items_weight: "2400",
    places_weight: "6",
    circuits_weight: "3",
    defaulted: { items: 12, sites: 2, circuits: 0 },
    raised: { items: 3, sites: 0, circuits: 1 },
    infrastructure_demand: "8.03",
    other_demand: "2",
    demand: "10.03",
    supply: "9",
    balance: "-1.03",
    coverage_pct: "89.73",
    own_units: "6",
    own_share_pct: "66.67",
    outside_units: "3",
    annual_cost: "0.00",
    by_category: [{ category: "staff", label: "Staff", lines: 3, units: "6", annual_cost: "0.00" }],
    multiplying_lines: [],
    demand_by_region: [],
    ...more,
  };
}

function report(active: Partial<CapacityView> = {}): CapacityReport {
  return {
    as_of: "2026-11-14",
    weight_per_resource_unit: "300",
    active: view(active),
    with_drafts: view(),
  };
}

describe("the support weight in its parts", () => {
  it("has a row for the items, the places and the circuits, with the counts of each", () => {
    const markup = html(createElement(WeightParts, { report: report() }));
    const places = markup.split('data-part="places"')[1]?.split("</tr>")[0] ?? "";
    expect(places).toContain('data-testid="part-weight" data-value="6"');
    expect(places).toContain('data-testid="part-defaulted" data-value="2"');
    expect(places).toContain("counts of sites");
    // Its headers sort it.
    expect(markup.match(/class="sort-header"/g)).toHaveLength(7);
  });
});

describe("the balance tried beside the balance in force", () => {
  it("marks a figure that differs, and no other", () => {
    const markup = html(
      createElement(TriedBeside, {
        inForce: report(),
        tried: report({ places_weight: "16", support_weight: "2419" }),
      }),
    );
    expect(markup).toContain('data-figure="places_weight" data-differs="true"');
    expect(markup).toContain('data-figure="supply" data-differs="false"');
    const places = markup.split('data-figure="places_weight"')[1]?.split("</tr>")[0] ?? "";
    expect(places).toContain('data-testid="in-force-active" data-value="6"');
    expect(places).toContain('data-testid="tried-active" data-value="16"');
  });
});

describe("the weight of a place", () => {
  it("shows a region's own alone", () => {
    const markup = html(createElement(PlaceWeightFacts, { place: { support_weight: "2" } }));
    expect(markup).toContain('data-testid="place-weight" data-value="2"');
    expect(markup).not.toContain("place-weight-in-force");
  });

  it("shows a site's default as inherited, with its setting, and that it was raised", () => {
    const markup = html(
      createElement(PlaceWeightFacts, {
        place: {
          support_weight: null,
          effective: {
            support_weight: { value: "4", source: "setting", source_hid: null, raised_from: "3" },
          },
        },
      }),
    );
    expect(markup).toContain("None of its own");
    expect(markup).toContain('data-source="setting" class="inherited"');
    expect(markup).toContain("The default of a site, default_site_weight");
    expect(markup).toContain("Raised to the minimum, minimum_site_weight, from 3");
  });

  it("shows a weight of its own plainly", () => {
    const markup = html(
      createElement(WeightInForce, {
        weight: { value: "2", source: "own", source_hid: null, raised_from: null },
        kind: "site",
      }),
    );
    expect(markup).not.toContain("inherited");
    expect(markup).toContain("Set here");
    expect(markup).not.toContain("Raised");
  });
});
