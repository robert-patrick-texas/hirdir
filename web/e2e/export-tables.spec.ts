// The browser scenarios of 0.9.13's exports (P-286, P-287): every table a file is taken
// for is taken out from the Import page, beside the upload, in one press each, an empty
// one as the template of its import, and every table at once as one zip; and the three
// tables of Geography from the Geography page, to be corrected and loaded back.
//
// The file keeps the rules of support.ts. It signs in as an Admin of its own, and a
// View-only account of its own; its mark is in every name it gives a record and every
// file it loads. The other files make records in the tables beside it, so a table
// "holds nothing" only while the page says so: the template is taken from a table that
// holds nothing when there is one, and from the header row of its file otherwise; and a
// file loaded back keeps the rows of this file's records alone, so that nothing another
// file changes meanwhile is read or changed. That every row of every table loads back as
// nothing to change is the server's test, over all of them (tests/api).

import { readFile, writeFile } from "node:fs/promises";
import { inflateRawSync } from "node:zlib";
import {
  type Download,
  expect,
  type Locator,
  type Page,
  type Request,
  type TestInfo,
} from "@playwright/test";
import { count, importFile, region, whenApplied } from "./structure";
import { createAccount, expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const id = mark("export-tables");
const network = `Example net ${id}`;
const regionName = `Region ${id}`;
const sites = [`Site-A ${id}`, `Site-B ${id}`];

// Every table, in the order their files are loaded: its name for people and its file.
const TABLES: ReadonlyArray<readonly [string, string]> = [
  ["Tags", "tags"],
  ["Vendors", "vendors"],
  ["Catalog entries", "catalog-entries"],
  ["Contacts", "contacts"],
  ["Contacts of vendors", "vendor-contacts"],
  ["Operators", "operators"],
  ["Regions", "regions"],
  ["Sites", "sites"],
  ["Locations", "locations"],
  ["Contacts of places", "contact-assignments"],
  ["Owners", "owners"],
  ["People of owners", "owner-members"],
  ["Networks", "networks"],
  ["External systems", "external-systems"],
  ["Support agreements", "agreements"],
  ["Contracts", "contracts"],
  ["Contacts of agreements and contracts", "contract-contacts"],
  ["Purchase requests", "purchase-requests"],
  ["Lines of purchase requests", "purchase-lines"],
  ["Items", "items"],
  ["Device groups", "device-groups"],
  ["Members of device groups", "device-group-members"],
  ["Replacements of items", "item-replacements"],
  ["Addresses", "addresses"],
  ["Coverage of items under contracts", "contract-coverage"],
  ["Registrations with external systems", "registrations"],
  ["Capacity lines", "capacity-lines"],
  ["Circuit groups", "circuit-groups"],
  ["Circuits", "circuits"],
  ["Carriers of circuits", "circuit-carriers"],
  ["Cost lines of circuits", "circuit-costs"],
  ["Contacts of circuits", "circuit-contacts"],
  ["Devices of circuits", "circuit-devices"],
];

// The header rows of the files, as their imports read them (examples/ holds the same).
const HEADERS = {
  tags: "hid,label,colour,description",
  networks: "hid,label,kind",
  regions:
    "hid,name,parent,code,ship_address1,ship_address2,ship_city,ship_state,ship_postal_code,ship_country,ship_instructions,operator,support_weight,links,notes,record_status,tags",
  sites:
    "hid,name,region,code,address1,address2,city,state,postal_code,country,ship_address1,ship_address2,ship_city,ship_state,ship_postal_code,ship_country,ship_instructions,ship_same_as_address,operator,latitude,longitude,support_weight,links,notes,record_status,tags",
  locations:
    "hid,name,site,parent,code,kind,address1,address2,city,state,postal_code,country,ship_address1,ship_address2,ship_city,ship_state,ship_postal_code,ship_country,ship_instructions,ship_same_as_address,operator,latitude,longitude,support_weight,links,notes,record_status,tags",
};

/** The name the server gives a file it exports: the product's, the table's and the moment's. */
function serverName(table: string, extension: string): RegExp {
  return new RegExp(`^hirdir-${table}-\\d{8}T\\d{6}[-+]\\d{4}\\.${extension}$`);
}

/** The list of tables on the Import page. */
function tables(page: Page): Locator {
  return page.getByTestId("export-tables");
}

function tableRow(page: Page, entity: string): Locator {
  return tables(page).locator(`tr[data-entity="${entity}"]`);
}

/** A file the browser saved, copied here first, as it may be elsewhere. */
async function saved(download: Promise<Download>, testInfo: TestInfo): Promise<Buffer> {
  const file = await download;
  const path = testInfo.outputPath(file.suggestedFilename());
  await file.saveAs(path);
  return readFile(path);
}

/** Press a button that exports, and take the file it saves, with the name it was given. */
async function exported(
  page: Page,
  button: Locator,
  testInfo: TestInfo,
): Promise<{ name: string; content: Buffer }> {
  const download = page.waitForEvent("download");
  await button.click();
  const name = (await download).suggestedFilename();
  return { name, content: await saved(download, testInfo) };
}

/** The next `POST /exports` the page sends. */
function exportAsked(page: Page): Promise<Request> {
  return page.waitForRequest(
    (request) => request.method() === "POST" && request.url().endsWith("/api/v1/exports"),
  );
}

/** Rows of cells of CSV text, as RFC 4180 has them. */
function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  for (let at = 0; at < text.length; at += 1) {
    const char = text[at];
    if (quoted) {
      if (char !== '"') cell += char;
      else if (text[at + 1] === '"') {
        cell += '"';
        at += 1;
      } else quoted = false;
    } else if (char === '"') quoted = true;
    else if (char === ",") {
      row.push(cell);
      cell = "";
    } else if (char === "\n") {
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
    } else if (char !== "\r") cell += char;
  }
  if (cell !== "" || row.length > 0) rows.push([...row, cell]);
  return rows;
}

