// 0.9.7, the rows ticked retired at once and those that were a mistake deleted (P-227,
// P-228, P-236):
//
//   Retire, on the lists of items and of groups, for the Inventory role: it asks first
//   and says how many, says what the answer did, and keeps ticked the rows it refused.
//   A View-only person sees no Retire; Inventory sees Retire and no Delete.
//
//   Delete, for an Admin, on the same lists and on the page of an item and of a group: it
//   asks first with what the server's dry run answers, how many will be deleted and which
//   are refused with what depends on each, as links; a reason is typed; a record deleted
//   from its page shows its list with a message, and its page then says it was deleted.
//
// The file keeps the rules of support.ts: an Admin of its own, an Inventory and a
// View-only account of its own, its mark in every name, and every list filtered down to
// its own records before anything is counted.

import { type Browser, expect, type Locator, type Page } from "@playwright/test";
import { importFile } from "./structure";
import { type Account, createAccount, expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const random = mark("x").slice(2);
const suffix = mark("removal", random);
const upper = random.toUpperCase();

const vendor = `Example Networks ${suffix}`;
const pid = `EN-9300-48P-${suffix}`;
const prefix = `site7-sw-rm-${suffix}`;
const hosts = [1, 2, 3, 4, 5].map((place) => `${prefix}-0${place}`);
const groupPrefix = `site7-grp-rm-${suffix}`;
// The fourth is nested in the third, which a deletion of the third alone is refused for.
const groupNames = [1, 2, 3, 4].map((place) => `${groupPrefix}-0${place}`);

function host(at: number): string {
  return hosts[at] ?? "";
}

function groupName(at: number): string {
  return groupNames[at] ?? "";
}

/** The accounts of this file that are not its Admin, made when first asked for. */
const others: { inventory?: Account; viewer?: Account } = {};

async function signInAs(browser: Browser, account: Account) {
  const context = await browser.newContext();
  const page = await context.newPage();
  const seen = await watch(context);
  await signIn(page, account);
  return { context, page, seen };
}

function gridRow(page: Page, grid: string, text: string): Locator {
  return page.getByTestId(grid).locator("[row-id]", { hasText: text });
}

function rowBox(page: Page, grid: string, text: string): Locator {
  return gridRow(page, grid, text).locator(".ag-selection-checkbox input");
}

async function openItems(page: Page, count: number) {
  await page.goto(`./items?filter=${encodeURIComponent(`hostname:prefix:${prefix}`)}`);
  await expect(page.getByTestId("grid-total")).toHaveText(
    `${count} ${count === 1 ? "item" : "items"}`,
  );
}

async function openGroups(page: Page, count: number) {
  await page.goto(`./groups?filter=${encodeURIComponent(`name:prefix:${groupPrefix}`)}`);
  await expect(page.getByTestId("grid-total")).toHaveText(
    `${count} ${count === 1 ? "group" : "groups"}`,
  );
}

test("the switches and the groups of this file are loaded, with an Inventory and a View-only account", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(180_000);
  await signIn(page, account);
  await importFile(page, "vendors", `vendors-${suffix}.csv`, ["name"], [[vendor]]);
  await importFile(
    page,
    "catalog_entries",
    `catalog-entries-${suffix}.csv`,
    ["vendor", "pid", "model_name", "type", "support_weight"],
    [[vendor, pid, "Example 9300 48-port", "switch", "1.00"]],
  );
  await importFile(
    page,
    "items",
    `items-${suffix}.csv`,
    ["vendor", "pid", "serial_number", "hostname"],
    hosts.map((name, place) => [vendor, pid, `ENR${upper}0${place + 1}`, name]),
  );
  await importFile(
    page,
    "device_groups",
    `device-groups-${suffix}.csv`,
    ["name", "type", "parent"],
    groupNames.map((name, place) => [name, "custom", place === 3 ? groupName(2) : ""]),
  );
  others.inventory = await createAccount(request, `e2e-${suffix}-ivy`, "inventory");
  others.viewer = await createAccount(request, `e2e-${suffix}-viewer`, "viewer");
});

