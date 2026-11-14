// The browser scenario of the portfolio of a vendor in release 0.6.0:
//
//   S31  A vendor with switches, a virtual machine template, a software application and
//        a service: the portfolio lists all four kinds with cost and weight totals, and
//        its items are exported like any other grid.
//
// It keeps to the rules of support.ts: an account and names of its own, and a vendor of
// its own, so that every number of the portfolio is of this file's records alone.

import { readFile } from "node:fs/promises";
import { expect, type Locator, type Page } from "@playwright/test";
import { importFile } from "./structure";
import { expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const random = mark("x").slice(2);
const suffix = mark("portfolio", random);
const upper = random.toUpperCase();

const vendor = `Example Systems ${suffix}`;
const switchPid = `EX-SW-${suffix}`;
const vmPid = `EX-VM-${suffix}`;
const appPid = `EX-APP-${suffix}`;
const servicePid = `EX-SVC-${suffix}`;
const prefix = `pf-${suffix}`;
const names = [
  `${prefix}-sw-01`,
  `${prefix}-sw-02`,
  `${prefix}-vm-01`,
  `${prefix}-app`,
  `${prefix}-svc`,
];

/** One measure of one row of a table of the portfolio. */
function measure(row: Locator, name: string): Locator {
  return row.locator(`[data-measure="${name}"]`);
}

/** Open the page of the vendor from the list of vendors, filtered down to it. */
async function openVendor(page: Page) {
  await page.goto(`./vendors?filter=${encodeURIComponent(`name:eq:${vendor}`)}`);
  await expect(page.getByTestId("grid-total")).toHaveText("1 vendor");
  await page.getByTestId("grid-vendors").getByRole("link", { name: vendor, exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: vendor })).toBeVisible();
}

test("a vendor with models of all four kinds, and an item of each, are loaded from files", async ({
  page,
  account,
}) => {
  test.setTimeout(180_000);
  const seen = await watch(page.context());
  await signIn(page, account);

  await importFile(page, "vendors", `vendors-${suffix}.csv`, ["name"], [[vendor]]);
  await importFile(
    page,
    "catalog_entries",
    `catalog-entries-${suffix}.csv`,
    [
      "vendor",
      "pid",
      "model_name",
      "kind",
      "type",
      "est_value",
      "support_weight",
      "annual_support_cost",
    ],
    [
      [vendor, switchPid, "Example switch", "hardware", "switch", "8000.00", "1.00", "900.00"],
      [vendor, vmPid, "Example virtual appliance", "virtual_machine", "", "0.00", "0.50", "400.00"],
      [vendor, appPid, "Example manager", "software", "", "2500.00", "0.25", "1500.00"],
      [vendor, servicePid, "Example cloud service", "service", "", "", "0.25", "600.00"],
    ],
  );
  // In Prod, so that each carries its support weight. The software and the service have
  // no serial number and no host name: they are known by their names.
  await importFile(
    page,
    "items",
    `items-${suffix}.csv`,
    ["vendor", "pid", "serial_number", "hostname", "name", "lifecycle_state"],
    [
      [vendor, switchPid, `EXS${upper}01`, names[0] ?? "", "", "Prod"],
      [vendor, switchPid, `EXS${upper}02`, names[1] ?? "", "", "Prod"],
      [vendor, vmPid, "", names[2] ?? "", "", "Prod"],
      [vendor, appPid, "", "", names[3] ?? "", "Prod"],
      [vendor, servicePid, "", "", names[4] ?? "", "Prod"],
    ],
  );
  await expectClean(page, seen);
});