function toCsv(rows: readonly (readonly string[])[]): string {
  const quote = (cell: string) => (/[",\n\r]/.test(cell) ? `"${cell.replace(/"/g, '""')}"` : cell);
  return rows.map((row) => `${row.map(quote).join(",")}\n`).join("");
}

/** The names of the files in a zip, in their order, and the text of each, read with Node alone. */
function unzip(zip: Buffer): Array<{ name: string; text: () => string }> {
  // The end of the central directory: its signature, searched for from the end.
  let end = zip.length - 22;
  while (end >= 0 && zip.readUInt32LE(end) !== 0x06054b50) end -= 1;
  expect(end, "the end of the zip's central directory").toBeGreaterThanOrEqual(0);
  const entries = zip.readUInt16LE(end + 10);
  let at = zip.readUInt32LE(end + 16);
  const files: Array<{ name: string; text: () => string }> = [];
  for (let one = 0; one < entries; one += 1) {
    expect(zip.readUInt32LE(at), "a header of the central directory").toBe(0x02014b50);
    const method = zip.readUInt16LE(at + 10);
    const size = zip.readUInt32LE(at + 20);
    const nameLength = zip.readUInt16LE(at + 28);
    const extraLength = zip.readUInt16LE(at + 30);
    const commentLength = zip.readUInt16LE(at + 32);
    const local = zip.readUInt32LE(at + 42);
    const name = zip.toString("utf8", at + 46, at + 46 + nameLength);
    files.push({
      name,
      text: () => {
        const start = local + 30 + zip.readUInt16LE(local + 26) + zip.readUInt16LE(local + 28);
        const data = zip.subarray(start, start + size);
        return (method === 8 ? inflateRawSync(data) : data).toString("utf8");
      },
    });
    at += 46 + nameLength + extraLength + commentLength;
  }
  return files;
}

/** Load a file on the Import page and see its preview. */
async function preview(page: Page, name: string, content: string | Buffer, entity: string) {
  await page.goto("./import");
  await expect(page.getByRole("heading", { level: 1, name: "Import" })).toBeVisible();
  await page.getByLabel("File", { exact: true }).setInputFiles({
    name,
    mimeType: name.endsWith(".json") ? "application/json" : "text/csv",
    buffer: Buffer.isBuffer(content) ? content : Buffer.from(content, "utf8"),
  });
  // The name of the file says what it holds.
  await expect(page.getByLabel("Records")).toHaveValue(entity);
  await page.getByRole("button", { name: "Preview", exact: true }).click();
  await expect(page.getByTestId("import-job")).toHaveAttribute("data-status", "previewed", {
    timeout: 20_000,
  });
}

test("the Import page lists every table in the order of loading, and exports one before the list has come", async ({
  page,
  account,
}, testInfo) => {
  const seen = await watch(page.context());
  await signIn(page, account);
  // The list is held back: the buttons work from the start all the same.
  let release = () => {};
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/v1/exports/tables", async (route) => {
    await held;
    await route.continue();
  });
  await page.goto("./import");
  const list = region(page, "What can be loaded and exported");
  await expect(list).toBeVisible();
  await expect(tableRow(page, "tags").getByTestId("table-count")).toHaveText("…");
  const asked = exportAsked(page);
  const tags = await exported(
    page,
    list.getByRole("button", { name: "Export Tags as CSV" }),
    testInfo,
  );
  // The whole table, by the server's word for it, and nothing beside it (review X2).
  expect((await asked).postDataJSON()).toEqual({ entity: "tags", format: "csv", whole: true });
  expect(tags.name).toMatch(serverName("tags", "csv"));
  expect(tags.content.toString("utf8").split("\n")[0]).toBe(HEADERS.tags);
  await expect(tableRow(page, "tags")).toContainText(/Exported to hirdir-tags-.*\.csv\./);
  release();

  // Every table, in the order their files are loaded, each with how many it holds.
  await expect(tables(page).locator("tbody th")).toHaveText(TABLES.map(([label]) => label));
  await expect(tables(page).getByTestId("table-count").filter({ hasText: "…" })).toHaveCount(0);
  // How many hold nothing is said too, as "33 tables, 5 holding nothing yet": it is what
  // the other files have made so far.
  await expect(page.getByTestId("export-tables-said")).toHaveText(
    new RegExp(`^${TABLES.length} tables(, [^,]+ holding nothing yet)?, in the order`),
  );
  // The upload is where it was, beside the list.
  await expect(page.getByLabel("File", { exact: true })).toBeVisible();
  await expectClean(page, seen);
});

test("a table that holds nothing is exported as its template, filled in, and loaded back as one record", async ({
  page,
  account,
}, testInfo) => {
  const seen = await watch(page.context());
  await signIn(page, account);
  await page.goto("./import");
  const row = tableRow(page, "networks");
  await expect(row).toHaveAttribute("data-count", /^\d+$/);
  const empty = (await row.getAttribute("data-count")) === "0";
  let header: string;
  if (empty) {
    // The page says so, and that its CSV is the template: the header row alone.
    await expect(row.getByTestId("table-count")).toHaveText("None");
    const template = await exported(
      page,
      row.getByRole("button", { name: "Export the CSV template of Networks" }),
      testInfo,
    );
    expect(template.name).toMatch(serverName("networks", "csv"));
    expect(template.content.toString("utf8")).toBe(`${HEADERS.networks}\n`);
    header = HEADERS.networks;
  } else {
    // Another file, or an earlier run, made one: its header row is the template.
    testInfo.annotations.push({ type: "note", description: "Networks held records already" });
    const file = await exported(
      page,
      row.getByRole("button", { name: "Export Networks as CSV" }),
      testInfo,
    );
    header = file.content.toString("utf8").split("\n")[0] ?? "";
    expect(header).toBe(HEADERS.networks);
  }

  // One row is added to the template, and the file is loaded back: it makes one network.
  await preview(page, `networks-${id}.csv`, `${header}\n,${network},vrf\n`, "networks");
  await expect(count(page, "created")).toHaveText("1");
  await expect(count(page, "rejected")).toHaveText("0");
  await page.getByRole("button", { name: "Apply 1 row" }).click();
  await whenApplied(page, 1);
  await expect(page.getByTestId("import-created")).toContainText(network);
  // The counts are read again once it is applied: the table holds something now.
  await expect(tableRow(page, "networks").getByTestId("table-count")).not.toHaveText("None");
  await expect(tableRow(page, "networks")).not.toHaveAttribute("data-count", "0");
  await expectClean(page, seen);
});

test("a table with records is exported and loaded back as nothing to change", async ({
  page,
  account,
}, testInfo) => {
  const seen = await watch(page.context());
  await signIn(page, account);
  await page.goto("./import");
  const file = await exported(
    page,
    tableRow(page, "networks").getByRole("button", { name: "Export Networks as JSON" }),
    testInfo,
  );
  expect(file.name).toMatch(serverName("networks", "json"));
  const envelope = JSON.parse(file.content.toString("utf8")) as {
    entity: string;
    records: Array<{ hid: string; label: string }>;
  };
  expect(envelope.entity).toBe("networks");
  // This file's own records, as they were exported: those of others may change meanwhile.
  const own = envelope.records.filter((record) => record.label === network);
  expect(own).toHaveLength(1);
  await preview(
    page,
    `networks-${id}.json`,
    JSON.stringify({ ...envelope, records: own }),
    "networks",
  );
  await expect(count(page, "unchanged")).toHaveText("1");
  await expect(count(page, "created")).toHaveText("0");
  await expect(count(page, "updated")).toHaveText("0");
  await expect(count(page, "rejected")).toHaveText("0");
  await expectClean(page, seen);
});

test("everything is exported as one zip, a file to each table in the order of loading", async ({
  page,
  account,
}, testInfo) => {
  test.setTimeout(120_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  await page.goto("./import");
  const list = region(page, "What can be loaded and exported");
  for (const format of ["csv", "json"]) {
    const zip = await exported(
      page,
      list.getByRole("button", { name: `Export everything as ${format.toUpperCase()}` }),
      testInfo,
    );
    expect(zip.name).toMatch(serverName(`all-${format}`, "zip"));
    const files = unzip(zip.content);
    expect(files.map((one) => one.name)).toEqual(TABLES.map(([, name]) => `${name}.${format}`));
    // The file of each table is the whole table: this file's network is in it.
    expect(files.find((one) => one.name === `networks.${format}`)?.text()).toContain(network);
    await expect(list.locator(".table-exports-all")).toContainText(
      new RegExp(`Exported to hirdir-all-${format}-.*\\.zip\\.`),
    );
  }
  await expectClean(page, seen);
});

test("an export a busy server refuses says so beside its button, and is pressed again", async ({
  page,
  account,
}, testInfo) => {
  const seen = await watch(page.context());
  await signIn(page, account);
  await page.goto("./import");
  // The next export is refused as a server past its ceiling refuses one (P-265).
  await page.route(
    "**/api/v1/exports",
    (route) =>
      route.fulfill({
        status: 503,
        headers: { "Retry-After": "5", "Content-Type": "application/problem+json" },
        body: JSON.stringify({
          type: "about:blank",
          title: "Busy",
          status: 503,
          detail: "the server is busy and this request was not answered; try again shortly",
          errors: [],
          busy: { health: "busy", because: ["response_ms"], refusing: "long", retry_after: 5 },
        }),
      }),
    { times: 1 },
  );
  const row = tableRow(page, "sites");
  const button = row.getByRole("button", {
    name: /^Export (the CSV template of )?Sites( as CSV)?$/,
  });
  await button.click();
  await expect(row.locator(".alert-error")).toHaveText(
    "The server is busy and did not answer this. Try again in 5 seconds.",
  );
  await expect(button).toBeEnabled();
  const again = await exported(page, button, testInfo);
  expect(again.name).toMatch(serverName("sites", "csv"));
  await expect(row.locator(".alert-error")).toHaveCount(0);
  await expectClean(page, seen, ["503 POST"]);
});

test("a View-only person exports from the list, and has no upload", async ({
  page,
  request,
}, testInfo) => {
  const viewer = await createAccount(request, `e2e-${id}-viewer`, "viewer");
  const seen = await watch(page.context());
  await signIn(page, viewer);
  await page.goto("./import");
  await expect(page.getByText("Importing needs the Inventory role.")).toBeVisible();
  await expect(page.getByLabel("File", { exact: true })).toHaveCount(0);
  const file = await exported(
    page,
    tableRow(page, "regions").getByRole("button", { name: "Export Regions as JSON" }),
    testInfo,
  );
  expect(file.name).toMatch(serverName("regions", "json"));
  await expectClean(page, seen);
});

test("Geography exports its three tables, and twenty shipping addresses are corrected in a file and loaded back", async ({
  page,
  account,
}, testInfo) => {
  test.setTimeout(180_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  // A region and two sites of this file's own.
  await importFile(page, "regions", `regions-${id}.csv`, ["hid", "name"], [["", regionName]]);
  await importFile(
    page,
    "sites",
    `sites-${id}.csv`,
    ["hid", "name", "region", "ship_address1", "ship_city", "ship_country"],
    sites.map((site) => ["", site, regionName, "100 Sample Street", "Riverton", "US"]),
  );

  await page.goto("./geography");
  await expect(page.getByRole("heading", { level: 1, name: "Geography" })).toBeVisible();
  const line = page.getByTestId("geography-export");
  // Each of the three, as CSV, in the columns its import reads, and as JSON, its envelope.
  for (const [entity, label] of [
    ["regions", "Regions"],
    ["sites", "Sites"],
    ["locations", "Locations"],
  ] as const) {
    const asked = exportAsked(page);
    const csv = await exported(
      page,
      line.getByRole("button", { name: `Export ${label} as CSV` }),
      testInfo,
    );
    expect((await asked).postDataJSON()).toEqual({ entity, format: "csv", whole: true });
    expect(csv.name).toMatch(serverName(entity, "csv"));
    expect(csv.content.toString("utf8").split("\n")[0]).toBe(HEADERS[entity]);
    const json = await exported(
      page,
      line.getByRole("button", { name: `Export ${label} as JSON` }),
      testInfo,
    );
    expect(json.name).toMatch(serverName(entity, "json"));
    expect((JSON.parse(json.content.toString("utf8")) as { entity: string }).entity).toBe(entity);
    await expect(line).toContainText(new RegExp(`Exported to hirdir-${entity}-.*\\.json\\.`));
  }

  // The sites as CSV: the shipping address of this file's two is corrected in the file,
  // whose other rows are left out, and the file is loaded back.
  const file = await exported(
    page,
    line.getByRole("button", { name: "Export Sites as CSV" }),
    testInfo,
  );
  const [head = [], ...rows] = parseCsv(file.content.toString("utf8"));
  const name = head.indexOf("name");
  const street = head.indexOf("ship_address1");
  const own = rows.filter((row) => sites.includes(row[name] ?? ""));
  expect(own.map((row) => row[street])).toEqual(["100 Sample Street", "100 Sample Street"]);
  const corrected = own.map((row, place) =>
    row.map((cell, column) => (column === street ? `${place + 2}00 Sample Street` : cell)),
  );
  const path = testInfo.outputPath(`sites-${id}-corrected.csv`);
  await writeFile(path, toCsv([head, ...corrected]));
  await preview(page, `sites-${id}-corrected.csv`, await readFile(path), "sites");
  await expect(count(page, "updated")).toHaveText("2");
  await expect(count(page, "created")).toHaveText("0");
  await expect(count(page, "rejected")).toHaveText("0");
  await page.getByRole("button", { name: "Apply 2 rows" }).click();
  await whenApplied(page, 2);

  // The sites hold the corrected addresses, and their file says so when exported again.
  await page.goto("./geography");
  const again = await exported(
    page,
    page.getByTestId("geography-export").getByRole("button", { name: "Export Sites as JSON" }),
    testInfo,
  );
  const records = (
    JSON.parse(again.content.toString("utf8")) as {
      records: Array<{ name: string; ship_address1: string }>;
    }
  ).records.filter((record) => sites.includes(record.name));
  expect(records.map((record) => [record.name, record.ship_address1])).toEqual([
    [sites[0], "200 Sample Street"],
    [sites[1], "300 Sample Street"],
  ]);
  await expectClean(page, seen);
});
