// The browser scenario of links, release 0.7.0 (P-138):
//
//   S46  A location is given two links, a site one and a catalog entry one, each an
//        address and its text: each shows on its record and opens in a new tab with
//        nothing of hirdir's, an item shows the link of its model, a link loaded from a
//        file shows as it was written there, and an address that is no web address is
//        refused with the server's reason.
//
// On the way: the editor of a list of links, which adds, removes and moves them and
// saves them whole; a link with no text, which shows its address; and a region, whose
// link is not the site's: a place inherits none from the places above it.
//
// The file keeps the rules of support.ts: it signs in as an Admin of its own, and its
// mark is in every name it gives a record.

import { expect, type Locator, type Page } from "@playwright/test";
import { importFile, openItem, region } from "./structure";
import { expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const suffix = mark("links");
const vendor = `Example Networks ${suffix}`;
const pid = `EN-9300-48P-${suffix}`;
const regionName = `Links Region ${suffix}`;
const siteName = `Links Site ${suffix}`;
const site = `${regionName} > ${siteName}`;
const roomName = "Room 102";
const room = `${site} > ${roomName}`;
const host = `site9-sw-links-${suffix}`;

// Every address is of the reserved example domains.
const SHEET = { url: `https://www.example.com/${suffix}/datasheet.pdf`, text: "Data sheet" };
const GUIDE = { url: `https://www.example.com/${suffix}/install.html`, text: "Install guide" };
const REGION_PAGE = `https://intranet.example.net/${suffix}/region`;
const SITE_PAGE = { url: `https://intranet.example.net/${suffix}/site`, text: "Site page" };
const PLAN = {
  url: `https://intranet.example.net/${suffix}/room-102/plan.pdf`,
  text: "Floor plan",
};
const RACKS = `http://intranet.example.net/${suffix}/room-102/racks`;

function treeRow(page: Page, path: string): Locator {
  return page.getByTestId("geography-tree").locator(`tr[data-path="${path}"]`);
}

/** The links a record shows, in their order, each as a link of the page. */
function shown(page: Page, testId = "links"): Locator {
  return page.getByTestId(testId).getByRole("link");
}

/** Every link opens in a new tab, and gives the page it opens nothing of hirdir's. */
async function expectSafe(links: Locator) {
  for (const link of await links.all()) {
    await expect(link).toHaveAttribute("target", "_blank");
    await expect(link).toHaveAttribute("rel", "noopener noreferrer");
  }
}

/** Open a place's page from the tree of the Geography page, by its path. */
async function openPlace(page: Page, path: string, name: string) {
  await page.goto("./geography");
  await expect(page.getByRole("heading", { level: 1, name: "Geography" })).toBeVisible();
  const parts = path.split(" > ");
  if (parts.length > 2) {
    // A location is in the inside of its site, which is fetched when it is opened.
    const siteRow = treeRow(page, parts.slice(0, 2).join(" > "));
    await siteRow.getByRole("button", { name: `Open ${parts[1]}` }).click();
  }
  await treeRow(page, path).getByRole("link", { name, exact: true }).click();
  await expect(page.getByTestId("place-path")).toHaveText(path);
}

/** Fill one link of the editor: its address and its text. */
async function fillLink(editor: Locator, number: number, url: string, text: string) {
  const link = editor.getByRole("group", { name: `Link ${number}`, exact: true });
  await link.getByLabel("Address").fill(url);
  await link.getByLabel("Text").fill(text);
}

test("S46: links on a site, a location, a catalog entry and the item of that model", async ({
  page,
  account,
}) => {
  test.setTimeout(240_000);
  const seen = await watch(page.context());
  await signIn(page, account);

  // The model, the places and the item come from files: the link of the model and the
  // link of the region are written in their files as a file writes them.
  await importFile(page, "vendors", `vendors-${suffix}.csv`, ["name"], [[vendor]]);
  await importFile(
    page,
    "catalog_entries",
    `catalog-entries-${suffix}.csv`,
    ["vendor", "pid", "model_name", "type", "links"],
    [[vendor, pid, "Example 9300 48-port", "switch", `${SHEET.text} <${SHEET.url}>`]],
  );
  await importFile(
    page,
    "regions",
    `regions-${suffix}.csv`,
    ["name", "links"],
    [[regionName, `<${REGION_PAGE}>`]],
  );
  await importFile(
    page,
    "sites",
    `sites-${suffix}.csv`,
    ["name", "region"],
    [[siteName, regionName]],
  );
  await importFile(
    page,
    "locations",
    `locations-${suffix}.csv`,
    ["name", "site", "kind"],
    [[roomName, site, "room"]],
  );
  await importFile(
    page,
    "items",
    `items-${suffix}.csv`,
    ["vendor", "pid", "serial_number", "hostname", "location"],
    [[vendor, pid, `ENL${suffix.toUpperCase()}1`, host, room]],
  );

  // The region shows the link of its file: with no text, its address.
  await openPlace(page, regionName, regionName);
  const regionLinks = region(page, "Links");
  await expect(shown(page)).toHaveCount(1);
  await expect(shown(page).first()).toHaveText(REGION_PAGE);
  await expect(shown(page).first()).toHaveAttribute("href", REGION_PAGE);
  await expectSafe(shown(page));
  await expect(regionLinks.getByRole("button", { name: "Change the links" })).toBeVisible();

  // The site has none, its region's not among them, and is given one.
  await openPlace(page, site, siteName);
  const siteLinks = region(page, "Links");
  await expect(siteLinks.getByTestId("links")).toHaveText("This site has no links.");
  await siteLinks.getByRole("button", { name: "Add links" }).click();
  await fillLink(siteLinks, 1, SITE_PAGE.url, SITE_PAGE.text);
  await siteLinks.getByRole("button", { name: "Save the links" }).click();
  await expect(page.getByText("The links were saved.")).toBeVisible();
  await expect(shown(page)).toHaveCount(1);
  await expect(shown(page).first()).toHaveText(SITE_PAGE.text);
  await expect(shown(page).first()).toHaveAttribute("href", SITE_PAGE.url);
  await expectSafe(shown(page));

  // The room is given two, in an order that is then changed, and one that is no web
  // address on the way, which the server refuses, naming it.
  await openPlace(page, room, roomName);
  const roomLinks = region(page, "Links");
  await roomLinks.getByRole("button", { name: "Add links" }).click();
  await fillLink(roomLinks, 1, PLAN.url, PLAN.text);
  await roomLinks.getByRole("button", { name: "Add a link" }).click();
  await fillLink(roomLinks, 2, `ftp://intranet.example.net/${suffix}/racks`, "");
  await roomLinks.getByRole("button", { name: "Save the links" }).click();
  const second = roomLinks.getByRole("group", { name: "Link 2", exact: true });
  await expect(second.getByLabel("Address")).toHaveAttribute("aria-invalid", "true");
  await expect(second).toContainText("link 2: an address that begins with https:// or http://");
  await expect(
    roomLinks.getByRole("group", { name: "Link 1", exact: true }).getByLabel("Address"),
  ).not.toHaveAttribute("aria-invalid", "true");
  // Put right, and moved up to be the first.
  await second.getByLabel("Address").fill(RACKS);
  await second.getByRole("button", { name: "Up" }).click();
  await expect(
    roomLinks.getByRole("group", { name: "Link 1", exact: true }).getByLabel("Address"),
  ).toHaveValue(RACKS);
  // A third is added and taken away again before anything is saved.
  await roomLinks.getByRole("button", { name: "Add a link" }).click();
  await fillLink(roomLinks, 3, GUIDE.url, GUIDE.text);
  await roomLinks
    .getByRole("group", { name: "Link 3", exact: true })
    .getByRole("button", { name: "Remove" })
    .click();
  await expect(roomLinks.getByRole("group", { name: "Link 3", exact: true })).toHaveCount(0);
  await roomLinks.getByRole("button", { name: "Save the links" }).click();
  await expect(page.getByText("The links were saved.")).toBeVisible();
  // In the order given: the one with no text shows its address.
  await expect(shown(page)).toHaveText([RACKS, PLAN.text]);
  await expect(shown(page).nth(1)).toHaveAttribute("href", PLAN.url);
  await expectSafe(shown(page));
  // Read again, the page holds them in that order.
  await page.reload();
  await expect(shown(page)).toHaveText([RACKS, PLAN.text]);

  // The catalog entry shows the link of its file, and is given a second, first.
  await page.goto(`./catalog?filter=${encodeURIComponent(`pid:eq:${pid}`)}`);
  await page.getByTestId("grid-catalog").getByRole("link", { name: pid }).click();
  await expect(page.getByRole("heading", { level: 1, name: `${vendor} ${pid}` })).toBeVisible();
  const entryLinks = region(page, "Links");
  await expect(shown(page)).toHaveText([SHEET.text]);
  await expect(shown(page).first()).toHaveAttribute("href", SHEET.url);
  await entryLinks.getByRole("button", { name: "Change the links" }).click();
  await entryLinks.getByRole("button", { name: "Add a link" }).click();
  await fillLink(entryLinks, 2, GUIDE.url, GUIDE.text);
  await entryLinks
    .getByRole("group", { name: "Link 2", exact: true })
    .getByRole("button", { name: "Up" })
    .click();
  await entryLinks.getByRole("button", { name: "Save the links" }).click();
  await expect(page.getByText("The links were saved.")).toBeVisible();
  await expect(shown(page)).toHaveText([GUIDE.text, SHEET.text]);
  await expectSafe(shown(page));

  // The item shows the links of its model, as what it has from its catalog entry.
  await openItem(page, host);
  const model = page.getByTestId("model-links");
  await expect(model).toHaveAttribute("data-source", "catalog");
  await expect(shown(page, "model-links-list")).toHaveText([GUIDE.text, SHEET.text]);
  await expect(shown(page, "model-links-list").nth(1)).toHaveAttribute("href", SHEET.url);
  await expectSafe(shown(page, "model-links-list"));
  await expect(model).toContainText(`Inherited from the catalog entry ${vendor} ${pid}`);

  await expectClean(page, seen, ["422 PATCH"]);
});
