// Settings as text, and text as a setting's value. A setting's value is whatever kind
// its default is: a number, a word or a list. The server checks every value it is sent.
//
// `GET /settings` lists the settings of the inventory, which an Admin changes, and after
// them the values that are fixed in the code (D-187): each with `fixed` true, what it
// limits and why it is fixed. A fixed value is listed and never changed.

interface Setting {
  default: unknown;
}

/** What the page needs of a setting or a fixed value to tell them apart and show them. */
export interface Listed {
  key: string;
  value: unknown;
  default: unknown;
  fixed?: boolean | undefined;
  options?: readonly string[] | null | undefined;
}

/** A setting's value as people read it. Blank for a kind this build does not know. */
export function settingText(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  if (Array.isArray(value)) return value.map(String).join(", ");
  // A fixed value may say something of each of several things, as what each condition
  // says of health: each thing with what it holds, one after another.
  if (value !== null && typeof value === "object") {
    return Object.entries(value)
      .map(([name, held]) => `${name}: ${settingText(held)}`)
      .join("; ");
  }
  return "";
}

/** The settings that may be changed, and after them the values fixed in the code. */
export function splitSettings<T extends Listed>(all: readonly T[]): { settings: T[]; fixed: T[] } {
  return {
    settings: all.filter((one) => one.fixed !== true),
    fixed: all.filter((one) => one.fixed === true),
  };
}

/**
 * How a new value of a setting is given: ticked from its options where it is a list,
 * chosen from them where it is one value of a list, and typed otherwise.
 */
export type SettingInput = "set" | "choice" | "text";

export function settingInput(setting: Listed): SettingInput {
  const listed = Array.isArray(setting.value) || Array.isArray(setting.default);
  if (listed) return "set";
  return setting.options && setting.options.length > 0 ? "choice" : "text";
}

export type SettingRead = { ok: true; value: unknown } | { ok: false; error: string };

/**
 * What was typed, as the value to send for a setting.
 *
 * A setting whose default is a whole number is sent a whole number. A decimal is sent
 * as the text that was typed, so that it reaches the server digit for digit. A word is
 * sent as it stands. Blank is not a value: returning to the default is its own action.
 */
export function settingValue(setting: Setting, typed: string): SettingRead {
  const text = typed.trim();
  if (text === "") return { ok: false, error: "Give a value, or return it to its default." };
  if (typeof setting.default === "number") {
    if (/^\d{1,15}$/.test(text)) return { ok: true, value: Number.parseInt(text, 10) };
    if (/^\d+\.\d+$/.test(text)) return { ok: true, value: text };
    return { ok: false, error: "A number that is not negative." };
  }
  return { ok: true, value: text };
}

/**
 * The values ticked for a setting that is a list, as they are sent: in the order of its
 * options, so that the same choice is always sent the same way. One at least: a list
 * setting holds one or more.
 */
export function listValue(chosen: readonly string[], options: readonly string[]): SettingRead {
  if (chosen.length === 0) return { ok: false, error: "Tick one at least." };
  const known = options.filter((option) => chosen.includes(option));
  const others = chosen.filter((value) => !options.includes(value));
  return { ok: true, value: [...known, ...others] };
}
