// The browser scenario of release 0.2.0, which walks S06, S07, S10 and part of S11 through
// the web UI: a vendor, a catalog entry and two items; a value inherited and overridden,
// each with its source; the grid filtered and sorted by the server; an item moved through
// the lifecycle; a change the rules refuse; a stale edit refused; a deep link reloaded.
//
// The environment that names the server and the Admin is described in support.ts.
//
// Every address below is relative to the base URL, so the same test runs at the root
// and under a prefix. Every name in it is made up, with a random part so that the test
// can be run again on the same server.

import { randomBytes } from "node:crypto";
import { expect, type Locator, type Page, test } from "@playwright/test";
import { expectClean, signIn, username, watch } from "./support";

const suffix = randomBytes(3).toString("hex");
const vendor = `Example Networks ${suffix}`;
const pid = `EN-4800-48P-${suffix}`;
const first = `site2-sw-access-${suffix}-01`;
const second = `site2-sw-access-${suffix}-02`;

function main(page: Page): Locator {
  return page.getByRole("navigation", { name: "Main" });
}

function region(page: Page, name: string): Locator {
  return page.getByRole("region", { name, exact: true });
}

/** The row of the "Values in force" table for one field that inherits. */
function inForce(page: Page, field: string): Locator {
  return region(page, "Values in force").locator(`tr[data-field="${field}"]`);
}

/** The names of the rows the grid shows, in order. */
async function gridNames(page: Page): Promise<string[]> {
  return page.getByTestId("grid-items").locator('[row-id] [col-id="name"]').allTextContents();
}

async function createItem(page: Page, hostname: string, serial: string, state: string) {
  await main(page).getByRole("link", { name: "Items" }).click();
  await page.getByRole("button", { name: "New item" }).click();
  const form = region(page, "New item");
  await form.getByLabel("Catalog entry").selectOption({ label: pid });
  await form.getByLabel("Serial number").fill(serial);
  await form.getByLabel("Hostname").fill(hostname);
  if (state) await form.getByLabel("Lifecycle state").selectOption(state);
  await form.getByRole("button", { name: "Create item" }).click();
  await expect(page.getByRole("heading", { level: 1, name: hostname })).toBeVisible();
}

/** Open an item from the grid, having filtered the grid down to this run's two items. */
async function openItem(page: Page, hostname: string) {
  await page.goto(
    `./items?filter=${encodeURIComponent(`hostname:prefix:site2-sw-access-${suffix}`)}`,
  );
  await page.getByTestId("grid-items").getByRole("link", { name: hostname }).click();
  await expect(page.getByRole("heading", { level: 1, name: hostname })).toBeVisible();
}

async function move(page: Page, to: string, reason: string) {
  const form = region(page, "Move to another state");
  await form.getByLabel("Move to").selectOption(to);
  await form.getByLabel("Reason").selectOption({ label: reason });
  await form.getByRole("button", { name: "Move" }).click();
  await expect(page.getByTestId("state")).toHaveText(to);
}

