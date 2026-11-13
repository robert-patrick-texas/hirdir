// The browser scenarios of release 0.3.0: files in and out, and one change to many items.
//
//   S15  Preview an import, change one of its rows in the web UI, then apply: nothing is
//        applied, and a new preview is asked for.
//   S16  Filter the grid, select rows, copy, and export CSV and JSON: the clipboard and
//        both files hold the same rows and columns, each with `hid` first.
//   S17  (the browser's part) A bulk edit whose rows somebody changed after the preview
//        is shown which rows, and none of it is applied.
//
// On the way: a file refused whole, rejected rows left out on request, a vendor that an
// import had to create and that is then reviewed, and a clipboard that refuses.
//
// The environment that names the server and the Admin is described in support.ts. Every
// name below is made up, with a random part so that the scenarios can be run again on
// the same server. They run in order: the later ones use what the first loads.

import { randomBytes } from "node:crypto";
import { readFile } from "node:fs/promises";
import {
  type Download,
  expect,
  type Locator,
  type Page,
  type Request,
  type TestInfo,
  test,
} from "@playwright/test";
import { expectClean, signIn, watch } from "./support";

test.describe.configure({ mode: "serial" });

const suffix = randomBytes(3).toString("hex");
const vendor = `Example Networks ${suffix}`;
const pid = `EN-4800-24T-${suffix}`;
const prefix = `site2-sw-dist-${suffix}`;
const hosts = [`${prefix}-01`, `${prefix}-02`, `${prefix}-03`];
const serials = hosts.map((_, place) => `ENX${suffix.toUpperCase()}${place + 1}`);
const filter = `hostname:prefix:${prefix}`;
const SHOWN = [
  "hid",
  "name",
  "vendor",
  "pid",
  "serial_number",
  "lifecycle_state",
  "disposition",
  "expected_online",
  "owner",
  "tags",
  "est_value",
  "ldos",
];

function main(page: Page): Locator {
  return page.getByRole("navigation", { name: "Main" });
}

function region(page: Page, name: string): Locator {
  return page.getByRole("region", { name, exact: true });
}

function count(page: Page, which: string): Locator {
  return page.getByTestId("preview-counts").locator(`[data-count="${which}"] dd`);
}

function previewRow(page: Page, row: number): Locator {
  return page.getByTestId("preview-rows").locator(`tr[data-row="${row}"]`);
}

function csv(header: string[], rows: string[][]): Buffer {
  return Buffer.from([header, ...rows].map((row) => `${row.join(",")}\n`).join(""), "utf8");
}

/** Rows of cells, of text that this test wrote: no cell holds a comma, a quote or a line break. */
function cells(text: string, separator: string): string[][] {
  expect(text).not.toContain('"');
  return text
    .replace(/\n$/, "")
    .split("\n")
    .map((line) => line.split(separator));
}

/** A value of a JSON export as a CSV file writes it. */
function asCell(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (Array.isArray(value)) return value.join(";");
  return String(value);
}

async function chooseFile(page: Page, name: string, content: Buffer) {
  await page.getByLabel("File", { exact: true }).setInputFiles({
    name,
    mimeType: name.endsWith(".json") ? "application/json" : "text/csv",
    buffer: content,
  });
}

/** Change an item on a page of its own, as somebody else would in the meantime. */
async function changeElsewhere(page: Page, hostname: string, assetTag: string) {
  const other = await page.context().newPage();
  await other.goto(`./items?filter=${encodeURIComponent(`hostname:eq:${hostname}`)}`);
  await other.getByTestId("grid-items").getByRole("link", { name: hostname }).click();
  await expect(other.getByRole("heading", { level: 1, name: hostname })).toBeVisible();
  const details = region(other, "Details");
  await details.getByLabel("Asset tag").fill(assetTag);
  await details.getByRole("button", { name: "Save" }).click();
  await expect(other.getByText("The item was saved.")).toBeVisible();
  await other.close();
}

