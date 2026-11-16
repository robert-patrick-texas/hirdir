// 0.8.0: Try, the what-if of the capacity report (P-141, P-156). What the panel holds,
// as text the way it was typed, and the request it sends: every figure that is not the
// one in force, the staff lines changed, left out and added. The server checks each and
// works both balances out; nothing is saved, and the answer is never kept.

import type { Schemas } from "../api/client";
import { settingText } from "./settings";
import { isWeightSetting, WEIGHT_SETTINGS, weightSettingLabel } from "./weights";

export type TryBody = Schemas["CapacityTry"];
export type TryAnswer = Schemas["CapacityTryOut"];
export type Tried = Schemas["CapacityTried"];

/** The eight figures a Try may change, by the names of their settings. */
export const FIGURE_KEYS = [
  ...WEIGHT_SETTINGS,
  "weight_per_resource_unit",
  "stack_discount_pct",
] as const;
export type FigureKey = (typeof FIGURE_KEYS)[number];
export type Figures = Record<FigureKey, string>;

export function isFigureKey(key: string): key is FigureKey {
  return (FIGURE_KEYS as readonly string[]).includes(key);
}

/** A figure as people read it. */
export function figureLabel(key: FigureKey): string {
  if (key === "weight_per_resource_unit") return "Support weight one engineer carries";
  if (key === "stack_discount_pct") return "Stack discount, percent";
  return weightSettingLabel(key);
}

/** What a figure is, beside its input. */
export function figureHint(key: FigureKey): string {
  if (key === "weight_per_resource_unit") {
    return "The support weight one resource unit carries: a mid-level position, by convention. Blank tries its default.";
  }
  if (key === "stack_discount_pct") {
    return "Taken off each member of a stack whose model sets none. Blank tries its default.";
  }
  if (key.startsWith("default_")) return "Counted where one of its kind gives none. Blank: none.";
  return "A weight below it is raised to it. Blank: none.";
}

/** What `GET /settings` gives the panel of a setting. */
interface Setting {
  key: string;
  value: unknown;
}

/** The figures in force, as the inputs start with them: a blank weight is blank. */
export function figuresOf(settings: readonly Setting[]): Figures {
  const figures = Object.fromEntries(FIGURE_KEYS.map((key) => [key, ""])) as Figures;
  for (const setting of settings) {
    if (isFigureKey(setting.key)) figures[setting.key] = settingText(setting.value);
  }
  return figures;
}

/** A staff line that is there, as the panel holds it. */
export interface StaffLineTry {
  hid: string;
  name: string;
  /** Whether it counts as it is: a draft or a line out of date does not, in force. */
  standing: "active" | "draft" | "out of date";
  /** As the line has them. */
  quantity: string;
  unitsEach: string;
  /** As they are tried. */
  triedQuantity: string;
  triedUnitsEach: string;
  leaveOut: boolean;
}

/** A staff line that is not there, to be tried as if it were. */
export interface AddedLine {
  /** Which row of the panel it is: never sent. */
  id: number;
  name: string;
  quantity: string;
  unitsEach: string;
}

/** What the panel needs of a capacity line. */
interface Line {
  hid: string;
  name: string;
  quantity: string | null;
  units_each: string | null;
  record_status: string;
  in_date: boolean;
}

export function staffLinesOf(lines: readonly Line[]): StaffLineTry[] {
  return lines
    .filter((line) => line.record_status !== "retired")
    .map((line) => ({
      hid: line.hid,
      name: line.name,
      standing: line.record_status === "draft" ? "draft" : line.in_date ? "active" : "out of date",
      quantity: line.quantity ?? "",
      unitsEach: line.units_each ?? "",
      triedQuantity: line.quantity ?? "",
      triedUnitsEach: line.units_each ?? "",
      leaveOut: false,
    }));
}

/** A Try to send, and which row of the panel each line of it came from. */
export interface TryRequest {
  body: TryBody;
  /** The HID of the line of each entry of `staff.change`, in order. */
  changed: string[];
  /** The id of the row of each entry of `staff.add`, in order. */
  added: number[];
}

function differs(typed: string, was: string): boolean {
  return typed.trim() !== was.trim();
}

/**
 * The request of a Try: each figure whose text is not the one in force, blank as null,
 * which tries it at its default; the staff lines whose quantity or units of one were
 * changed, with what was changed alone; those left out; and the rows added that hold
 * anything, a row left wholly blank being no line.
 */
export function tryRequest(
  figures: Figures,
  inForce: Figures,
  lines: readonly StaffLineTry[],
  added: readonly AddedLine[],
): TryRequest {
  const body: TryBody = {};
  for (const key of FIGURE_KEYS) {
    if (!differs(figures[key], inForce[key])) continue;
    const text = figures[key].trim();
    body[key] = text === "" ? null : text;
  }
  const change: NonNullable<NonNullable<TryBody["staff"]>["change"]> = [];
  const changed: string[] = [];
  const leaveOut: string[] = [];
  for (const line of lines) {
    if (line.leaveOut) {
      leaveOut.push(line.hid);
      continue;
    }
    const quantity = line.triedQuantity.trim();
    const unitsEach = line.triedUnitsEach.trim();
    const one: { hid: string; quantity?: string; units_each?: string } = { hid: line.hid };
    if (quantity !== "" && differs(quantity, line.quantity)) one.quantity = quantity;
    if (unitsEach !== "" && differs(unitsEach, line.unitsEach)) one.units_each = unitsEach;
    if (one.quantity === undefined && one.units_each === undefined) continue;
    change.push(one);
    changed.push(line.hid);
  }
  const add: NonNullable<NonNullable<TryBody["staff"]>["add"]> = [];
  const addedIds: number[] = [];
  for (const row of added) {
    const name = row.name.trim();
    const quantity = row.quantity.trim();
    const unitsEach = row.unitsEach.trim();
    if (name === "" && quantity === "" && unitsEach === "") continue;
    add.push({ name, units_each: unitsEach, ...(quantity === "" ? {} : { quantity }) });
    addedIds.push(row.id);
  }
  if (change.length > 0 || leaveOut.length > 0 || add.length > 0) {
    body.staff = {
      ...(add.length > 0 ? { add } : {}),
      ...(change.length > 0 ? { change } : {}),
      ...(leaveOut.length > 0 ? { leave_out: leaveOut } : {}),
    };
  }
  return { body, changed, added: addedIds };
}

/** Where the server's message of each input of the panel is found, by the field it names. */
export function staffFields(request: TryRequest): {
  change: Map<string, number>;
  add: Map<number, number>;
} {
  return {
    change: new Map(request.changed.map((hid, place) => [hid, place])),
    add: new Map(request.added.map((id, place) => [id, place])),
  };
}

/** A setting a Try changed, as an Admin saves it: by its key, at the value tried. */
export interface ToSave {
  key: FigureKey;
  value: string | null;
}

/**
 * The settings to save of a Try: those its answer says were changed, each at the value
 * it was tried with, blank as null, which returns it to its default.
 */
export function settingsToSave(tried: Tried): ToSave[] {
  return tried.changed.filter(isFigureKey).map((key) => ({ key, value: tried[key] }));
}

/** A value tried, as text: blank says so. */
export function triedText(key: FigureKey, value: string | null): string {
  if (value !== null && value !== "") return value;
  return isWeightSetting(key) ? "blank" : "its default";
}
