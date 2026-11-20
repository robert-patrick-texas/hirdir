import { describe, expect, it } from "vitest";
import {
  BLACK,
  colourProblem,
  colourWords,
  contrast,
  isColour,
  luminance,
  pasted,
  placeIn,
  readColour,
  restingStep,
  sameColour,
  stepAfterKey,
  stepOf,
  stepWords,
  textOn,
  WHITE,
} from "./colour";

// The grid and the slider as `GET /colours` gives them (hirdir.domain.colours): a row to
// each shade, the lightest first, the eight hues across; the four middle shades of each hue.
const HUES = [
  ["#fee0dc", "#febfb7", "#ff968a", "#f66d62", "#e24942", "#be2f2c", "#94221f", "#6c1614"],
  ["#fee2cf", "#ffc29a", "#fb9d59", "#ec7c0e", "#c96805", "#a35303", "#7e3f02", "#5c2b00"],
  ["#f4e8bb", "#e5d183", "#d3b63b", "#bb9c00", "#9e8406", "#7f6a03", "#625101", "#463a00"],
  ["#d0f3d0", "#a8e3a9", "#7acf7e", "#4db956", "#11a22f", "#028321", "#016517", "#00480e"],
  ["#b9f5f4", "#7ae6e5", "#0cd1d1", "#0db5b5", "#009a9a", "#027c7c", "#045f5f", "#004444"],
  ["#d9eaff", "#b3d4ff", "#86bafe", "#54a0fe", "#1d84f5", "#0169cd", "#0050a0", "#003975"],
  ["#ebe3fe", "#d9c6fe", "#c4a4fe", "#b082f7", "#9964e5", "#7e4ac2", "#613897", "#45266e"],
  ["#ffddec", "#febad9", "#f990c4", "#e96cad", "#d44996", "#b2307a", "#8a235e", "#651643"],
];
const GRID = Array.from({ length: 8 }, (_, shade) => HUES.map((hue) => hue[shade] ?? ""));
const SLIDER = HUES.flatMap((hue) => hue.slice(2, 6));

