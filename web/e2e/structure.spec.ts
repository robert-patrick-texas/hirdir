// The browser scenarios of release 0.4.0: what a person does in S18 to S23.
//
//   S18  Two power supplies and a module in a switch; the switch is given another owner
//        and moved to Prod. The minor items show the new owner and the new state, as
//        inherited from the item they are in; the component count is one, not four.
//   S19  A stack of four switches with one master shows the master's serial number, and
//        another's at once when another member is made the master.
//   S20  The stack weighs 2.00 under the global discount of 50, and 2.80 with 30 set on
//        its model; four components and one managed node throughout; the annual support
//        cost is that of four switches.
//   S21  The stack's master is replaced for an RMA: two item records linked by the
//        replacement, the departed switch's membership ended, the stack's HID unchanged.
//   S22  A controller domain: a cluster of two controllers and forty access points.
//        Forty-two components, the cluster one managed node, each access point lists its
//        controllers.
//   S23  The same address under two networks, then twice under one: all are accepted,
//        and only the pair under one network is in the report of duplicates.
//
// On the way: the files of the new entities on the Import page, the new columns of the
// item grid, a minor item given a state of its own and returned to inheriting, an item
// taken out of the item it is in and put back, a membership changed, an address marked
// as primary, changed and removed, a network renamed and removed.
//
// The environment that names the server and the Admin is described in support.ts. Every
// name, serial number and address below is made up, with a random part so that the
// scenarios can be run again on the same server. The addresses are of the ranges
// reserved for documentation. The scenarios run in order: the later ones use what the
// earlier ones made.

import { randomBytes } from "node:crypto";
import { expect, type Locator, type Page, test } from "@playwright/test";
import { expectClean, signIn, watch } from "./support";

test.describe.configure({ mode: "serial" });

const suffix = randomBytes(3).toString("hex");
const upper = suffix.toUpperCase();
const vendor = `Example Networks ${suffix}`;
const switchPid = `EN-9300-48P-${suffix}`;
const supplyPid = `EN-PWR-715-${suffix}`;
const modulePid = `EN-NM-8X-${suffix}`;
const controllerPid = `EN-WLC-9800-${suffix}`;
const accessPointPid = `EN-AP-9130-${suffix}`;
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

// S19 to S21: a stack of four, and the switch that replaces its master.
const stackPrefix = `site2-sw-stk-${suffix}`;
const stackHosts = [1, 2, 3, 4].map((place) => `${stackPrefix}-0${place}`);
const stackSerials = [1, 2, 3, 4].map((place) => `ENS${upper}0${place}`);
const stack = `site2-sw-stack-${suffix}`;
const spare = `${stackPrefix}-09`;
const spareSerial = `ENS${upper}09`;

// S22: a controller domain.
const wirelessPrefix = `site2-wl-${suffix}`;
const controllers = [`${wirelessPrefix}-wlc-01`, `${wirelessPrefix}-wlc-02`];
const controllerSerials = [`ENW${upper}01`, `ENW${upper}02`];
const accessPoints = Array.from(
  { length: 40 },
  (_, place) => `${wirelessPrefix}-ap-${String(place + 1).padStart(3, "0")}`,
);
const accessPointSerials = accessPoints.map(
  (_, place) => `ENA${upper}${String(place + 1).padStart(3, "0")}`,
);
const domain = `site2-wlan-${suffix}`;
const cluster = `site2-wlc-cluster-${suffix}`;

// S23: networks and addresses. The address is in the range reserved for documentation,
// and written as the server stores it: lower case, with no leading zeros in a group.
const red = `Red ${suffix}`;
const black = `Black ${suffix}`;
const shared = `2001:db8:${Number.parseInt(suffix.slice(0, 4), 16).toString(16)}:${Number.parseInt(
  suffix.slice(4),
  16,
).toString(16)}::10`;
const second = shared.replace(/::10$/, "::11");

function main(page: Page): Locator {
  return page.getByRole("navigation", { name: "Main" });
}

function region(page: Page, name: string): Locator {
  return page.getByRole("region", { name, exact: true });
}

function csv(header: string[], rows: string[][]): Buffer {
  return Buffer.from([header, ...rows].map((row) => `${row.join(",")}\n`).join(""), "utf8");
}

