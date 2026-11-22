import { describe, expect, it } from "vitest";
import { ENTITIES } from "./imports";
import {
  countWords,
  type ExportTable,
  everythingName,
  exportLabel,
  holdsNothing,
  tableRows,
  tablesText,
} from "./tables";

const TABLES: ExportTable[] = [
  { entity: "tags", label: "Tags", file: "tags", count: 4, columns: ["hid", "name"] },
  { entity: "regions", label: "Regions", file: "regions", count: 0, columns: ["hid", "name"] },
  { entity: "sites", label: "Sites", file: "sites", count: 1250, columns: ["hid", "name"] },
];

describe("tableRows", () => {
  it("lists the tables as the server gives them, in its order", () => {
    expect(tableRows(TABLES)).toEqual([
      { entity: "tags", label: "Tags", count: 4 },
      { entity: "regions", label: "Regions", count: 0 },
      { entity: "sites", label: "Sites", count: 1250 },
    ]);
  });

  it("lists every table this build knows, with no count, until the server has said", () => {
    const rows = tableRows(undefined);
    expect(rows.map((row) => row.entity)).toEqual(ENTITIES.map((entity) => entity.value));
    expect(rows.every((row) => row.count === null)).toBe(true);
  });

  it("lists the countries and the states first, as Choices exports them (P-321)", () => {
    expect(
      tableRows(undefined)
        .slice(0, 3)
        .map((row) => row.label),
    ).toEqual(["Countries", "States", "Tags"]);
    expect(tableRows(undefined, ["states", "countries"]).map((row) => row.entity)).toEqual([
      "countries",
      "states",
    ]);
  });

  it("keeps only the tables asked for, in the order of loading", () => {
    const only = ["sites", "regions"] as const;
    expect(tableRows(TABLES, only).map((row) => row.entity)).toEqual(["regions", "sites"]);
    expect(tableRows(undefined, ["locations", "sites", "regions"]).map((row) => row.label)).toEqual(
      ["Regions", "Sites", "Locations"],
    );
  });
});

describe("the words of a table", () => {
  const [tags, regions, sites] = tableRows(TABLES);
  const unknown = { entity: "tags" as const, label: "Tags", count: null };

  it("says how many records a table holds, and none where it holds nothing", () => {
    expect(countWords(sites?.count ?? null)).toBe("1,250");
    expect(countWords(0)).toBe("None");
    expect(countWords(null)).toBe("…");
  });

  it("knows a table holds nothing only when the server said so", () => {
    expect(regions && holdsNothing(regions)).toBe(true);
    expect(tags && holdsNothing(tags)).toBe(false);
    expect(holdsNothing(unknown)).toBe(false);
  });

  it("names a table's buttons the same whatever it holds, as Geography, which does not count, names them", () => {
    expect(regions && exportLabel(regions, "csv")).toBe("Export Regions as CSV");
    expect(regions && exportLabel(regions, "json")).toBe("Export Regions as JSON");
    expect(sites && exportLabel(sites, "csv")).toBe("Export Sites as CSV");
    expect(exportLabel(unknown, "csv")).toBe("Export Tags as CSV");
  });

  it("says how many tables there are and how many hold nothing", () => {
    expect(tablesText(tableRows(TABLES))).toBe("3 tables, 1 holding nothing yet");
    expect(tablesText(tableRows(TABLES, ["tags", "sites"]))).toBe("2 tables");
    expect(tablesText(tableRows(TABLES, ["regions"]))).toBe("1 table, holding nothing yet");
    const empty = TABLES.map((table) => ({ ...table, count: 0 }));
    expect(tablesText(tableRows(empty))).toBe("3 tables, all holding nothing yet");
    expect(tablesText(tableRows(undefined))).toBe(`${ENTITIES.length} tables`);
  });
});

describe("everythingName", () => {
  it("names the zip after the product, as the server names one", () => {
    expect(everythingName("csv", "hirdir")).toBe("hirdir-all-csv.zip");
    expect(everythingName("json", "Example Inventory")).toBe("Example-Inventory-all-json.zip");
  });
});
