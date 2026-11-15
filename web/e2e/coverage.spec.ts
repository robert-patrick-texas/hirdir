// The browser scenarios of the coverage of a contract in release 0.6.1, for what only
// unit tests held before, and the contracts that still count an item out of service:
//
//   D-141  Coverage made by mistake is removed outright, several at once. A coverage that
//          was ended because its item left is marked until the vendor has been told, which
//          is said for several at once and clears the mark; one whose item was brought
//          back is opened again.
//   D-162  The contracts that still count an item out of service are a field of the item
//          list: the column Still counted under of the coverage report's list for the
//          vendor is the server's, filtered and sorted by it, in the item grid's column
//          chooser too, and said on the page of the item.
//
// It keeps to the rules of support.ts: an account and names of its own, and every report
// and grid filtered down to this file's records before anything is counted.

import { expect, type Page } from "@playwright/test";
import {
  chooseColumns,
  gridRow,
  newContract,
  openContract,
  pickContract,
  ROOM,
  resetGrid,
} from "./contractSteps";
import { importFile, openItem, region } from "./structure";
import { expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const random = mark("x").slice(2);
const suffix = mark("coverage", random);
const upper = random.toUpperCase();
const year = new Date().getFullYear();

const vendor = `Example Networks ${suffix}`;
const pid = `EN-9500-48Y-${suffix}`;
const prefix = `site6-sw-${suffix}`;
const own = `hostname:prefix:${prefix}`;
// The first two leave service, the third leaves and comes back, the last two were mistakes.
const switches = [1, 2, 3, 4, 5].map((place) => `${prefix}-0${place}`);
const [left1, left2, back, mistake1, mistake2] = switches as [
  string,
  string,
  string,
  string,
  string,
];
const number = `CON-${suffix}-1`;
const ends = `${year + 2}-12-31`;
const coverage = "grid-contract-coverage";

/** Select rows of the coverage of the contract on show, by the names of their items. */
async function selectCoverage(page: Page, ...names: string[]) {
  for (const [at, name] of names.entries()) {
    await gridRow(page, coverage, name)
      .locator('[col-id="item.pid"]')
      .click(at === 0 ? {} : { modifiers: ["ControlOrMeta"] });
  }
  await expect(page.getByTestId("grid-selected")).toContainText(`${names.length} selected`);
}

/** Retire the item on show. */
async function retire(page: Page) {
  await page.getByRole("button", { name: "Retire item" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Retire item" }).click();
  await expect(page.getByText("The item was retired.")).toBeVisible();
}

/** The coverage of the item on show under this file's contract. */
function itsCoverage(page: Page) {
  return page.getByTestId("item-coverage").locator(`tr[data-contract="${number}"]`);
}

test("five switches are put under one contract from the item grid", async ({ page, account }) => {
  test.setTimeout(180_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  await importFile(page, "vendors", `vendors-${suffix}.csv`, ["name"], [[vendor]]);
  await importFile(
    page,
    "catalog_entries",
    `catalog-entries-${suffix}.csv`,
    ["vendor", "pid", "model_name", "type"],
    [[vendor, pid, "Example 9500 48-port", "switch"]],
  );
  await importFile(
    page,
    "items",
    `items-${suffix}.csv`,
    ["vendor", "pid", "serial_number", "hostname", "lifecycle_state"],
    switches.map((name, at) => [vendor, pid, `ENC${upper}0${at + 1}`, name, "Prod"]),
  );
  await newContract(page, { number, vendor, starts: `${year - 1}-01-01`, ends });

  await page.goto(`./items?filter=${encodeURIComponent(own)}`);
  await expect(page.getByTestId("grid-total")).toHaveText("5 items");
  await page.getByRole("button", { name: "Select all that match" }).click();
  await page.getByRole("button", { name: "Cover with a contract" }).click();
  const cover = page.getByTestId("cover-items");
  await expect(cover.getByRole("heading", { name: "Cover 5 items with a contract" })).toBeVisible();
  await pickContract(cover, number);
  await cover.getByRole("button", { name: "Cover 5 items" }).click();
  await expect(
    page.getByText(`5 items are now under ${number}. Nothing was written to any of them.`),
  ).toBeVisible();
  await expectClean(page, seen);
});

test("D-141: two coverages made by mistake are removed at once", async ({ page, account }) => {
  test.setTimeout(180_000);
  const seen = await watch(page.context());
  await signIn(page, account);

  await openContract(page, number);
  await expect(page.getByTestId("grid-total")).toHaveText("5 coverages");
  await selectCoverage(page, mistake1, mistake2);
  await page.getByRole("button", { name: "Remove coverage" }).click();
  const settle = page.getByTestId("settle-coverage");
  await expect(settle.getByRole("heading", { name: "Remove 2 coverages" })).toBeVisible();
  await expect(settle).toContainText(mistake1);
  await expect(settle).toContainText(mistake2);
  await settle.getByRole("button", { name: "Remove 2 coverages" }).click();
  await expect(
    page.getByText("2 coverages were removed. The audit trail holds what they were."),
  ).toBeVisible();
  await expect(page.getByTestId("grid-total")).toHaveText("3 coverages");
  await expect(page.getByTestId("covered-items")).toHaveText("3 items");

  // Removed outright: the switch was never under the contract, as far as it shows.
  await openItem(page, mistake1);
  await expect(region(page, "Coverage")).toContainText("It has never been under a contract.");
  await expectClean(page, seen);
});

test("D-141, D-162: two switches leave service, are counted under the contract, and the vendor is told at once", async ({
  page,
  account,
}) => {
  test.setTimeout(240_000);
  const seen = await watch(page.context());
  await signIn(page, account);

  // Retired, each has its coverage ended that day and marked, and says that the contract
  // still counts it.
  // Where each is, for once it is retired: the grid leaves it out until asked.
  const pages: string[] = [];
  for (const name of [left1, left2]) {
    await openItem(page, name);
    pages.push(page.url());
    await retire(page);
    await expect(itsCoverage(page)).toHaveAttribute("data-left-service", "true");
    const counted = page.getByTestId("item-counted-under");
    await expect(counted.locator(`[data-contract="${number}"]`)).toBeVisible();
    await expect(counted).toContainText("the list to send the vendor");
  }

  // The list for the vendor in the coverage report: the column is the server's field.
  await page.goto(
    `./reports/coverage?${new URLSearchParams({ filter: own, section: "out_of_service" }).toString()}`,
  );
  await expect(page.getByTestId("count-out_of_service")).toHaveAttribute("data-count", "2");
  await expect(page.getByTestId("grid-total")).toHaveText("2 items");
  const list = "grid-coverage-out_of_service";
  for (const name of [left1, left2]) {
    await expect(
      gridRow(page, list, name).locator('[col-id="out_of_service_contract.number"]'),
    ).toHaveText(number);
  }
  // The column is the field of the item list, under the header the page gave its own.
  const header = page
    .getByTestId(list)
    .locator('.ag-header-cell[col-id="out_of_service_contract.number"]');
  await expect(header).toContainText("Still counted under");

  // The item grid finds them by the contract that still counts them, and the column is in
  // its chooser.
  await page.goto(
    `./items?filter=${encodeURIComponent(`out_of_service_contract.number:eq:${number}`)}&archived=1`,
  );
  await expect(page.getByTestId("grid-total")).toHaveText("2 items");
  await chooseColumns(page, ["Still counted under"], ROOM);
  await expect(
    gridRow(page, "grid-items", left1).locator('[col-id="out_of_service_contract.number"]'),
  ).toHaveText(number);
  // Sorted by it on the server: the header sorts, and both rows stay.
  await page
    .getByTestId("grid-items")
    .locator('.ag-header-cell[col-id="out_of_service_contract.number"] .ag-header-cell-label')
    .click();
  await expect(page.getByTestId("grid-total")).toHaveText("2 items");
  await resetGrid(page);

  // The vendor is told of both, at once, from the page of the contract.
  await openContract(page, number);
  await expect(gridRow(page, coverage, left1).locator('[col-id="left_service"]')).toHaveText(
    "Ended: it left service",
  );
  await selectCoverage(page, left1, left2);
  await page.getByRole("button", { name: "Vendor told" }).click();
  const settle = page.getByTestId("settle-coverage");
  await expect(
    settle.getByRole("heading", { name: "The vendor has been told of 2 items" }),
  ).toBeVisible();
  await settle.getByRole("button", { name: "The vendor has been told" }).click();
  await expect(
    page.getByText("The vendor has been told of 2 items that left service."),
  ).toBeVisible();
  for (const name of [left1, left2]) {
    await expect(gridRow(page, coverage, name).locator('[col-id="left_service"]')).toHaveText("");
  }

  // The contract counts them no longer: the list for the vendor is empty, and the
  // switch says nothing of it.
  await page.goto(`./reports/coverage?filter=${encodeURIComponent(own)}`);
  await expect(page.getByTestId("count-out_of_service")).toHaveAttribute("data-count", "0");
  await page.goto(pages[0] ?? "");
  await expect(page.getByRole("heading", { level: 1, name: left1 })).toBeVisible();
  await expect(itsCoverage(page)).toHaveAttribute("data-left-service", "false");
  await expect(page.getByTestId("item-counted-under")).toHaveCount(0);

  await expectClean(page, seen);
});

test("D-141: a switch that left and came back has its coverage opened again", async ({
  page,
  account,
}) => {
  test.setTimeout(180_000);
  const seen = await watch(page.context());
  await signIn(page, account);

  await openItem(page, back);
  await expect(page.getByTestId("item-covered-until")).toHaveText(ends);
  await retire(page);
  await expect(itsCoverage(page)).toHaveAttribute("data-left-service", "true");
  // While it is retired its coverage is not opened again: it has not come back.
  await expect(
    itsCoverage(page).getByRole("button", { name: `Open the coverage under ${number} again` }),
  ).toHaveCount(0);

  await region(page, "Retired").getByRole("button", { name: "Bring back as active" }).click();
  await expect(page.getByText("The item is active again.")).toBeVisible();
  // Back in service, it is on no list of what has left, and its coverage stays ended
  // until a person opens it again.
  await expect(page.getByTestId("item-counted-under")).toHaveCount(0);
  await expect(itsCoverage(page)).toHaveAttribute("data-left-service", "true");
  await itsCoverage(page)
    .getByRole("button", { name: `Open the coverage under ${number} again` })
    .click();
  await expect(
    page.getByText(
      `The coverage of ${back} under ${number} is open again, with the period of the contract.`,
    ),
  ).toBeVisible();
  await expect(itsCoverage(page)).toHaveAttribute("data-left-service", "false");
  await expect(itsCoverage(page)).toHaveAttribute("data-in-force", "true");
  await expect(itsCoverage(page)).toContainText(ends);
  await expect(page.getByTestId("item-covered")).toHaveAttribute("data-covered", "true");
  await expect(page.getByTestId("item-covered-until")).toHaveText(ends);

  await expectClean(page, seen);
});
