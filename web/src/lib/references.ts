// References: a file that hirdir keeps, or a link to one kept elsewhere, each with a
// title and a kind, on one record or more (P-158 to P-162).
//
// A record lists its own, then those it has from the records it stands under, nearest
// first, each once and with where it comes from: the server works that out, and the page
// shows the list in groups, one for each record a reference comes from. A file is never
// opened as part of the page: a picture is shown from a copy the page fetched itself, and
// every other file is handed to the browser to save, typed so that it cannot be opened
// as a page (P-159).

import type { ApiError, Schemas } from "../api/client";
import { plural } from "./format";
import { placePath } from "./places";
import { sentence } from "./problems";

export type Reference = Schemas["ReferenceFileOut"];
export type Listed = Schemas["ListedReference"];
export type Source = Listed["source"];
/** The kinds of record a reference may be on. */
export type RecordKind = Schemas["ReferenceRecord"]["record_type"];

/** The list of choices that holds the kinds of reference. */
export const KIND_LIST = "reference_kind";
/** The most characters of a title. */
export const MAX_TITLE = 200;
/** The most references the server lists at once. */
export const PAGE = 1000;

/** The record a page shows, which its section of files and links is of. */
export interface Holder {
  kind: RecordKind;
  hid: string;
}

/** What a record is called in a sentence: "location", "catalog entry". */
export function recordNoun(kind: RecordKind): string {
  return kind === "catalog_entry" ? "catalog entry" : kind;
}

/** The page of a record that a reference is on. */
export function recordPage(kind: RecordKind, hid: string): string {
  const id = encodeURIComponent(hid);
  switch (kind) {
    case "catalog_entry":
      return `/catalog/${id}`;
    case "circuit":
      return `/circuits/${id}`;
    case "item":
      return `/items/${id}`;
    default:
      return placePath(kind, hid);
  }
}

/** The kind of record a listed reference comes from, for the link to it. */
export function sourceKind(source: Source, holder: RecordKind): RecordKind {
  if (source === "own") return holder;
  return source === "catalog" ? "catalog_entry" : source;
}

/** The references of one record that another lists: its own, its model's, a place's. */
export interface Group {
  /** The record they are attached to. */
  sourceHid: string;
  source: Source;
  /** That record's path or name. */
  label: string;
  references: Listed[];
}

/**
 * The references a record lists, in groups by the record each is attached to, in the
 * order the server lists them: its own first, then its model's, then each place
 * outward. Within a group they keep the server's order, by title.
 */
export function groupsOf(listed: readonly Listed[]): Group[] {
  const groups = new Map<string, Group>();
  for (const one of listed) {
    const key = one.source === "own" ? "own" : one.source_hid;
    let group = groups.get(key);
    if (group === undefined) {
      group = {
        sourceHid: one.source_hid,
        source: one.source,
        label: one.source_label,
        references: [],
      };
      groups.set(key, group);
    }
    group.references.push(one);
  }
  return [...groups.values()];
}

/** The pictures of a list, in its order: what the viewer moves through. */
export function picturesOf<T extends Pick<Listed, "form" | "shown_in_page" | "content_missing">>(
  listed: readonly T[],
): T[] {
  return listed.filter((one) => one.form === "file" && one.shown_in_page && !one.content_missing);
}

const UNITS = ["KB", "MB", "GB", "TB"] as const;

/**
 * A size as people read it: `512 bytes`, `2.4 MB`, `14 MB`. A kilobyte is 1,024 bytes,
 * as the limit of a file is counted. One decimal under ten, whole numbers above.
 */
