import { describe, expect, it } from "vitest";
import { buildPatch, type FieldSpec, formOf } from "./patch";
import {
  carryTyped,
  changedMeanwhile,
  forgetLeft,
  leave,
  meanwhileNote,
  peekLeft,
  savedRecord,
  touched,
} from "./typedAfterSave";

const SPECS: FieldSpec[] = [
  { name: "name", label: "Name", kind: "text" },
  { name: "comments", label: "Comments", kind: "longtext" },
  { name: "tags", label: "Tags", kind: "set" },
  { name: "is_external", label: "External", kind: "boolean" },
];

const SAVED = {
  hid: "ITM-000001",
  row_version: 4,
  name: "edge-a.example.net",
  comments: "first words",
  tags: ["lab"],
  is_external: false,
};

describe("touched", () => {
  it("names the fields that differ from what the form took", () => {
    const taken = formOf(SPECS, SAVED);
    expect(touched(SPECS, taken, taken)).toEqual([]);
    expect(touched(SPECS, taken, { ...taken, comments: "more", tags: ["lab", "core"] })).toEqual([
      "comments",
      "tags",
    ]);
  });
});

describe("carryTyped", () => {
  it("keeps what was typed after the save and takes the rest from the record read again", () => {
    const taken = formOf(SPECS, SAVED);
    const typed = { ...taken, comments: "typed after the save" };
    // Someone, or the server, changed the name meanwhile; the person did not.
    const read = { ...SAVED, row_version: 5, name: "edge-b.example.net" };
    const values = carryTyped(SPECS, taken, typed, read);
    expect(values.comments).toBe("typed after the save");
    expect(values.name).toBe("edge-b.example.net");
  });

  it("is the record read again when nothing was typed", () => {
    const taken = formOf(SPECS, SAVED);
    const read = { ...SAVED, row_version: 5, tags: ["lab", "core"] };
    expect(carryTyped(SPECS, taken, taken, read)).toEqual(formOf(SPECS, read));
  });
});

describe("changedMeanwhile", () => {
  const taken = formOf(SPECS, SAVED);
  const typed = { ...taken, name: "edge-mine.example.net", comments: "mine" };

  it("names a kept field that someone else changed meanwhile to something else", () => {
    // Someone saved the name and the tags; the person typed the name and the comments.
    const read = { ...SAVED, row_version: 5, name: "edge-theirs.example.net", tags: [] };
    expect(changedMeanwhile(SPECS, taken, typed, read)).toEqual(["name"]);
  });

  it("names nothing when the record kept the field, or took what was typed", () => {
    expect(changedMeanwhile(SPECS, taken, typed, { ...SAVED, row_version: 5 })).toEqual([]);
    const same = { ...SAVED, row_version: 5, name: "edge-mine.example.net" };
    expect(changedMeanwhile(SPECS, taken, typed, same)).toEqual([]);
  });
});

describe("meanwhileNote", () => {
  it("says what the record now has, a choice by its label", () => {
    const choice: FieldSpec = {
      name: "status",
      label: "Status",
      kind: "choice",
      options: [{ value: "in_service", label: "In service" }],
    };
    expect(meanwhileNote(SPECS[0] as FieldSpec, "edge-b.example.net")).toBe(
      "Changed meanwhile to “edge-b.example.net”; saving replaces it.",
    );
    expect(meanwhileNote(choice, "in_service")).toBe(
      "Changed meanwhile to “In service”; saving replaces it.",
    );
    expect(meanwhileNote(SPECS[3] as FieldSpec, true)).toBe(
      "Changed meanwhile to “Yes”; saving replaces it.",
    );
    expect(meanwhileNote(SPECS[0] as FieldSpec, "")).toBe(
      "Emptied meanwhile by someone else; saving replaces that.",
    );
  });
});

describe("savedRecord", () => {
  it("is what was sent over the record, with the version the server answered", () => {
    const before = { ...SAVED, comments: null };
    const after = savedRecord(before, { row_version: 4, comments: "first words" }, SAVED);
    expect(after.row_version).toBe(4);
    expect(after.comments).toBe("first words");
    // The next change goes with that version, and holds only what is new.
    const next = buildPatch<{ row_version: number }>(SPECS, after, {
      ...formOf(SPECS, after),
      name: "edge-c.example.net",
    });
    expect(next.body).toEqual({ row_version: 4, name: "edge-c.example.net" });
  });

  it("leaves the record as it was when the answer has no version", () => {
    expect(savedRecord(SAVED, { row_version: 4, name: "x" }, null)).toBe(SAVED);
    expect(savedRecord(SAVED, { row_version: 4, name: "x" }, { ok: true })).toBe(SAVED);
  });
});

describe("what a form left", () => {
  const held = {
    record: SAVED,
    taken: formOf(SPECS, SAVED),
    values: { ...formOf(SPECS, SAVED), comments: "typed" },
    meanwhile: [],
    at: 1_000,
  };

  it("is found by the form of the same record read again, until it is taken", () => {
    leave("ITM-000001 name", held);
    expect(peekLeft("ITM-000001 name", { row_version: 5 }, 2_000)).toBe(held);
    expect(peekLeft("ITM-000002 name", { row_version: 5 }, 2_000)).toBeNull();
    forgetLeft("ITM-000001 name");
    expect(peekLeft("ITM-000001 name", { row_version: 5 }, 2_000)).toBeNull();
  });

  it("is not found for an older record, or long after", () => {
    leave("ITM-000001 name", held);
    expect(peekLeft("ITM-000001 name", { row_version: 3 }, 2_000)).toBeNull();
    expect(peekLeft("ITM-000001 name", { row_version: 5 }, 1_000 + 121_000)).toBeNull();
    forgetLeft("ITM-000001 name");
  });
});
