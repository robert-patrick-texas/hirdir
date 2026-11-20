// 0.9.13: a colour is chosen from a grid of 64, by a slider of 32, or typed (P-285).
//
// What is stored is `#rrggbb`, whatever it is. The grid and the slider are what a form
// offers to press, as `GET /colours` gives them, and a colour that is not among them is
// as good as one that is. This holds what the picker reckons without a page: where a
// value is in the grid and on the slider, what a swatch and a step are called in words,
// the step a key moves the slider to, what is wrong with a typed value, and whether black
// or white text is read better on a colour.

/** The hues of the grid's columns, in the order of the rainbow, as the server fixes them. */
export const HUES = ["red", "orange", "yellow", "green", "teal", "blue", "violet", "pink"] as const;

type Grid = readonly (readonly string[])[];

const COLOUR = /^#[0-9a-f]{6}$/i;

/** A colour as the server takes it, `#rrggbb` in either case, after the blanks around it. */
export function isColour(typed: string): boolean {
  return COLOUR.test(typed.trim());
}

/** Whether two values are the same colour: the case of the letters says nothing. */
export function sameColour(one: string, other: string): boolean {
  return one.trim().toLowerCase() === other.trim().toLowerCase();
}

/**
 * What is wrong with a typed colour, said before anything is sent, or null where it is
 * acceptable. Blank is no colour, and acceptable.
 */
export function colourProblem(typed: string): string | null {
  if (typed.trim() === "" || isColour(typed)) return null;
  return "In the form #1f6feb: a # and six of the digits 0 to 9 and the letters a to f.";
}

/**
 * The box once something is pasted into it: the pasted text, without the blanks around
 * it, in place of what was selected. A paste is never cut short: it is judged whole.
 */
export function pasted(value: string, text: string, start: number, end: number): string {
  return `${value.slice(0, start)}${text.trim()}${value.slice(end)}`.trim();
}

/** Where a swatch is in the grid: its row, which is its shade, and its column, its hue. */
export interface Place {
  row: number;
  column: number;
}

/** Where a value is in the grid, or null where it is none of its swatches. */
export function placeIn(grid: Grid, value: string): Place | null {
  for (const [row, swatches] of grid.entries()) {
    const column = swatches.findIndex((swatch) => sameColour(swatch, value));
    if (column >= 0) return { row, column };
  }
  return null;
}

/** The step of the slider a value is, or -1 where it is none of them. */
export function stepOf(slider: readonly string[], value: string): number {
  if (value.trim() === "") return -1;
  return slider.findIndex((step) => sameColour(step, value));
}

function channels(colour: string): [number, number, number] | null {
  if (!isColour(colour)) return null;
  const hex = colour.trim().slice(1);
  return [0, 2, 4].map((at) => Number.parseInt(hex.slice(at, at + 2), 16)) as [
    number,
    number,
    number,
  ];
}

/**
 * Where the slider stands for a value that is none of its steps, so that a move goes on
 * from near it: for a swatch of the grid, the step of the same hue nearest in shade; for
 * any other colour, the step nearest to it in red, green and blue; for no colour, the
 * first. The slider shows no choice there: it only waits (see `stepWords`).
 */
export function restingStep(grid: Grid, slider: readonly string[], value: string): number {
  const at = stepOf(slider, value);
  if (at >= 0 || slider.length === 0) return Math.max(at, 0);
  const place = placeIn(grid, value);
  let best = 0;
  let bestDistance = Number.POSITIVE_INFINITY;
  if (place) {
    for (const [step, colour] of slider.entries()) {
      const there = placeIn(grid, colour);
      if (there?.column !== place.column) continue;
      const distance = Math.abs(there.row - place.row);
      if (distance < bestDistance) [best, bestDistance] = [step, distance];
    }
    if (bestDistance < Number.POSITIVE_INFINITY) return best;
  }
  const wanted = channels(value);
  if (!wanted) return 0;
  for (const [step, colour] of slider.entries()) {
    const have = channels(colour);
    if (!have) continue;
    const distance = have.reduce((sum, part, index) => sum + (part - (wanted[index] ?? 0)) ** 2, 0);
    if (distance < bestDistance) [best, bestDistance] = [step, distance];
  }
  return best;
}

/**
 * The step a key moves the slider to from the step it stands at, as a range input moves
 * by itself: one step for an arrow, four (a hue) for Page Up and Page Down, the ends for
 * Home and End. Null for a key that does not move it.
 */
export function stepAfterKey(from: number, key: string, count: number): number | null {
  const last = Math.max(count - 1, 0);
  const moved: Record<string, number> = {
    ArrowRight: from + 1,
    ArrowUp: from + 1,
    ArrowLeft: from - 1,
    ArrowDown: from - 1,
    PageUp: from + 4,
    PageDown: from - 4,
    Home: 0,
    End: last,
  };
  const to = moved[key];
  return to === undefined ? null : Math.min(Math.max(to, 0), last);
}

/** A swatch in words: its hue, its shade and its value, as `orange, shade 3 of 8, #fb9d59`. */
export function colourWords(grid: Grid, value: string): string {
  const place = placeIn(grid, value);
  const hue = place ? HUES[place.column] : undefined;
  if (!place || hue === undefined) return value.trim();
  return `${hue}, shade ${place.row + 1} of ${grid.length}, ${value.trim()}`;
}

/**
 * What the slider holds, in words. A range input always stands at one of its steps;
 * where the value is none of them, it says so here, and its thumb is drawn hollow.
 */
export function stepWords(grid: Grid, slider: readonly string[], value: string): string {
  const step = stepOf(slider, value);
  if (step >= 0) return `Step ${step + 1} of ${slider.length}: ${colourWords(grid, value)}`;
  if (value.trim() === "") return `No step: no colour is chosen`;
  if (!isColour(value)) return `No step: what is typed is not a colour`;
  return `No step: ${value.trim()} is not one of the ${slider.length}`;
}

/** The relative luminance of a colour, as WCAG 2 reckons it: 0 for black, 1 for white. */
export function luminance(colour: string): number {
  const parts = channels(colour);
  if (!parts) return 0;
  const [red, green, blue] = parts.map((part) => {
    const value = part / 255;
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  }) as [number, number, number];
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
}

/** The contrast of two colours, as WCAG 2 reckons it: from 1 to 21. */
export function contrast(one: string, other: string): number {
  const [light, dark] = [luminance(one), luminance(other)].sort((a, b) => b - a) as [
    number,
    number,
  ];
  return (light + 0.05) / (dark + 0.05);
}

export const BLACK = "#000000";
export const WHITE = "#ffffff";

/**
 * The text that is read better on a colour: black or white, whichever has the greater
 * contrast with it, black where the two are equal.
 */
export function textOn(colour: string): typeof BLACK | typeof WHITE {
  return contrast(colour, BLACK) >= contrast(colour, WHITE) ? BLACK : WHITE;
}