export function sizeText(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || !Number.isFinite(bytes) || bytes < 0) return "";
  if (bytes < 1024) return plural(Math.round(bytes), "byte");
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < UNITS.length - 1) {
    value /= 1024;
    unit += 1;
  }
  let shown = value < 10 ? Math.round(value * 10) / 10 : Math.round(value);
  // Rounded up to the next unit: 1,023.7 KB is 1 MB.
  if (shown >= 1024 && unit < UNITS.length - 1) {
    shown = 1;
    unit += 1;
  }
  return `${Number.isInteger(shown) ? shown : shown.toFixed(1)} ${UNITS[unit]}`;
}

/** The name of a file without any directory it was given with. */
function baseName(fileName: string): string {
  return fileName.replace(/\\/g, "/").split("/").pop() ?? "";
}

/**
 * The extension of a file name in lower case, as the server reads it: what follows the
 * last dot, where something comes before that dot. Blank where it has none.
 */
export function extensionOf(fileName: string): string {
  const name = baseName(fileName);
  const dot = name.lastIndexOf(".");
  return dot > 0 ? name.slice(dot + 1).toLowerCase() : "";
}

/** The title a file is given to start with: its name without the extension. */
export function titleOf(fileName: string): string {
  const name = baseName(fileName).trim();
  const dot = name.lastIndexOf(".");
  const stem = dot > 0 ? name.slice(0, dot).trim() : name;
  return stem.slice(0, MAX_TITLE);
}

/** The extensions of the pictures hirdir knows, which a photograph usually is. */
const PICTURES: readonly string[] = [
  "jpg",
  "jpeg",
  "png",
  "gif",
  "webp",
  "heic",
  "heif",
  "tif",
  "tiff",
];

/**
 * The kind a file is given to start with, where one is a sensible first choice: a
 * picture is a photograph, and a catalog entry's file its administration guide. Blank
 * otherwise: the person chooses. `kinds` are the values the list offers.
 */
export function firstKind(holder: RecordKind, fileName: string, kinds: readonly string[]): string {
  const wanted = PICTURES.includes(extensionOf(fileName))
    ? "photograph"
    : holder === "catalog_entry"
      ? "administration_guide"
      : "";
  return kinds.includes(wanted) ? wanted : "";
}

/** The kinds of file a reference may be, as the settings say. */
export interface FileTypes {
  /** What `reference_file_types` takes: null where the settings do not say. */
  taken: string[] | null;
  /** What `refused_file_types` never takes. */
  refused: string[];
}

function extensions(value: unknown): string[] | null {
  return Array.isArray(value) && value.every((one) => typeof one === "string") ? value : null;
}

/** The kinds of file taken and refused, from the settings and the values fixed beside them. */
export function fileTypesOf(settings: ReadonlyArray<{ key: string; value: unknown }>): FileTypes {
  const of = (key: string) => extensions(settings.find((one) => one.key === key)?.value);
  return { taken: of("reference_file_types"), refused: of("refused_file_types") ?? [] };
}

/**
 * Why the page refuses a file before sending it, or null when it does not: an extension
 * that is never taken, or one the setting `reference_file_types` does not take. The
 * server checks again, and checks the content too. Until the settings are read, nothing
 * is refused here.
 */
export function refusalOf(
  fileName: string,
  taken: readonly string[] | null,
  refused: readonly string[] = [],
): string | null {
  const extension = extensionOf(fileName);
  if (extension !== "" && refused.includes(extension)) {
    return `A file of the kind ${extension} is never taken: it is a web page, a script or a program.`;
  }
  if (taken === null || taken.includes(extension)) return null;
  const kind = extension === "" ? "with no extension" : `of the kind ${extension}`;
  return `A file ${kind} is not taken. The kinds taken are ${taken.join(", ")}: the setting reference_file_types says which.`;
}

/**
 * The largest file the server takes, in bytes, as its refusal of a larger one says it:
 * "a reference file is at most 100 MB". Null when the message names no limit.
 */
export function limitOf(message: string): number | null {
  const found = /at most ([\d,]+) MB/i.exec(message);
  if (!found?.[1]) return null;
  const megabytes = Number.parseInt(found[1].replace(/,/g, ""), 10);
  return Number.isFinite(megabytes) && megabytes > 0 ? megabytes * 1024 * 1024 : null;
}