test("View-only: the rows are ticked, and no Retire or Delete is offered", async ({ browser }) => {
  const { context, page, seen } = await signInAs(browser, others.viewer as Account);
  await openItems(page, hosts.length);
  await rowBox(page, "grid-items", host(0)).check();
  await expect(page.getByTestId("grid-selected")).toContainText("1 selected");
  await expect(page.getByRole("button", { name: /^Retire/ })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /^Delete/ })).toHaveCount(0);
  await openGroups(page, groupNames.length);
  await rowBox(page, "grid-device-groups", groupName(0)).check();
  await expect(page.getByRole("button", { name: /^Retire/ })).toHaveCount(0);
  await expectClean(page, seen);
  await context.close();
});

test("Inventory: the items ticked are retired at once, after saying how many, and no Delete is offered", async ({
  browser,
}) => {
  const { context, page, seen } = await signInAs(browser, others.inventory as Account);
  await openItems(page, hosts.length);
  await expect(page.getByRole("button", { name: /^Delete/ })).toHaveCount(0);
  const retire = page.getByRole("button", { name: /^Retire( \(|$)/ });
  await expect(retire).toBeDisabled();

  await rowBox(page, "grid-items", host(0)).check();
  await rowBox(page, "grid-items", host(1)).check();
  await expect(retire).toHaveText("Retire (2)");
  await retire.click();
  const dialog = page.getByTestId("removal-dialog");
  await expect(dialog.getByRole("heading", { name: "Retire 2 items?" })).toBeVisible();
  // Cancel retires nothing, and leaves the rows ticked.
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByTestId("grid-selected")).toContainText("2 selected");

  await retire.click();
  await dialog.getByRole("button", { name: "Retire 2 items" }).click();
  await expect(page.getByTestId("removal-outcome")).toHaveText("Retired 2 items.");
  // What is retired is hidden as before, and shown again with archived records.
  await expect(page.getByTestId("grid-total")).toHaveText("3 items");
  await expect(gridRow(page, "grid-items", host(0))).toHaveCount(0);
  await page.getByLabel("Include archived").check();
  await expect(page.getByTestId("grid-total")).toHaveText("5 items");

  // All that match is a count, not particular rows: Retire is not for it.
  await page.getByRole("button", { name: "Select all that match" }).click();
  await expect(retire).toBeDisabled();
  await expect(retire).toHaveText("Retire");
  await page.getByRole("button", { name: "Clear selection" }).click();
  await page.getByLabel("Include archived").uncheck();
  // Nor on an item's page.
  await gridRow(page, "grid-items", host(4))
    .getByRole("link", { name: host(4) })
    .click();
  await expect(page.getByRole("heading", { level: 1, name: host(4) })).toBeVisible();
  await expect(page.getByRole("button", { name: "Retire item" })).toBeVisible();
  await expect(page.getByRole("button", { name: /^Delete/ })).toHaveCount(0);
  await expectClean(page, seen);
  await context.close();
});

test("Inventory: one retired already is counted, and one refused is named with why and stays ticked", async ({
  browser,
}) => {
  const { context, page, seen } = await signInAs(browser, others.inventory as Account);
  await openItems(page, 3);
  await page.getByLabel("Include archived").check();
  await expect(page.getByTestId("grid-total")).toHaveText("5 items");
  // The rules of the server refuse little when an item is retired: the answer is made
  // to refuse the last row ticked, as one that the rules refused, and the others go.
  await page.route("**/api/v1/items/retire", async (route) => {
    const asked = route.request().postDataJSON() as { hids: string[] };
    const refused = asked.hids.at(-1) ?? "";
    const response = await route.fetch({
      postData: JSON.stringify({ hids: asked.hids.slice(0, -1) }),
    });
    const answer = (await response.json()) as { refused: unknown[] };
    answer.refused.push({ hid: refused, label: host(3), detail: "an example refusal" });
    await route.fulfill({ response, json: answer });
  });
  await rowBox(page, "grid-items", host(0)).check();
  await rowBox(page, "grid-items", host(2)).check();
  await rowBox(page, "grid-items", host(3)).check();
  await page.getByRole("button", { name: "Retire (3)" }).click();
  await page.getByTestId("removal-dialog").getByRole("button", { name: "Retire 3 items" }).click();
  const outcome = page.getByTestId("removal-outcome");
  await expect(outcome).toContainText(
    "Retired 1 item. 1 item retired already. 1 item refused, still ticked:",
  );
  await expect(outcome.getByRole("listitem")).toHaveText(`${host(3)}: an example refusal`);
  await expect(outcome.getByRole("link", { name: host(3) })).toBeVisible();
  // The row refused stays ticked, and the others are let go.
  await expect(page.getByTestId("grid-selected")).toContainText("1 selected");
  await expect(rowBox(page, "grid-items", host(3))).toBeChecked();
  await expect(rowBox(page, "grid-items", host(2))).not.toBeChecked();
  await page.getByLabel("Include archived").uncheck();
  await expectClean(page, seen);
  await context.close();
});