function count(page: Page, which: string): Locator {
  return page.getByTestId("preview-counts").locator(`[data-count="${which}"] dd`);
}

/** Load a CSV file on the Import page: preview it, see that every row is new, apply it. */
async function importFile(
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

/** Open an item from the grid, by its hostname. */
async function openItem(page: Page, hostname: string) {
  await page.goto(`./items?filter=${encodeURIComponent(`hostname:eq:${hostname}`)}`);
  await page.getByTestId("grid-items").getByRole("link", { name: hostname, exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: hostname })).toBeVisible();
}

async function openGroup(page: Page, name: string) {
  await page.goto(`./groups?filter=${encodeURIComponent(`name:eq:${name}`)}`);
  await page.getByTestId("grid-device-groups").getByRole("link", { name, exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
}

/** The summary of the items a filter keeps. */
async function summary(page: Page, filter: string, by = "") {
  const query = new URLSearchParams({ filter, ...(by ? { by } : {}) });
  await page.goto(`./reports?${query.toString()}`);
  await expect(page.getByRole("heading", { level: 1, name: "Summary" })).toBeVisible();
  await expect(page.getByTestId("totals")).toBeVisible();
}

/** Find an item in a picker by what is typed, and choose it. */
async function pick(within: Locator, label: string, typed: string, name: string) {
  await within.getByLabel(label, { exact: true }).fill(typed);
  await within
    .getByRole("list", { name: "Items that match" })
    .getByRole("button", { name: new RegExp(`^${name}( |$)`) })
    .click();
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

function memberRow(page: Page, hostname: string): Locator {
  return page.getByTestId("members").locator("tbody tr", { hasText: hostname });
}

test("the catalog, the owners and the items the scenarios use are loaded from files", async ({
  page,
}) => {
  test.setTimeout(180_000);
  const seen = await watch(page.context());
  await signIn(page);

  // The first page shows the headline totals of the inventory.
  await expect(region(page, "The inventory in numbers").getByTestId("totals")).toBeVisible();
  await expect(page.getByTestId("total-components")).toHaveText(/^[\d,]+$/);
  await expect(page.getByTestId("total-nodes")).toHaveText(/^[\d,]+$/);

  await importFile(
    page,
    "catalog_entries",
    `catalog-entries-${suffix}.csv`,
    ["vendor", "pid", "model_name", "type", "est_value", "support_weight", "annual_support_cost"],
    [
      [vendor, switchPid, "Example 9300 48-port", "switch", "18000.00", "1.00", "1200.00"],
      [vendor, supplyPid, "Example 715 W supply", "power-supply", "400.00", "", ""],
      [vendor, modulePid, "Example 8-port uplink module", "module", "2500.00", "", ""],
      [vendor, controllerPid, "Example 9800 controller", "wireless-controller", "30000.00", "", ""],
      [vendor, accessPointPid, "Example 9130 access point", "access-point", "900.00", "", ""],
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
  // The four switches of the stack, in Prod so that they carry weight.
  await importFile(
    page,
    "items",
    `items-${suffix}-stack.csv`,
    ["vendor", "pid", "serial_number", "hostname", "lifecycle_state", "owner"],
    stackHosts.map((host, place) => [
      vendor,
      switchPid,
      stackSerials[place] ?? "",
      host,
      "Prod",
      engineering,
    ]),
  );
  // Two controllers and forty access points.
  await importFile(
    page,
    "items",
    `items-${suffix}-wireless.csv`,
    ["vendor", "pid", "serial_number", "hostname"],
    [
      ...controllers.map((host, place) => [
        vendor,
        controllerPid,
        controllerSerials[place] ?? "",
        host,
      ]),
      ...accessPoints.map((host, place) => [
        vendor,
        accessPointPid,
        accessPointSerials[place] ?? "",
        host,
      ]),
    ],
  );
  await expectClean(page, seen);
});

test("S18: minor items have the owner and the standing of the item they are in", async ({
  page,
}) => {
  test.setTimeout(240_000);
  const seen = await watch(page.context());
  await signIn(page);
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
  // filtered by what the column shows.
  await page.goto(`./items?filter=${encodeURIComponent(filter)}`);
  await expect(page.getByTestId("grid-total")).toHaveText("4 items");
  await page.getByText("Columns", { exact: true }).click();
  await page.getByRole("button", { name: "Reset layout and filters" }).click();
  const columns = page.getByRole("group", { name: "Columns to show" });
  for (const column of ["Major or minor", "In item", "Position", "Depth"]) {
    await columns.getByLabel(column, { exact: true }).check();
  }
  for (const column of ["Vendor", "Serial number", "Tags", "Estimated value", "LDoS"]) {
    await columns.getByLabel(column, { exact: true }).uncheck();
  }
  await page.getByText("Columns", { exact: true }).click();
  await page.getByLabel("Filter", { exact: true }).fill(filter);
  await page.getByRole("button", { name: "Apply", exact: true }).click();
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

test("S19, S20: a stack reads its serial number from its master, and earns the discount", async ({
  page,
}) => {
  test.setTimeout(240_000);
  const seen = await watch(page.context());
  await signIn(page);
  const filter = `group.name:eq:${stack}`;

  // A stack of four, made with its members: one request, checked as a whole.
  await main(page).getByRole("link", { name: "Groups" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Groups" })).toBeVisible();
  await page.getByRole("button", { name: "New group" }).click();
  const form = region(page, "New group");
  await form.getByLabel("Name (required)").fill(stack);
  await form.getByLabel("Type").selectOption("stack");
  await form.getByLabel("Hostname").fill(stack);
  await form.getByLabel("Owner").selectOption({ label: engineering });
  for (const host of stackHosts) {
    await pick(form, "Find an item to add", stackPrefix, host);
  }
  const pending = page.getByTestId("pending-members").locator("tbody tr");
  await expect(pending).toHaveCount(4);
  // Each was given the next position. No master yet: the page says so before the server does.
  await expect(form.getByLabel(`Position of ${stackHosts[3]}`)).toHaveValue("4");
  await expect(page.getByTestId("stack-problem")).toContainText("exactly one master");
  await form.getByLabel(`Role of ${stackHosts[0]}`).selectOption("master");
  await expect(page.getByTestId("stack-problem")).toHaveCount(0);
  await form.getByRole("button", { name: "Create group" }).click();
  await expect(page.getByRole("heading", { level: 1, name: stack })).toBeVisible();
  const stackPath = new URL(page.url()).pathname;

  // The stack shows the serial number of its master (S19).
  await expect(page.getByTestId("group-serial")).toHaveText(stackSerials[0] ?? "");
  await expect(page.getByTestId("group-master")).toContainText(stackHosts[0] ?? "");
  await expect(page.getByTestId("member-count")).toHaveText("4 current members");
  await expect(page.getByTestId("members").locator("tbody tr")).toHaveCount(4);
  await expect(memberRow(page, stackHosts[0] ?? "")).toHaveAttribute("data-role", "master");
  // Nobody disagrees about the owner: every member has the owner the stack has.
  await expect(page.getByTestId("group-owner")).toHaveAttribute("data-disputed", "false");

  // Another member is made the master: the serial number changes at once.
  await memberRow(page, stackHosts[1] ?? "")
    .getByRole("button", { name: `Make ${stackHosts[1]} the master` })
    .click();
  await expect(page.getByText(`${stackHosts[1]} is now the master of ${stack}.`)).toBeVisible();
  await expect(page.getByTestId("group-serial")).toHaveText(stackSerials[1] ?? "");
  await expect(memberRow(page, stackHosts[1] ?? "")).toHaveAttribute("data-role", "master");
  await expect(memberRow(page, stackHosts[0] ?? "")).toHaveAttribute("data-role", "member");
  // And back, so that the first switch is the master again.
  await memberRow(page, stackHosts[0] ?? "")
    .getByRole("button", { name: `Make ${stackHosts[0]} the master` })
    .click();
  await expect(page.getByTestId("group-serial")).toHaveText(stackSerials[0] ?? "");

  // The master does not leave a stack that has other members: the server says so.
  await memberRow(page, stackHosts[0] ?? "")
    .getByRole("button", { name: `End the membership of ${stackHosts[0]}` })
    .click();
  const ending = region(page, `End the membership of ${stackHosts[0]}`);
  await ending.getByRole("button", { name: "End membership" }).click();
  await expect(ending.getByText("make another member the master first")).toBeVisible();
  await ending.getByRole("button", { name: "Cancel" }).click();

  // A member of the stack with another owner: the owner of the stack is marked (P-67).
  await openItem(page, stackHosts[3] ?? "");
  const details = region(page, "Details");
  await details.getByLabel("Owner").selectOption({ label: campus });
  await details.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("The item was saved.")).toBeVisible();
  // Its page lists the stack it is in, and as what.
  const memberships = page.getByTestId("memberships").locator("tbody tr");
  await expect(memberships).toHaveCount(1);
  await expect(memberships.first()).toContainText(stack);
  await expect(memberships.first()).toContainText("Member, position 4");
  await memberships.first().getByRole("link", { name: stack }).click();
  await expect(page.getByRole("heading", { level: 1, name: stack })).toBeVisible();
  expect(new URL(page.url()).pathname).toBe(stackPath);
  await expect(page.getByTestId("group-owner")).toHaveAttribute("data-disputed", "true");
  await expect(page.getByTestId("group-owner")).toContainText(engineering);
  await expect(page.getByTestId("group-owner")).toContainText("Members disagree");
  await expect(page.getByTestId("owner-disputed")).toBeVisible();

  // The grid of groups: the stack, with its master's serial number and four members.
  await page.goto(`./groups?filter=${encodeURIComponent(`name:eq:${stack}`)}`);
  await expect(page.getByTestId("grid-total")).toHaveText("1 group");
  const groupRow = page.getByTestId("grid-device-groups").locator("[row-id]").first();
  await expect(groupRow.locator('[col-id="type"]')).toHaveText("Stack");
  await expect(groupRow.locator('[col-id="serial_number"]')).toHaveText(stackSerials[0] ?? "");
  await expect(groupRow.locator('[col-id="member_count"]')).toHaveText("4");

  // S20. Under the global discount of 50, four switches of weight 1.00 weigh 2.00 as a
  // stack: four components, one managed node, and the support cost of four switches.
  await page.goto(`./catalog?filter=${encodeURIComponent(`pid:eq:${switchPid}`)}`);
  await page.getByTestId("grid-catalog").getByRole("link", { name: switchPid }).click();
  await expect(
    page.getByRole("heading", { level: 1, name: `${vendor} ${switchPid}` }),
  ).toBeVisible();
  await expect(page.getByTestId("stack-discount")).toHaveAttribute("data-source", "setting");
  await expect(page.getByTestId("stack-discount")).toContainText("50");
  await summary(page, filter);
  await expect(page.getByTestId("total-components")).toHaveText("4");
  await expect(page.getByTestId("total-nodes")).toHaveText("1");
  // A weight is written without the zeros that say nothing: 2, or 2.00.
  await expect(page.getByTestId("total-weight")).toHaveText(/^2(\.00?)?$/);
  await expect(page.getByTestId("total-cost")).toHaveText("4,800.00");
  await expect(page.getByTestId("total-value")).toHaveText("72,000.00");
  // The kinds beside the headline count: these are hardware, which the count takes.
  const hardware = page.getByTestId("totals-by-kind").locator('tr[data-kind="hardware"]');
  await expect(hardware.locator("td").nth(0)).toHaveText("4");
  await expect(hardware.locator("td").nth(2)).toHaveText("Yes");

  // The model sets its own discount of 30: the stack weighs 2.80. Nothing else changes.
  await page.goto(`./catalog?filter=${encodeURIComponent(`pid:eq:${switchPid}`)}`);
  await page.getByTestId("grid-catalog").getByRole("link", { name: switchPid }).click();
  const entry = region(page, "Details");
  await entry.getByLabel("Stack discount %").fill("30");
  await entry.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("The catalog entry was saved.")).toBeVisible();
  await expect(page.getByTestId("stack-discount")).toHaveAttribute("data-source", "own");
  await summary(page, filter);
  await expect(page.getByTestId("total-weight")).toHaveText(/^2\.80?$/);
  await expect(page.getByTestId("total-components")).toHaveText("4");
  await expect(page.getByTestId("total-nodes")).toHaveText("1");
  await expect(page.getByTestId("total-cost")).toHaveText("4,800.00");
  // By owner: the stack's members fall in two rows, and it is a managed node in both.
  await page.getByLabel("By", { exact: true }).selectOption("owner");
  const rows = page.getByTestId("summary-rows").locator("tbody tr");
  await expect(rows).toHaveCount(2);
  await expect(rows.filter({ hasText: campus }).locator("td").nth(2)).toHaveText("1");
  await expect(rows.filter({ hasText: engineering }).locator("td").nth(2)).toHaveText("1");
  await expect(page.getByTestId("total-nodes")).toHaveText("1");

  // The item grid finds the members by the group they are in, and by its type.
  await page.goto(`./items?filter=${encodeURIComponent(`${filter} group.type:eq:stack`)}`);
  await expect(page.getByTestId("grid-total")).toHaveText("4 items");

  await expectClean(page, seen, ["422 PATCH"]);
});

test("S21: the master of the stack is replaced, and the stack stays the stack", async ({
  page,
}) => {
  test.setTimeout(180_000);
  const seen = await watch(page.context());
  await signIn(page);
  const master = stackHosts[0] ?? "";
  await openGroup(page, stack);
  const stackPath = new URL(page.url()).pathname;
  await expect(page.getByTestId("group-serial")).toHaveText(stackSerials[0] ?? "");

  // The master goes back under an RMA. What takes its place is a new item, made here.
  await openItem(page, master);
  await expect(region(page, "Replacement")).toContainText(
    `${master} replaced no item, and was not replaced.`,
  );
  await region(page, "Replacement").getByRole("button", { name: "Replace this item" }).click();
  const replace = region(page, `Replace ${master}`);
  await replace.getByLabel("Reason").selectOption({ label: "RMA" });
  await replace.getByLabel("Reference").fill(`RMA-${upper}`);
  await replace
    .getByLabel("What takes its place")
    .selectOption({ label: "A new item, created now" });
  const fresh = replace.getByRole("group", { name: "The new item" });
  // The same model is offered, as it is more often than not.
  await expect(fresh.getByLabel("Catalog entry").locator("option:checked")).toContainText(
    switchPid,
  );
  await fresh.getByLabel("Serial number").fill(spareSerial);
  await fresh.getByLabel("Hostname").fill(spare);
  await replace.getByRole("button", { name: "Replace", exact: true }).click();
  await expect(page.getByText(`${master} was replaced by ${spare}.`)).toBeVisible();

  // Two item records, linked by the replacement. The one that left is in no group now.
  const replacedBy = page.getByTestId("replaced-by");
  await expect(replacedBy).toContainText(spare);
  await expect(replacedBy).toContainText("RMA");
  await expect(replacedBy).toContainText(`RMA-${upper}`);
  await expect(region(page, "Groups")).toContainText(`${master} is a member of no group.`);
  // An item is replaced once: the action is no longer offered.
  await expect(page.getByRole("button", { name: "Replace this item" })).toHaveCount(0);
  await replacedBy.getByRole("link").click();
  await expect(page.getByRole("heading", { level: 1, name: spare })).toBeVisible();
  await expect(page.getByTestId("replaces")).toContainText(master);
  const memberships = page.getByTestId("memberships").locator("tbody tr");
  await expect(memberships.first()).toContainText(stack);
  await expect(memberships.first()).toContainText("Master, position 1");

  // The stack is the same record: its HID is unchanged, and its master is the new switch.
  await memberships.first().getByRole("link", { name: stack }).click();
  await expect(page.getByRole("heading", { level: 1, name: stack })).toBeVisible();
  expect(new URL(page.url()).pathname).toBe(stackPath);
  await expect(page.getByTestId("group-serial")).toHaveText(spareSerial);
  await expect(page.getByTestId("member-count")).toHaveText("4 current members");
  await expect(page.getByTestId("members").locator("tbody tr")).toHaveCount(4);
  await expect(memberRow(page, spare)).toHaveAttribute("data-role", "master");
  // The departed switch's membership has an end date, and is kept.
  await region(page, "Members").getByLabel("Show past memberships").check();
  await expect(page.getByTestId("members").locator("tbody tr")).toHaveCount(5);
  const departed = memberRow(page, master);
  await expect(departed).toHaveAttribute("data-current", "false");
  await expect(departed.locator("td").nth(-2)).toHaveText(/^\d{4}-\d{2}-\d{2}$/);
  await region(page, "Members").getByLabel("Show past memberships").uncheck();
  await expect(page.getByTestId("members").locator("tbody tr")).toHaveCount(4);

  // A membership is changed: the last member is given another position.
  await memberRow(page, stackHosts[3] ?? "")
    .getByRole("button", { name: `Change the membership of ${stackHosts[3]}` })
    .click();
  const change = region(page, `The membership of ${stackHosts[3]}`);
  await change.getByLabel("Position").fill("8");
  await change.getByRole("button", { name: "Save membership" }).click();
  await expect(page.getByText(`The membership of ${stackHosts[3]} was saved.`)).toBeVisible();
  await expect(
    memberRow(page, stackHosts[3] ?? "")
      .locator("td")
      .first(),
  ).toHaveText("8");

  await expectClean(page, seen);
});

test("S22: a controller domain, a cluster of controllers and forty access points", async ({
  page,
}) => {
  test.setTimeout(240_000);
  const seen = await watch(page.context());
  await signIn(page);

  // The domain, with nobody in it yet.
  await main(page).getByRole("link", { name: "Groups" }).click();
  await page.getByRole("button", { name: "New group" }).click();
  let form = region(page, "New group");
  await form.getByLabel("Name (required)").fill(domain);
  await form.getByLabel("Type").selectOption("controller_domain");
  await form.getByRole("button", { name: "Create group" }).click();
  await expect(page.getByRole("heading", { level: 1, name: domain })).toBeVisible();
  await expect(page.getByTestId("member-count")).toHaveText("0 current members");

  // The cluster of the two controllers, nested in the domain.
  await main(page).getByRole("link", { name: "Groups" }).click();
  await page.getByRole("button", { name: "New group" }).click();
  form = region(page, "New group");
  await form.getByLabel("Name (required)").fill(cluster);
  await form.getByLabel("Type").selectOption("cluster");
  await form.getByLabel("In group").selectOption({ label: domain });
  for (const host of controllers) {
    await pick(form, "Find an item to add", `${wirelessPrefix}-wlc`, host);
  }
  await form.getByLabel(`Role of ${controllers[0]}`).selectOption("active");
  await form.getByLabel(`Role of ${controllers[1]}`).selectOption("standby");
  await form.getByRole("button", { name: "Create group" }).click();
  await expect(page.getByRole("heading", { level: 1, name: cluster })).toBeVisible();
  await expect(page.getByTestId("member-count")).toHaveText("2 current members");
  await expect(memberRow(page, controllers[1] ?? "")).toHaveAttribute("data-role", "standby");

  // Forty access points join the domain as its endpoints, from a file of members.
  await importFile(
    page,
    "device_group_members",
    `device-group-members-${suffix}.csv`,
    ["group", "item", "role"],
    accessPointSerials.map((serial) => [domain, serial, "endpoint"]),
  );

  // The domain: forty members, and the cluster within it.
  await openGroup(page, domain);
  await expect(page.getByTestId("member-count")).toHaveText("40 current members");
  await expect(page.getByTestId("members").locator("tbody tr")).toHaveCount(40);
  await expect(
    page.getByTestId("nested-groups").getByRole("link", { name: cluster }),
  ).toBeVisible();

  // Each access point lists its controllers: the members of the cluster in its domain.
  for (const host of [accessPoints[0] ?? "", accessPoints[39] ?? ""]) {
    await openItem(page, host);
    const listed = page.getByTestId("controllers").getByRole("listitem");
    await expect(listed).toHaveCount(2);
    await expect(listed.nth(0)).toContainText(controllers[0] ?? "");
    await expect(listed.nth(1)).toContainText(controllers[1] ?? "");
    await expect(page.getByTestId("memberships").locator("tbody tr").first()).toContainText(
      "Endpoint",
    );
  }

  // Forty-two components. The cluster is one managed node, and each access point is one.
  await summary(page, `hostname:prefix:${wirelessPrefix}`);
  await expect(page.getByTestId("total-components")).toHaveText("42");
  await expect(page.getByTestId("total-nodes")).toHaveText("41");
  // By type, as the catalog has them, with the labels of the list.
  await page.getByLabel("By", { exact: true }).selectOption("type");
  const rows = page.getByTestId("summary-rows").locator("tbody tr");
  await expect(rows).toHaveCount(2);
  const points = page.getByTestId("summary-rows").locator('tr[data-key="access-point"]');
  await expect(points.locator("td").nth(1)).toHaveText("40");
  await expect(points.locator("td").nth(2)).toHaveText("40");
  const wlcs = page.getByTestId("summary-rows").locator('tr[data-key="wireless-controller"]');
  await expect(wlcs.locator("td").nth(1)).toHaveText("2");
  await expect(wlcs.locator("td").nth(2)).toHaveText("1");
  // The summary can be come back to: what it is by and its filter are in the address.
  await page.reload();
  await expect(page.getByLabel("By", { exact: true })).toHaveValue("type");
  await expect(page.getByLabel("Filter", { exact: true })).toHaveValue(
    `hostname:prefix:${wirelessPrefix}`,
  );
  await expect(page.getByTestId("total-components")).toHaveText("42");

  // The grid of items, by the group an item is in.
  await page.goto(`./items?filter=${encodeURIComponent(`group.name:eq:${domain}`)}`);
  await expect(page.getByTestId("grid-total")).toHaveText("40 items");

  await expectClean(page, seen);
});

test("S23: the same address under two networks, and twice under one", async ({ page }) => {
  test.setTimeout(240_000);
  const seen = await watch(page.context());
  await signIn(page);
  const [first = "", other = "", third = ""] = stackHosts.slice(1);

  // Two networks, and one more to rename and remove.
  await main(page).getByRole("link", { name: "Addresses" }).click();
  await page
    .getByRole("navigation", { name: "Addresses" })
    .getByRole("link", { name: "Networks" })
    .click();
  await expect(page.getByRole("heading", { level: 1, name: "Networks" })).toBeVisible();
  for (const label of [red, black, `Green ${suffix}`]) {
    await page.getByRole("button", { name: "New network" }).click();
    await region(page, "New network").getByLabel("Label").fill(label);
    await region(page, "New network").getByRole("button", { name: "Create network" }).click();
    await expect(page.getByText(`The network ${label} was created.`)).toBeVisible();
  }
  const networks = page.getByTestId("networks").locator("tbody tr");
  const green = networks.filter({ hasText: `Green ${suffix}` });
  await green.getByRole("button", { name: `Rename or change the network Green ${suffix}` }).click();
  const edit = region(page, `The network Green ${suffix}`);
  await edit.getByLabel("Label").fill(`Amber ${suffix}`);
  await edit.getByLabel("Kind").selectOption("vrf");
  await edit.getByRole("button", { name: "Save" }).click();
  const amber = networks.filter({ hasText: `Amber ${suffix}` });
  await expect(amber).toContainText("VRF");
  await expect(amber).toContainText("0 addresses");
  await amber.getByRole("button", { name: "Remove" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Remove network" }).click();
  await expect(page.getByText(`The network Amber ${suffix} was removed.`)).toBeVisible();
  await expect(amber).toHaveCount(0);

  /** Give the item on show an address under a network. `stored` is the address as the server keeps it. */
  async function addAddress(address: string, network: string, stored = address) {
    const addresses = region(page, "Addresses");
    await addresses.getByRole("button", { name: "Add an address" }).click();
    const form = region(page, "New address");
    await form.getByLabel("Address (required)").fill(address);
    await form.getByLabel("Network").selectOption({ label: network });
    await expect(form.getByLabel("Role")).toHaveValue("management");
    await form.getByRole("button", { name: "Add address" }).click();
    await expect(page.getByText(`The address ${stored} was added.`)).toBeVisible();
  }
  const addressRow = (address: string) =>
    page.getByTestId("addresses").locator(`tbody tr[data-address="${address}"]`);

  // The same address under Red on one switch and under Black on another: two addresses.
  await openItem(page, first);
  await expect(region(page, "Addresses")).toContainText(`There is no address on ${first}.`);
  // Written in upper case and with leading zeros: the server stores the canonical form.
  await addAddress(shared.toUpperCase().replace("::10", "::0010"), red, shared);
  await expect(addressRow(shared)).toContainText(red);
  // The first management address of an item is its primary one.
  await expect(addressRow(shared)).toContainText("Primary");
  await openItem(page, other);
  await addAddress(shared, black);
  await expect(addressRow(shared)).toContainText(black);

  // Nothing is held more than once yet.
  await page.goto("./reports/duplicates");
  await expect(
    page.getByRole("heading", { level: 1, name: "Addresses held more than once" }),
  ).toBeVisible();
  await expect(page.getByTestId("duplicates")).toBeVisible();
  await expect(page.getByTestId("duplicates").locator(`tr[data-address="${shared}"]`)).toHaveCount(
    0,
  );

  // The same address a second time under Red: accepted, and reported.
  await openItem(page, third);
  await addAddress(shared, red);
  await page.goto("./reports/duplicates");
  const held = page.getByTestId("duplicates").locator(`tr[data-address="${shared}"]`);
  await expect(held).toHaveCount(1);
  await expect(held).toHaveAttribute("data-network", red);
  await expect(held).toContainText("2 times");
  await expect(held.getByRole("link", { name: first })).toBeVisible();
  await expect(held.getByRole("link", { name: third })).toBeVisible();
  await expect(held.getByRole("link", { name: other })).toHaveCount(0);
  // A holder leads to its own page.
  await held.getByRole("link", { name: third }).click();
  await expect(page.getByRole("heading", { level: 1, name: third })).toBeVisible();

  // A second management address, marked as primary: the mark leaves the first.
  await addAddress(second, red);
  await expect(addressRow(shared)).toContainText("Primary");
  await expect(addressRow(second)).not.toContainText("Primary");
  await addressRow(second)
    .getByRole("button", { name: `Make ${second} (${red}) the primary management address` })
    .click();
  await expect(page.getByText(`${second} is now the primary management address.`)).toBeVisible();
  await expect(addressRow(second).locator("td").nth(2)).toHaveText("Primary");
  await expect(addressRow(shared).locator("td").nth(2)).toHaveText("");
  // The primary one is listed first.
  await expect(page.getByTestId("addresses").locator("tbody tr").first()).toHaveAttribute(
    "data-address",
    second,
  );
  // An address is changed: a loopback now, which cannot be primary.
  await addressRow(shared)
    .getByRole("button", { name: `Change the address ${shared} (${red})` })
    .click();
  const change = region(page, `The address ${shared}`);
  await change.getByLabel("Role").selectOption("loopback");
  await change.getByRole("button", { name: "Save address" }).click();
  await expect(page.getByText(`The address ${shared} was saved.`)).toBeVisible();
  await expect(addressRow(shared)).toContainText("Loopback");
  await expect(
    addressRow(shared).getByRole("button", { name: /the primary management address$/ }),
  ).toHaveCount(0);

  // The grid of every address: the three of this run that are under Red.
  await page.goto(`./addresses?filter=${encodeURIComponent(`network.label:eq:${red}`)}`);
  await expect(page.getByRole("heading", { level: 1, name: "Addresses" })).toBeVisible();
  await expect(page.getByTestId("grid-total")).toHaveText("3 addresses");
  // The item grid finds an item by any of its addresses, and by the network of one.
  await page.goto(
    `./items?filter=${encodeURIComponent(`address:eq:${shared} network.label:eq:${black}`)}`,
  );
  await expect(page.getByTestId("grid-total")).toHaveText("1 item");
  await expect(page.getByTestId("grid-items").getByRole("link", { name: other })).toBeVisible();

  // A network that addresses are under cannot be removed.
  await page.goto("./networks");
  const redRow = page.getByTestId("networks").locator("tbody tr").filter({ hasText: red });
  await expect(redRow).toContainText("3 addresses");
  await expect(redRow.getByRole("button", { name: "Remove" })).toBeDisabled();

  // The second address is removed. The pair under Red stays in the report.
  await openItem(page, third);
  await addressRow(second).getByRole("button", { name: "Remove" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Remove address" }).click();
  await expect(page.getByText(`The address ${second} was removed.`)).toBeVisible();
  await expect(addressRow(second)).toHaveCount(0);
  await page.goto("./reports/duplicates");
  await expect(page.getByTestId("duplicates").locator(`tr[data-address="${shared}"]`)).toHaveCount(
    1,
  );

  await expectClean(page, seen);
});
