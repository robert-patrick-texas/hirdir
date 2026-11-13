import { describe, expect, it } from "vitest";
import { settingText, settingValue } from "./settings";

describe("settingText", () => {
  it("writes a number, a word and a list as people read them", () => {
    expect(settingText(50)).toBe("50");
    expect(settingText(30.5)).toBe("30.5");
    expect(settingText("USD")).toBe("USD");
    expect(settingText(["Test", "Prod", "Down"])).toBe("Test, Prod, Down");
  });

  it("is blank for a kind it does not know", () => {
    expect(settingText(null)).toBe("");
    expect(settingText({ a: 1 })).toBe("");
    expect(settingText(Number.NaN)).toBe("");
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
