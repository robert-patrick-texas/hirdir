// 0.8.0: the words of a weight in force, of a default and of a minimum (P-155). Every
// number here is invented.

import { describe, expect, it } from "vitest";
import {
  defaultKey,
  type EffectiveWeight,
  isWeightSetting,
  minimumKey,
  raisedText,
  siteWeightHint,
  WEIGHT_SETTINGS,
  weightInherited,
  weightSettingLabel,
  weightSource,
} from "./weights";

function weight(more: Partial<EffectiveWeight>): EffectiveWeight {
  return { value: null, source: "none", source_hid: null, raised_from: null, ...more };
}

describe("the settings of a default and a minimum", () => {
  it("are six, a default and a minimum of each kind", () => {
    expect(WEIGHT_SETTINGS).toEqual([
      "default_item_weight",
      "minimum_item_weight",
      "default_site_weight",
      "minimum_site_weight",
      "default_circuit_weight",
      "minimum_circuit_weight",
    ]);
    expect(defaultKey("site")).toBe("default_site_weight");
    expect(minimumKey("circuit")).toBe("minimum_circuit_weight");
    expect(isWeightSetting("minimum_item_weight")).toBe(true);
    expect(isWeightSetting("weight_per_resource_unit")).toBe(false);
  });

  it("are called by what they are of", () => {
    expect(weightSettingLabel("default_item_weight")).toBe("Default weight of a major item");
    expect(weightSettingLabel("minimum_site_weight")).toBe("Minimum weight of a site");
    expect(weightSettingLabel("default_circuit_weight")).toBe("Default weight of a circuit");
  });
});

describe("where a weight in force came from", () => {
  it("is the record's own, its model's, the default of its kind or nothing", () => {
    expect(weightSource(weight({ value: "2", source: "own" }), "site")).toBe("Set here");
    expect(weightSource(weight({ value: "1", source: "catalog" }), "item")).toBe(
      "From the catalog entry",
    );
    expect(weightSource(weight({ value: "3", source: "setting" }), "site")).toBe(
      "The default of a site, default_site_weight",
    );
    expect(weightSource(weight({ value: "3", source: "setting" }), "item")).toBe(
      "The default of a major item, default_item_weight",
    );
    expect(weightSource(weight({}), "circuit")).toBe("Not set");
    expect(weightSource(null, "circuit")).toBe("Not set");
  });

  it("is inherited unless it is the record's own or nothing", () => {
    expect(weightInherited(weight({ value: "3", source: "setting" }))).toBe(true);
    expect(weightInherited(weight({ value: "1", source: "catalog" }))).toBe(true);
    expect(weightInherited(weight({ value: "2", source: "own" }))).toBe(false);
    expect(weightInherited(weight({}))).toBe(false);
  });
});

describe("a weight raised to the minimum", () => {
  it("says so, with what it was before", () => {
    expect(raisedText(weight({ value: "1", source: "own", raised_from: "0.5" }), "site")).toBe(
      "Raised to the minimum, minimum_site_weight, from 0.5",
    );
    // A weight of zero is a weight, and is raised.
    expect(raisedText(weight({ value: "1", source: "setting", raised_from: "0" }), "item")).toBe(
      "Raised to the minimum, minimum_item_weight, from 0",
    );
  });

  it("says nothing where it was not raised", () => {
    expect(raisedText(weight({ value: "2", source: "own" }), "site")).toBe("");
    expect(raisedText(null, "site")).toBe("");
  });
});

describe("what a blank weight of a site counts at", () => {
  it("names the default in force where the site has none", () => {
    expect(siteWeightHint(null, weight({ value: "3", source: "setting" }))).toBe(
      "Blank counts at default_site_weight, 3. A weight below minimum_site_weight is raised to it.",
    );
    // Raised, the default is what it was before.
    expect(
      siteWeightHint(null, weight({ value: "4", source: "setting", raised_from: "3" })),
    ).toContain("Blank counts at default_site_weight, 3.");
  });

  it("says that a blank counts for nothing while there is no default", () => {
    expect(siteWeightHint(null, weight({}))).toContain(
      "Blank counts for nothing while default_site_weight is blank.",
    );
  });

  it("says that a weight is set here, and for a new site what a blank would do", () => {
    expect(siteWeightHint("2", weight({ value: "2", source: "own" }))).toMatch(/^Set here\. /);
    expect(siteWeightHint(null, null)).toMatch(/^Blank counts at default_site_weight where/);
  });
});
