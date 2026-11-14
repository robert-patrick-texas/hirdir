// The browser scenarios of release 0.4.0, as release 0.4.1 has them, for an item and what
// is in it: what a person does in S18.
//
//   S18  Two power supplies and a module in a switch; the switch is given another owner
//        and moved to Prod. The minor items show the new owner and the new state, as
//        inherited from the item they are in; the component count is one, not four.
//
// And what 0.4.1 added: minor items stay out of the item grid until Include minor items
// is turned on; a condition is set on an item's page, what is seen of it is recorded, and
// its health is a mark in the grid; the summary holds no money, which is in the
// management report.
//
// On the way: the files of the catalog and of the owners on the Import page, the new
// columns of the item grid, a minor item given a state of its own and returned to
// inheriting, an item taken out of the item it is in and put back.
//
// The scenarios of a stack and of its addresses are in stack.spec.ts, and those of a
// controller domain in wireless.spec.ts. The three were one file, and are three so that
// they run side by side: each loads the catalog and the owners it needs, under names of
// its own.
//
// The environment that names the server and the Admin is described in support.ts, with
// what a spec file does to be run beside the others: this one signs in as an Admin of its
// own, and every summary and grid it counts in is filtered down to what it made. Every
// name and serial number below is made up, with the mark of this file and a random part,
// so that the scenarios can be run again on the same server. The scenarios run in order:
// the later ones use what the earlier ones made.

