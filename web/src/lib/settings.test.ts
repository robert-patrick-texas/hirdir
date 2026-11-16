import { describe, expect, it } from "vitest";
import {
  listValue,
  settingInput,
  settingText,
  settingValue,
  splitSettings,
  withExtension,
} from "./settings";

describe("settingText", () => {
  it("writes a number, a word and a list as people read them", () => {
    expect(settingText(50)).toBe("50");
    expect(settingText(30.5)).toBe("30.5");
    expect(settingText(0.05)).toBe("0.05");
    expect(settingText("USD")).toBe("USD");
    expect(settingText(["Test", "Prod", "Down"])).toBe("Test, Prod, Down");
  });

  it("writes a fixed value that says something of several things, each with what it holds", () => {
    expect(
      settingText({
        failed: ["failed", "dead"],
        degraded: ["degraded", "suspect"],
        good: ["good"],
      }),
    ).toBe("failed: failed, dead; degraded: degraded, suspect; good: good");
    expect(settingText({ a: 1 })).toBe("a: 1");
  });

  it("is blank for a kind it does not know", () => {
    expect(settingText(null)).toBe("");
    expect(settingText(undefined)).toBe("");
    expect(settingText(Number.NaN)).toBe("");
    expect(settingText(true)).toBe("");
  });
});

describe("splitSettings", () => {
  it("puts the settings first and the fixed values apart, each in the order it came", () => {
    const all = [
      { key: "currency", value: "USD", default: "USD", fixed: false },
      { key: "max_page_size", value: 1000, default: 1000, fixed: true },
      { key: "time_zone", value: "UTC", default: "UTC" },
      { key: "received_state", value: "Delivered", default: "Delivered", fixed: true },
    ];
    const { settings, fixed } = splitSettings(all);
    expect(settings.map((one) => one.key)).toEqual(["currency", "time_zone"]);
    expect(fixed.map((one) => one.key)).toEqual(["max_page_size", "received_state"]);
  });
});

describe("settingInput", () => {
  it("ticks a list, chooses one of a list, and types the rest", () => {
    expect(
      settingInput({
        key: "count_kinds",
        value: ["hardware"],
        default: ["hardware", "virtual_machine"],
        options: ["hardware", "virtual_machine", "software", "service"],
      }),
    ).toBe("set");
    expect(
      settingInput({
        key: "end_of_life_date",
        value: "ldos",
        default: "ldos",
        options: ["end_of_sale", "ldos"],
      }),
    ).toBe("choice");
    expect(settingInput({ key: "currency", value: "USD", default: "USD", options: null })).toBe(
      "text",
    );
    expect(settingInput({ key: "max_items_per_request", value: 1000, default: 1000 })).toBe("text");
  });

  it("makes the kinds of file a list of extensions, to which another is added", () => {
    expect(
      settingInput({
        key: "reference_file_types",
        value: ["pdf", "jpg"],
        default: ["pdf", "jpg", "png"],
        options: ["pdf", "jpg", "png"],
      }),
    ).toBe("extensions");
  });
});

describe("withExtension", () => {
  it("adds an extension as the server keeps it, in lower case and without its dot", () => {
    expect(withExtension(["pdf"], " .KMZ ")).toEqual({ ok: true, list: ["pdf", "kmz"] });
    expect(withExtension([], "dwg")).toEqual({ ok: true, list: ["dwg"] });
  });

  it("refuses nothing typed, and one the list has already", () => {
    expect(withExtension(["pdf"], "  ")).toEqual({
      ok: false,
      error: "Type an extension, as pdf.",
    });
    expect(withExtension(["pdf"], "PDF")).toEqual({
      ok: false,
      error: "pdf is in the list already.",
    });
  });
});

describe("settingValue", () => {
  it("sends a whole number as a number, where the default is one", () => {
    expect(settingValue({ default: 1 }, " 7 ")).toEqual({ ok: true, value: 7 });
    expect(settingValue({ default: 300 }, "450")).toEqual({ ok: true, value: 450 });
  });

  it("sends a decimal as the text that was typed", () => {
    expect(settingValue({ default: 50 }, "30.50")).toEqual({ ok: true, value: "30.50" });
  });

  it("sends a word as it stands", () => {
    expect(settingValue({ default: "USD" }, " eur ")).toEqual({ ok: true, value: "eur" });
  });

  it("refuses what is not a number for a number, and a blank for anything", () => {
    expect(settingValue({ default: 50 }, "half").ok).toBe(false);
    expect(settingValue({ default: 50 }, "-5").ok).toBe(false);
    expect(settingValue({ default: 50 }, "").ok).toBe(false);
    expect(settingValue({ default: "USD" }, "  ").ok).toBe(false);
  });
});

describe("listValue", () => {
  it("sends what is ticked in the order of the options", () => {
    expect(listValue(["Prod", "Test"], ["Test", "Prod", "Down"])).toEqual({
      ok: true,
      value: ["Test", "Prod"],
    });
  });

  it("keeps a value that is not among the options, after them", () => {
    expect(listValue(["Old", "Prod"], ["Test", "Prod"])).toEqual({
      ok: true,
      value: ["Prod", "Old"],
    });
  });

  it("refuses nothing ticked", () => {
    expect(listValue([], ["Test"]).ok).toBe(false);
  });
});
