// The browser scenarios of the settings in release 0.7.0 and 0.9.3:
//
//   P-136  Admin → Settings lists each setting with its value, its default, what it is for
//          and whether it is at its default, and one button returns it to its default;
//          beneath, the values fixed in the code, each with what it limits and why it is
//          fixed, and nothing to change them with.
//   P-171  Change opens the form of that setting directly beneath its row, across the
//          table, the first setting's as the last's: the focus moves into it, and back to
//          that setting's Change button when it closes, set, returned to its default or
//          cancelled. One form is open at a time, and what was typed in the one that
//          closes is let go. The table fits a window 1280 pixels wide with nothing
//          scrolled, the two buttons of a row one above the other; a narrower window
//          scrolls it sideways. (row-forms.spec.ts holds the same of the other pages.)
//
// They keep to the rules of support.ts: an account of their own. They change a setting
// that other files read, which rule 5 forbids for any change that could alter what they
// see: they raise `max_items_per_request`, the most items one request may cover, add to a
// group or receive, from its default of 1000 to 2000, and return it to its default. A
// higher limit only lets more through: every request another file sends while it is
// raised is taken as it would be at the default, and the web UI sends pieces that are
// larger but never refused. So they run beside the others, and one after the other, in
// this file: two files that changed the one setting at once would each be refused the
// other's version.

import { expect, type Locator, type Page } from "@playwright/test";
import { expectClean, signIn, test, watch } from "./support";

const key = "max_items_per_request";

test("P-136: a setting is changed, then returned to its default with one button", async ({
  page,
  account,
}) => {
  test.setTimeout(120_000);
  const seen = await watch(page.context());
  await signIn(page, account);

  await page.goto("./admin/settings");
  await expect(page.getByRole("heading", { level: 1, name: "Settings" })).toBeVisible();
  const row = page.getByTestId("settings").locator(`tr[data-setting="${key}"]`);
  await expect(row).toContainText("how many items one request may cover");
  await expect(row).toContainText("a whole number from 100 to 5,000");
  await expect(page.getByTestId(`default-${key}`)).toHaveText("1000");

  // Raised: it is no longer at its default, and says so.
  await row.getByRole("button", { name: `Change ${key}` }).click();
  const form = page.getByTestId("setting-form");
  await expect(form.getByRole("heading", { name: `Change ${key}` })).toBeVisible();
  await form.getByLabel("New value").fill("2000");
  await form.getByRole("button", { name: "Set", exact: true }).click();
  await expect(page.getByText(`${key} was set to 2000.`)).toBeVisible();
  await expect(row).toHaveAttribute("data-default", "false");
  await expect(page.getByTestId(`value-${key}`)).toHaveText("2000");
  await expect(page.getByTestId(`standing-${key}`)).toHaveText("Set here");

  // One button returns it to its default.
  await row.getByRole("button", { name: `Return ${key} to its default` }).click();
  await expect(page.getByText(`${key} is at its default again: 1000.`)).toBeVisible();
  await expect(row).toHaveAttribute("data-default", "true");
  await expect(page.getByTestId(`value-${key}`)).toHaveText("1000");
  await expect(page.getByTestId(`standing-${key}`)).toHaveText("At its default");
  await expect(row.getByRole("button", { name: `Return ${key} to its default` })).toBeDisabled();

  // The values fixed in the code are listed, each with what it limits and why it is
  // fixed, and the decision that fixed it where one did. Nothing there is changed.
  const fixed = page.getByTestId("fixed-values");
  const pageSize = fixed.locator('tr[data-fixed="max_page_size"]');
  await expect(pageSize).toContainText("1000");
  await expect(pageSize).toContainText("a limit that protects the service");
  const outOfService = fixed.locator('tr[data-fixed="out_of_service_states"]');
  await expect(outOfService).toContainText("Pending-Removal, Released, Archived");
  await expect(outOfService).toContainText("D-142");
  await expect(fixed.locator('tr[data-fixed="condition_health"]')).toContainText(
    "failed: failed, dead",
  );
  await expect(fixed.locator("input, select, textarea, td button")).toHaveCount(0);
  // And a fixed value is not among the settings.
  await expect(
    page.getByTestId("settings").locator('tr[data-setting="max_page_size"]'),
  ).toHaveCount(0);

  await expectClean(page, seen);
});

