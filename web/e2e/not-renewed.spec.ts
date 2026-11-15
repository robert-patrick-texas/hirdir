// The browser scenario of the flag not to renew in release 0.7.0 (P-118, P-131, S42):
//
//   Three telephones of one model and a switch of another. The model of the telephones
//   is flagged not to be renewed on its catalog page, and one telephone is given its own
//   word, No, on its page: the values in force say where each has it from, and the item
//   grid has the flag in force in its column chooser. The third telephone, in service
//   and under no contract, is no gap: the coverage report counts it as not to be renewed,
//   by model, and the count leads to it. Two telephones and the switch are under one
//   contract, which is renewed: the flagged telephone is left behind, its coverage ending
//   with the old term, and the answer counts it; the other two follow into the new term.
//
// It keeps to the rules of support.ts: an account and names of its own, and nothing
// changed that another file reads. The coverage report is read with a filter of this
// file's vendor.

import { expect, type Page } from "@playwright/test";
import { chooseColumns, gridRow, openContract, pickContract, ROOM } from "./contractSteps";
import { freshGrid, importFile, openItem, region } from "./structure";
import { expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const random = mark("x").slice(2);
const suffix = mark("not-renewed", random);
const upper = random.toUpperCase();
const year = new Date().getFullYear();

const vendor = `Example Voice ${suffix}`;
const phoneModel = `EV-PHONE-${upper}`;
const switchModel = `EV-SW-${upper}`;
const flagged = `phone-${suffix}-01`;
const ownNo = `phone-${suffix}-02`;
const spare = `phone-${suffix}-03`;
const switchName = `sw-${suffix}-01`;
const contract = `CON-${upper}-V1`;
const renewed = `CON-${upper}-V2`;
const starts = `${year - 1}-01-01`;
const ends = `${year + 1}-12-31`;
const renewedStarts = `${year}-01-01`;
const renewedEnds = `${year + 3}-12-31`;

/** The flag not to renew among the values in force on the page of an item. */
function flagInForce(page: Page) {
  return page.locator('tr[data-field="do_not_renew"]');
}

test("S42: the flag on a model and on an item, the coverage report, and a renewal that leaves one behind", async ({
  page,
  account,
}) => {
  test.setTimeout(300_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  await importFile(page, "vendors", `vendors-${suffix}.csv`, ["name"], [[vendor]]);
  await importFile(
    page,
    "catalog_entries",
    `catalog-entries-${suffix}.csv`,
    ["vendor", "pid", "model_name", "type"],
    [
      [vendor, phoneModel, "Example desk phone", "phone"],
      [vendor, switchModel, "Example access switch", "switch"],
    ],
  );
  await importFile(
    page,
    "items",
    `items-${suffix}.csv`,
    ["vendor", "pid", "serial_number", "hostname", "lifecycle_state"],
    [
      [vendor, phoneModel, `EVP${upper}01`, flagged, "Prod"],
      [vendor, phoneModel, `EVP${upper}02`, ownNo, "Prod"],
      [vendor, phoneModel, `EVP${upper}03`, spare, "Prod"],
      [vendor, switchModel, `EVS${upper}01`, switchName, "Prod"],
    ],
  );

  // The model is flagged on its page: every item of it has the flag, unless it says not.
  await page.goto(`./catalog?filter=${encodeURIComponent(`pid:eq:${phoneModel}`)}`);
  await page
    .getByTestId("grid-catalog")
    .getByRole("link", { name: phoneModel, exact: true })
    .click();
  await expect(page.getByTestId("entry-do-not-renew")).toHaveAttribute("data-value", "false");
  await region(page, "Details").getByLabel("Not to be renewed").check();
  await region(page, "Details").getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("The catalog entry was saved.")).toBeVisible();
  await expect(page.getByTestId("entry-do-not-renew")).toHaveAttribute("data-value", "true");

  // One telephone says No of its own; the first has the model's, with that source.
  await openItem(page, ownNo);
  await region(page, "Details").getByLabel("Not to be renewed").selectOption({ label: "No" });
  await region(page, "Details").getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("The item was saved.")).toBeVisible();
  await expect(flagInForce(page)).toHaveAttribute("data-source", "own");
  await expect(flagInForce(page).locator("td").first()).toHaveText("No");
  await openItem(page, flagged);
  await expect(flagInForce(page)).toHaveAttribute("data-source", "catalog");
  await expect(flagInForce(page).locator("td").first()).toHaveText("Yes");
  await expect(flagInForce(page).locator("td").first()).toHaveClass(/inherited/);

  // The item grid has the flag in force in its column chooser, filtered by the server.
  await freshGrid(page, `catalog.vendor:eq:${vendor}`);
  await chooseColumns(page, ["Not to be renewed"], ROOM);
  for (const [host, word] of [
    [flagged, "Yes"],
    [ownNo, "No"],
    [spare, "Yes"],
    [switchName, "No"],
  ] as const) {
    await expect(
      gridRow(page, "grid-items", host).locator('[col-id="effective.do_not_renew"]'),
    ).toHaveText(word);
  }
  await page
    .getByLabel("Filter", { exact: true })
    .fill(`catalog.vendor:eq:${vendor} effective.do_not_renew:eq:true`);
  await page.getByRole("button", { name: "Apply", exact: true }).click();
  await expect(page.getByTestId("grid-total")).toHaveText("2 items");

  // A contract over two of the telephones and the switch.
  await page.goto("./contracts");
  await page.getByRole("button", { name: "New contract" }).click();
  const form = region(page, "New contract");
  await form.getByLabel("Number (required)").fill(contract);
  await form.getByLabel("Vendor", { exact: true }).selectOption({ label: vendor });
  await form.getByLabel("Starts on").fill(starts);
  await form.getByLabel("Ends on").fill(ends);
  await form.getByRole("button", { name: "Create contract" }).click();
  await expect(page.getByRole("heading", { level: 1, name: contract })).toBeVisible();
  for (const host of [flagged, ownNo, switchName]) {
    await openItem(page, host);
    await page.getByRole("button", { name: "Cover with a contract" }).click();
    const cover = page.getByTestId("cover-items");
    await pickContract(cover, contract);
    await cover.getByRole("button", { name: `Cover ${host}` }).click();
    await expect(page.getByTestId("item-covered-until")).toHaveText(ends);
  }

  // The coverage report of this vendor: the spare telephone, in service under no
  // contract, is not to be renewed and no gap, counted by its model.
  await page.goto(`./reports/coverage?filter=${encodeURIComponent(`catalog.vendor:eq:${vendor}`)}`);
  await expect(page.getByTestId("total-in-service")).toHaveText("4");
  await expect(page.getByTestId("total-covered")).toHaveText("3");
  await expect(page.getByTestId("total-uncovered")).toHaveText("0");
  await expect(page.getByTestId("total-not-renewed")).toHaveText("1");
  await expect(page.getByTestId("count-not_renewed")).toHaveAttribute("data-count", "1");
  await expect(page.getByTestId("count-uncovered")).toHaveAttribute("data-count", "0");
  // The counts come first: no list is read until one is opened.
  await expect(page.getByTestId("no-list-open")).toBeVisible();
  const byModel = page.getByTestId("not-renewed-by-model").locator(`tr[data-pid="${phoneModel}"]`);
  await expect(byModel).toHaveAttribute("data-count", "1");
  await expect(byModel).toContainText("Example desk phone");
  await byModel.getByRole("link", { name: /^1 item of / }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Items" })).toBeVisible();
  await expect(
    page.getByTestId("grid-items").getByRole("link", { name: spare, exact: true }),
  ).toBeVisible();
  await expect(page.getByTestId("grid-total")).toHaveText("1 item");
  // And the list of them, opened on the report.
  await page.goto(
    `./reports/coverage?${new URLSearchParams({ filter: `catalog.vendor:eq:${vendor}`, section: "not_renewed" }).toString()}`,
  );
  await expect(page.getByTestId("section-heading")).toHaveText("Not to be renewed");
  await expect(gridRow(page, "grid-coverage-not_renewed", spare)).toBeVisible();

  // The contract is renewed: the flagged telephone is left behind, its coverage ending
  // with the term before, and the other two follow into the new one.
  await openContract(page, contract);
  await region(page, "Renew").getByRole("button", { name: "Renew", exact: true }).click();
  const renewal = page.getByTestId("renew-form");
  await renewal.getByLabel("New number").fill(renewed);
  await renewal.getByLabel("New period: starts on").fill(renewedStarts);
  await renewal.getByLabel("New period: ends on").fill(renewedEnds);
  await renewal.getByRole("button", { name: "Renew for 3 items" }).click();
  await expect(page.getByRole("heading", { level: 1, name: renewed })).toBeVisible();
  await expect(
    page.getByText("1 coverage of an item not to be renewed was ended with the present term."),
  ).toBeVisible();
  await openItem(page, flagged);
  await expect(page.getByTestId("item-covered-until")).toHaveText(ends);
  await openItem(page, ownNo);
  await expect(page.getByTestId("item-covered-until")).toHaveText(renewedEnds);
  await openItem(page, switchName);
  await expect(page.getByTestId("item-covered-until")).toHaveText(renewedEnds);

  await expectClean(page, seen);
});