test("Inventory: the groups ticked are retired at once", async ({ browser }) => {
  const { context, page, seen } = await signInAs(browser, others.inventory as Account);
  await openGroups(page, groupNames.length);
  await rowBox(page, "grid-device-groups", groupName(0)).check();
  await rowBox(page, "grid-device-groups", groupName(1)).check();
  await page.getByRole("button", { name: "Retire (2)" }).click();
  const dialog = page.getByTestId("removal-dialog");
  await expect(dialog.getByRole("heading", { name: "Retire 2 groups?" })).toBeVisible();
  await dialog.getByRole("button", { name: "Retire 2 groups" }).click();
  await expect(page.getByTestId("removal-outcome")).toHaveText("Retired 2 groups.");
  await expect(page.getByTestId("grid-total")).toHaveText("2 groups");
  await expectClean(page, seen);
  await context.close();
});

test("Admin: the items ticked that were a mistake are deleted, after the dry run and a reason", async ({
  page,
  account,
}) => {
  const seen = await watch(page.context());
  await signIn(page, account);
  await openItems(page, 2);
  await page.getByLabel("Include archived").check();
  await expect(page.getByTestId("grid-total")).toHaveText("5 items");
  await rowBox(page, "grid-items", host(0)).check();
  await rowBox(page, "grid-items", host(1)).check();
  await page.getByRole("button", { name: "Delete (2)" }).click();
  const dialog = page.getByTestId("removal-dialog");
  await expect(dialog.getByRole("heading", { name: "Delete 2 items?" })).toBeVisible();
  await expect(dialog.getByTestId("delete-said")).toHaveText("2 items will be deleted.");
  const go = dialog.getByRole("button", { name: "Delete 2 items" });
  // A reason is typed first, and spaces alone are none.
  await expect(go).toBeDisabled();
  await dialog.getByLabel("Reason").fill("   ");
  await expect(go).toBeDisabled();
  await dialog.getByLabel("Reason").fill(`a wrong file ${suffix}`);
  await go.click();
  await expect(page.getByTestId("removal-outcome")).toHaveText("Deleted 2 items.");
  await expect(page.getByTestId("grid-total")).toHaveText("3 items");
  await expect(gridRow(page, "grid-items", host(0))).toHaveCount(0);
  await page.getByLabel("Include archived").uncheck();
  await expectClean(page, seen);
});