import { readFile } from "node:fs/promises";
import {
  type Download,
  expect,
  type Locator,
  type Page,
  type Request,
  type TestInfo,
} from "@playwright/test";
import { count, freshGrid, importFile, main, openItem, pick, region, summary } from "./structure";
import { expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const suffix = mark("minor-items");
const upper = suffix.toUpperCase();
const vendor = `Example Networks ${suffix}`;
const switchPid = `EN-9300-48P-${suffix}`;
const supplyPid = `EN-PWR-715-${suffix}`;
const modulePid = `EN-NM-8X-${suffix}`;
// A catalog entry as a form offers it: its PID, and its model name beside it.
const switchEntry = `${switchPid} (Example 9300 48-port)`;
const supplyEntry = `${supplyPid} (Example 715 W supply)`;
const moduleEntry = `${modulePid} (Example 8-port uplink module)`;
const engineering = `Network Engineering ${suffix}`;
const campus = `Campus Services ${suffix}`;

// S18: a switch and what is in it.
const chassisPrefix = `site2-sw-acc-${suffix}`;
const chassis = `${chassisPrefix}-01`;
const supplyA = `${chassisPrefix}-01-ps-a`;
const supplyB = `${chassisPrefix}-01-ps-b`;
const uplink = `${chassisPrefix}-01-nm-1`;

/** The rows of a file the browser saved, the header among them. */
async function savedRows(download: Download, testInfo: TestInfo): Promise<string[]> {
  const path = testInfo.outputPath(download.suggestedFilename());
  await download.saveAs(path);
  return (await readFile(path, "utf8")).replace(/\n$/, "").split("\n");
}

function exportsSent(page: Page): Promise<Request> {
  return page.waitForRequest(
    (request) => request.method() === "POST" && request.url().endsWith("/api/v1/exports"),
  );
}

async function move(page: Page, to: string, reason: string) {
  const form = region(page, "Move to another state");
  await form.getByLabel("Move to").selectOption(to);
  await form.getByLabel("Reason").selectOption({ label: reason });
  await form.getByRole("button", { name: "Move" }).click();
  await expect(page.getByTestId("state")).toHaveText(to);
}

async function addMinorItem(page: Page, entry: string, hostname: string, position: string) {
  await region(page, "Minor items").getByRole("button", { name: "Add a minor item" }).click();
  const form = region(page, "New minor item");
  await form.getByLabel("Catalog entry").selectOption({ label: entry });
  await form.getByLabel("Serial number").fill(`${hostname}-sn`.toUpperCase());
  await form.getByLabel("Hostname").fill(hostname);
  await form.getByLabel("Position").fill(position);
  await form.getByRole("button", { name: "Create minor item" }).click();
  await expect(page.getByText(`${hostname} was added to ${chassis}.`)).toBeVisible();
}

/** The row of one minor item in the table of an item's page. */
function minorRow(page: Page, hostname: string): Locator {
  return page.getByTestId("minor-items").locator("tbody tr", { hasText: hostname });
}

test("the catalog and the owners the scenarios use are loaded from files", async ({
  page,
  account,
}) => {
  test.setTimeout(180_000);
  const seen = await watch(page.context());
  await signIn(page, account);

  // The first page shows the headline of the summary: the components beside the managed
  // nodes, the support weight and the components by health. It shows no money.
  const headline = region(page, "The inventory in numbers");
  await expect(headline.getByTestId("totals")).toBeVisible();
  await expect(page.getByTestId("total-components")).toHaveText(/^[\d,]+$/);
  await expect(page.getByTestId("total-nodes")).toHaveText(/^[\d,]+$/);
  await expect(page.getByTestId("total-weight")).toBeVisible();
  for (const health of ["good", "degraded", "failed", "unknown"]) {
    await expect(headline.getByTestId(`total-health-${health}`)).toHaveText(/^[\d,]+$/);
  }
  await expect(headline.getByTestId("totals-by-health")).toContainText("Degraded");
  await expect(page.getByTestId("total-value")).toHaveCount(0);
  await expect(page.getByTestId("total-cost")).toHaveCount(0);
  await expect(headline.getByTestId("totals")).not.toContainText(/value|cost/i);
  await expect(headline.getByRole("link", { name: "management report" })).toBeVisible();

  await importFile(
    page,
    "catalog_entries",
    `catalog-entries-${suffix}.csv`,
    ["vendor", "pid", "model_name", "type", "est_value", "support_weight", "annual_support_cost"],
    [
      [vendor, switchPid, "Example 9300 48-port", "switch", "18000.00", "1.00", "1200.00"],
      [vendor, supplyPid, "Example 715 W supply", "power-supply", "400.00", "", ""],
      [vendor, modulePid, "Example 8-port uplink module", "module", "2500.00", "", ""],
    ],
  );
  await importFile(
    page,
    "owners",
    `owners-${suffix}.csv`,
    ["label", "organization"],
    [
      [engineering, "Example Operations"],
      [campus, "Example Operations"],
    ],
  );
  await expectClean(page, seen);
});

test("S18: minor items have the owner and the standing of the item they are in", async ({
  page,
  account,
}) => {
  test.setTimeout(240_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  const filter = `hostname:prefix:${chassisPrefix}`;

  // The switch, parked with the team: a major item, and so one component.
  await main(page).getByRole("link", { name: "Items" }).click();
  await page.getByRole("button", { name: "New item" }).click();
  const newItem = region(page, "New item");
  await newItem.getByLabel("Catalog entry").selectOption({ label: switchEntry });
  await newItem.getByLabel("Serial number").fill(`ENC${upper}01`);
  await newItem.getByLabel("Hostname").fill(chassis);
  await newItem.getByLabel("Owner").selectOption({ label: engineering });
  await newItem.getByLabel("Lifecycle state").selectOption("Assigned");
  await newItem.getByRole("button", { name: "Create item" }).click();
  await expect(page.getByRole("heading", { level: 1, name: chassis })).toBeVisible();
  await expect(page.getByTestId("major-or-minor")).toHaveText("Major item");
  await expect(region(page, "Minor items")).toContainText(`There is no minor item in ${chassis}.`);
  await summary(page, filter);
  await expect(page.getByTestId("total-components")).toHaveText("1");
  await expect(page.getByTestId("total-items")).toHaveText("1");

  // Two power supplies and a module in it.
  await openItem(page, chassis);
  await addMinorItem(page, supplyEntry, supplyA, "PS-A");
  await addMinorItem(page, supplyEntry, supplyB, "PS-B");
  await addMinorItem(page, moduleEntry, uplink, "Slot 1");
  await expect(page.getByTestId("minor-items").locator("tbody tr")).toHaveCount(3);
  // Each has the state and the owner of the switch, and says they are inherited.
  for (const host of [supplyA, supplyB, uplink]) {
    const cells = minorRow(page, host).locator("td[data-source]");
    await expect(cells.nth(0)).toHaveText("Assigned");
    await expect(cells.nth(0)).toHaveAttribute("data-source", "parent_item");
    await expect(cells.nth(1)).toHaveText(engineering);
    await expect(cells.nth(1)).toHaveAttribute("data-source", "parent_item");
  }

  // Another owner for the switch, and on to Prod.
  const details = region(page, "Details");
  await details.getByLabel("Owner").selectOption({ label: campus });
  await details.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("The item was saved.")).toBeVisible();
  await move(page, "Test", "Staged");
  await move(page, "Prod", "Deployed");

  // The minor items show the new owner and the new state. Nothing was written to them.
  for (const host of [supplyA, supplyB, uplink]) {
    const cells = minorRow(page, host).locator("td[data-source]");
    await expect(cells.nth(0)).toHaveText("Prod");
    await expect(cells.nth(0)).toHaveAttribute("data-source", "parent_item");
    await expect(cells.nth(0)).toHaveClass(/inherited/);
    await expect(cells.nth(1)).toHaveText(campus);
    await expect(cells.nth(1)).toHaveAttribute("data-source", "parent_item");
  }

  // The component count rose by one, not four: minor items are not counted.
  await summary(page, filter);
  await expect(page.getByTestId("total-components")).toHaveText("1");
  await expect(page.getByTestId("total-nodes")).toHaveText("1");
  await expect(page.getByTestId("total-items")).toHaveText("4");
  // By owner: all four under the owner in force, the minor items with the switch.
  await page.getByLabel("By", { exact: true }).selectOption("owner");
  const rows = page.getByTestId("summary-rows").locator("tbody tr");
  await expect(rows).toHaveCount(1);
  await expect(rows.first().locator("th")).toHaveText(campus);
  await expect(rows.first().locator("td").nth(0)).toHaveText("4");
  await expect(rows.first().locator("td").nth(1)).toHaveText("1");

  // The page of a power supply: where it is, and whose standing it has.
  await openItem(page, chassis);
  await minorRow(page, supplyA).getByRole("link", { name: supplyA }).click();
  await expect(page.getByRole("heading", { level: 1, name: supplyA })).toBeVisible();
  await expect(page.getByTestId("major-or-minor")).toHaveText("Minor item");
  await expect(page.getByTestId("parent")).toContainText(chassis);
  await expect(page.getByTestId("position")).toHaveText("PS-A");
  await expect(page.getByTestId("owner")).toHaveAttribute("data-source", "parent_item");
  await expect(page.getByTestId("owner")).toContainText(campus);
  await expect(page.getByTestId("standing")).toHaveAttribute("data-source", "parent_item");
  await expect(page.getByTestId("state")).toHaveText("Prod");
  await expect(page.getByTestId("state")).toHaveClass(/inherited/);
  await expect(page.getByTestId("disposition")).toHaveText("Production");
  await expect(page.getByTestId("intent")).toHaveText("Expected online");
  await expect(page.getByTestId("standing-inherited")).toContainText(
    "This minor item has no state of its own.",
  );
  await expect(page.getByTestId("standing-inherited").getByRole("link")).toHaveText(chassis);

  // The supply fails: it is given a state of its own, and goes its own way.
  await move(page, "Pending-Removal", "RMA");
  await expect(page.getByTestId("standing")).toHaveAttribute("data-source", "own");
  await expect(page.getByTestId("state")).not.toHaveClass(/inherited/);
  await expect(page.getByTestId("standing-inherited")).toHaveCount(0);
  // And it comes back: returned to the standing of the switch, by a move like any other.
  await region(page, "A state of its own")
    .getByRole("button", { name: `Return to the standing of ${chassis}` })
    .click();
  await expect(page.getByText(`The item has the standing of ${chassis} again.`)).toBeVisible();
  await expect(page.getByTestId("state")).toHaveText("Prod");
  await expect(page.getByTestId("standing")).toHaveAttribute("data-source", "parent_item");
  const moves = region(page, "History").locator('tbody[data-action="transition"]');
  await expect(moves).toHaveCount(2);

  // The grid: the state in force in the State column, lighter for the minor items, and
  // filtered by what the column shows. Minor items are in it once they are asked for.
  await page.goto(`./items?filter=${encodeURIComponent(filter)}`);
  await page.getByText("Columns", { exact: true }).click();
  await page.getByRole("button", { name: "Reset layout and filters" }).click();
  const columns = page.getByRole("group", { name: "Columns to show" });
  for (const column of ["Major or minor", "In item", "Position", "Depth"]) {
    await columns.getByLabel(column, { exact: true }).check();
  }
  // The grid draws only the columns in view: room is made for the ones looked at here.
  for (const column of ["Vendor", "Serial number", "Health", "Tags", "LDoS"]) {
    await columns.getByLabel(column, { exact: true }).uncheck();
  }
  await page.getByText("Columns", { exact: true }).click();
  await page.getByLabel("Filter", { exact: true }).fill(filter);
  await page.getByRole("button", { name: "Apply", exact: true }).click();
  await expect(page.getByTestId("grid-total")).toHaveText("1 item");
  await page.getByLabel("Include minor items").check();
  await expect(page.getByTestId("grid-total")).toHaveText("4 items");
  const grid = page.getByTestId("grid-items");
  const gridRow = (host: string) => grid.locator("[row-id]", { hasText: host });
  // Sorted by name: the switch, then the module and the two supplies.
  const supplyRow = gridRow(supplyA);
  await expect(supplyRow.locator('[col-id="is_major"]')).toHaveText("Minor");
  await expect(supplyRow.locator('[col-id="parent"]')).toHaveText(chassis);
  await expect(supplyRow.locator('[col-id="position"]')).toHaveText("PS-A");
  await expect(supplyRow.locator('[col-id="depth"]')).toHaveText("1");
  await expect(supplyRow.locator('[col-id="lifecycle_state"]')).toHaveText("Prod");
  await expect(supplyRow.locator('[col-id="lifecycle_state"]')).toHaveClass(/cell-inherited/);
  await expect(supplyRow.locator('[col-id="owner.label"]')).toHaveText(campus);
  await expect(supplyRow.locator('[col-id="owner.label"]')).toHaveClass(/cell-inherited/);
  const switchRow = grid.locator("[row-id]").first();
  await expect(switchRow.locator('[col-id="is_major"]')).toHaveText("Major");
  await expect(switchRow.locator('[col-id="lifecycle_state"]')).not.toHaveClass(/cell-inherited/);
  // The State filter keeps the rows whose cell shows the state: all four are in Prod.
  await grid.locator('[role="columnheader"][col-id="lifecycle_state"]').focus();
  await page.keyboard.press("Control+Enter");
  await page.getByRole("group", { name: "Show rows where State is" }).getByLabel("Prod").check();
  await page.locator(".ag-popup").getByRole("button", { name: "Apply" }).click();
  await expect(page.getByTestId("grid-total")).toHaveText("4 items");
  // Minor items only.
  await grid.locator('[role="columnheader"][col-id="is_major"]').focus();
  await page.keyboard.press("Control+Enter");
  await page
    .getByRole("group", { name: "Show rows where Major or minor is" })
    .getByLabel("Minor")
    .check();
  await page.locator(".ag-popup").getByRole("button", { name: "Apply" }).click();
  await expect(page.getByTestId("grid-total")).toHaveText("3 items");
  await page.getByText("Columns", { exact: true }).click();
  await page.getByRole("button", { name: "Reset layout and filters" }).click();
  await page.getByText("Columns", { exact: true }).click();

  // The module is taken out of the switch: a major item now, counted, with what is its own.
  await openItem(page, uplink);
  await region(page, "Where it is")
    .getByRole("button", { name: `Take out of ${chassis}` })
    .click();
  await expect(page.getByText(`${uplink} was taken out of ${chassis}.`)).toBeVisible();
  await expect(page.getByTestId("major-or-minor")).toHaveText("Major item");
  await expect(page.getByTestId("state")).toHaveText("—");
  await summary(page, filter);
  await expect(page.getByTestId("total-components")).toHaveText("2");
  // And put back, found by a part of the name of the switch.
  await openItem(page, uplink);
  const place = region(page, "Where it is");
  await place.getByRole("button", { name: "Put in another item" }).click();
  await pick(place, "The item to put it in", chassis, chassis);
  await expect(page.getByTestId("chosen-parent")).toContainText(chassis);
  await place.getByLabel("Position").fill("Slot 2");
  await place.getByRole("button", { name: "Put it there" }).click();
  await expect(page.getByText(`${uplink} is now in ${chassis}.`)).toBeVisible();
  await expect(page.getByTestId("major-or-minor")).toHaveText("Minor item");
  await expect(page.getByTestId("position")).toHaveText("Slot 2");
  await expect(page.getByTestId("state")).toHaveText("Prod");
  await summary(page, filter);
  await expect(page.getByTestId("total-components")).toHaveText("1");
  await expect(page.getByTestId("total-items")).toHaveText("4");

  await expectClean(page, seen);
});

test("minor items stay out of the grid of items until Include minor items is on", async ({
  page,
  account,
}, testInfo) => {
  test.setTimeout(180_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  const filter = `hostname:prefix:${chassisPrefix}`;
  const typed = { field: "hostname", op: "prefix", value: chassisPrefix };
  const total = page.getByTestId("grid-total");
  const minor = page.getByLabel("Include minor items");

  // As a new reader has the grid: the switch is off, and the switch alone is in it.
  await freshGrid(page, filter);
  await expect(minor).not.toBeChecked();
  await expect(total).toHaveText("1 item");
  await expect(page.getByTestId("grid-items").getByRole("link", { name: chassis })).toBeVisible();
  await expect(page.getByTestId("grid-items").getByRole("link", { name: supplyA })).toHaveCount(0);

  // What is exported is what the grid shows: the switch is part of the filter that is sent.
  await page.getByRole("button", { name: "Select all that match" }).click();
  await expect(page.getByTestId("grid-selected")).toContainText(
    "all 1 item that match the filter selected",
  );
  let sent = exportsSent(page);
  let download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export CSV" }).click();
  expect((await sent).postDataJSON().filter).toEqual({
    and: [typed, { field: "is_major", op: "eq", value: true }],
  });
  expect(await savedRows(await download, testInfo)).toHaveLength(2);
  // And what is edited in bulk: one item, by the same filter.
  const previewed = page.waitForRequest(
    (request) => request.method() === "POST" && request.url().endsWith("/items/bulk-update"),
  );
  await page.getByRole("button", { name: "Bulk edit" }).click();
  const bulk = page.getByTestId("bulk-edit");
  await expect(bulk).toContainText("all 1 item that match the filter");
  // The condition and what is observed are among what a bulk edit sets.
  const offered = await bulk.getByLabel("Field to change").locator("option").allTextContents();
  expect(offered).toContain("Condition");
  expect(offered).toContain("Observed status");
  await bulk.getByLabel("Field to change").selectOption({ label: "Comments" });
  await bulk.getByRole("button", { name: "Add", exact: true }).click();
  await bulk.getByRole("group", { name: "Comments" }).getByLabel("Set to").fill("Major only");
  await bulk.getByRole("button", { name: "Preview the change" }).click();
  expect((await previewed).postDataJSON().filter).toEqual({
    and: [typed, { field: "is_major", op: "eq", value: true }],
  });
  await expect(count(page, "updated")).toHaveText("1");
  // Nothing is applied: the preview was what was wanted.
  await bulk.getByRole("button", { name: "Cancel" }).click();
  await expect(bulk).toHaveCount(0);

  // Turned on, the three minor items are in the grid, and in what is exported.
  await minor.check();
  await expect(total).toHaveText("4 items");
  await expect(page.getByTestId("grid-items").getByRole("link", { name: supplyA })).toBeVisible();
  sent = exportsSent(page);
  download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export CSV" }).click();
  expect((await sent).postDataJSON().filter).toEqual(typed);
  expect(await savedRows(await download, testInfo)).toHaveLength(5);

  // The switch is remembered, as the layout of the columns is.
  await page.reload();
  await expect(minor).toBeChecked();
  await expect(total).toHaveText("4 items");
  await minor.uncheck();
  await expect(total).toHaveText("1 item");
  await page.reload();
  await expect(minor).not.toBeChecked();
  await expect(total).toHaveText("1 item");

  // A link to particular items shows the minor items among them, whatever was remembered:
  // the minor items of the switch, from its own page.
  await openItem(page, chassis);
  await region(page, "Minor items").getByRole("link", { name: "3 minor items" }).click();
  await expect(total).toHaveText("3 items");
  await expect(minor).toBeChecked();
  // The link did not change what is remembered.
  await main(page).getByRole("link", { name: "Items" }).click();
  await expect(page.getByTestId("grid-items")).toBeVisible();
  await expect(minor).not.toBeChecked();

  await page.getByText("Columns", { exact: true }).click();
  await page.getByRole("button", { name: "Reset layout and filters" }).click();
  await expectClean(page, seen);
});

test("a condition set on the item's page, what is seen of it, and its health in the grid", async ({
  page,
  account,
}) => {
  test.setTimeout(180_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  const health = page.getByTestId("health");
  const observed = page.getByTestId("observed");

  // Nobody has said anything of the switch yet: its health is unknown, and says why.
  await openItem(page, chassis);
  await expect(health).toHaveAttribute("data-health", "unknown");
  await expect(health).toContainText("Unknown");
  await expect(health).toContainText("nothing is said of its condition");
  await expect(page.getByTestId("condition")).toHaveText("Nobody has said");
  await expect(observed).toHaveText("Nobody has looked");

  // A condition, from the list of choices.
  const condition = region(page, "Record the condition");
  await expect(condition.getByLabel("Condition").locator("option")).toHaveText([
    "Nobody has said",
    "Untested",
    "Good",
    "Degraded",
    "Suspect",
    "Failed",
    "Dead",
  ]);
  await condition.getByLabel("Condition").selectOption({ label: "Good" });
  await condition.getByRole("button", { name: "Save condition" }).click();
  await expect(page.getByText("The condition of the item was saved.")).toBeVisible();
  await expect(page.getByTestId("condition")).toHaveText("Good");
  await expect(health).toHaveAttribute("data-health", "good");
  await expect(health).toContainText("its condition is good");

  // It is seen unreachable. The switch is in Prod and expected online: it has failed.
  const seeing = region(page, "Record what is seen");
  await seeing.getByLabel("Observed status").selectOption("unreachable");
  await seeing.getByRole("button", { name: "Record what is seen" }).click();
  await expect(page.getByText(`What is seen of ${chassis} was recorded.`)).toBeVisible();
  await expect(observed).toHaveAttribute("data-observed", "unreachable");
  await expect(observed).toContainText("Unreachable · seen");
  await expect(health).toHaveAttribute("data-health", "failed");
  await expect(health).toContainText("it is expected online and is observed unreachable");
  // The moment it was seen is on the page. "Seen now" states the same again, later.
  const moment = observed.locator("time");
  const first = await moment.getAttribute("datetime");
  expect(first).toMatch(/^\d{4}-\d{2}-\d{2}T/);
  await page.waitForTimeout(1100);
  await seeing.getByRole("button", { name: "Seen now" }).click();
  await expect(page.getByText("Unreachable was seen again, now.")).toBeVisible();
  await expect(observed).toHaveAttribute("data-observed", "unreachable");
  await expect.poll(() => moment.getAttribute("datetime")).not.toBe(first);

  // Present is what a person saw, and the page words it so.
  await expect(seeing.getByLabel("Observed status").locator('option[value="present"]')).toHaveText(
    "Present: a person saw it, in place and in order",
  );
  await seeing.getByLabel("Observed status").selectOption("present");
  await seeing.getByRole("button", { name: "Record what is seen" }).click();
  await expect(observed).toHaveAttribute("data-observed", "present");
  await expect(observed).toContainText("a person saw it, in place and in order");
  await expect(observed).toContainText("last checked");
  await expect(health).toHaveAttribute("data-health", "good");

  // The hardware is thought to be bad: degraded, whatever is seen.
  await condition.getByLabel("Condition").selectOption({ label: "Suspect" });
  await condition.getByRole("button", { name: "Save condition" }).click();
  await expect(page.getByTestId("condition")).toHaveText("Suspect");
  await expect(health).toHaveAttribute("data-health", "degraded");
  await expect(health).toContainText("its condition is suspect");
  // Neither moved the switch in the lifecycle.
  await expect(page.getByTestId("state")).toHaveText("Prod");
  // Each change is in the history, the condition as an ordinary field.
  await expect(region(page, "History").locator("tbody tr", { hasText: "condition" })).toHaveCount(
    2,
  );

  // The grid: the health is a mark in its colour, with its word, shown from the start.
  await freshGrid(page, `hostname:eq:${chassis}`);
  await expect(page.getByTestId("grid-total")).toHaveText("1 item");
  const grid = page.getByTestId("grid-items");
  const cell = grid.locator("[row-id]").first().locator('[col-id="health"]');
  await expect(cell).toHaveText("Degraded");
  await expect(cell.locator(".health")).toHaveClass(/health-degraded/);
  await expect(cell.locator(".health-dot")).toHaveAttribute("aria-hidden", "true");
  // The mark has a colour of its own, and it is not the colour of an unknown health.
  const amber = await cell
    .locator(".health-dot")
    .evaluate((dot) => getComputedStyle(dot).backgroundColor);
  expect(amber).not.toBe("rgba(0, 0, 0, 0)");
  // The reasons show when the cell has the focus, beneath the grid, and on hover.
  await cell.click();
  await expect(page.getByTestId("grid-cell-note")).toHaveText("Health: its condition is suspect");
  await grid.locator("[row-id]").first().locator('[col-id="name"]').hover();
  await cell.hover();
  await expect(page.locator(".ag-tooltip")).toHaveText("its condition is suspect");
  // Condition and Observed status are columns too, hidden until asked for.
  await expect(grid.locator('[role="columnheader"][col-id="condition"]')).toHaveCount(0);
  await expect(grid.locator('[role="columnheader"][col-id="observed_status"]')).toHaveCount(0);
  await page.getByText("Columns", { exact: true }).click();
  const columns = page.getByRole("group", { name: "Columns to show" });
  await columns.getByLabel("Condition", { exact: true }).check();
  await columns.getByLabel("Observed status", { exact: true }).check();
  await columns.getByLabel("Observed at", { exact: true }).check();
  // The grid draws only the columns in view: room is made for the ones looked at here.
  for (const column of ["Vendor", "PID", "Serial number", "Owner", "Tags"]) {
    await columns.getByLabel(column, { exact: true }).uncheck();
  }
  await page.getByText("Columns", { exact: true }).click();
  const row = grid.locator("[row-id]").first();
  await expect(row.locator('[col-id="condition"]')).toHaveText("Suspect");
  await expect(row.locator('[col-id="observed_status"]')).toHaveText("Present");
  await expect(row.locator('[col-id="observed_at"]')).toHaveText(/\d{4}/);
  // The grid filters by the health: this switch is among the degraded, not among the good.
  await grid.locator('[role="columnheader"][col-id="health"]').focus();
  await page.keyboard.press("Control+Enter");
  await page.getByRole("group", { name: "Show rows where Health is" }).getByLabel("Good").check();
  await page.locator(".ag-popup").getByRole("button", { name: "Apply" }).click();
  await expect(page.getByTestId("grid-total")).toHaveText("No items");
  await grid.locator('[role="columnheader"][col-id="health"]').focus();
  await page.keyboard.press("Control+Enter");
  const healths = page.getByRole("group", { name: "Show rows where Health is" });
  await healths.getByLabel("Good").uncheck();
  await healths.getByLabel("Degraded").check();
  await page.locator(".ag-popup").getByRole("button", { name: "Apply" }).click();
  await expect(page.getByTestId("grid-total")).toHaveText("1 item");
  // And sorts by it.
  const sorted = page.waitForRequest(
    (request) => request.method() === "POST" && request.url().endsWith("/items/query"),
  );
  await grid.locator('[role="columnheader"][col-id="health"]').click();
  expect((await sorted).postDataJSON().sort).toEqual(["health"]);
  await expect(page.getByTestId("grid-total")).toHaveText("1 item");
  await page.getByText("Columns", { exact: true }).click();
  await page.getByRole("button", { name: "Reset layout and filters" }).click();
  await page.getByText("Columns", { exact: true }).click();

  // The summary counts the components by health and by condition, and can be by either.
  await summary(page, `hostname:prefix:${chassisPrefix}`, "health");
  await expect(page.getByTestId("total-health-degraded")).toHaveText("1");
  await expect(page.getByTestId("total-health-good")).toHaveText("0");
  const suspect = page.getByTestId("totals-by-condition").locator('tr[data-condition="suspect"]');
  await expect(suspect.locator("th")).toHaveText("Suspect");
  await expect(suspect.locator("td").nth(1)).toHaveText("1");
  const degraded = page.getByTestId("summary-rows").locator('tr[data-key="degraded"]');
  await expect(degraded.locator("th")).toHaveText("Degraded");
  await expect(degraded.locator('td[data-health="degraded"]')).toHaveText("1");
  await page.getByLabel("By", { exact: true }).selectOption("condition");
  await expect(page.getByTestId("summary-rows").locator('tr[data-key="suspect"] th')).toHaveText(
    "Suspect",
  );

  // What was seen is cleared, and the moment with it. The condition stands.
  await openItem(page, chassis);
  await region(page, "Record what is seen")
    .getByRole("button", { name: "Clear what is seen" })
    .click();
  await expect(page.getByText(`What was seen of ${chassis} was cleared.`)).toBeVisible();
  await expect(observed).toHaveText("Nobody has looked");
  await expect(health).toHaveAttribute("data-health", "degraded");
  // The condition is cleared in turn: nobody says anything of the switch again.
  await region(page, "Record the condition")
    .getByLabel("Condition")
    .selectOption({ label: "Nobody has said" });
  await region(page, "Record the condition")
    .getByRole("button", { name: "Save condition" })
    .click();
  await expect(page.getByTestId("condition")).toHaveText("Nobody has said");
  await expect(health).toHaveAttribute("data-health", "unknown");

  // The list of conditions is edited where the other lists of choices are.
  await page.goto("./admin/choices?list=item_condition");
  await expect(page.getByRole("heading", { level: 1, name: "Choices" })).toBeVisible();
  await expect(page.getByLabel("List")).toHaveValue("item_condition");
  await expect(page.getByRole("rowheader")).toHaveText([
    "untested",
    "good",
    "degraded",
    "suspect",
    "failed",
    "dead",
  ]);
  await expect(page.getByText("says nothing about health either way")).toBeVisible();

  await expectClean(page, seen);
});
