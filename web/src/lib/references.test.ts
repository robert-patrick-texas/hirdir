import { describe, expect, it, vi } from "vitest";
import {
  DOWNLOAD_TYPE,
  downloadBlob,
  erasureText,
  extensionOf,
  fileTypesOf,
  firstKind,
  groupsOf,
  type Listed,
  limitOf,
  pictureBlob,
  picturesOf,
  recordPage,
  refusalOf,
  refusedText,
  type SaveDeps,
  saveReference,
  sizeText,
  sourceKind,
  titleOf,
  withFirstKinds,
} from "./references";

const AT = "2026-11-16T15:04:05Z";

function listed(
  title: string,
  source: Listed["source"],
  sourceHid: string,
  sourceLabel: string,
  more: Partial<Listed> = {},
): Listed {
  return {
    hid: `ref-${title}`,
    title,
    kind: "floor_plan",
    form: "file",
    file_name: `${title}.pdf`,
    media_type: "application/pdf",
    size_bytes: 1000,
    sha256: "0".repeat(64),
    url: null,
    notes: null,
    shown_in_page: false,
    content_missing: false,
    attachments: [],
    attachment_count: 1,
    row_version: 1,
    created_at: AT,
    created_by: null,
    created_by_name: "ivy",
    updated_at: AT,
    updated_by: null,
    updated_by_name: "ivy",
    attachment_hid: `att-${title}`,
    source,
    source_hid: sourceHid,
    source_label: sourceLabel,
    ...more,
  };
}

const ROOM = "Americas > Central > Site-2 > Building 1 > Floor 2 > Room 102";
const FLOOR = "Americas > Central > Site-2 > Building 1 > Floor 2";
const SITE = "Americas > Central > Site-2";

describe("the references a record lists", () => {
  it("are grouped by the record each comes from, its own first and then outward", () => {
    const groups = groupsOf([
      listed("Rack photograph", "own", "rack", "Rack 4"),
      listed("Wiring", "own", "rack", "Rack 4"),
      listed("Admin guide", "catalog", "model", "Cisco C9300-48P"),
      listed("Room plan", "location", "room", ROOM),
      listed("Floor plan", "location", "floor", FLOOR),
      listed("Site map", "site", "site", SITE),
    ]);
    expect(groups.map((group) => [group.source, group.label, group.references.length])).toEqual([
      ["own", "Rack 4", 2],
      ["catalog", "Cisco C9300-48P", 1],
      ["location", ROOM, 1],
      ["location", FLOOR, 1],
      ["site", SITE, 1],
    ]);
    expect(groups[0]?.references.map((one) => one.title)).toEqual(["Rack photograph", "Wiring"]);
  });

  it("are no groups when there are none", () => {
    expect(groupsOf([])).toEqual([]);
  });

  it("keep one group for a record however its references come", () => {
    const groups = groupsOf([
      listed("A", "location", "floor", FLOOR),
      listed("B", "site", "site", SITE),
      listed("C", "location", "floor", FLOOR),
    ]);
    expect(groups.map((group) => group.references.map((one) => one.title))).toEqual([
      ["A", "C"],
      ["B"],
    ]);
  });

  it("show their pictures in the viewer, and no picture whose content is missing", () => {
    const shown = picturesOf([
      listed("Front", "own", "rack", "Rack 4", { shown_in_page: true }),
      listed("Plan", "own", "rack", "Rack 4"),
      listed("Back", "own", "rack", "Rack 4", { shown_in_page: true, content_missing: true }),
      listed("Map", "site", "site", SITE, { shown_in_page: true }),
    ]);
    expect(shown.map((one) => one.title)).toEqual(["Front", "Map"]);
  });

  it("lead to the page of the record each is on", () => {
    expect(recordPage("catalog_entry", "e 1")).toBe("/catalog/e%201");
    expect(recordPage("item", "i1")).toBe("/items/i1");
    expect(recordPage("circuit", "c1")).toBe("/circuits/c1");
    expect(recordPage("location", "l1")).toBe("/geography/location/l1");
    expect(recordPage("site", "s1")).toBe("/geography/site/s1");
    expect(recordPage("region", "r1")).toBe("/geography/region/r1");
    expect(sourceKind("own", "item")).toBe("item");
    expect(sourceKind("catalog", "item")).toBe("catalog_entry");
    expect(sourceKind("site", "location")).toBe("site");
  });
});

