// 0.9.7: every value of a list that names another record is a link (P-232), the stack of
// an item first: in the colour of the text around it, underlined under the pointer and
// with the keyboard's focus, reached by the keyboard as the name is, and pressed without
// selecting the row. What is copied is the text, as before.
//
// This file loads a model, an owner and a switch of its own, makes a stack of it, and
// reads the item list filtered down to that switch.

import { randomBytes } from "node:crypto";
import { expect, type Locator, type Page } from "@playwright/test";
import { importFile, main, pick, region } from "./structure";
import { expectClean, mark, signIn, test, watch } from "./support";

const random = randomBytes(3).toString("hex");
const suffix = mark("value-links", random);
const vendor = `Example Networks ${suffix}`;
const pid = `EN-4800-${suffix}`;
const owner = `Network Engineering ${suffix}`;
const host = `site9-sw-links-${suffix}-01`;
const stack = `site9-sw-stack-${suffix}`;

const HID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";

/** The item list, filtered down to the switch. */
async function openList(page: Page): Promise<Locator> {
  await page.goto(`./items?filter=${encodeURIComponent(`hostname:eq:${host}`)}`);
  const grid = page.getByTestId("grid-items");
  // The one row there is: its cells are found by their column.
  await expect(grid.locator('[role="gridcell"][col-id="stack"]', { hasText: stack })).toHaveCount(
    1,
    { timeout: 20_000 },
  );
  return grid;
}

/** How a link is drawn: its colour and underline, and those of the text of its cell. */
function looks(link: Locator) {
  return link.evaluate((element) => {
    const cell = element.closest(".ag-cell") as HTMLElement;
    return {
      colour: getComputedStyle(element).color,
      cellColour: getComputedStyle(cell).color,
      underline: getComputedStyle(element).textDecorationLine,
    };
  });
}

test("a stack is made of a switch of this file's own", async ({ page, account }) => {
  test.setTimeout(180_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  await importFile(
    page,
    "catalog_entries",
    `catalog-entries-${suffix}.csv`,
    ["vendor", "pid", "model_name", "type"],
    [[vendor, pid, "Example 4800 48-port", "switch"]],
  );
  await importFile(
    page,
    "owners",
    `owners-${suffix}.csv`,
    ["label", "organization"],
    [[owner, "Example Operations"]],
  );
  await importFile(
    page,
    "items",
    `items-${suffix}.csv`,
    ["vendor", "pid", "serial_number", "hostname", "lifecycle_state", "owner"],
    [[vendor, pid, `ENL${suffix.toUpperCase()}01`, host, "Prod", owner]],
  );
  await main(page).getByRole("link", { name: "Groups" }).click();
  await page.getByRole("button", { name: "New group" }).click();
  const form = region(page, "New group");
  await form.getByLabel("Name (required)").fill(stack);
  await form.getByLabel("Type").selectOption("stack");
  await pick(form, "Find an item to add", host, host);
  await form.getByRole("button", { name: "Create group" }).click();
  await expect(page.getByRole("heading", { level: 1, name: stack })).toBeVisible();
  await expectClean(page, seen);
});

test("the stack of an item is a link in the colour of its text, underlined under the pointer", async ({
  page,
  account,
}) => {
  const seen = await watch(page.context());
  await signIn(page, account);
  const grid = await openList(page);
  const link = grid
    .locator('[role="gridcell"][col-id="stack"]')
    .getByRole("link", { name: `${stack} #1` });
  await expect(link).toBeVisible();
  // Under whatever prefix the app is served at, the address ends with the stack's own.
  await expect(link).toHaveAttribute("href", new RegExp(`/groups/${HID}$`));
  await page.mouse.move(0, 0);
  const still = await looks(link);
  expect(still.colour).toBe(still.cellColour);
  expect(still.underline).toBe("none");
  await link.hover();
  expect((await looks(link)).underline).toBe("underline");

  // The other values of the row that name a record lead to theirs, in the same style
  // (the vendor stands beyond the window, where the grid draws no cell).
  for (const [column, name, path] of [
    ["catalog.pid", pid, `/catalog/${HID}`],
    ["owner.label", owner, `/owners/${HID}`],
  ] as const) {
    const other = grid.locator(`[role="gridcell"][col-id="${column}"]`).getByRole("link", { name });
    await expect(other).toHaveAttribute("href", new RegExp(`${path}$`));
    await expect(other).toHaveClass(/value-link/);
  }
  // The name that opens the row's own record stays the link it is.
  await expect(
    grid.locator('[role="gridcell"][col-id="name"]').getByRole("link", { name: host }),
  ).not.toHaveClass(/value-link/);
  await expectClean(page, seen);
});

test("a press on the stack opens it and selects no row, and a press with Ctrl opens a tab", async ({
  page,
  account,
}) => {
  const seen = await watch(page.context());
  await signIn(page, account);
  const grid = await openList(page);
  const link = grid
    .locator('[role="gridcell"][col-id="stack"]')
    .getByRole("link", { name: `${stack} #1` });
  const tab = page.context().waitForEvent("page");
  await link.click({ modifiers: ["ControlOrMeta"] });
  const opened = await tab;
  await opened.close();
  await expect(grid.locator(".ag-row-selected")).toHaveCount(0);
  await expect(page.getByTestId("grid-selected")).toHaveCount(0);

  const href = await link.evaluate(
    (element) => new URL((element as HTMLAnchorElement).href).pathname,
  );
  await link.click();
  await expect(page.getByRole("heading", { level: 1, name: stack })).toBeVisible();
  expect(new URL(page.url()).pathname).toBe(href);
  await expectClean(page, seen);
});

test("the keyboard reaches the stack as it reaches the name, and Enter opens it", async ({
  page,
  account,
}) => {
  const seen = await watch(page.context());
  await signIn(page, account);
  const grid = await openList(page);
  // The cell of the name has the focus; the stack is the next to the right.
  await grid.locator('[role="gridcell"][col-id="name"]').focus();
  await page.keyboard.press("ArrowRight");
  const cell = grid.locator('[role="gridcell"][col-id="stack"]');
  await expect(cell).toHaveClass(/ag-cell-focus/);
  const link = cell.getByRole("link", { name: `${stack} #1` });
  expect((await looks(link)).underline).toBe("underline");
  // Tab does not stop at it: it is in the grid's order, not the page's.
  await expect(link).toHaveAttribute("tabindex", "-1");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { level: 1, name: stack })).toBeVisible();
  await expectClean(page, seen);
});

test("a copied row holds the text of its values, as before", async ({
  page,
  browserName,
  account,
}) => {
  test.skip(browserName !== "chromium", "reading the clipboard back needs Chromium's permission");
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
  const seen = await watch(page.context());
  await signIn(page, account);
  const grid = await openList(page);
  await grid.locator('[role="gridcell"][col-id="serial_number"]').click();
  await expect(page.getByTestId("grid-selected")).toContainText("1 selected");
  await page.getByRole("button", { name: "Copy", exact: true }).click();
  await expect(page.getByText("Copied 1 item to the clipboard, with a header row.")).toBeVisible();
  const copied = await page.evaluate(() => navigator.clipboard.readText());
  for (const text of [host, pid, vendor, owner]) expect(copied).toContain(text);
  expect(copied).not.toMatch(/<a|href=/);
  await expectClean(page, seen);
});