/** The row of a setting in the table of settings. */
function rowOf(page: Page, setting: string): Locator {
  return page.getByTestId("settings").locator(`tr[data-setting="${setting}"]`);
}

/** The Change button of a setting's row. */
function changeOf(page: Page, setting: string): Locator {
  return rowOf(page, setting).getByRole("button", { name: `Change ${setting}`, exact: true });
}

/** The row directly beneath a setting's row, where its form is while it is open. */
function formRowOf(page: Page, setting: string): Locator {
  return page
    .getByTestId("settings")
    .locator(`tr[data-setting="${setting}"] + tr[data-form-of="${setting}"]`);
}

/**
 * Open the form of a setting by its Change button, and find it directly beneath the
 * setting's row, in a row of its own whose one cell spans every column, with the focus on
 * a field of it, and that field in view not far below the button.
 */
async function openBeneath(page: Page, setting: string): Promise<Locator> {
  const button = changeOf(page, setting);
  await button.click();
  const formRow = formRowOf(page, setting);
  const form = formRow.getByTestId("setting-form");
  await expect(form.getByRole("heading", { name: `Change ${setting}` })).toBeVisible();
  await expect(page.getByTestId("setting-form")).toHaveCount(1);
  await expect(button).toHaveAttribute("aria-expanded", "true");
  const columns = await page.getByTestId("settings").locator("thead th").count();
  await expect(formRow.locator("> td")).toHaveCount(1);
  await expect(formRow.locator("> td")).toHaveAttribute("colspan", String(columns));
  await expect(form.locator(":focus")).toHaveCount(1);
  await expect(form.locator(":focus")).toHaveAttribute("name", /.+/);
  // The setting stays in view above the form, and the form's first field is in view
  // beneath it: on a window of 1280 x 800, less than 400 pixels below the button.
  const field = form.locator("input, select, textarea").first();
  await expect(button).toBeInViewport();
  await expect(field).toBeInViewport();
  const from = await button.boundingBox();
  const to = await field.boundingBox();
  const below = from && to ? to.y - from.y : Number.NaN;
  expect(below, `the first field of the form of ${setting}, below its Change`).toBeGreaterThan(0);
  expect(below, `the first field of the form of ${setting}, below its Change`).toBeLessThan(400);
  return form;
}

/** The form is closed, and the focus is on the setting's Change button, in view. */
async function closedTo(page: Page, setting: string) {
  await expect(page.getByTestId("setting-form")).toHaveCount(0);
  await expect(page.getByTestId("settings").locator("tr[data-form-of]")).toHaveCount(0);
  const button = changeOf(page, setting);
  await expect(button).toBeFocused();
  await expect(button).toHaveAttribute("aria-expanded", "false");
  await expect(button).toBeInViewport();
}

