// 0.9.7, rows are ticked (P-233): a box to each row of a list at its left, one in the
// heading that ticks every row on show and clears them, pressing a row selecting it as
// before, and the buttons that act on the rows chosen saying how many.
//
// It keeps to the rules of support.ts: an account and names of its own, and the list
// filtered down to this file's vendors before anything is counted.

import { expect, type Locator, type Page } from "@playwright/test";
import { importFile } from "./structure";
import { expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const suffix = mark("ticked");
const vendors = [1, 2, 3].map((place) => `Example Ticked ${suffix} ${place}`) as [
  string,
  string,
  string,
];
const grid = "grid-vendors";

function gridRow(page: Page, text: string): Locator {
  return page.getByTestId(grid).locator("[row-id]", { hasText: text });
}

/** The box at the left of a row. */
function rowBox(page: Page, text: string): Locator {
  return gridRow(page, text).locator(".ag-selection-checkbox input");
}

async function openVendors(page: Page) {
  await page.goto(`./vendors?filter=${encodeURIComponent(`name:contains:${suffix}`)}`);
  await expect(page.getByTestId("grid-total")).toHaveText("3 vendors");
}

test("the vendors of this file are loaded", async ({ page, account }) => {
  test.setTimeout(120_000);
  await signIn(page, account);
  await importFile(
    page,
    "vendors",
    `vendors-${suffix}.csv`,
    ["name"],
    vendors.map((name) => [name]),
  );
});

test("rows are ticked by their boxes and by the one in the heading, and the buttons say how many", async ({
  page,
  account,
}) => {
  const seen = await watch(page.context());
  await signIn(page, account);
  await openVendors(page);
  const copy = page.getByRole("button", { name: /^Copy( \(|$)/ });
  const all = page.getByTestId("grid-tick-all");
  await expect(copy).toHaveText("Copy");
  await expect(copy).toBeDisabled();

  // A box to each row: two ticked, one after the other, both stay ticked.
  await rowBox(page, vendors[0]).check();
  await rowBox(page, vendors[2]).check();
  await expect(page.getByTestId("grid-selected")).toContainText("2 selected");
  await expect(copy).toHaveText("Copy (2)");
  await expect(page.getByRole("button", { name: "Export CSV (2)" })).toBeEnabled();
  await expect(all).not.toBeChecked();
  await expect
    .poll(() => all.evaluate((box) => (box as HTMLInputElement).indeterminate))
    .toBe(true);

  // The box in the heading ticks every row on show, and clears them.
  await all.check();
  await expect(copy).toHaveText("Copy (3)");
  await expect(rowBox(page, vendors[1])).toBeChecked();
  await all.uncheck();
  await expect(copy).toHaveText("Copy");
  await expect(page.getByTestId("grid-selected")).toHaveCount(0);

  // Pressing a row selects it alone, as before, and ticks its box.
  await rowBox(page, vendors[0]).check();
  await gridRow(page, vendors[1]).locator('[col-id="review_status"]').click();
  await expect(page.getByTestId("grid-selected")).toContainText("1 selected");
  await expect(rowBox(page, vendors[1])).toBeChecked();
  await expect(rowBox(page, vendors[0])).not.toBeChecked();
  await expect(copy).toHaveText("Copy (1)");

  // All that match is a count, not the rows.
  await page.getByRole("button", { name: "Select all that match" }).click();
  await expect(copy).toHaveText("Copy (all 3)");
  await expect(page.getByRole("button", { name: "Export JSON (all 3)" })).toBeEnabled();
  await page.getByRole("button", { name: "Clear selection" }).click();
  await expect(copy).toHaveText("Copy");
  await expectClean(page, seen);
});

test("the box in the heading waits for the rows of a list that is slow to come", async ({
  page,
  account,
}) => {
  await signIn(page, account);
  let hold: () => void = () => undefined;
  const held = new Promise<void>((resolve) => {
    hold = resolve;
  });
  await page.route("**/api/v1/vendors?*", async (route) => {
    await held;
    await route.continue();
  });
  await page.goto(`./vendors?filter=${encodeURIComponent(`name:contains:${suffix}`)}`);
  const all = page.getByTestId("grid-tick-all");
  await expect(all).toBeDisabled();
  await expect(page.getByRole("button", { name: /^Copy( \(|$)/ })).toBeDisabled();
  hold();
  await expect(page.getByTestId("grid-total")).toHaveText("3 vendors");
  await all.check();
  await expect(page.getByRole("button", { name: /^Copy( \(|$)/ })).toHaveText("Copy (3)");
});