test("S31: the portfolio lists all four kinds with cost and weight totals, and exports", async ({
  page,
  account,
}, testInfo) => {
  test.setTimeout(180_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  await openVendor(page);

  // The totals: five items, of which the two switches and the virtual machine are
  // components; the support weight and the annual support cost of all five.
  const portfolio = page.getByTestId("portfolio");
  await expect(portfolio.getByTestId("portfolio-items")).toHaveText("5");
  await expect(portfolio.getByTestId("portfolio-components")).toHaveText("3");
  await expect(portfolio.getByTestId("portfolio-weight")).toHaveText("3");
  await expect(portfolio.getByTestId("portfolio-value")).toHaveText("18,500.00");
  await expect(portfolio.getByTestId("portfolio-cost")).toHaveText("4,300.00");
  // No contract covers any of them yet.
  await expect(portfolio.getByTestId("portfolio-covered")).toHaveText("0");

  // All four kinds, each with its items, its weight and its cost.
  const kinds = portfolio.getByTestId("portfolio-kinds").locator("tbody tr");
  await expect(kinds).toHaveCount(4);
  for (const [kind, items, weight, cost] of [
    ["hardware", "2", "2", "1,800.00"],
    ["virtual_machine", "1", "0.5", "400.00"],
    ["software", "1", "0.25", "1,500.00"],
    ["service", "1", "0.25", "600.00"],
  ] as const) {
    const row = portfolio.getByTestId("portfolio-kinds").locator(`tr[data-kind="${kind}"]`);
    await expect(measure(row, "items")).toHaveText(items);
    await expect(measure(row, "weight")).toHaveText(weight);
    await expect(measure(row, "cost")).toHaveText(cost);
  }

  // The models, one row for each that has items, and sorted by a header in the browser.
  const models = portfolio.getByTestId("portfolio-models");
  await expect(models.locator("tbody tr")).toHaveCount(4);
  await expect(measure(models.locator(`tr[data-pid="${switchPid}"]`), "items")).toHaveText("2");
  await expect(measure(models.locator(`tr[data-pid="${switchPid}"]`), "value")).toHaveText(
    "16,000.00",
  );
  await models.locator('button[data-sort="cost"]').click();
  await expect(models.locator("tbody tr").first()).toHaveAttribute("data-pid", vmPid);
  await models.locator('button[data-sort="cost"]').click();
  await expect(models.locator("tbody tr").first()).toHaveAttribute("data-pid", switchPid);
  // With no agreement, no contract and no capacity line, the page says so.
  await expect(portfolio).toContainText("There is no support agreement with this vendor.");
  await expect(portfolio).toContainText("No capacity line names this vendor.");

  // Its items, as a grid: the item list with the filter of the portfolio.
  await expect(page.getByTestId("grid-total")).toHaveText("5 items");
  const grid = page.getByTestId("grid-vendor-items");
  for (const name of names) {
    await expect(grid.getByRole("link", { name, exact: true })).toBeVisible();
  }
  // What is about cover stands right after the name, and is shown from the start.
  await expect(grid.locator('[role="columnheader"][col-id="covered"]')).toHaveCount(1);
  await expect(grid.locator('[role="columnheader"][col-id="contract.number"]')).toHaveCount(1);

  // It is exported like any other: every item of the vendor, with `hid` first.
  const sent = page.waitForRequest(
    (request) => request.method() === "POST" && request.url().endsWith("/api/v1/exports"),
  );
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export CSV" }).click();
  const asked = (await sent).postDataJSON() as { entity: string; filter: unknown };
  expect(asked.entity).toBe("items");
  expect(JSON.stringify(asked.filter)).toContain("catalog.vendor_hid");
  const file = await download;
  expect(file.suggestedFilename()).toMatch(/^hirdir-items-.*\.csv$/);
  const path = testInfo.outputPath(file.suggestedFilename());
  await file.saveAs(path);
  const lines = (await readFile(path, "utf8")).replace(/\n$/, "").split("\n");
  const header = (lines[0] ?? "").trim().split(",");
  expect(header[0]).toBe("hid");
  for (const column of ["covered", "covered_until", "contracts", "pid"]) {
    expect(header, column).toContain(column);
  }
  expect(lines).toHaveLength(6);
  // Each of the five is a row of the file, by what the columns on show know it by: the
  // serial number of a switch, the name of the software and of the service, and the PID
  // of the one virtual machine. The Name column of the grid shows a host name where an
  // item has no name; the file has the name alone, and the host name is a column that
  // is not on show.
  const rows = lines.slice(1);
  for (const known of [`EXS${upper}01`, `EXS${upper}02`, vmPid, names[3] ?? "", names[4] ?? ""]) {
    expect(
      rows.filter((row) => row.split(",").includes(known)),
      known,
    ).toHaveLength(1);
  }

  await expectClean(page, seen);
});