async function openGrid(page: Page) {
  await page.goto(`./items?filter=${encodeURIComponent(filter)}`);
  await expect(page.getByTestId("grid-total")).toHaveText("3 items");
  // The same columns whatever an earlier run left behind in this browser.
  await page.getByText("Columns", { exact: true }).click();
  await page.getByRole("button", { name: "Reset layout and filters" }).click();
  await page.getByText("Columns", { exact: true }).click();
  await page.getByLabel("Filter", { exact: true }).fill(filter);
  await page.getByRole("button", { name: "Apply", exact: true }).click();
  await expect(page.getByTestId("grid-total")).toHaveText("3 items");
}

function gridRow(page: Page, hostname: string): Locator {
  return page.getByTestId("grid-items").locator("[row-id]", { hasText: hostname });
}

/** The text of a file the browser saved. It is copied here first: the browser may be elsewhere. */
async function saved(download: Download, testInfo: TestInfo): Promise<string> {
  const path = testInfo.outputPath(download.suggestedFilename());
  await download.saveAs(path);
  return readFile(path, "utf8");
}

function exportsSent(page: Page): Promise<Request> {
  return page.waitForRequest(
    (request) => request.method() === "POST" && request.url().endsWith("/api/v1/exports"),
  );
}

test("S15: an import is previewed, and is not applied once a record has changed", async ({
  page,
}) => {
  test.setTimeout(120_000);
  const seen = await watch(page.context());
  await signIn(page);
  await main(page).getByRole("link", { name: "Import" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Import" })).toBeVisible();

  // A file with a column the records do not have is refused whole, and the page says why.
  await chooseFile(page, `items-${suffix}.csv`, csv(["hid", "rack_colour"], [["", "teal"]]));
  // The name of the file suggested what it holds.
  await expect(page.getByLabel("Records")).toHaveValue("items");
  await page.getByRole("button", { name: "Preview", exact: true }).click();
  await expect(page.getByText(/'rack_colour' is not a column of items/)).toBeVisible();
  await expect(page.getByTestId("import-job")).toHaveCount(0);

  // Three new items of a model nobody has entered yet. The preview says what it would do.
  const header = ["hid", "vendor", "pid", "serial_number", "hostname", "description"];
  const first = hosts.map((host, place) => ["", vendor, pid, serials[place] ?? "", host, ""]);
  await chooseFile(page, `items-${suffix}.csv`, csv(header, first));
  await page.getByRole("button", { name: "Preview", exact: true }).click();
  const job = page.getByTestId("import-job");
  await expect(job).toHaveAttribute("data-status", "previewed");
  await expect(page).toHaveURL(/\/import\/[0-9a-f-]{36}$/);
  await expect(count(page, "created")).toHaveText("3");
  await expect(count(page, "rejected")).toHaveText("0");
  await expect(previewRow(page, 1)).toHaveAttribute("data-outcome", "create");
  await expect(previewRow(page, 1).locator('[data-field="hostname"]')).toHaveText(
    `hostname: (blank) → ${hosts[0]}`,
  );
  // The vendor and the catalog entry do not exist: the row says it will make them.
  await expect(previewRow(page, 1)).toContainText(`creates the vendor ${vendor}, to be reviewed`);
  await expect(page.getByTestId("import-status")).toHaveText("Previewed, not applied");

  // A preview has an address of its own: it is there again after a reload.
  await page.reload();
  await expect(count(page, "created")).toHaveText("3");
  await page.getByRole("button", { name: "Apply 3 rows" }).click();
  await expect(page.getByTestId("preview-applied")).toContainText("3 created");
  await expect(job).toHaveAttribute("data-status", "applied");
  await expect(page.getByRole("button", { name: /^Apply/ })).toHaveCount(0);
  // The rows now lead to the records they made, and the job is among the past imports.
  await expect(previewRow(page, 1).getByRole("link")).toHaveAttribute("href", /\/items\//);
  await expect(page.getByTestId("import-jobs").locator("tbody tr").first()).toContainText(
    `items-${suffix}.csv`,
  );

  // The vendor the import had to create is marked unreviewed, and is reviewed here.
  await main(page).getByRole("link", { name: "Vendors" }).click();
  await page.getByTestId("grid-vendors").getByRole("link", { name: vendor }).click();
  await expect(page.getByRole("heading", { level: 1, name: vendor })).toContainText("Unreviewed");
  await expect(page.getByTestId("review-status")).toHaveText("Unreviewed");
  const details = region(page, "Details");
  await details.getByLabel("Review status").selectOption("reviewed");
  await details.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("The vendor was saved.")).toBeVisible();
  await expect(page.getByTestId("review-status")).toHaveText("Reviewed");
  await expect(page.getByRole("heading", { level: 1, name: vendor })).not.toContainText(
    "Unreviewed",
  );

  // A second file: two rows change a description, the third names an owner nobody has.
  const second = [
    ["", vendor, pid, serials[0] ?? "", hosts[0] ?? "", "Distribution pair A", ""],
    ["", vendor, pid, serials[1] ?? "", hosts[1] ?? "", "Distribution pair A", ""],
    ["", vendor, pid, serials[2] ?? "", hosts[2] ?? "", "", `No Such Team ${suffix}`],
  ];
  await main(page).getByRole("link", { name: "Import" }).click();
  await chooseFile(page, `items-${suffix}-changes.csv`, csv([...header, "owner"], second));
  await page.getByRole("button", { name: "Preview", exact: true }).click();
  await expect(job).toHaveAttribute("data-status", "previewed");
  await expect(count(page, "updated")).toHaveText("2");
  await expect(count(page, "rejected")).toHaveText("1");
  await expect(previewRow(page, 1).locator('[data-field="description"]')).toHaveText(
    "description: (blank) → Distribution pair A",
  );
  // Only the rejected row, with the reason it is rejected for.
  await job.getByLabel("Show").selectOption("rejected");
  await expect(page.getByTestId("preview-rows").locator("tbody tr")).toHaveCount(1);
  await expect(previewRow(page, 3)).toContainText(`there is no owner No Such Team ${suffix}`);
  await job.getByLabel("Show").selectOption("");
  await expect(page.getByTestId("preview-rows").locator("tbody tr")).toHaveCount(3);
  // With a rejected row the file is not applied as it is: the rest may be.
  await expect(page.getByRole("button", { name: "Apply 3 rows" })).toHaveCount(0);
  const applyRest = page.getByRole("button", { name: "Apply the other 2 rows" });
  await expect(applyRest).toBeVisible();

  // Meanwhile one of the previewed rows is changed in the web UI.
  await changeElsewhere(page, hosts[0] ?? "", `AT-${suffix}-1`);

  // Apply: nothing is applied, the row in the way is named, and a new preview is asked for.
  const stalePath = new URL(page.url()).pathname;
  await applyRest.click();
  const refusal = page.getByTestId("preview-out-of-date");
  await expect(refusal).toContainText("Nothing was applied.");
  await expect(refusal.locator('li[data-row="1"]')).toContainText("changed since the preview");
  await expect(refusal.locator("li")).toHaveCount(1);
  await expect(job).toHaveAttribute("data-status", "failed");
  await expect(page.getByTestId("import-status")).toHaveText("Failed: nothing was applied");
  await expect(previewRow(page, 1)).toHaveAttribute("data-stale", "true");
  await expect(page.getByRole("button", { name: /^Apply/ })).toHaveCount(0);

  // The new preview, from the same file: the same two changes, now against the item as it is.
  await refusal.getByRole("button", { name: "Preview again" }).click();
  await expect(job).toHaveAttribute("data-status", "previewed");
  expect(new URL(page.url()).pathname).not.toBe(stalePath);
  // Nothing of the failed apply was kept: both rows are still to be updated.
  await expect(count(page, "updated")).toHaveText("2");
  await applyRest.click();
  await expect(page.getByTestId("preview-applied")).toContainText("2 updated");
  await expect(page.getByTestId("import-status")).toHaveText("Applied, without the rejected rows");

  // The past imports, newest first: the one applied, the one that failed, the first.
  const jobs = page.getByTestId("import-jobs").locator("tbody tr");
  await expect(jobs.nth(0)).toContainText("Applied, without the rejected rows");
  await expect(jobs.nth(1)).toContainText("Failed: nothing was applied");
  await expect(jobs.nth(0)).toHaveAttribute("aria-current", "true");
  // A past import is opened from the list.
  await jobs.nth(1).getByRole("link").click();
  await expect(job).toHaveAttribute("data-status", "failed");
  expect(new URL(page.url()).pathname).toBe(stalePath);

  await expectClean(page, seen, ["422 POST", "409 POST"]);
});

test("S16: the clipboard and the exported files hold the same rows and columns", async ({
  page,
  browserName,
}, testInfo) => {
  test.skip(browserName !== "chromium", "reading the clipboard back needs Chromium's permission");
  test.setTimeout(120_000);
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
  const seen = await watch(page.context());
  await signIn(page);
  await openGrid(page);

  // Select two rows: one, and with Ctrl another.
  await gridRow(page, hosts[0] ?? "")
    .locator('[col-id="catalog.pid"]')
    .click();
  await gridRow(page, hosts[2] ?? "")
    .locator('[col-id="catalog.pid"]')
    .click({ modifiers: ["ControlOrMeta"] });
  await expect(page.getByTestId("grid-selected")).toContainText("2 selected");

  // Copy: tab-separated text with a header row.
  let sent = exportsSent(page);
  await page.getByRole("button", { name: "Copy", exact: true }).click();
  await expect(page.getByText("Copied 2 items to the clipboard, with a header row.")).toBeVisible();
  const copied = (await sent).postDataJSON();
  expect(copied.hids).toHaveLength(2);
  const clipboard = cells(await page.evaluate(() => navigator.clipboard.readText()), "\t");

  // Export the same rows as CSV and as JSON. Each is saved as a file, with the server's name.
  let download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export CSV" }).click();
  const csvFile = await download;
  expect(csvFile.suggestedFilename()).toMatch(/^hirdir-items-\d{8}T\d{6}[+-]\d{4}\.csv$/);
  const exported = cells(await saved(csvFile, testInfo), ",");

  download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export JSON" }).click();
  const jsonFile = await download;
  expect(jsonFile.suggestedFilename()).toMatch(/^hirdir-items-.*\.json$/);
  const envelope = JSON.parse(await saved(jsonFile, testInfo));
  expect(envelope.schema).toBe("hirdir/1");
  expect(envelope.entity).toBe("items");
  const records: Array<Record<string, unknown>> = envelope.records;

  // The same columns, `hid` first: the ones on show, by the names an export has for them.
  expect(clipboard[0]).toEqual(SHOWN);
  expect(exported[0]).toEqual(SHOWN);
  for (const record of records) expect(Object.keys(record)).toEqual(SHOWN);
  // The same rows, in the grid's order, and the same cells.
  expect(clipboard).toHaveLength(3);
  expect(clipboard).toEqual(exported);
  expect(records.map((record) => SHOWN.map((name) => asCell(record[name])))).toEqual(
    exported.slice(1),
  );
  expect(clipboard.slice(1).map((row) => row[4])).toEqual([serials[0], serials[2]]);
  for (const row of clipboard.slice(1)) expect(row[0]).toMatch(/^[0-9a-f-]{36}$/);
  // The value in force, as the grid shows it: the item's own description is not a column
  // on show, and so is in none of the three.
  expect(clipboard[0]).not.toContain("description");

  // Another order and another column: the clipboard follows the grid.
  const grid = page.getByTestId("grid-items");
  const nameHeader = grid.locator('[role="columnheader"][col-id="name"]');
  await nameHeader.click();
  await nameHeader.click();
  await expect(nameHeader).toHaveAttribute("aria-sort", "descending");
  await page.getByText("Columns", { exact: true }).click();
  await page.getByRole("group", { name: "Columns to show" }).getByLabel("Tags").uncheck();
  await page.getByRole("group", { name: "Columns to show" }).getByLabel("Hostname").check();
  await page.getByText("Columns", { exact: true }).click();

  // All that match the filter: shown as a count, and sent as the filter, never as rows.
  await page.getByRole("button", { name: "Select all that match" }).click();
  await expect(page.getByTestId("grid-selected")).toContainText(
    "all 3 items that match the filter selected",
  );
  sent = exportsSent(page);
  await page.getByRole("button", { name: "Copy", exact: true }).click();
  await expect(page.getByText("Copied 3 items to the clipboard, with a header row.")).toBeVisible();
  const all = (await sent).postDataJSON();
  expect(all.hids).toBeUndefined();
  expect(all.filter).toEqual({ field: "hostname", op: "prefix", value: prefix });
  expect(all.sort).toEqual(["-name"]);
  const everything = cells(await page.evaluate(() => navigator.clipboard.readText()), "\t");
  expect(everything[0]).toEqual([
    "hid",
    "name",
    "hostname",
    ...SHOWN.slice(2).filter((name) => name !== "tags"),
  ]);
  expect(everything.slice(1).map((row) => row[2])).toEqual([...hosts].reverse());

  download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export CSV" }).click();
  expect(cells(await saved(await download, testInfo), ",")).toEqual(everything);

  // Selecting a row takes the place of "all that match".
  await gridRow(page, hosts[1] ?? "")
    .locator('[col-id="catalog.pid"]')
    .click();
  await expect(page.getByTestId("grid-selected")).toContainText("1 selected");
  await page.getByRole("button", { name: "Clear selection" }).click();
  await expect(page.getByTestId("grid-selected")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Copy", exact: true })).toBeDisabled();

  await page.getByText("Columns", { exact: true }).click();
  await page.getByRole("button", { name: "Reset layout and filters" }).click();
  await expectClean(page, seen);
});

test("a clipboard that refuses: the rows are shown, selected, to be copied by hand", async ({
  page,
}) => {
  const seen = await watch(page.context());
  // A browser that does not let the page write to the clipboard, as on a page without HTTPS.
  await page.addInitScript(() => {
    const refuse = () => Promise.reject(new DOMException("denied", "NotAllowedError"));
    Object.defineProperty(navigator.clipboard, "write", { value: refuse });
    Object.defineProperty(navigator.clipboard, "writeText", { value: refuse });
  });
  await signIn(page);
  await openGrid(page);
  await page.getByRole("button", { name: "Select all that match" }).click();
  await page.getByRole("button", { name: "Copy", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Copy by hand" })).toBeVisible();
  const box = page.getByRole("textbox", { name: "Copy by hand" });
  const rows = cells(await box.inputValue(), "\t");
  expect(rows[0]).toEqual(SHOWN);
  expect(rows).toHaveLength(4);
  // The whole text is selected, so that Ctrl+C takes it.
  await expect(box).toBeFocused();
  expect(
    await box.evaluate((area: HTMLTextAreaElement) => area.selectionEnd - area.selectionStart),
  ).toBe((await box.inputValue()).length);
  await page.getByRole("button", { name: "Done" }).click();
  await expect(box).toHaveCount(0);
  await expectClean(page, seen);
});

test("S17: a bulk edit shows before and after, and is not applied once an item has changed", async ({
  page,
}) => {
  test.setTimeout(120_000);
  const seen = await watch(page.context());
  await signIn(page);
  await openGrid(page);
  const comment = `Refresh candidate ${suffix}`;

  // All that match the filter, edited at once: the rows go to the server as the filter.
  await page.getByRole("button", { name: "Select all that match" }).click();
  await page.getByRole("button", { name: "Bulk edit" }).click();
  const form = page.getByTestId("bulk-edit");
  await expect(form).toContainText("all 3 items that match the filter");
  // The fields that tell one item from another are not offered.
  const offered = await form.getByLabel("Field to change").locator("option").allTextContents();
  expect(offered).toContain("Comments");
  for (const identity of ["Serial number", "Asset tag", "MAC address", "Name", "Hostname"]) {
    expect(offered).not.toContain(identity);
  }
  await form.getByLabel("Field to change").selectOption({ label: "Comments" });
  await form.getByRole("button", { name: "Add", exact: true }).click();
  await form.getByRole("group", { name: "Comments" }).getByLabel("Set to").fill(comment);
  const previewed = page.waitForRequest(
    (request) => request.method() === "POST" && request.url().endsWith("/items/bulk-update"),
  );
  await form.getByRole("button", { name: "Preview the change" }).click();
  const body = (await previewed).postDataJSON();
  expect(body.hids).toBeUndefined();
  expect(body.filter).toEqual({ field: "hostname", op: "prefix", value: prefix });
  expect(body.set).toEqual({ comments: comment });

  // Before and after, for each row. Nothing has been changed yet.
  await expect(count(page, "updated")).toHaveText("3");
  for (const row of [1, 2, 3]) {
    await expect(previewRow(page, row).locator('[data-field="comments"]')).toHaveText(
      `comments: (blank) → ${comment}`,
    );
  }
  await expect(previewRow(page, 2)).toContainText(hosts[1] ?? "");

  // Somebody changes one of the three in the meantime.
  await changeElsewhere(page, hosts[1] ?? "", `AT-${suffix}-2`);

  // Apply: the row that was changed is named, and nothing at all is applied.
  await form.getByRole("button", { name: "Apply 3 items" }).click();
  const refusal = form.getByTestId("preview-out-of-date");
  await expect(refusal).toContainText("Nothing was applied.");
  await expect(refusal.locator("li")).toHaveCount(1);
  await expect(refusal.locator('li[data-row="2"]')).toContainText(hosts[1] ?? "");
  await expect(previewRow(page, 2)).toHaveAttribute("data-stale", "true");
  await expect(form.getByRole("button", { name: /^Apply/ })).toHaveCount(0);

  // Previewed again, against the items as they are now, it applies.
  await refusal.getByRole("button", { name: "Preview again" }).click();
  await expect(form.getByTestId("preview-out-of-date")).toHaveCount(0);
  // Nothing of the refused edit was kept: all three are still to be changed.
  await expect(count(page, "updated")).toHaveText("3");
  await form.getByRole("button", { name: "Apply 3 items" }).click();
  await expect(form.getByTestId("preview-applied")).toContainText("3 updated");
  await form.getByRole("button", { name: "Close" }).click();
  await expect(form).toHaveCount(0);

  // Particular rows are named by their HIDs, and a cleared field is sent as null.
  await expect(page.getByTestId("grid-total")).toHaveText("3 items");
  await gridRow(page, hosts[0] ?? "")
    .locator('[col-id="catalog.pid"]')
    .click();
  await gridRow(page, hosts[1] ?? "")
    .locator('[col-id="catalog.pid"]')
    .click({ modifiers: ["Shift"] });
  await expect(page.getByTestId("grid-selected")).toContainText("2 selected");
  await page.getByRole("button", { name: "Bulk edit" }).click();
  await expect(form).toContainText("the 2 selected items");
  await form.getByLabel("Field to change").selectOption({ label: "Comments" });
  await form.getByRole("button", { name: "Add", exact: true }).click();
  await form.getByRole("group", { name: "Comments" }).getByLabel("Clear it instead").check();
  const cleared = page.waitForRequest(
    (request) => request.method() === "POST" && request.url().endsWith("/items/bulk-update"),
  );
  await form.getByRole("button", { name: "Preview the change" }).click();
  const second = (await cleared).postDataJSON();
  expect(second.hids).toHaveLength(2);
  expect(second.filter).toBeUndefined();
  expect(second.set).toEqual({ comments: null });
  await expect(count(page, "updated")).toHaveText("2");
  await expect(previewRow(page, 1).locator('[data-field="comments"]')).toHaveText(
    `comments: ${comment} → (blank)`,
  );
  await form.getByRole("button", { name: "Apply 2 items" }).click();
  await expect(form.getByTestId("preview-applied")).toContainText("2 updated");
  await form.getByRole("button", { name: "Close" }).click();

  // The bulk edits are among the past previews, with the one that failed.
  await main(page).getByRole("link", { name: "Import" }).click();
  await page.getByRole("region", { name: "Past imports" }).getByLabel("Show").selectOption("bulk");
  const jobs = page.getByTestId("import-jobs").locator("tbody tr");
  await expect(jobs.nth(0)).toContainText("Applied");
  await expect(jobs.nth(2)).toContainText("Failed: nothing was applied");

  await expectClean(page, seen, ["409 POST"]);
});
