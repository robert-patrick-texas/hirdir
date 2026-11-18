// 0.9.7, rows are ticked (P-233): a box to each row of a list at its left, one in the
// heading that ticks the rows read so far and clears them, a press on a row ticking or
// unticking it alone, and the buttons that act on the rows chosen saying how many.
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

  // Pressing a row ticks it, and unticks nothing else; pressed again, it is unticked.
  await rowBox(page, vendors[0]).check();
  await gridRow(page, vendors[1]).locator('[col-id="review_status"]').click();
  await expect(page.getByTestId("grid-selected")).toContainText("2 selected");
  await expect(rowBox(page, vendors[1])).toBeChecked();
  await expect(rowBox(page, vendors[0])).toBeChecked();
  await expect(copy).toHaveText("Copy (2)");
  await gridRow(page, vendors[1]).locator('[col-id="review_status"]').click();
  await expect(rowBox(page, vendors[1])).not.toBeChecked();
  await expect(rowBox(page, vendors[0])).toBeChecked();
  await expect(copy).toHaveText("Copy (1)");

  // Shift with a press takes the rows between the row pressed last and this one.
  await gridRow(page, vendors[0]).locator('[col-id="review_status"]').click();
  await gridRow(page, vendors[0]).locator('[col-id="review_status"]').click();
  await expect(copy).toHaveText("Copy (1)");
  await gridRow(page, vendors[2])
    .locator('[col-id="review_status"]')
    .click({ modifiers: ["Shift"] });
  await expect(copy).toHaveText("Copy (3)");

  // A press on a link with Ctrl opens it in a new tab, and changes no tick.
  const opened = page.context().waitForEvent("page");
  await gridRow(page, vendors[1])
    .getByRole("link", { name: vendors[1] })
    .click({
      modifiers: ["ControlOrMeta"],
    });
  await (await opened).close();
  await expect(copy).toHaveText("Copy (3)");
  await all.uncheck();
  await rowBox(page, vendors[0]).check();
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