describe("a typed colour", () => {
  it("is # and six hex digits, in either case, with blanks around it", () => {
    expect(isColour("#eeaa00")).toBe(true);
    expect(isColour("#EEAA00")).toBe(true);
    expect(isColour(" #eeaa00 ")).toBe(true);
    expect(isColour("eeaa00")).toBe(false);
    expect(isColour("#eea")).toBe(false);
    expect(isColour("#eeaa0g")).toBe(false);
  });

  it("is said to be wrong before it is sent, and blank is no colour", () => {
    expect(colourProblem("")).toBeNull();
    expect(colourProblem("  ")).toBeNull();
    expect(colourProblem("#1f6feb")).toBeNull();
    expect(colourProblem("orange")).toMatch(/^In the form #1f6feb/);
  });

  it("is read before it is sent: none, a colour in lower case, or refused", () => {
    expect(readColour("")).toEqual({ ok: true, colour: null });
    expect(readColour(" #EEAA00 ")).toEqual({ ok: true, colour: "#eeaa00" });
    const refused = readColour("rubbish");
    expect(refused.ok).toBe(false);
    expect(refused.ok ? "" : refused.error).toMatch(/^In the form #1f6feb/);
  });

  it("is pasted whole, without the blanks around it, in place of what is selected", () => {
    expect(pasted("", " #1f6feb ", 0, 0)).toBe("#1f6feb");
    expect(pasted("#eeaa00", "#1F6FEB\n", 0, 7)).toBe("#1F6FEB");
    expect(pasted("#", " 1f6feb", 1, 1)).toBe("#1f6feb");
    expect(colourProblem(pasted("", " #1f6feb", 0, 0))).toBeNull();
  });

  it("is the same colour whatever the case of its letters", () => {
    expect(sameColour("#EEAA00", "#eeaa00")).toBe(true);
    expect(sameColour("#eeaa00", "#eeaa01")).toBe(false);
  });
});

describe("the grid and the slider", () => {
  it("find a value by its shade and hue, and its step", () => {
    expect(placeIn(GRID, "#FB9D59")).toEqual({ row: 2, column: 1 });
    expect(placeIn(GRID, "#123456")).toBeNull();
    expect(stepOf(SLIDER, "#fb9d59")).toBe(4);
    expect(stepOf(SLIDER, "#651643")).toBe(-1);
    expect(stepOf(SLIDER, "")).toBe(-1);
    expect(SLIDER).toHaveLength(32);
  });

  it("name a swatch by its hue, its shade and its value", () => {
    expect(colourWords(GRID, "#fb9d59")).toBe("orange, shade 3 of 8, #fb9d59");
    expect(colourWords(GRID, "#651643")).toBe("pink, shade 8 of 8, #651643");
    expect(colourWords(GRID, "#123456")).toBe("#123456");
  });

  it("say the step in words, and that a value is none of them", () => {
    expect(stepWords(GRID, SLIDER, "#fb9d59")).toBe("Step 5 of 32: orange, shade 3 of 8, #fb9d59");
    expect(stepWords(GRID, SLIDER, "")).toBe("No step: no colour is chosen");
    expect(stepWords(GRID, SLIDER, "#eeaa00")).toBe("No step: #eeaa00 is not one of the 32");
    expect(stepWords(GRID, SLIDER, "#ee")).toBe("No step: what is typed is not a colour");
  });

  it("rest the slider near a value that is none of its steps", () => {
    // The lightest and the darkest shades rest at the nearest middle shade of their hue.
    expect(restingStep(GRID, SLIDER, "#fee0dc")).toBe(0);
    expect(restingStep(GRID, SLIDER, "#6c1614")).toBe(3);
    expect(restingStep(GRID, SLIDER, "#651643")).toBe(31);
    // Any other colour at the step nearest to it; no colour at the first.
    expect(restingStep(GRID, SLIDER, "#eeaa00")).toBe(SLIDER.indexOf("#ec7c0e"));
    expect(restingStep(GRID, SLIDER, "#0dd0d0")).toBe(SLIDER.indexOf("#0cd1d1"));
    expect(restingStep(GRID, SLIDER, "")).toBe(0);
    expect(restingStep(GRID, SLIDER, "#bb9c00")).toBe(SLIDER.indexOf("#bb9c00"));
  });

  it("move the slider by a key as a range input moves, within its ends", () => {
    expect(stepAfterKey(3, "ArrowRight", 32)).toBe(4);
    expect(stepAfterKey(3, "ArrowDown", 32)).toBe(2);
    expect(stepAfterKey(0, "ArrowLeft", 32)).toBe(0);
    expect(stepAfterKey(31, "ArrowUp", 32)).toBe(31);
    expect(stepAfterKey(30, "PageUp", 32)).toBe(31);
    expect(stepAfterKey(9, "PageDown", 32)).toBe(5);
    expect(stepAfterKey(9, "Home", 32)).toBe(0);
    expect(stepAfterKey(9, "End", 32)).toBe(31);
    expect(stepAfterKey(9, "Tab", 32)).toBeNull();
  });
});

describe("the text on a chip", () => {
  it("is black or white, whichever has the greater contrast", () => {
    // The owner's own example: #eeaa00, somewhat orange, takes black.
    expect(textOn("#eeaa00")).toBe(BLACK);
    expect(textOn("#ffffff")).toBe(BLACK);
    expect(textOn("#000000")).toBe(WHITE);
    expect(textOn("#1f6feb")).toBe(WHITE);
    expect(textOn("#fee0dc")).toBe(BLACK);
    expect(textOn("#00480e")).toBe(WHITE);
  });

  it("reckons luminance and contrast as WCAG 2 does", () => {
    expect(luminance("#000000")).toBe(0);
    expect(luminance("#ffffff")).toBeCloseTo(1, 6);
    expect(contrast("#000000", "#ffffff")).toBeCloseTo(21, 6);
    expect(contrast("#ffffff", "#000000")).toBeCloseTo(21, 6);
    expect(contrast("#777777", "#777777")).toBe(1);
  });

  it("is chosen for every swatch so that it reads at least 4.5 to 1", () => {
    for (const swatch of GRID.flat()) {
      expect(contrast(swatch, textOn(swatch))).toBeGreaterThanOrEqual(4.5);
    }
  });
});
