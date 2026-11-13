// Settings as text, and text as a setting's value. A setting's value is whatever kind
// its default is: a number, a word or a list. The server checks every value it is sent.

interface Setting {
  default: unknown;
}

/** A setting's value as people read it. Blank for a kind this build does not know. */
export function settingText(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  if (Array.isArray(value)) return value.map(String).join(", ");
  return "";
}

export type SettingRead = { ok: true; value: unknown } | { ok: false; error: string };

/**
 * What was typed, as the value to send for a setting.
 *
 * A setting whose default is a whole number is sent a whole number. A decimal is sent
 * as the text that was typed, so that it reaches the server digit for digit. A word is
 * sent as it stands. Blank is not a value: resetting to the default is its own action.
 */
export function settingValue(setting: Setting, typed: string): SettingRead {
  const text = typed.trim();
  if (text === "") return { ok: false, error: "Give a value, or reset to the default." };
  if (typeof setting.default === "number") {
    if (/^\d{1,15}$/.test(text)) return { ok: true, value: Number.parseInt(text, 10) };
    if (/^\d+\.\d+$/.test(text)) return { ok: true, value: text };
    return { ok: false, error: "A number that is not negative." };
  }
  return { ok: true, value: text };
}