test("the box in the heading ticks the rows read so far, and shows all ticked only when the whole list is", async ({
  page,
  account,
}) => {
  test.setTimeout(120_000);
  // More rows than the grid reads in its first block of a hundred.
  const many = mark("ticked");
  const names = Array.from(
    { length: 130 },
    (_, at) => `Example Many ${many} ${String(at + 1).padStart(3, "0")}`,
  );
  await signIn(page, account);
  await importFile(
    page,
    "vendors",
    `vendors-${many}.csv`,
    ["name"],
    names.map((name) => [name]),
  );
  const seen = await watch(page.context());
  await page.goto(`./vendors?filter=${encodeURIComponent(`name:contains:${many}`)}`);
  await expect(page.getByTestId("grid-total")).toHaveText("130 vendors");
  const all = page.getByTestId("grid-tick-all");
  const copy = page.getByRole("button", { name: /^Copy( \(|$)/ });
  const half = () => all.evaluate((box) => (box as HTMLInputElement).indeterminate);

  await expect(all).toHaveAccessibleName("Tick the 100 rows read so far");
  await all.click();
  await expect(copy).toHaveText("Copy (100)");
  // A hundred of 130 are ticked: the box shows the half mark, not all ticked.
  await expect(all).not.toBeChecked();
  await expect.poll(half).toBe(true);
  await expect(all).toHaveAccessibleName("Clear the 100 rows read so far");

  // The second block is read as the list is scrolled to its end: its rows come unticked.
  await page
    .getByTestId(grid)
    .locator(".ag-grid-viewport, .ag-body-viewport")
    .first()
    .evaluate((rows) => {
      rows.scrollTop = rows.scrollHeight;
    });
  await expect(all).toHaveAccessibleName("Tick the 130 rows read so far");
  await expect.poll(half).toBe(true);
  await expect(copy).toHaveText("Copy (100)");
  await all.click();
  await expect(copy).toHaveText("Copy (130)");
  await expect(all).toBeChecked();
  await expect.poll(half).toBe(false);
  await all.click();
  await expect(copy).toHaveText("Copy");
  await expectClean(page, seen);
});

test("Shift with a press or with Space ticks the rows from the one last pressed to this one, and unticks nothing", async ({
  page,
  account,
}) => {
  test.setTimeout(120_000);
  const shift = mark("ticked");
  const names = Array.from(
    { length: 12 },
    (_, at) => `Example Shift ${shift} ${String(at).padStart(2, "0")}`,
  );
  await signIn(page, account);
  await importFile(
    page,
    "vendors",
    `vendors-${shift}.csv`,
    ["name"],
    names.map((name) => [name]),
  );
  const seen = await watch(page.context());
  await page.goto(`./vendors?filter=${encodeURIComponent(`name:contains:${shift}`)}`);
  await expect(page.getByTestId("grid-total")).toHaveText("12 vendors");
  await page.getByRole("columnheader", { name: "Name" }).click();
  const row = (at: number) => gridRow(page, names[at] ?? "");
  const press = (at: number, modifiers: ("Shift" | "ControlOrMeta")[] = []) =>
    row(at).locator('[col-id="review_status"]').click({ modifiers });
  /** The rows ticked, by their place in the list. */
  const ticked = () =>
    page
      .getByTestId(grid)
      .locator(".ag-row-selected[row-index]")
      .evaluateAll((rows) =>
        [...new Set(rows.map((one) => Number(one.getAttribute("row-index"))))].sort(
          (one, other) => one - other,
        ),
      );
  const clear = async () => {
    await page.getByRole("button", { name: "Clear selection" }).click();
    await expect.poll(ticked).toEqual([]);
  };
  await expect(row(0)).toHaveAttribute("row-index", "0");

  // Rows 0 and 9 ticked; 3 ticked and unticked; Shift with a press on 6: 3 to 6 join them.
  await press(0);
  await press(9);
  await press(3);
  await press(3);
  await press(6, ["Shift"]);
  await expect.poll(ticked).toEqual([0, 3, 4, 5, 6, 9]);
  await clear();

  // 1 to 6 by Shift; 4 unticked by a press; Shift with a press on 8: 4 to 8, and 1 to 3 stay.
  await press(1);
  await press(6, ["Shift"]);
  await press(4);
  await expect.poll(ticked).toEqual([1, 2, 3, 5, 6]);
  await press(8, ["Shift"]);
  await expect.poll(ticked).toEqual([1, 2, 3, 4, 5, 6, 7, 8]);
  await clear();

  // The keyboard the same: Space unticks 4, Shift with Space on 7 ticks 4 to 7.
  await press(1);
  await press(6, ["Shift"]);
  await row(4).locator('[col-id="review_status"]').focus();
  await page.keyboard.press("Space");
  await expect.poll(ticked).toEqual([1, 2, 3, 5, 6]);
  for (let step = 0; step < 3; step += 1) await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Shift+Space");
  await expect.poll(ticked).toEqual([1, 2, 3, 4, 5, 6, 7]);
  await clear();

  // Within a range, Shift with a press on a box shortens nothing: 0, 2 to 6 and 9 stay.
  await press(9);
  await press(0);
  await press(2);
  await press(6, ["Shift"]);
  await expect.poll(ticked).toEqual([0, 2, 3, 4, 5, 6, 9]);
  await row(4)
    .locator(".ag-selection-checkbox input")
    .click({ modifiers: ["Shift"] });
  await expect.poll(ticked).toEqual([0, 2, 3, 4, 5, 6, 9]);
  await expect(page.getByTestId("grid-selected")).toContainText("7 selected");
  await expectClean(page, seen);
});

test("Shift across rows not read yet ticks the rows read and the row pressed, and says the rest were not", async ({
  page,
  account,
}) => {
  test.setTimeout(180_000);
  const far = mark("ticked");
  const names = Array.from(
    { length: 250 },
    (_, at) => `Example Far ${far} ${String(at).padStart(3, "0")}`,
  );
  await signIn(page, account);
  await importFile(
    page,
    "vendors",
    `vendors-${far}.csv`,
    ["name"],
    names.map((name) => [name]),
  );
  const seen = await watch(page.context());
  await page.goto(`./vendors?filter=${encodeURIComponent(`name:contains:${far}`)}`);
  await expect(page.getByTestId("grid-total")).toHaveText("250 vendors");
  const row = (at: number) => gridRow(page, names[at] ?? "");
  await expect(row(3)).toHaveAttribute("row-index", "3");
  await row(3).locator('[col-id="review_status"]').click();

  // To the end at once: the block of rows 100 to 199 is never read.
  await page
    .getByTestId(grid)
    .locator(".ag-grid-viewport, .ag-body-viewport")
    .first()
    .evaluate((rows) => {
      rows.scrollTop = rows.scrollHeight;
    });
  await row(245)
    .locator('[col-id="review_status"]')
    .click({ modifiers: ["Shift"] });
  // 3 to 99 and 200 to 245 are ticked, the row pressed among them; 100 rows were not read.
  await expect(row(245).locator(".ag-selection-checkbox input")).toBeChecked();
  await expect(page.getByTestId("grid-selected")).toContainText("143 selected");
  await expect(page.getByTestId("grid-range-unread")).toHaveText(
    " · 100 rows between were not read yet, and so not ticked: scroll through them, then press again with Shift",
  );
  // The next press without Shift lets the words go.
  await row(247).locator('[col-id="review_status"]').click();
  await expect(page.getByTestId("grid-range-unread")).toHaveCount(0);
  await expect(page.getByTestId("grid-selected")).toContainText("144 selected");
  await expectClean(page, seen);
});
