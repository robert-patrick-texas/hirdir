import { describe, expect, it } from "vitest";
import {
  ENTITIES,
  entityLabel,
  fileIdentity,
  fileType,
  guessEntity,
  isEntity,
  modeLabel,
  previewQuery,
} from "./imports";

describe("entities", () => {
  it("are listed in the order they are loaded", () => {
    expect(ENTITIES.map((entity) => entity.value)).toEqual([
      "tags",
      "vendors",
      "catalog_entries",
      "owners",
      "items",
    ]);
  });

  it("are known by name, and one this build does not know is shown as sent", () => {
    expect(isEntity("catalog_entries")).toBe(true);
    expect(isEntity("contracts")).toBe(false);
    expect(entityLabel("catalog_entries")).toBe("Catalog entries");
    expect(entityLabel("contracts")).toBe("contracts");
  });
});

describe("modeLabel", () => {
  it("names the modes of a file and the one a bulk edit has", () => {
    expect(modeLabel("upsert")).toBe("Create and update");
    expect(modeLabel("create")).toBe("Create only");
    expect(modeLabel("update")).toBe("Update only");
  });
});

describe("fileType", () => {
  it("goes by the end of the name first", () => {
    expect(fileType({ name: "items.csv", type: "" })).toBe("text/csv");
    expect(fileType({ name: "ITEMS.CSV", type: "application/vnd.ms-excel" })).toBe("text/csv");
    expect(fileType({ name: "items.json", type: "text/plain" })).toBe("application/json");
  });

  it("goes by the browser's type when the name says nothing", () => {
    expect(fileType({ name: "export", type: "text/csv;charset=utf-8" })).toBe("text/csv");
    expect(fileType({ name: "export", type: "application/json" })).toBe("application/json");
  });

  it("knows no other format", () => {
    expect(fileType({ name: "items.xlsx", type: "application/vnd.ms-excel" })).toBeNull();
    expect(fileType({ name: "notes", type: "" })).toBeNull();
  });
});

describe("guessEntity", () => {
  it("reads the kind of record from a file's name", () => {
    expect(guessEntity("items.csv")).toBe("items");
    expect(guessEntity("catalog-entries.csv")).toBe("catalog_entries");
    expect(guessEntity("Catalog Entries (2).json")).toBe("catalog_entries");
    expect(guessEntity("hirdir-vendors-20261113T163125-0500.csv")).toBe("vendors");
  });

  it("guesses nothing from a name that says nothing", () => {
    expect(guessEntity("refresh-2030.csv")).toBe("");
  });
});

describe("previewQuery", () => {
  it("puts the entity, the mode and the name beside the file, and leaves a blank out", () => {
    expect(previewQuery("items", "create", "items.csv")).toEqual({
      entity: "items",
      mode: "create",
      file_name: "items.csv",
    });
    expect(previewQuery("", "", "refresh.json")).toEqual({ file_name: "refresh.json" });
    expect(previewQuery("tags", "", " ")).toEqual({ entity: "tags" });
  });

  it("keeps a name within what the server takes, and its ending with it", () => {
    const name = `${"a".repeat(300)}.csv`;
    const sent = previewQuery("items", "", name).file_name ?? "";
    expect(sent).toHaveLength(255);
    expect(sent.endsWith(".csv")).toBe(true);
  });
});

describe("fileIdentity", () => {
  it("is the same for the same file sent the same way, and no other", () => {
    const file = { name: "items.csv", size: 1200, lastModified: 1794000000000 };
    expect(fileIdentity(file, "items", "")).toBe(fileIdentity({ ...file }, "items", ""));
    expect(fileIdentity(file, "items", "create")).not.toBe(fileIdentity(file, "items", ""));
    expect(fileIdentity({ ...file, lastModified: 1794000000001 }, "items", "")).not.toBe(
      fileIdentity(file, "items", ""),
    );
  });
});
