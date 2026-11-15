// The browser scenario of the settings in release 0.7.0:
//
//   P-136  Admin → Settings lists each setting with its value, its default, what it is for
//          and whether it is at its default, and one button returns it to its default;
//          beneath, the values fixed in the code, each with what it limits and why it is
//          fixed, and nothing to change them with.
//
// It keeps to the rules of support.ts: an account of its own. It changes a setting that
// other files read, which rule 5 forbids for any change that could alter what they see:
// it raises `max_items_per_request`, the most items one request may cover, add to a group
// or receive, from its default of 1000 to 2000, and returns it to its default. A higher
// limit only lets more through: every request another file sends while it is raised is
// taken as it would be at the default, and the web UI sends pieces that are larger but
// never refused. So it runs beside the others.

import { expect } from "@playwright/test";
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
