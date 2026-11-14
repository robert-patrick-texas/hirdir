// What the scenarios of minor items, of a stack and of a controller domain do alike:
// load a file on the Import page, open a record from its grid, read a summary. The
// three files were one until they were to run side by side, and each now loads the
// records it needs under names of its own.

import { expect, type Locator, type Page } from "@playwright/test";

export function main(page: Page): Locator {
  return page.getByRole("navigation", { name: "Main" });
}

export function region(page: Page, name: string): Locator {
  return page.getByRole("region", { name, exact: true });
}

function csv(header: string[], rows: string[][]): Buffer {
  return Buffer.from([header, ...rows].map((row) => `${row.join(",")}\n`).join(""), "utf8");
}

export function count(page: Page, which: string): Locator {
  return page.getByTestId("preview-counts").locator(`[data-count="${which}"] dd`);
}

/** Load a CSV file on the Import page: preview it, see that every row is new, apply it. */
export async function importFile(
  page: Page,
  entity: string,
  name: string,
  header: string[],
  rows: string[][],
) {
  // Opened afresh, so that the form holds nothing of the file before.
  await page.goto("./import");
  await expect(page.getByRole("heading", { level: 1, name: "Import" })).toBeVisible();
  await page.getByLabel("File", { exact: true }).setInputFiles({
    name,
    mimeType: "text/csv",
    buffer: csv(header, rows),
  });
  // The name of the file suggested what it holds, the new kinds of record among them.
  await expect(page.getByLabel("Records")).toHaveValue(entity);
  await page.getByRole("button", { name: "Preview", exact: true }).click();
  const job = page.getByTestId("import-job");
  await expect(job).toHaveAttribute("data-status", "previewed");
  await expect(count(page, "created")).toHaveText(String(rows.length));
  await expect(count(page, "rejected")).toHaveText("0");
  await page
    .getByRole("button", { name: `Apply ${rows.length} ${rows.length === 1 ? "row" : "rows"}` })
    .click();
  await expect(page.getByTestId("preview-applied")).toContainText(`${rows.length} created`);
}

/**
 * Open an item from the grid, by its hostname. The link asks for minor items too, as the
 * links of the app do: the grid leaves them out otherwise.
 */
export async function openItem(page: Page, hostname: string) {
  await page.goto(`./items?filter=${encodeURIComponent(`hostname:eq:${hostname}`)}&minor=1`);
  await page.getByTestId("grid-items").getByRole("link", { name: hostname, exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: hostname })).toBeVisible();
}

export async function openGroup(page: Page, name: string) {
  await page.goto(`./groups?filter=${encodeURIComponent(`name:eq:${name}`)}`);
  await page.getByTestId("grid-device-groups").getByRole("link", { name, exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
}

/** The summary of the items a filter keeps. */
export async function summary(page: Page, filter: string, by = "") {
  const query = new URLSearchParams({ filter, ...(by ? { by } : {}) });
  await page.goto(`./reports?${query.toString()}`);
  await expect(page.getByRole("heading", { level: 1, name: "Summary" })).toBeVisible();
  await expect(page.getByTestId("totals")).toBeVisible();
}

/** Start the grid of items as a new reader has it, with one filter in the filter box. */
export async function freshGrid(page: Page, filter: string) {
  await page.goto("./items");
  await expect(page.getByTestId("grid-items")).toBeVisible();
  await page.getByText("Columns", { exact: true }).click();
  await page.getByRole("button", { name: "Reset layout and filters" }).click();
  await page.getByText("Columns", { exact: true }).click();
  await page.getByLabel("Filter", { exact: true }).fill(filter);
  await page.getByRole("button", { name: "Apply", exact: true }).click();
}

/** Find an item in a picker by what is typed, and choose it. */
export async function pick(within: Locator, label: string, typed: string, name: string) {
  await within.getByLabel(label, { exact: true }).fill(typed);
  await within
    .getByRole("list", { name: "Items that match" })
    .getByRole("button", { name: new RegExp(`^${name}( |$)`) })
    .click();
}

export function memberRow(page: Page, hostname: string): Locator {
  return page.getByTestId("members").locator("tbody tr", { hasText: hostname });
}