test("catalog values and their sources, the grid, the lifecycle, a stale edit", async ({
  page,
  baseURL,
}) => {
  test.setTimeout(180_000);
  expect(baseURL).toBeTruthy();
  const base = new URL(baseURL ?? "");
  const seen = await watch(page.context());
  await signIn(page);

  // A vendor.
  await main(page).getByRole("link", { name: "Vendors" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Vendors" })).toBeVisible();
  await page.getByRole("button", { name: "New vendor" }).click();
  await region(page, "New vendor").getByLabel("Name").fill(vendor);
  await region(page, "New vendor").getByRole("button", { name: "Create vendor" }).click();
  await expect(page.getByRole("heading", { level: 1, name: vendor })).toBeVisible();

  // A catalog entry with a value and a last day of support.
  await main(page).getByRole("link", { name: "Catalog" }).click();
  await page.getByRole("button", { name: "New catalog entry" }).click();
  const newEntry = region(page, "New catalog entry");
  await newEntry.getByLabel("Vendor").selectOption({ label: vendor });
  await newEntry.getByLabel("PID").fill(pid);
  await newEntry.getByLabel("Estimated value").fill("18000");
  await newEntry.getByLabel("Last day of support (LDoS)").fill("2034-04-30");
  await newEntry.getByRole("button", { name: "Create catalog entry" }).click();
  await expect(page.getByRole("heading", { level: 1, name: `${vendor} ${pid}` })).toBeVisible();
  const entryPath = new URL(page.url()).pathname;
  // The stack discount is inherited from the global setting, and says so.
  await expect(page.getByTestId("stack-discount")).toHaveAttribute("data-source", "setting");

  // Two items of it. Each shows the catalog's value, with the catalog as its source (S06).
  await createItem(page, first, "FCW0000X001", "Delivered");
  const firstPath = new URL(page.url()).pathname;
  expect(firstPath.startsWith(`${base.pathname}items/`)).toBe(true);
  await expect(inForce(page, "est_value")).toHaveAttribute("data-source", "catalog");
  await expect(inForce(page, "est_value")).toContainText("18000.00");
  await expect(inForce(page, "est_value")).toContainText("From the catalog entry");
  await createItem(page, second, "FCW0000X002", "");
  await expect(inForce(page, "est_value")).toHaveAttribute("data-source", "catalog");

  // Override the value on the second: its own value, with itself as the source.
  const details = region(page, "Details");
  await details.getByLabel("Estimated value").fill("21000.50");
  await details.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("The item was saved.")).toBeVisible();
  await expect(inForce(page, "est_value")).toHaveAttribute("data-source", "own");
  await expect(inForce(page, "est_value")).toContainText("21000.50");
  await expect(inForce(page, "est_value")).toContainText("Set here");
  await expect(inForce(page, "ldos")).toHaveAttribute("data-source", "catalog");
  await expect(inForce(page, "ldos")).toContainText("2034-04-30");

  // Change the last day of support on the catalog entry: both items show it at once (S07).
  await page.getByRole("link", { name: `${vendor} ${pid}` }).click();
  await expect(page.getByRole("heading", { level: 1, name: `${vendor} ${pid}` })).toBeVisible();
  expect(new URL(page.url()).pathname).toBe(entryPath);
  const entryDetails = region(page, "Details");
  await entryDetails.getByLabel("Last day of support (LDoS)").fill("2035-06-30");
  await entryDetails.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("The catalog entry was saved.")).toBeVisible();

  // The link from the entry to its items: the grid, filtered by the server.
  await page.getByRole("link", { name: "Items of this entry" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Items" })).toBeVisible();
  await expect(page.getByTestId("grid-total")).toHaveText("2 items");
  expect(await gridNames(page)).toEqual([first, second]);
  const grid = page.getByTestId("grid-items");
  // Hide three columns, to bring the last ones into view, and ask for the estimated
  // value, which the grid does not show until it is asked for.
  await page.getByText("Columns", { exact: true }).click();
  const shown = page.getByRole("group", { name: "Columns to show" });
  await expect(shown.getByLabel("Estimated value", { exact: true })).not.toBeChecked();
  for (const column of ["Expected online", "Owner", "Tags"]) {
    await shown.getByLabel(column).uncheck();
  }
  await shown.getByLabel("Estimated value", { exact: true }).check();
  await page.getByText("Columns", { exact: true }).click();
  await expect(grid.locator('[role="columnheader"][col-id="owner.label"]')).toHaveCount(0);
  const ldosCells = grid.locator('[row-id] [col-id="effective.ldos"]');
  await expect(ldosCells).toHaveText(["2035-06-30", "2035-06-30"]);
  // An inherited value is shown as inherited; the overridden one is not.
  const values = grid.locator('[row-id] [col-id="effective.est_value"]');
  await expect(values).toHaveText(["18000.00", "21000.50"]);
  await expect(values.nth(0)).toHaveClass(/cell-inherited/);
  await expect(values.nth(1)).not.toHaveClass(/cell-inherited/);

  // Sort by a column: the server sorts, and the rows come back in the other order.
  const nameHeader = grid.locator('[role="columnheader"][col-id="name"]');
  await nameHeader.click();
  await expect(nameHeader).toHaveAttribute("aria-sort", "ascending");
  await nameHeader.click();
  await expect(nameHeader).toHaveAttribute("aria-sort", "descending");
  await expect.poll(() => gridNames(page)).toEqual([second, first]);

  // Filter by a column, from the keyboard: only the item that has a state is left.
  await grid.locator('[role="columnheader"][col-id="lifecycle_state"]').focus();
  await page.keyboard.press("Control+Enter");
  const filter = page.getByRole("group", { name: "Show rows where State is" });
  await filter.getByLabel("Delivered").check();
  await page.locator(".ag-popup").getByRole("button", { name: "Apply" }).click();
  await expect(page.getByTestId("grid-total")).toHaveText("1 item");
  expect(await gridNames(page)).toEqual([first]);

  // Select the row: the count of selected rows is shown.
  await grid.locator('[row-id] [col-id="catalog.pid"]').first().click();
  await expect(page.getByTestId("grid-selected")).toContainText("1 selected");

  // The short form in the filter box, joined to the column filter by the server. The link
  // from the entry put its own condition in the box; a second one is added to it.
  const box = page.getByLabel("Filter", { exact: true });
  const fromLink = await box.inputValue();
  expect(fromLink).toMatch(/^catalog_entry_hid:eq:/);
  await box.fill(`${fromLink} serial_number:eq:FCW0000X002`);
  await page.getByRole("button", { name: "Apply", exact: true }).click();
  await expect(page.getByTestId("grid-total")).toHaveText("No items");
  await box.fill(`${fromLink} serial_number:prefix:fcw0000x`);
  await page.getByRole("button", { name: "Apply", exact: true }).click();
  await expect(page.getByTestId("grid-total")).toHaveText("1 item");
  // A filter the server cannot read is refused, and the refusal is shown.
  await box.fill(`${fromLink} no_such_field:eq:1`);
  await page.getByRole("button", { name: "Apply", exact: true }).click();
  await expect(
    page.getByText("no_such_field is not a field this list can be filtered by"),
  ).toBeVisible();
  await box.fill(fromLink);
  await page.getByRole("button", { name: "Apply", exact: true }).click();
  await expect(page.getByTestId("grid-total")).toHaveText("1 item");
  await page.getByText("Columns", { exact: true }).click();
  await page.getByRole("button", { name: "Reset layout and filters" }).click();
  await page.getByText("Columns", { exact: true }).click();

  // The layout and the last filter are remembered: after a reload the grid comes back
  // with the same filter, the same sort and the same columns.
  await page.goto("./items");
  await box.fill(`hostname:prefix:site2-sw-access-${suffix}`);
  await page.getByRole("button", { name: "Apply", exact: true }).click();
  await expect(page.getByTestId("grid-total")).toHaveText("2 items");
  await nameHeader.click();
  await nameHeader.click();
  await expect(nameHeader).toHaveAttribute("aria-sort", "descending");
  await page.getByText("Columns", { exact: true }).click();
  await page.getByRole("group", { name: "Columns to show" }).getByLabel("Owner").uncheck();
  await page.getByRole("group", { name: "Columns to show" }).getByLabel("Hostname").check();
  await page.getByText("Columns", { exact: true }).click();
  await expect(grid.locator('[role="columnheader"][col-id="hostname"]')).toHaveCount(1);
  await page.reload();
  await expect(page.getByTestId("grid-total")).toHaveText("2 items");
  await expect(box).toHaveValue(`hostname:prefix:site2-sw-access-${suffix}`);
  await expect(nameHeader).toHaveAttribute("aria-sort", "descending");
  await expect.poll(() => gridNames(page)).toEqual([second, first]);
  await expect(grid.locator('[role="columnheader"][col-id="hostname"]')).toHaveCount(1);
  await expect(grid.locator('[role="columnheader"][col-id="owner.label"]')).toHaveCount(0);
  await page.getByText("Columns", { exact: true }).click();
  await page.getByRole("button", { name: "Reset layout and filters" }).click();
  await expect(box).toHaveValue("");
  await expect(grid.locator('[role="columnheader"][col-id="hostname"]')).toHaveCount(0);

  // Both items show the entry's new date, and neither was written to.
  await openItem(page, first);
  await expect(inForce(page, "ldos")).toContainText("2035-06-30");
  await expect(inForce(page, "ldos")).toHaveAttribute("data-source", "catalog");

  // Walk the first item Delivered → Assigned → Test → Prod (S10).
  await expect(page.getByTestId("state")).toHaveText("Delivered");
  await move(page, "Assigned", "Received");
  await expect(page.getByTestId("disposition")).toHaveText("Staging");
  await move(page, "Test", "Staged");
  await move(page, "Prod", "Deployed");
  await expect(page.getByTestId("disposition")).toHaveText("Production");
  await expect(page.getByTestId("intent")).toHaveText("Expected online");

  // Within Prod: a spare, offline. That is an ordinary change, and the rules allow it.
  const standing = region(page, "Change the disposition or the intent");
  await standing.getByLabel("Disposition").selectOption("Spare");
  await standing.getByLabel("Expected online").selectOption({ label: "No" });
  await standing.getByRole("button", { name: "Save standing" }).click();
  await expect(page.getByTestId("disposition")).toHaveText("Spare");
  await expect(page.getByTestId("intent")).toHaveText("Expected offline");

  // Excess and online in Prod: the rules refuse it, the form says why, nothing changes.
  await standing.getByLabel("Disposition").selectOption("Excess");
  await standing.getByLabel("Expected online").selectOption({ label: "Yes" });
  await standing.getByRole("button", { name: "Save standing" }).click();
  await expect(
    standing.getByText(/an item in Prod is one of Production, Spare, not Excess/),
  ).toBeVisible();
  await expect(page.getByTestId("disposition")).toHaveText("Spare");
  await expect(page.getByTestId("intent")).toHaveText("Expected offline");

  // Each move is in the history, with who and why.
  const history = region(page, "History");
  const moves = history.locator('tbody[data-action="transition"]');
  await expect(moves).toHaveCount(3);
  for (const [place, reason, from, to] of [
    [0, "deployed", "Test", "Prod"],
    [1, "staged", "Assigned", "Test"],
    [2, "received", "Delivered", "Assigned"],
  ] as const) {
    await expect(moves.nth(place)).toContainText(username);
    await expect(moves.nth(place).locator("tr", { hasText: "state_reason" })).toContainText(reason);
    const state = moves.nth(place).locator("tr", { hasText: "lifecycle_state" });
    await expect(state.locator("td").nth(-2)).toHaveText(from);
    await expect(state.locator("td").nth(-1)).toHaveText(to);
  }

  // A stale edit. A second page changes the item while the first still shows it as it was.
  const other = await page.context().newPage();
  await other.goto(`.${firstPath.slice(base.pathname.length - 1)}`);
  await expect(other.getByRole("heading", { level: 1, name: first })).toBeVisible();
  const otherDetails = region(other, "Details");
  await otherDetails.getByLabel("Asset tag").fill(`AT-${suffix}`);
  await otherDetails.getByRole("button", { name: "Save" }).click();
  await expect(other.getByText("The item was saved.")).toBeVisible();
  await other.close();

  // The first page saves against the version it read: refused, plainly, and not sent again.
  await details.getByLabel("Comments").fill("Moved to the spares shelf");
  await details.getByRole("button", { name: "Save" }).click();
  const refusal = details.getByText("This record has changed.");
  await expect(refusal).toBeVisible();
  await expect(details).toContainText("Someone changed it after you opened it");
  await expect(details).toContainText("your change was not saved");
  await details.getByRole("button", { name: "Reload" }).click();
  // Reloaded: the other page's change is there, this page's was not saved.
  await expect(details.getByLabel("Asset tag")).toHaveValue(`AT-${suffix}`);
  await expect(details.getByLabel("Comments")).toHaveValue("");
  await expect(refusal).toHaveCount(0);

  // Reload the deep link: the same page comes back, under the same prefix, still signed in.
  await page.reload();
  await expect(page.getByRole("heading", { level: 1, name: first })).toBeVisible();
  expect(new URL(page.url()).pathname).toBe(firstPath);
  await expect(page.locator(".who-name")).toHaveText(username);
  await expect(page.getByTestId("state")).toHaveText("Prod");
  expect(new URL(await page.evaluate(() => document.baseURI)).pathname).toBe(base.pathname);

  // The three refusals above are the only requests that failed.
  await expectClean(page, seen, ["422 POST", "422 PATCH", "409 PATCH"]);
});
