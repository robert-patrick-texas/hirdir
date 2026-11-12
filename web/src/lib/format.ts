// Turning what the server sends into text for people.

const NONE = "(none)";

/** One value of an audit change, as text. */
export function formatValue(value: unknown): string {
  if (value === null || value === undefined) return NONE;
  if (typeof value === "string") return value === "" ? '""' : value;
  if (typeof value === "number" || typeof value === "boolean" || typeof value === "bigint") {
    return String(value);
  }
  try {
    return JSON.stringify(value) ?? String(value);
  } catch {
    return String(value);
  }
}

/** One entry of an audit event's `changes`, as "field: old → new". */
export function formatChange(change: Readonly<Record<string, unknown>>): string {
  const { field } = change;
  if (typeof field !== "string" || field === "") return formatValue(change);
  return `${field}: ${formatValue(change.old)} → ${formatValue(change.new)}`;
}

/** Every entry of an audit event's `changes`, one line each. */
export function formatChanges(
  changes: ReadonlyArray<Readonly<Record<string, unknown>>> | null | undefined,
): string[] {
  return (changes ?? []).map(formatChange);
}

function two(value: number): string {
  return String(value).padStart(2, "0");
}

/** A moment in the reader's own time zone, as `2026-01-31 14:05:09`. Blank when there is none. */
export function formatTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return iso;
  const date = `${at.getFullYear()}-${two(at.getMonth() + 1)}-${two(at.getDate())}`;
  return `${date} ${two(at.getHours())}:${two(at.getMinutes())}:${two(at.getSeconds())}`;
}

/** "1 second", "2 seconds". */
export function plural(count: number, one: string, many = `${one}s`): string {
  return `${count} ${count === 1 ? one : many}`;
}
