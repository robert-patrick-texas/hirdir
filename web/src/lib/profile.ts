// 0.9.14: a person's own profile (P-289, P-294, P-295). What its page reckons without a
// page: the fields of its forms, what is wrong with the three boxes of the access code
// before anything is sent, and the least length the setting says.

import type { FieldSpec } from "./patch";

/** The fields of the contact a person is, which they change themselves, in order. */
export const DETAIL_SPECS: readonly FieldSpec[] = [
  {
    name: "name",
    label: "Name",
    kind: "text",
    required: true,
    maxLength: 200,
    hint: "Your name, as every list shows it.",
  },
  {
    name: "email",
    label: "Email",
    kind: "text",
    maxLength: 254,
    hint: "Belongs to one contact only.",
  },
  { name: "phone", label: "Phone", kind: "text", maxLength: 50 },
  { name: "phone2", label: "Second phone", kind: "text", maxLength: 50 },
  { name: "organization", label: "Organization", kind: "text", maxLength: 200 },
];

/** The fields of an operator that the person behind it changes: its label and its colour. */
export const OPERATOR_SPECS: readonly FieldSpec[] = [
  {
    name: "label",
    label: "Label",
    kind: "text",
    required: true,
    maxLength: 40,
    hint: "Short, and of your choosing: initials, a surname, a code such as Op2. It is what lists and reports show.",
  },
  {
    name: "colour",
    label: "Colour",
    kind: "colour",
    hint: "Press a colour, move the slider, or type one in the form #1f6feb. A dot in this colour stands beside the label. Blank is no colour.",
    sample: (values) => (typeof values.label === "string" ? values.label : ""),
    sampleAs: "operator",
  },
];

/** The setting that says the least length of an access code that is typed (P-295). */
export const MIN_LENGTH_KEY = "access_code_min_length";

/**
 * The least length of a typed access code, from the settings as `GET /settings` lists
 * them, or null where they do not say: not read yet, not read at all, or no whole number
 * of one or more. The page then names no length, and the server still holds the code to it.
 */
export function minLengthOf(
  settings: ReadonlyArray<{ key: string; value?: unknown }> | null | undefined,
): number | null {
  const value = settings?.find((setting) => setting.key === MIN_LENGTH_KEY)?.value;
  return typeof value === "number" && Number.isInteger(value) && value >= 1 ? value : null;
}

/** What the page says of a new access code before one is typed. */
export function codeWords(least: number | null): string {
  const length =
    least === null ? "" : `At least ${least} ${least === 1 ? "character" : "characters"}. `;
  return `${length}Your other sessions end when it is changed; this one stays signed in.`;
}

/** The three boxes of the access code: the code in hand, the new one, and the new one again. */
export interface CodeBoxes {
  current: string;
  wanted: string;
  again: string;
}

/** The boxes as the page opens them, and as it leaves them once the code is changed. */
export const NO_CODES: CodeBoxes = { current: "", wanted: "", again: "" };

/**
 * What is wrong with the three boxes before anything is sent, by the name of the box. A
 * box left empty is said at once: an empty code in hand would be refused as a wrong one,
 * and counted against the person as a failed sign-in is. Two new codes that differ are
 * said at the second. How long the new code must be is left to the server, which says it.
 */
export function codeProblems(boxes: CodeBoxes): Record<string, string> {
  const found: Record<string, string> = {};
  if (boxes.current === "") found.current_access_code = "Type the access code you have.";
  if (boxes.wanted === "") found.access_code = "Type a new access code.";
  if (boxes.again !== boxes.wanted) {
    found.access_code_again = "The two new codes differ. Type the same code in both.";
  }
  return found;
}
