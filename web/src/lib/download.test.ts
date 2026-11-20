import { describe, expect, it } from "vitest";
import { ApiError } from "../api/client";
import { latestOf, type Saved, saveDownload, savedText } from "./download";

function saver() {
  const saved: Array<{ name: string; text: Promise<string> }> = [];
  return {
    saved,
    save: (blob: Blob, name: string) => {
      saved.push({ name, text: blob.text() });
    },
  };
}

describe("saveDownload", () => {
  it("saves the file under the name the server gave it", async () => {
    const { saved, save } = saver();
    const file = { blob: new Blob(["hid,name\n"]), fileName: "hirdir-sites-20261120.csv" };
    const name = await saveDownload(Promise.resolve(file), "hirdir-sites.csv", save);
    expect(name).toBe("hirdir-sites-20261120.csv");
    expect(saved.map((one) => one.name)).toEqual(["hirdir-sites-20261120.csv"]);
    expect(await saved[0]?.text).toBe("hid,name\n");
  });

  it("saves it under the name the page made where the server gave none", async () => {
    const { saved, save } = saver();
    const file = { blob: new Blob([""]), fileName: null };
    expect(await saveDownload(Promise.resolve(file), "hirdir-all-csv.zip", save)).toBe(
      "hirdir-all-csv.zip",
    );
    expect(saved.map((one) => one.name)).toEqual(["hirdir-all-csv.zip"]);
  });

  it("saves nothing when the server refused, and says why", async () => {
    const { saved, save } = saver();
    const busy = new ApiError({ status: 503, title: "Busy", retryAfter: 5 });
    await expect(saveDownload(Promise.reject(busy), "x.csv", save)).rejects.toBe(busy);
    expect(saved).toEqual([]);
  });
});

describe("latestOf", () => {
  it("finds what came of the button of a few pressed last", () => {
    const busy = new ApiError({ status: 503, title: "Busy" });
    const saved = new Map<string, Saved>([
      ["sites csv", { name: "sites.csv" }],
      ["regions csv", { error: busy }],
      ["sites json", { working: true }],
    ]);
    expect(latestOf(saved, ["sites csv", "sites json"])).toEqual({
      key: "sites json",
      saved: { working: true },
    });
    expect(latestOf(saved, ["regions csv", "regions json"])).toEqual({
      key: "regions csv",
      saved: { error: busy },
    });
    expect(latestOf(saved, ["locations csv"])).toBeNull();
  });
});

describe("savedText", () => {
  it("says what became of an export", () => {
    expect(savedText(undefined)).toBe("");
    expect(savedText({ working: true })).toBe("Exporting…");
    expect(savedText({ name: "hirdir-sites.csv" })).toBe("Exported to hirdir-sites.csv.");
    // A refusal is said by the refusal itself, beside the button.
    expect(savedText({ error: new ApiError({ status: 503, title: "Busy" }) })).toBe("");
  });
});