test("P-171: a setting is changed in a form beneath its row, which the focus moves into and back from", async ({
  page,
  account,
}) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 1280, height: 800 });
  const seen = await watch(page.context());
  await signIn(page, account);
  await page.goto("./admin/settings");
  await expect(page.getByRole("heading", { level: 1, name: "Settings" })).toBeVisible();
  const rows = page.getByTestId("settings").locator("tr[data-setting]");
  await expect(rows.first()).toBeVisible();
  const keys = await rows.evaluateAll((all) => all.map((row) => row.dataset.setting ?? ""));
  const first = keys[0] ?? "";
  const last = keys[keys.length - 1] ?? "";
  expect(first).not.toBe(last);
  await expect(page.getByTestId("setting-form")).toHaveCount(0);

  // 0.9.12 (P-278): the setting whose row is the tallest, its description the longest. Its
  // row is taller than what the window has left beside the form, so its Change button, at
  // the head of the row, went out of sight above the window when the form opened.
  const heights = await rows.evaluateAll((all) =>
    all.map((row) => row.getBoundingClientRect().height),
  );
  const tallest = keys[heights.indexOf(Math.max(...heights))] ?? "";
  expect(Math.max(...heights), `the row of ${tallest}`).toBeGreaterThan(400);

  // The first setting, the last and the tallest: each opens beneath its own row, and
  // Cancel closes it, with the focus back on its Change button.
  for (const setting of [first, last, tallest]) {
    const form = await openBeneath(page, setting);
    await form.getByRole("button", { name: "Cancel", exact: true }).click();
    await closedTo(page, setting);
  }

  // While its form is open the buttons of the tallest row stand at its foot, directly
  // above the form, and at its head again once the form is closed.
  const opener = changeOf(page, tallest);
  const tallRow = rowOf(page, tallest);
  const headOf = async () => {
    const [row, button] = [await tallRow.boundingBox(), await opener.boundingBox()];
    return row && button ? button.y - row.y : Number.NaN;
  };
  expect(await headOf(), "closed, Change is at the head of its row").toBeLessThan(40);
  const tallForm = await openBeneath(page, tallest);
  const [button, panel] = [await opener.boundingBox(), await tallForm.boundingBox()];
  const above = button && panel ? panel.y - (button.y + button.height) : Number.NaN;
  expect(above, "open, Change is directly above the form").toBeGreaterThanOrEqual(0);
  expect(above, "open, Change is directly above the form").toBeLessThan(120);
  await tallForm.getByRole("button", { name: "Cancel", exact: true }).click();
  await closedTo(page, tallest);
  expect(await headOf(), "closed again, Change is at the head of its row").toBeLessThan(40);

  // One form at a time: Change on another setting closes the first, and what was typed
  // in it and not set is let go.
  let form = await openBeneath(page, key);
  await expect(form.getByLabel("New value")).toBeFocused();
  await form.getByLabel("New value").fill("1234");
  const other = keys.find((one) => one !== key) ?? "";
  await openBeneath(page, other);
  await expect(formRowOf(page, key)).toHaveCount(0);
  await expect(changeOf(page, key)).toHaveAttribute("aria-expanded", "false");
  form = await openBeneath(page, key);
  await expect(formRowOf(page, other)).toHaveCount(0);
  await expect(form.getByLabel("New value")).toHaveValue("1000");

  // Set: the form closes, the row says what was set, and the focus is on its Change.
  await form.getByLabel("New value").fill("2000");
  await form.getByRole("button", { name: "Set", exact: true }).click();
  await expect(page.getByText(`${key} was set to 2000.`)).toBeVisible();
  await expect(page.getByTestId(`value-${key}`)).toHaveText("2000");
  await closedTo(page, key);

  // A value it does not take is refused beneath its field, and the form stays open.
  form = await openBeneath(page, key);
  await form.getByLabel("New value").fill("50");
  await form.getByRole("button", { name: "Set", exact: true }).click();
  await expect(form.getByLabel("New value")).toHaveAttribute("aria-invalid", "true");
  await expect(formRowOf(page, key)).toHaveCount(1);

  // Returned to its default from the form: it closes, and the focus is on its Change.
  await form.getByRole("button", { name: "Return to its default", exact: true }).click();
  await expect(page.getByText(`${key} is at its default again: 1000.`)).toBeVisible();
  await expect(page.getByTestId(`value-${key}`)).toHaveText("1000");
  await closedTo(page, key);

  // The table fits the window of 1280 with nothing scrolled, a setting changed just now
  // among its rows, and the two buttons of a row stand one above the other. A narrower
  // window scrolls it sideways.
  const scroller = page.getByTestId("settings").locator("xpath=..");
  const widths = () => scroller.evaluate((one) => [one.clientWidth, one.scrollWidth] as const);
  const [column, table] = await widths();
  expect(table, "the width of the table of settings, in its column of 1280").toBeLessThanOrEqual(
    column,
  );
  const change = await changeOf(page, key).boundingBox();
  const back = await rowOf(page, key)
    .getByRole("button", { name: `Return ${key} to its default` })
    .boundingBox();
  expect(change && back && back.y >= change.y + change.height).toBe(true);
  expect(change && back && Math.abs(back.x - change.x) < 2).toBe(true);
  await page.setViewportSize({ width: 900, height: 800 });
  await expect.poll(async () => (await widths())[1] > (await widths())[0]).toBe(true);
  await expectClean(page, seen, ["422 PUT"]);
});