/** Why a file over the limit the server named is not sent. */
export function tooLarge(limit: number): string {
  return `A reference file is at most ${sizeText(limit)}: this one is larger.`;
}

/**
 * Why the server refused a file, in a line: what it said, and what it said of the file
 * where that adds to it, as the reference that has the same content (409). A file over
 * the limit (413) is said to be so, with the limit, and nothing more.
 */
export function refusedText(error: Pick<ApiError, "message" | "fields" | "status">): string {
  const said = [sentence(error.message)];
  if (error.status !== 413) {
    for (const message of Object.values(error.fields)) {
      if (!error.message.toLowerCase().includes(message.toLowerCase()))
        said.push(sentence(message));
    }
  }
  return said.filter(Boolean).join(" ");
}

/** What a download is typed as: never the file's own type, so it cannot be opened as a page. */
export const DOWNLOAD_TYPE = "application/octet-stream";

/** A file's content as it is handed to the browser to save. */
export function downloadBlob(content: Blob): Blob {
  return new Blob([content], { type: DOWNLOAD_TYPE });
}

/** The pictures a page shows in an `<img>`: those that every browser shows. */
const SHOWN_TYPES: readonly string[] = ["image/jpeg", "image/png", "image/gif", "image/webp"];

/**
 * A picture's content as the viewer shows it: typed as the picture it is, where it is
 * one a browser shows, and as nothing that runs otherwise. The type is the reference's
 * own and never what the answer said.
 */
export function pictureBlob(content: Blob, mediaType: string | null): Blob {
  const type = mediaType !== null && SHOWN_TYPES.includes(mediaType) ? mediaType : DOWNLOAD_TYPE;
  return new Blob([content], { type });
}

/** What saving a file needs of the browser. */
export interface SaveDeps {
  createObjectURL: (blob: Blob) => string;
  revokeObjectURL: (url: string) => void;
  document: Pick<Document, "createElement" | "body">;
  later: (run: () => void, milliseconds: number) => void;
}

// How long the copy in memory is kept for the browser to start saving it, in milliseconds.
const KEEP_FOR = 60_000;

function browserDeps(): SaveDeps {
  return {
    createObjectURL: (blob) => URL.createObjectURL(blob),
    revokeObjectURL: (url) => URL.revokeObjectURL(url),
    document,
    later: (run, milliseconds) => {
      window.setTimeout(run, milliseconds);
    },
  };
}

/**
 * Have the browser save a file under its name. It is typed `application/octet-stream`
 * whatever it is, and handed over through a hidden link with `download`: it is never
 * opened in a tab, a frame or an object of the page.
 */
export function saveReference(content: Blob, fileName: string, deps: SaveDeps = browserDeps()) {
  const url = deps.createObjectURL(downloadBlob(content));
  const link = deps.document.createElement("a");
  link.href = url;
  link.download = fileName;
  link.rel = "noopener";
  link.hidden = true;
  deps.document.body.append(link);
  try {
    link.click();
  } finally {
    link.remove();
    deps.later(() => deps.revokeObjectURL(url), KEEP_FOR);
  }
}

/**
 * What erasing a reference says first: that it goes at once from every record it is on,
 * naming how many, and that the backups on the server keep a copy until they rotate out
 * (P-160). The page cannot read how many backups the server keeps: it says the default.
 */
export function erasureText(form: Reference["form"], records: number): string {
  const where = records <= 1 ? "from the record it is on" : `from all ${records} records it is on`;
  const what =
    form === "file"
      ? `The file and its content are erased at once, ${where}.`
      : `The link is erased at once, ${where}.`;
  return `${what} Nothing can bring it back here. The backups on the server keep a copy until they rotate out: 14 days, unless the server is set otherwise.`;
}