describe("the size of a file", () => {
  it("is read as people read it", () => {
    expect(sizeText(0)).toBe("0 bytes");
    expect(sizeText(1)).toBe("1 byte");
    expect(sizeText(1023)).toBe("1,023 bytes");
    expect(sizeText(1024)).toBe("1 KB");
    expect(sizeText(1536)).toBe("1.5 KB");
    expect(sizeText(120 * 1024)).toBe("120 KB");
    expect(sizeText(Math.round(2.4 * 1024 * 1024))).toBe("2.4 MB");
    expect(sizeText(4718592)).toBe("4.5 MB");
    expect(sizeText(14 * 1024 * 1024 + 300)).toBe("14 MB");
    expect(sizeText(100 * 1024 * 1024)).toBe("100 MB");
    expect(sizeText(3 * 1024 ** 3)).toBe("3 GB");
  });

  it("rounds up into the next unit", () => {
    expect(sizeText(1024 * 1024 - 100)).toBe("1 MB");
  });

  it("is blank for a link, which has none", () => {
    expect(sizeText(null)).toBe("");
    expect(sizeText(undefined)).toBe("");
    expect(sizeText(-1)).toBe("");
  });
});

describe("a file chosen to upload", () => {
  it("is titled by its name without the extension", () => {
    expect(titleOf("b1-floor-2.pdf")).toBe("b1-floor-2");
    expect(titleOf("Rack 4 front.JPG")).toBe("Rack 4 front");
    expect(titleOf("c9300.admin.guide.pdf")).toBe("c9300.admin.guide");
    expect(titleOf("README")).toBe("README");
    expect(titleOf(".profile")).toBe(".profile");
    expect(titleOf("C:\\scans\\loa.pdf")).toBe("loa");
    expect(titleOf(`${"x".repeat(250)}.pdf`)).toHaveLength(200);
  });

  it("has the extension the server reads", () => {
    expect(extensionOf("plan.PDF")).toBe("pdf");
    expect(extensionOf("archive.tar.gz")).toBe("gz");
    expect(extensionOf("README")).toBe("");
    expect(extensionOf(".profile")).toBe("");
    expect(extensionOf("dir.d/notes")).toBe("");
  });

  it("starts as a photograph when it is a picture, and as a guide on a catalog entry", () => {
    const kinds = ["photograph", "floor_plan", "administration_guide", "other"];
    expect(firstKind("location", "rack.jpeg", kinds)).toBe("photograph");
    expect(firstKind("catalog_entry", "front.png", kinds)).toBe("photograph");
    expect(firstKind("catalog_entry", "admin.pdf", kinds)).toBe("administration_guide");
    expect(firstKind("location", "plan.pdf", kinds)).toBe("");
    expect(firstKind("item", "labels.HEIC", kinds)).toBe("photograph");
    // A kind the list no longer offers is not chosen.
    expect(firstKind("location", "rack.jpg", ["floor_plan"])).toBe("");
  });

  // 0.9.8: chosen in the moment before the kinds of file were read.
  it("is given its first kind when the kinds are read, unless the person chose one", () => {
    const kinds = ["photograph", "floor_plan", "administration_guide", "other"];
    const photo = { file: { name: "rack.jpg" }, kind: "", kindChosen: false };
    const plan = { file: { name: "plan.pdf" }, kind: "", kindChosen: false };
    const theirs = { file: { name: "front.png" }, kind: "", kindChosen: true };
    const other = { file: { name: "side.png" }, kind: "floor_plan", kindChosen: true };
    const given = withFirstKinds([photo, plan, theirs, other], "location", kinds);
    expect(given.map((one) => one.kind)).toEqual(["photograph", "", "", "floor_plan"]);
    // Nothing to give: the list itself, so that nothing is drawn again.
    const none = [plan, theirs, other];
    expect(withFirstKinds(none, "location", kinds)).toBe(none);
    expect(withFirstKinds([photo], "location", [])).toEqual([photo]);
  });

  it("is refused in the page when the setting does not take its extension", () => {
    const taken = ["jpg", "png", "pdf"];
    const refused = ["exe", "html", "svg"];
    expect(refusalOf("plan.pdf", taken, refused)).toBeNull();
    expect(refusalOf("PLAN.PDF", taken, refused)).toBeNull();
    expect(refusalOf("setup.exe", taken, refused)).toMatch(/never taken.*a program/);
    expect(refusalOf("drawing.svg", [...taken, "svg"], refused)).toMatch(/never taken/);
    expect(refusalOf("notes.docx", taken, refused)).toBe(
      "A file of the kind docx is not taken. The kinds taken are jpg, png, pdf: the setting reference_file_types says which.",
    );
    expect(refusalOf("README", taken, refused)).toMatch(/^A file with no extension is not taken/);
  });

  it("is checked against the kinds the settings take and those never taken", () => {
    expect(
      fileTypesOf([
        { key: "currency", value: "USD" },
        { key: "reference_file_types", value: ["pdf", "jpg"] },
        { key: "refused_file_types", value: ["exe", "html"] },
      ]),
    ).toEqual({ taken: ["pdf", "jpg"], refused: ["exe", "html"] });
    expect(fileTypesOf([])).toEqual({ taken: null, refused: [] });
    expect(fileTypesOf([{ key: "reference_file_types", value: "pdf" }])).toEqual({
      taken: null,
      refused: [],
    });
  });

  it("is left to the server while the settings are not read", () => {
    expect(refusalOf("notes.docx", null, [])).toBeNull();
    expect(refusalOf("setup.exe", null, ["exe"])).toMatch(/never taken/);
  });

  it("refused by the server says why, and names the reference with the same content", () => {
    expect(
      refusedText({
        status: 409,
        message: "this file is on that record already, as Floor plan",
        detail: "this file is on that record already, as Floor plan",
        fields: { file: "the same content is reference ref-1, Floor plan" },
      }),
    ).toBe(
      "This file is on that record already, as Floor plan. The same content is reference ref-1, Floor plan.",
    );
    expect(
      refusedText({
        status: 422,
        message: "the file is refused: it is a web page",
        detail: "the file is refused: it is a web page",
        fields: { file: "it is a web page" },
      }),
    ).toBe("The file is refused: it is a web page.");
    expect(
      refusedText({
        status: 413,
        message: "a reference file is at most 100 MB",
        detail: "a reference file is at most 100 MB",
        fields: { file: "too large" },
      }),
    ).toBe("A reference file is at most 100 MB.");
  });

  it("refused by the proxy in front, which gives no reason, is said to be too large", () => {
    expect(
      refusedText({ status: 413, message: "The server answered 413", detail: "", fields: {} }),
    ).toBe("The file is larger than the server takes.");
  });

  it("is held to the limit the server named when it refused a larger one", () => {
    expect(limitOf("a reference file is at most 100 MB")).toBe(100 * 1024 * 1024);
    expect(limitOf("A reference file is at most 2,048 MB.")).toBe(2048 * 1024 * 1024);
    expect(limitOf("the file is refused")).toBeNull();
  });
});

