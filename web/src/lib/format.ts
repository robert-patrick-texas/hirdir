// Turning what the server sends into text for people.

const NONE = "(none)";
// A full timestamp with its zone, as the server writes one: 2026-01-31T19:05:09.123Z.
const MOMENT = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})$/;

/** One value of an audit change, as text. */
export function formatValue(value: unknown): string {
  if (value === null || value === undefined) return NONE;
  if (typeof value === "string") {
    if (value === "") return '""';
    // A moment in an audit change is shown as every other moment is.
    return MOMENT.test(value) ? formatTime(value) : value;
  }
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

/**
 * Every time is shown in the application's time zone, so that everybody refers to the
 * same time whatever zone they sit in. It is the installation's `time_zone` setting, and
 * this zone until that has been read.
 */
export const DEFAULT_ZONE = "America/New_York";
let zoneInUse = DEFAULT_ZONE;

function isZone(zone: string): boolean {
  try {
    new Intl.DateTimeFormat("en-US", { timeZone: zone });
    return true;
  } catch {
    return false;
  }
}

/** Take the installation's `time_zone` setting as the zone every time is shown in. */
export function setZone(zone: unknown): void {
  zoneInUse = typeof zone === "string" && isZone(zone) ? zone : DEFAULT_ZONE;
}

/** The application's time zone: the one every time on a page is shown in. */
export function appZone(): string {
  return zoneInUse;
}

const SHORT: Intl.DateTimeFormatOptions = {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
  timeZoneName: "short",
};
const LONG: Intl.DateTimeFormatOptions = { dateStyle: "full", timeStyle: "long" };
// A grid formats thousands of times: one formatter for each zone, made once.
const formatters = new Map<string, Intl.DateTimeFormat>();

function formatter(zone: string, options: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
  const key = `${zone} ${options.dateStyle ?? "short"}`;
  let made = formatters.get(key);
  if (made === undefined) {
    made = new Intl.DateTimeFormat("en-US", { ...options, timeZone: zone });
    formatters.set(key, made);
  }
  return made;
}

/**
 * A moment in the application's time zone, with the zone's short name, as
 * `2026-01-31 14:05:09 EST`. Blank when there is none.
 */
export function formatTime(iso: string | null | undefined, zone: string = appZone()): string {
  if (!iso) return "";
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return iso;
  const part: Record<string, string> = {};
  for (const { type, value } of formatter(zone, SHORT).formatToParts(at)) part[type] = value;
  const date = `${part.year}-${part.month}-${part.day}`;
  return `${date} ${part.hour}:${part.minute}:${part.second} ${part.timeZoneName}`;
}

/** The same moment written out in full, with the name of the zone it is shown in. */
export function formatTimeLong(iso: string | null | undefined, zone: string = appZone()): string {
  if (!iso) return "";
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return iso;
  return `${formatter(zone, LONG).format(at)} (${zone})`;
}

/** What a zone's clocks show at a moment, as if that reading were a time in UTC. */
function reading(at: number, zone: string): number {
  const part: Record<string, number> = {};
  for (const { type, value } of formatter(zone, SHORT).formatToParts(new Date(at))) {
    part[type] = Number(value);
  }
  const { year = 0, month = 1, day = 1, hour = 0, minute = 0, second = 0 } = part;
  return Date.UTC(year, month - 1, day, hour, minute, second);
}

/**
 * The moment at which a zone's clocks show a date and a time of day. A day of the month
 * past the end of the month runs on into the next, as it does for a Date.
 */
export function momentIn(
  zone: string,
  year: number,
  month: number,
  day: number,
  hour = 0,
  minute = 0,
  second = 0,
): Date {
  const wanted = Date.UTC(year, month - 1, day, hour, minute, second);
  let at = wanted;
  // The zone's offset is not known until the moment is: two steps find it, also on the
  // day the clocks change.
  for (let step = 0; step < 3; step += 1) {
    const off = wanted - reading(at, zone);
    if (off === 0) break;
    at += off;
  }
  return new Date(at);
}

/**
 * Today's date in the application's time zone, as `2026-01-31`: the day a membership
 * ends or a replacement is made when nobody says otherwise, as the server has it.
 */
export function today(zone: string = appZone(), now: Date = new Date()): string {
  const part: Record<string, string> = {};
  for (const { type, value } of formatter(zone, SHORT).formatToParts(now)) part[type] = value;
  return `${part.year}-${part.month}-${part.day}`;
}

/** "1 second", "2 seconds". */
export function plural(count: number, one: string, many = `${one}s`): string {
  return `${count} ${count === 1 ? one : many}`;
}

/** A MAC address as people write it: twelve stored hex digits as `00:00:5e:00:53:02`. */
export function formatMac(digits: string | null | undefined): string {
  if (!digits) return "";
  return /^[0-9a-f]{12}$/i.test(digits) ? (digits.match(/../g) ?? []).join(":") : digits;
}

/** What to call an item: its name, or the hostname, serial number or asset tag standing in. */
export function itemName(item: {
  name?: string | null;
  hostname?: string | null;
  serial_number?: string | null;
  asset_tag?: string | null;
}): string {
  return item.name || item.hostname || item.serial_number || item.asset_tag || "(no name)";
}
