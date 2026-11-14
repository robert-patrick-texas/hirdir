// The browser scenarios of drafts and of archived items, which release 0.6.0 owes:
//
//   S34  A draft site with draft items is left out of every count until it is made
//        active: the grid, the summary and the tree of places.
//   S35  An archived item is hidden by default, greyed when it is included, still reached
//        by its HID, and its history is intact.
//
// It keeps to the rules of support.ts: an account and names of its own, a region of its
// own, and every grid, report and tree filtered down to this file's items before
// anything is counted.

import { expect, type Locator, type Page } from "@playwright/test";
import { importFile, region, summary } from "./structure";
import { expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const random = mark("x").slice(2);
const suffix = mark("drafts", random);
const upper = random.toUpperCase();

const vendor = `Example Networks ${suffix}`;
const pid = `EN-9300-48P-${suffix}`;
const north = `North ${suffix}`;
const siteName = `Site-N ${suffix}`;
const site = `${north} > ${siteName}`;
const room = `${site} > Room 1`;
// The two switches that are planned with the site, as drafts.
const draftPrefix = `site8-new-${suffix}`;
const drafts = [1, 2].map((place) => `${draftPrefix}-0${place}`) as [string, string];
const ofDrafts = `hostname:prefix:${draftPrefix}`;
// The switch that is archived.
const old = `site8-old-${suffix}-01`;

function gridRow(page: Page, text: string): Locator {
  return page.getByTestId("grid-items").locator("[row-id]", { hasText: text });
}

function treeRow(page: Page, path: string): Locator {
  return page.getByTestId("geography-tree").locator(`tr[data-path="${path}"]`);
}

/** The tree of places, counting this file's draft switches, with drafts or without. */
async function geography(page: Page, withDrafts: boolean) {
  const query = new URLSearchParams({ filter: ofDrafts, ...(withDrafts ? { drafts: "1" } : {}) });
  await page.goto(`./geography?${query.toString()}`);
  await expect(page.getByRole("heading", { level: 1, name: "Geography" })).toBeVisible();
  await expect(page.getByTestId("geography-tree")).toBeVisible();
}

/** Move the item on show to another state, with a reason. */
async function move(page: Page, to: string, reason: string) {
  const form = region(page, "Move to another state");
  await form.getByLabel("Move to").selectOption(to);
  await form.getByLabel("Reason").selectOption({ label: reason });
  await form.getByRole("button", { name: "Move" }).click();
  await expect(page.getByTestId("state")).toHaveText(to);
}

test("a model, a region, a draft site with a room, and three switches are loaded from files", async ({
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
    ["vendor", "pid", "model_name", "type", "support_weight"],
    [[vendor, pid, "Example 9300 48-port", "switch", "1.00"]],
  );
  await importFile(page, "regions", `regions-${suffix}.csv`, ["name"], [[north]]);
  // The site is a draft: it is planned, and not in use yet.
  await importFile(
    page,
    "sites",
    `sites-${suffix}.csv`,
    ["name", "region", "record_status"],
    [[siteName, north, "draft"]],
  );
  await importFile(
    page,
    "locations",
    `locations-${suffix}.csv`,
    ["name", "site", "kind"],
    [["Room 1", site, "room"]],
  );
  // Two draft switches in the room of the draft site, and one that is in service
  // elsewhere, which S35 archives.
  await importFile(
    page,
    "items",
    `items-${suffix}.csv`,
    ["vendor", "pid", "serial_number", "hostname", "lifecycle_state", "location", "record_status"],
    [
      [vendor, pid, `END${upper}01`, drafts[0], "Prod", room, "draft"],
      [vendor, pid, `END${upper}02`, drafts[1], "Prod", room, "draft"],
      [vendor, pid, `END${upper}09`, old, "Prod", "", "active"],
    ],
  );
  await expectClean(page, seen);
});

test("S34: a draft site with draft items is left out of every count until made active", async ({
  page,
  account,
}) => {
  test.setTimeout(240_000);
  const seen = await watch(page.context());
  await signIn(page, account);

  // The grid leaves drafts out until they are asked for, and then shows them greyed.
  await page.goto(`./items?filter=${encodeURIComponent(ofDrafts)}`);
  await expect(page.getByTestId("grid-total")).toHaveText("No items");
  await page.getByLabel("Include drafts").check();
  await expect(page.getByTestId("grid-total")).toHaveText("2 items");
  await expect(gridRow(page, drafts[0])).toHaveClass(/row-dim/);
  await expect(gridRow(page, drafts[1])).toHaveClass(/row-dim/);
  await page.getByLabel("Include drafts").uncheck();
  await expect(page.getByTestId("grid-total")).toHaveText("No items");

  // The summary counts none of them, and both when drafts are asked for.
  await summary(page, ofDrafts);
  await expect(page.getByTestId("total-items")).toHaveText("0");
  await expect(page.getByTestId("total-components")).toHaveText("0");
  await page.getByLabel("Include drafts").check();
  await expect(page.getByTestId("total-items")).toHaveText("2");
  await expect(page.getByTestId("total-components")).toHaveText("2");

  // The tree of places leaves the draft site out, and shows it, with what is in it,
  // when drafts are asked for.
  await geography(page, false);
  await expect(treeRow(page, north)).toBeVisible();
  await expect(treeRow(page, site)).toHaveCount(0);
  await geography(page, true);
  await expect(treeRow(page, site).locator('[data-count="items"]')).toHaveText("2");

  // The site is made active by its own action, which asks first.
  await treeRow(page, site).getByRole("link", { name: siteName, exact: true }).click();
  await expect(page.getByTestId("place-path")).toHaveText(site);
  await region(page, "Make active").getByRole("button", { name: "Make site active" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Make site active" }).click();
  await expect(page.getByText(`${siteName} is active.`)).toBeVisible();
  await expect(region(page, "Make active")).toHaveCount(0);

  // The site is in the tree now. Its two switches are still drafts, and still counted
  // nowhere: a draft item is left out whatever place it is in.
  await geography(page, false);
  await expect(treeRow(page, site).locator('[data-count="items"]')).toHaveText("0");
  await summary(page, ofDrafts);
  await expect(page.getByTestId("total-items")).toHaveText("0");

  // Each switch is made active on its own page, found in the grid with drafts included.
  for (const host of drafts) {
    await page.goto(
      `./items?${new URLSearchParams({ filter: `hostname:eq:${host}`, drafts: "1" }).toString()}`,
    );
    await expect(page.getByLabel("Include drafts")).toBeChecked();
    await page.getByTestId("grid-items").getByRole("link", { name: host, exact: true }).click();
    await expect(page.getByRole("heading", { level: 1, name: host })).toBeVisible();
    const details = region(page, "Details");
    await expect(details.getByLabel("Record status")).toHaveValue("draft");
    await details.getByLabel("Record status").selectOption({ label: "Active" });
    await details.getByRole("button", { name: "Save" }).click();
    await expect(page.getByText("The item was saved.")).toBeVisible();
    await expect(details.getByLabel("Record status")).toHaveValue("active");
  }

  // Made active, they are counted: by the summary, by the tree and by the grid, with
  // no draft asked for.
  await summary(page, ofDrafts);
  await expect(page.getByTestId("total-items")).toHaveText("2");
  await expect(page.getByTestId("total-components")).toHaveText("2");
  await geography(page, false);
  await expect(treeRow(page, site).locator('[data-count="items"]')).toHaveText("2");
  await expect(treeRow(page, site).locator('[data-count="components"]')).toHaveText("2");
  await page.goto(`./items?filter=${encodeURIComponent(ofDrafts)}`);
  await page.getByLabel("Include drafts").uncheck();
  await expect(page.getByTestId("grid-total")).toHaveText("2 items");
  await expect(gridRow(page, drafts[0])).not.toHaveClass(/row-dim/);

  await expectClean(page, seen);
});

test("S35: an archived item is hidden, greyed when included, reached by its HID, with its history", async ({
  page,
  account,
  baseURL,
}) => {
  test.setTimeout(240_000);
  const base = new URL(baseURL ?? "");
  const seen = await watch(page.context());
  await signIn(page, account);
  const only = `hostname:eq:${old}`;

  // The switch leaves service: Pending-Removal, Released, Archived.
  await page.goto(`./items?filter=${encodeURIComponent(only)}`);
  await expect(page.getByTestId("grid-total")).toHaveText("1 item");
  await page.getByTestId("grid-items").getByRole("link", { name: old, exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: old })).toBeVisible();
  const itemPath = new URL(page.url()).pathname;
  await move(page, "Pending-Removal", "Decommissioned");
  await move(page, "Released", "Decommissioned");
  await move(page, "Archived", "Decommissioned");

  // Hidden by default.
  await page.goto(`./items?filter=${encodeURIComponent(only)}`);
  await expect(page.getByTestId("grid-total")).toHaveText("No items");
  // Greyed when it is included.
  await page.getByLabel("Include archived").check();
  await expect(page.getByTestId("grid-total")).toHaveText("1 item");
  await expect(gridRow(page, old)).toHaveClass(/row-dim/);
  await expect(gridRow(page, old).locator('[col-id="lifecycle_state"]')).toHaveText("Archived");
  await page.getByLabel("Include archived").uncheck();
  await expect(page.getByTestId("grid-total")).toHaveText("No items");
  // The summary counts it no longer.
  await summary(page, only);
  await expect(page.getByTestId("total-items")).toHaveText("0");

  // Still reached by its HID, which is in the address of its page.
  await page.goto(`.${itemPath.slice(base.pathname.length - 1)}`);
  await expect(page.getByRole("heading", { level: 1, name: old })).toBeVisible();
  await expect(page.getByTestId("state")).toHaveText("Archived");

  // Its history is intact: how it was made, and each of its three moves, with who made it.
  // The first move gave the reason, which is in its entry.
  await expect(region(page, "History")).toContainText("decommissioned");
  const history = region(page, "History");
  await expect(history.locator('tbody[data-action="create"]')).toHaveCount(1);
  const moves = history.locator('tbody[data-action="transition"]');
  await expect(moves).toHaveCount(3);
  for (const [place, to] of [
    [0, "Archived"],
    [1, "Released"],
    [2, "Pending-Removal"],
  ] as const) {
    await expect(moves.nth(place)).toContainText(account.username);
    await expect(
      moves.nth(place).locator("tr", { hasText: "lifecycle_state" }).locator("td").nth(-1),
    ).toHaveText(to);
  }

  await expectClean(page, seen);
});