describe("a download", () => {
  it("is never typed as the file's own type", async () => {
    const page = new Blob(["<html><script>alert(1)</script></html>"], { type: "text/html" });
    const saved = downloadBlob(page);
    expect(saved.type).toBe(DOWNLOAD_TYPE);
    expect(await saved.text()).toBe(await page.text());
  });

  it("is saved through a hidden link with the file's name, and the address is let go", () => {
    const made: Blob[] = [];
    const later: Array<() => void> = [];
    const link = {
      href: "",
      download: "",
      rel: "",
      hidden: false,
      click: vi.fn(),
      remove: vi.fn(),
    };
    const append = vi.fn();
    const revoke = vi.fn();
    const deps: SaveDeps = {
      createObjectURL: (blob) => {
        made.push(blob);
        return "blob:https://inventory.example/1";
      },
      revokeObjectURL: revoke,
      document: {
        createElement: (() => link) as unknown as Document["createElement"],
        body: { append } as unknown as HTMLElement,
      },
      later: (run) => later.push(run),
    };
    saveReference(new Blob(["%PDF-1.7"], { type: "application/pdf" }), "b1-floor-2.pdf", deps);
    expect(made.map((blob) => blob.type)).toEqual([DOWNLOAD_TYPE]);
    expect(link).toMatchObject({
      href: "blob:https://inventory.example/1",
      download: "b1-floor-2.pdf",
      hidden: true,
    });
    expect(append).toHaveBeenCalledWith(link);
    expect(link.click).toHaveBeenCalledTimes(1);
    expect(link.remove).toHaveBeenCalledTimes(1);
    expect(revoke).not.toHaveBeenCalled();
    for (const run of later) run();
    expect(revoke).toHaveBeenCalledWith("blob:https://inventory.example/1");
  });

  it("of a picture to show is typed as that picture, and only as one a browser shows", () => {
    const content = new Blob(["GIF89a"]);
    expect(pictureBlob(content, "image/gif").type).toBe("image/gif");
    expect(pictureBlob(content, "image/svg+xml").type).toBe(DOWNLOAD_TYPE);
    expect(pictureBlob(content, "text/html").type).toBe(DOWNLOAD_TYPE);
    expect(pictureBlob(content, null).type).toBe(DOWNLOAD_TYPE);
  });
});

describe("erasing a reference", () => {
  it("says first how many records it goes from, and that the backups keep a copy", () => {
    expect(erasureText("file", 1)).toMatch(
      /^The file and its content are erased at once, from the record it is on\./,
    );
    expect(erasureText("file", 6)).toMatch(/from all 6 records it is on/);
    expect(erasureText("link", 2)).toMatch(/^The link is erased at once, from all 2 records/);
    expect(erasureText("file", 1)).toMatch(
      /backups on the server keep a copy until they rotate out: 14 days/,
    );
  });
});
