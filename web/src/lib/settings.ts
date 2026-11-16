// Settings as text, and text as a setting's value. A setting's value is whatever kind
// its default is: a number, a word, a list, or since 0.9.2 true or false
// (`help_on_sign_in`, P-169). The server checks every value it is sent.
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
  if (typeof value === "boolean") return value ? "Yes" : "No";
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
 * chosen from them where it is one value of a list, Yes or No where it is true or false,
 * and typed otherwise, as a setting whose default is blank is. A list of the extensions
 * of files is a list of its own, to which an Admin adds any other.
 */
export type SettingInput = "set" | "choice" | "flag" | "text" | "extensions";

/** The two values of a setting that is true or false, as the form offers them. */
export const FLAG_OPTIONS: ReadonlyArray<{ value: "true" | "false"; label: string }> = [
  { value: "true", label: "Yes" },
  { value: "false", label: "No" },
];

/** Whether a setting is true or false, by its default or its value. */
function isFlag(setting: Pick<Listed, "value" | "default">): boolean {
  return typeof setting.default === "boolean" || typeof setting.value === "boolean";
}

/** What the form of a setting starts with: its value as it is typed, or as it is chosen. */
export function settingStart(setting: Listed): string {
  if (isFlag(setting)) return setting.value === true ? "true" : "false";
  return settingText(setting.value);
}

/**
 * 0.9.0: the settings that are a list of the extensions of files, whose options are only
 * those hirdir knows: an Admin may add another (P-159).
 */
const EXTENSION_LISTS: readonly string[] = ["reference_file_types"];

export function settingInput(setting: Listed): SettingInput {
  if (EXTENSION_LISTS.includes(setting.key)) return "extensions";
  const listed = Array.isArray(setting.value) || Array.isArray(setting.default);
  if (listed) return "set";
  if (isFlag(setting)) return "flag";
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
  // 0.9.2: true or false is sent as JSON's true or false, and nothing else (P-169).
  if (typeof setting.default === "boolean") {
    if (text === "true" || text === "false") return { ok: true, value: text === "true" };
    return { ok: false, error: "Choose Yes or No." };
  }
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
export type ExtensionAdded = { ok: true; list: string[] } | { ok: false; error: string };

/**
 * A list of extensions with one more, as it was typed: in lower case and without the dot
 * before it, `.DWG` as `dwg`. What an extension may be is the server's to say, and it
 * says so when the list is set.
 */
export function withExtension(list: readonly string[], typed: string): ExtensionAdded {
  const extension = typed.trim().toLowerCase().replace(/^\.+/, "");
  if (extension === "") return { ok: false, error: "Type an extension, as pdf." };
  if (list.includes(extension)) return { ok: false, error: `${extension} is in the list already.` };
  return { ok: true, list: [...list, extension] };
}

export function listValue(chosen: readonly string[], options: readonly string[]): SettingRead {
  if (chosen.length === 0) return { ok: false, error: "Tick one at least." };
  const known = options.filter((option) => chosen.includes(option));
  const others = chosen.filter((value) => !options.includes(value));
  return { ok: true, value: [...known, ...others] };
}
