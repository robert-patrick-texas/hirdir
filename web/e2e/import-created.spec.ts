// 0.9.7, the records an import made (P-234): a past import lists them, a row of the file
// each, with its kind, its name as a link and what it is now, and after them the vendor
// and the catalog entry it made because a row named them. For an import of items the
// rows are ticked: Inventory retires them, and an Admin deletes them after the dry run
// and a reason, a deleted one then named in plain words. View-only ticks nothing.
//
// The file keeps the rules of support.ts: an Admin of its own, an Inventory and a
// View-only account of its own, its mark in every name, and the import found by its own
// address.

import { type Browser, expect, type Locator, type Page } from "@playwright/test";
import { importFile } from "./structure";
import { type Account, createAccount, expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const random = mark("x").slice(2);
const suffix = mark("import-created", random);
const upper = random.toUpperCase();

// Named by the rows alone: the import makes them for the rows.
const vendor = `Example Wrongfile ${suffix}`;
const pid = `EW-1000-${suffix}`;
const prefix = `site9-sw-wrong-${suffix}`;
const hosts = [1, 2, 3].map((place) => `${prefix}-0${place}`);

function host(at: number): string {
  return hosts[at] ?? "";
}

const others: { inventory?: Account; viewer?: Account } = {};
let address = "";

async function signInAs(browser: Browser, account: Account) {
  const context = await browser.newContext();
  const page = await context.newPage();
  const seen = await watch(context);
  await signIn(page, account);
  return { context, page, seen };
}

function made(page: Page): Locator {
  return page.getByTestId("import-created");
}

function madeRow(page: Page, text: string): Locator {
  return made(page).getByTestId("import-created-rows").locator("tbody tr", { hasText: text });
}

async function openImport(page: Page) {
  await page.goto(address);
  await expect(page.getByTestId("import-job")).toHaveAttribute("data-status", "applied");
  await expect(made(page).getByTestId("import-created-rows")).toBeVisible();
}

test("a file of three switches of a model and a vendor it names is imported, and lists what it made", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(120_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  await importFile(
    page,
    "items",
    `items-${suffix}.csv`,
    ["vendor", "pid", "serial_number", "hostname"],
    hosts.map((name, place) => [vendor, pid, `EWX${upper}0${place + 1}`, name]),
  );
  address = page.url();
  const rows = made(page).getByTestId("import-created-rows").locator("tbody tr");
  await expect(rows).toHaveCount(3);
  const first = madeRow(page, host(0));
  await expect(first.locator("td").nth(1)).toHaveText("1");
  await expect(first.locator("td").nth(2)).toHaveText("item");
  await expect(first.getByRole("link", { name: host(0) })).toBeVisible();
  await expect(first.locator("td").nth(4)).toHaveText("Active");
  const also = made(page).getByTestId("import-created-also");
  // The catalog entry is known by its vendor and its PID.
  await expect(also.getByRole("link", { name: vendor, exact: true })).toBeVisible();
  await expect(also.getByRole("link", { name: new RegExp(pid) })).toBeVisible();
  others.inventory = await createAccount(request, `e2e-${suffix}-ivy`, "inventory");
  others.viewer = await createAccount(request, `e2e-${suffix}-viewer`, "viewer");
  await expectClean(page, seen);
});

test("View-only: the list is read, and nothing is ticked or offered", async ({ browser }) => {
  const { context, page, seen } = await signInAs(browser, others.viewer as Account);
  await openImport(page);
  await expect(made(page).getByRole("checkbox")).toHaveCount(0);
  await expect(made(page).getByRole("button", { name: /^Retire/ })).toHaveCount(0);
  await expect(made(page).getByRole("button", { name: /^Delete/ })).toHaveCount(0);
  await expectClean(page, seen);
  await context.close();
});

test("Inventory: the rows ticked are retired, and no Delete is offered", async ({ browser }) => {
  const { context, page, seen } = await signInAs(browser, others.inventory as Account);
  await openImport(page);
  await expect(made(page).getByRole("button", { name: /^Delete/ })).toHaveCount(0);
  const retire = made(page).getByRole("button", { name: /^Retire/ });
  await expect(retire).toBeDisabled();
  await made(page).getByRole("checkbox", { name: "Tick row 1" }).check();
  await made(page).getByRole("checkbox", { name: "Tick row 2" }).check();
  await expect(retire).toHaveText("Retire (2)");
  await retire.click();
  await page.getByTestId("removal-dialog").getByRole("button", { name: "Retire 2 items" }).click();
  await expect(made(page).getByTestId("removal-outcome")).toHaveText("Retired 2 items.");
  await expect(madeRow(page, host(0)).locator("td").nth(4)).toHaveText("Retired");
  await expect(madeRow(page, host(1)).locator("td").nth(4)).toHaveText("Retired");
  await expect(madeRow(page, host(2)).locator("td").nth(4)).toHaveText("Active");
  await expect(retire).toHaveText("Retire");
  await expectClean(page, seen);
  await context.close();
});

test("Admin: the rows ticked are deleted after the dry run and a reason, and named in plain words", async ({
  page,
  account,
}) => {
  const seen = await watch(page.context());
  await signIn(page, account);
  await openImport(page);
  // The box in the heading ticks every row of the page.
  await made(page).getByRole("checkbox", { name: "Every row of this page" }).check();
  await made(page).getByRole("button", { name: "Delete (3)" }).click();
  const dialog = page.getByTestId("removal-dialog");
  await expect(dialog.getByTestId("delete-said")).toHaveText("3 items will be deleted.");
  await dialog.getByLabel("Reason").fill(`a wrong file ${suffix}`);
  await dialog.getByRole("button", { name: "Delete 3 items" }).click();
  await expect(made(page).getByTestId("removal-outcome")).toHaveText("Deleted 3 items.");
  const first = madeRow(page, host(0));
  await expect(first.locator("td").nth(4)).toHaveText("Deleted");
  await expect(first.getByRole("link")).toHaveCount(0);
  await expect(first.getByRole("checkbox")).toHaveCount(0);
  await expectClean(page, seen);
});

test("Admin: more than 1,000 ticked, Retire and Delete say they take 1,000 at a time and send nothing", async ({
  page,
  account,
}) => {
  const seen = await watch(page.context());
  await signIn(page, account);
  // An import that made 1,001 items is a large file to load beside the other files: its
  // list is answered here, as the server writes it, with invented records.
  await page.route("**/api/v1/imports/*/created?*", async (route) => {
    const items = Array.from({ length: 1001 }, (_, at) => ({
      row: at + 1,
      record_type: "item",
      record_hid: `0193a1f4-0000-7000-8000-${String(at).padStart(12, "0")}`,
      label: `${prefix}-many-${at + 1}`,
      state: "active",
    }));
    await route.fulfill({ json: { total: 1001, limit: 100, offset: 0, items, also: [] } });
  });
  const sent: string[] = [];
  page.on("request", (request) => {
    if (/\/(retire|delete)$/.test(request.url())) sent.push(request.url());
  });
  await page.goto(address);
  await expect(made(page).getByTestId("import-created-rows")).toBeVisible();
  await made(page).getByRole("checkbox", { name: "Every row of this page" }).check();
  await expect(made(page).getByTestId("import-created-too-many")).toHaveText(
    "Retire and Delete take at most 1,000 rows at a time, and 1,001 are ticked: untick some first.",
  );
  await expect(made(page).getByRole("button", { name: "Retire (1,001)" })).toBeDisabled();
  await expect(made(page).getByRole("button", { name: "Delete (1,001)" })).toBeDisabled();
  await made(page).getByRole("checkbox", { name: "Tick row 1", exact: true }).uncheck();
  await expect(made(page).getByTestId("import-created-too-many")).toHaveCount(0);
  await expect(made(page).getByRole("button", { name: "Retire (1,000)" })).toBeEnabled();
  expect(sent).toEqual([]);
  await expectClean(page, seen);
});
