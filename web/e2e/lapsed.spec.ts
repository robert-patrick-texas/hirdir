// The browser scenarios of a contract whose term has ended, in release 0.6.1, for what
// only unit tests held before:
//
//   D-140  A contract whose period has ended while its status still says Active has
//          lapsed: it is marked on its page, in the grid and among the contracts that
//          stand by themselves, and it covers nothing, so its switch has no cover.
//   D-150  Its renewal is late and in procurement: given the status Renewal pending, it
//          covers on past its end, its marks say to go through the account manager, the
//          switch says the same, no day is known to end its cover, and the coverage report
//          counts it. The renewal entered at last makes it Active in its new period.
//
// It keeps to the rules of support.ts: an account and names of its own, and every report
// and grid filtered down to this file's records before anything is counted.

import { expect } from "@playwright/test";
import {
  chooseColumns,
  gridRow,
  newContract,
  openContract,
  ROOM,
  resetGrid,
} from "./contractSteps";
import { importFile, openItem, region } from "./structure";
import { expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const random = mark("x").slice(2);
const suffix = mark("lapsed", random);
const upper = random.toUpperCase();
const year = new Date().getFullYear();

const vendor = `Example Networks ${suffix}`;
const pid = `EN-9200-24T-${suffix}`;
const switchName = `site8-sw-${suffix}-01`;
const own = `hostname:eq:${switchName}`;
const number = `CON-${suffix}-1`;
const renewed = `CON-${suffix}-2`;
const manager = "Avery Quinn, avery.quinn@example.com, +1 555 0187";
// A period that ended last year.
const starts = `${year - 2}-01-01`;
const ends = `${year - 1}-12-31`;
const renewedStarts = `${year}-01-01`;
const renewedEnds = `${year + 1}-12-31`;

test("a contract that has lapsed, and its renewal pending and then entered", async ({
  page,
  account,
}) => {
  test.setTimeout(240_000);
  const seen = await watch(page.context());
  await signIn(page, account);

  await importFile(page, "vendors", `vendors-${suffix}.csv`, ["name"], [[vendor]]);
  await importFile(
    page,
    "catalog_entries",
    `catalog-entries-${suffix}.csv`,
    ["vendor", "pid", "model_name", "type"],
    [[vendor, pid, "Example 9200 24-port", "switch"]],
  );
  await importFile(
    page,
    "items",
    `items-${suffix}.csv`,
    ["vendor", "pid", "serial_number", "hostname", "lifecycle_state"],
    [[vendor, pid, `ENL${upper}01`, switchName, "Prod"]],
  );

  // A contract whose period ended last year, and whose status still says Active.
  await newContract(page, { number, vendor, starts, ends, manager });
  const heading = page.getByRole("heading", { level: 1, name: number });
  await expect(heading.locator('[data-mark="lapsed"]')).toHaveText("Lapsed");
  await expect(page.getByTestId("contract-status")).toHaveAttribute("data-status", "active");
  await expect(page.getByTestId("lapsed")).toBeVisible();
  await expect(page.getByTestId("covers-today")).toContainText("No");
  await expect(page.getByTestId("lapsed-note")).toBeVisible();

  // The switch put under it is not covered: a lapsed contract covers nothing.
  await openItem(page, switchName);
  await page.getByRole("button", { name: "Cover with a contract" }).click();
  const cover = page.getByTestId("cover-items");
  await cover.getByLabel("Contract", { exact: true }).fill(number);
  await cover
    .getByRole("list", { name: "Contracts that match" })
    .getByRole("button", { name: new RegExp(`^${number} `) })
    .click();
  await cover.getByRole("button", { name: `Cover ${switchName}` }).click();
  await expect(page.getByTestId("item-covered")).toHaveAttribute("data-covered", "false");
  await expect(
    page.getByTestId("item-coverage").locator(`tr[data-contract="${number}"]`),
  ).toHaveAttribute("data-in-force", "false");

  // The grid of contracts marks it, and finds it by the mark.
  await page.goto(`./contracts?filter=${encodeURIComponent(`number:eq:${number} lapsed:eq:true`)}`);
  await expect(page.getByTestId("grid-total")).toHaveText("1 contract");
  await expect(gridRow(page, "grid-contracts", number).locator('[col-id="lapsed"]')).toHaveText(
    "Lapsed",
  );
  // So does the table of the contracts that stand by themselves, once the tables by
  // agreement are opened (P-212).
  await page.goto("./contracts");
  await page.getByTestId("contracts-grouped-line").click();
  await expect(
    page
      .getByTestId("contracts-grouped")
      .locator(`tr[data-contract="${number}"] [data-mark="lapsed"]`),
  ).toBeVisible();
  await expect(page.getByTestId("lapsed-contracts")).toBeVisible();

  // The coverage report of the switch: in service, and with no cover.
  await page.goto(`./reports/coverage?filter=${encodeURIComponent(own)}`);
  await expect(page.getByTestId("count-uncovered")).toHaveAttribute("data-count", "1");
  await expect(page.getByTestId("count-renewal_pending")).toHaveAttribute("data-count", "0");

  // The renewal is in procurement: the contract is given the status Renewal pending.
  await openContract(page, number);
  const details = region(page, "Details");
  await details.getByLabel("Status", { exact: true }).selectOption({ label: "Renewal pending" });
  await details.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("The contract was saved.")).toBeVisible();
  await expect(heading.locator('[data-mark="renewal-pending"]')).toHaveText("Renewal pending");
  await expect(heading.locator('[data-mark="lapsed"]')).toHaveCount(0);
  await expect(page.getByTestId("lapsed")).toHaveCount(0);
  await expect(page.getByTestId("renewal-pending")).toContainText(
    `go through the account manager (${manager}) before the support line is called`,
  );
  await expect(page.getByTestId("renewal-pending-note")).toBeVisible();
  await expect(page.getByTestId("covers-today")).toHaveText("Yes");

  // The switch is covered on, by escalation, and no day is known to end its cover.
  await openItem(page, switchName);
  await expect(page.getByTestId("item-covered")).toHaveAttribute("data-covered", "true");
  await expect(page.getByTestId("item-renewal-pending")).toHaveText(
    "Renewal pending: go through the account manager",
  );
  await expect(page.getByTestId("item-covered-until")).toHaveText(
    "No day is known: the renewal is pending",
  );

  // The report counts it among what is covered while a renewal is pending, and the grid
  // of the list says the status of the contract.
  await page.goto(
    `./reports/coverage?${new URLSearchParams({ filter: own, section: "renewal_pending" }).toString()}`,
  );
  await expect(page.getByTestId("count-uncovered")).toHaveAttribute("data-count", "0");
  await expect(page.getByTestId("count-renewal_pending")).toHaveAttribute("data-count", "1");
  await expect(page.getByTestId("section-heading")).toHaveText(
    "Covered while a renewal is pending",
  );
  const listed = gridRow(page, "grid-coverage-renewal_pending", switchName);
  await expect(listed.locator('[col-id="contract.status"]')).toHaveText("Renewal pending");
  await expect(listed.locator('[col-id="contract.number"]')).toHaveText(number);

  // In the item grid the status is a column to ask for, with whom to go through as its hint.
  await page.goto(`./items?filter=${encodeURIComponent(own)}`);
  await chooseColumns(page, ["Contract status", "Covered"], ROOM);
  const row = gridRow(page, "grid-items", switchName);
  await expect(row.locator('[col-id="contract.status"]')).toHaveText("Renewal pending");
  await expect(row.locator('[col-id="covered"]')).toHaveText("Yes");
  // A cell that has the focus says its hint beneath the grid.
  await row.locator('[col-id="covered"]').click();
  await expect(page.getByTestId("grid-cell-note")).toContainText(
    "Renewal pending: go through the account manager",
  );
  await resetGrid(page);

  // The renewal is entered at last: Active again, in its new period, and the switch is
  // covered to its end.
  await openContract(page, number);
  await region(page, "Renew").getByRole("button", { name: "Renew", exact: true }).click();
  const form = page.getByTestId("renew-form");
  await form.getByLabel("New number").fill(renewed);
  await form.getByLabel("New period: starts on").fill(renewedStarts);
  await form.getByLabel("New period: ends on").fill(renewedEnds);
  await form.getByRole("button", { name: "Renew for 1 item" }).click();
  await expect(page.getByRole("heading", { level: 1, name: renewed })).toBeVisible();
  await expect(page.getByTestId("contract-status")).toHaveAttribute("data-status", "active");
  await expect(page.getByTestId("renewal-pending")).toHaveCount(0);
  await expect(
    page.getByRole("heading", { level: 1, name: renewed }).locator("[data-mark]"),
  ).toHaveText(["Active"]);
  await expect(
    page.getByTestId("contract-terms").locator(`tr[data-term="${number}"]`),
  ).toBeVisible();
  await openItem(page, switchName);
  await expect(page.getByTestId("item-covered")).toHaveAttribute("data-covered", "true");
  await expect(page.getByTestId("item-renewal-pending")).toHaveCount(0);
  await expect(page.getByTestId("item-covered-until")).toHaveText(renewedEnds);

  await expectClean(page, seen);
});