test("Admin: an item deleted from its page shows the list, saying so, and its page then says it was deleted", async ({
  page,
  account,
}) => {
  const seen = await watch(page.context());
  await signIn(page, account);
  await openItems(page, 2);
  await gridRow(page, "grid-items", host(4))
    .getByRole("link", { name: host(4) })
    .click();
  await expect(page.getByRole("heading", { level: 1, name: host(4) })).toBeVisible();
  const address = page.url();
  await page.getByRole("button", { name: "Delete item" }).click();
  const dialog = page.getByTestId("removal-dialog");
  await expect(dialog.getByTestId("delete-said")).toHaveText("1 item will be deleted.");
  await dialog.getByLabel("Reason").fill(`a wrong file ${suffix}`);
  await dialog.getByRole("button", { name: "Delete 1 item" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Items" })).toBeVisible();
  expect(new URL(page.url()).pathname.endsWith("/items")).toBe(true);
  await expect(page.getByText(`Item ${host(4)} was deleted.`)).toBeVisible();

  // The page of the HID says what the server's 404 says: deleted, when, by whom, why.
  await page.goto(address);
  const problem = page.locator(".alert-error");
  await expect(problem).toContainText("deleted");
  await expect(problem).toContainText(account.username);
  await expect(page.getByTestId("deleted-reason")).toHaveText(
    `The reason given: a wrong file ${suffix}`,
  );
  await expectClean(page, seen, ["404 GET"]);
});

test("Admin: a group that a group is nested in is refused, naming it as a link, and stays ticked", async ({
  page,
  account,
}) => {
  const seen = await watch(page.context());
  await signIn(page, account);
  await openGroups(page, 2);
  await page.getByLabel("Include retired").check();
  await expect(page.getByTestId("grid-total")).toHaveText("4 groups");
  const dialog = page.getByTestId("removal-dialog");

  // The third alone: the fourth is nested in it, and nothing can be deleted.
  await rowBox(page, "grid-device-groups", groupName(2)).check();
  await page.getByRole("button", { name: "Delete (1)" }).click();
  await expect(dialog.getByTestId("delete-said")).toHaveText(
    "No groups can be deleted. 1 group refused, while what depends on each is there:",
  );
  const refused = dialog.getByTestId("delete-refused").getByRole("listitem");
  await expect(refused).toContainText(groupName(2));
  await expect(refused.getByRole("link", { name: groupName(3) })).toBeVisible();
  await expect(dialog.getByLabel("Reason")).toHaveCount(0);
  await expect(dialog.getByRole("button", { name: /^Delete \d/ })).toBeDisabled();
  await dialog.getByRole("button", { name: "Cancel" }).click();

  // With a retired group beside it: that one is deleted, and the third stays ticked.
  await rowBox(page, "grid-device-groups", groupName(0)).check();
  await page.getByRole("button", { name: "Delete (2)" }).click();
  await expect(dialog.getByTestId("delete-said")).toHaveText(
    "1 group will be deleted. 1 group refused, while what depends on each is there:",
  );
  await dialog.getByLabel("Reason").fill(`a wrong file ${suffix}`);
  await dialog.getByRole("button", { name: "Delete 1 group" }).click();
  const outcome = page.getByTestId("removal-outcome");
  await expect(outcome).toContainText("Deleted 1 group. 1 group refused, still ticked:");
  await expect(outcome.getByRole("link", { name: groupName(3) })).toBeVisible();
  await expect(page.getByTestId("grid-total")).toHaveText("3 groups");
  await expect(page.getByTestId("grid-selected")).toContainText("1 selected");
  await expect(rowBox(page, "grid-device-groups", groupName(2))).toBeChecked();
  await page.getByLabel("Include retired").uncheck();
  await expectClean(page, seen);
});

test("Admin: a group deleted from its page shows the list of groups, saying so", async ({
  page,
  account,
}) => {
  const seen = await watch(page.context());
  await signIn(page, account);
  await openGroups(page, 2);
  await gridRow(page, "grid-device-groups", groupName(3))
    .getByRole("link", { name: groupName(3) })
    .click();
  await expect(page.getByRole("heading", { level: 1, name: groupName(3) })).toBeVisible();
  await page.getByRole("button", { name: "Delete group" }).click();
  const dialog = page.getByTestId("removal-dialog");
  await expect(dialog.getByTestId("delete-said")).toHaveText("1 group will be deleted.");
  await dialog.getByLabel("Reason").fill(`a wrong file ${suffix}`);
  await dialog.getByRole("button", { name: "Delete 1 group" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Groups" })).toBeVisible();
  await expect(page.getByText(`Group ${groupName(3)} was deleted.`)).toBeVisible();
  await expectClean(page, seen);
});
