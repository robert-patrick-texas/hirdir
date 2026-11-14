// The browser scenarios of release 0.5.0, places and people: what a person does in S24
// to S28, in small.
//
//   S24  Americas > Central > Site-2 > Building 1 > Room 102 is laid out on the Geography
//        page, items are put there, and the tree shows the paths and the counts at every
//        level, with the items that are nowhere beneath, so that the numbers add up.
//   S25  A technical contact on the region and a shipping contact on the site: the room
//        shows both, each with the level it came from, in the lighter style.
//   S26  The technical contact is overridden on Building 1, then the one on the region is
//        changed: Room 102 keeps the building's, a room in another building shows the
//        new one. A level that says "none here" stops the looking further up.
//   S27  Site-2 is moved to another region: the paths, what is inherited and the counts
//        follow, and the items are the records they were.
//   S28  An item is given to an owner outside the team with no reason, which is refused,
//        then with one, and is marked as an exception.
//
// On the way: the location half of S18, a minor item that is where the item it is in is;
// the Location and Site columns of the item grid; a location chosen by searching, in the
// form of an item, of a device group and of a bulk edit; the reports by site and by
// region; the people of an owner; the six new kinds of record on the Import page.
//
// The file keeps the rules of support.ts. It signs in as an Admin of its own, and its
// mark is in every name it gives a record: the regions, the site and its code, the
// locations, the hostnames, the contacts, the owner, the group and the files it loads.
// Every count is read through a filter that keeps this file's items and no others, the
// tree's among them: the tree's totals and the items that are nowhere are then of those
// items, never of the whole inventory. Nothing is changed that another file reads: no
// setting, no list of choices, no account. The addresses are of example.net and the
// numbers of the range kept for fiction. The scenarios build on one another and run in
// order: the later ones use the places and the people the earlier ones made.

import type { Locator, Page } from "@playwright/test";
import { expect } from "@playwright/test";
import { count, importFile, main, openItem, region } from "./structure";
import { expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const id = mark("geography");

// The places, each named with the mark, and the paths the server works out for them.
const americasName = `Americas ${id}`;
const centralName = `Central ${id}`;
const eastName = `East ${id}`;
const siteName = `Site-2 ${id}`;
const buildingName = `Building 1 ${id}`;
const roomName = `Room 102 ${id}`;
const otherBuildingName = `Building 2 ${id}`;
const otherRoomName = `Room 201 ${id}`;
const path = (...names: string[]) => names.join(" > ");
const americas = americasName;
const central = path(americas, centralName);
const east = path(americas, eastName);
// The code of a site is unique among all sites, and is what a location is searched by.
const siteCode = `S2-${id}`;
const site = path(central, siteName);
const building = path(site, buildingName);
const room = path(building, roomName);
const otherBuilding = path(site, otherBuildingName);
const otherRoom = path(otherBuilding, otherRoomName);
const movedSite = path(east, siteName);
const movedRoom = path(movedSite, buildingName, roomName);
const movedOtherRoom = path(movedSite, otherBuildingName, otherRoomName);

// The items, and the filter that keeps them and no others.
const prefix = `${id}-`;
const filter = `hostname:prefix:${prefix}`;
const first = `${prefix}sw-01`;
const second = `${prefix}sw-02`;
const nowhere = `${prefix}sw-03`;
const fourth = `${prefix}sw-04`;
const supply = `${prefix}sw-01-ps-a`;
const group = `${prefix}closet`;

// The people.
const dana = `Dana Whitfield ${id}`;
const danaMail = `dana.whitfield.${id}@example.net`;
const receiving = `Receiving ${id}`;
const receivingMail = `receiving.${id}@example.net`;
const lee = `Lee Okafor ${id}`;
const leeMail = `lee.okafor.${id}@example.net`;
const priya = `Priya Raman ${id}`;
const priyaMail = `priya.raman.${id}@example.net`;
const facilities = `Campus Facilities ${id}`;

// The places as they are made: the address of the page of each, by its path.
const pages = new Map<string, string>();

/** A contact as a form offers it: its name, and its address beside it. */
function offered(name: string, mail: string): string {
  return `${name} (${mail})`;
}

/** The Geography page, counting this file's items only, with one place chosen or none. */
async function geography(page: Page, place = "") {
  const address = place === "" ? "./geography" : pages.get(place);
  expect(address, `the page of ${place}`).toBeDefined();
  await page.goto(`${address}?${new URLSearchParams({ filter }).toString()}`);
  await expect(page.getByRole("heading", { level: 1, name: "Geography" })).toBeVisible();
  await expect(page.getByTestId("geography-tree")).toBeVisible();
  if (place !== "") await expect(page.getByTestId("place-path")).toHaveText(place);
}

/** The row of one place in the tree, by its path. */
function treeRow(page: Page, place: string): Locator {
  return page.getByTestId("geography-tree").locator(`tr[data-path="${place}"]`);
}

/** See what the tree counts at or beneath a place: its items, and the components among them. */
async function expectCounts(row: Locator, items: number, components: number) {
  await expect(row.locator('[data-count="items"]')).toHaveText(String(items));
  await expect(row.locator('[data-count="components"]')).toHaveText(String(components));
}

/** Show the inside of the site in the tree, if it is not on show yet. */
async function openSite(page: Page, place: string) {
  const open = treeRow(page, place).getByRole("button", { name: `Open ${siteName}` });
  if ((await open.count()) > 0) await open.click();
  await expect(
    treeRow(page, place).getByRole("button", { name: `Close ${siteName}` }),
  ).toBeVisible();
}

/**
 * Make a place with one of the buttons of the page, and remember the address of its
 * page under its path.
 */
async function newPlace(
  page: Page,
  button: string,
  what: "region" | "site" | "location",
  place: string,
  more: { code?: string; kind?: string } = {},
) {
  await page.getByRole("button", { name: button, exact: true }).click();
  const form = region(page, `New ${what}`);
  await form.getByLabel("Name (required)").fill(place.split(" > ").at(-1) ?? "");
  if (more.code) await form.getByLabel("Code", { exact: true }).fill(more.code);
  if (more.kind) await form.getByLabel("Kind").selectOption({ label: more.kind });
  await form.getByRole("button", { name: `Create ${what}` }).click();
  // The page goes to the new place, which shows the path the server worked out.
  await expect(page.getByTestId("place-path")).toHaveText(place);
  await expect(page.getByTestId("place")).toHaveAttribute("data-level", what);
  pages.set(place, `.${new URL(page.url()).pathname.replace(/^.*(?=\/geography\/)/, "")}`);
}

/** Assign a contact to the place on show, in a role. */
async function assign(page: Page, role: string, contact: string, name: string) {
  const form = region(page, "Assign a contact");
  await form.getByLabel("Role").selectOption({ label: role });
  await form.getByLabel("Contact", { exact: true }).selectOption({ label: contact });
  await form.getByRole("button", { name: "Assign contact" }).click();
  await expect(page.getByText(`${name} is now a ${role} contact of`)).toBeVisible();
}

/** The row of one role in what the place on show has in force. */
function inForce(page: Page, role: string): Locator {
  return page.getByTestId("in-force-contacts").locator(`tr[data-role="${role}"]`);
}

/** Search for a location in a form's Location field, and choose it by its path. */
async function chooseLocation(form: Locator, typed: string, place: string, label = "Location") {
  await form.getByLabel(label, { exact: true }).fill(typed);
  await form
    .getByRole("list", { name: "Locations that match" })
    .getByRole("button", { name: place, exact: true })
    .click();
}

test("S24: the places are laid out, and the tree counts what is at or beneath each", async ({
  page,
  account,
}) => {
  test.setTimeout(180_000);
  const seen = await watch(page.context());
  await signIn(page, account);

  // Geography has an entry of its own in the navigation.
  await main(page).getByRole("link", { name: "Geography" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Geography" })).toBeVisible();
  await expect(page.getByTestId("geography-tree")).toBeVisible();
  await expect(page.getByTestId("no-place")).toBeVisible();

  // A region at the top, a region within it, a site in that, and two locations, one
  // within the other. Each is made where it belongs, and shows its path at once.
  await newPlace(page, "New region", "region", americas);
  await expect(page.getByTestId("place-facts")).toContainText("None: a region at the top");
  await newPlace(page, "New region in it", "region", central);
  await newPlace(page, "New site in it", "site", site, { code: siteCode });
  await newPlace(page, "New location in it", "location", building, { kind: "Building" });
  await newPlace(page, "New location in it", "location", room, { kind: "Room" });
  await expect(page.getByTestId("place-facts")).toContainText("Room");
  // The tree shows them where they are: the site was opened as its room was chosen.
  for (const path of [americas, central, site, building, room]) {
    await expect(treeRow(page, path)).toBeVisible();
  }
  await expect(treeRow(page, room)).toHaveAttribute("aria-current", "true");
  await expect(treeRow(page, site)).toContainText(siteCode);

  // A name that is taken beside it is refused as the server says it, at its field.
  await geography(page, central);
  await page.getByRole("button", { name: "New site in it", exact: true }).click();
  const twin = region(page, "New site");
  await twin.getByLabel("Name (required)").fill(siteName);
  await twin.getByRole("button", { name: "Create site" }).click();
  await expect(twin.locator('.alert-error[data-status="409"]')).toBeVisible();
  await expect(twin.getByLabel("Name (required)")).toHaveAttribute("aria-invalid", "true");
  await expect(twin.locator(".field-error")).toContainText("a site there has it");
  await twin.getByRole("button", { name: "Cancel" }).click();

  // Items are put there by a file, which names a location by its path. One is nowhere.
  await importFile(
    page,
    "items",
    `items-${id}.csv`,
    ["hostname", "location"],
    [
      [first, room],
      [second, room],
      [nowhere, ""],
    ],
  );

  // A minor item is where the item it is in is: nothing is copied down to it.
  await openItem(page, first);
  await expect(page.getByTestId("location")).toContainText(room);
  await expect(page.getByTestId("location")).toHaveAttribute("data-source", "own");
  await expect(page.getByTestId("site")).toHaveText(siteName);
  await region(page, "Minor items").getByRole("button", { name: "Add a minor item" }).click();
  const minor = region(page, "New minor item");
  await minor.getByLabel("Hostname").fill(supply);
  await minor.getByLabel("Position").fill("PS-A");
  await expect(minor.getByTestId("chosen-location_hid")).toHaveText("Where the item it is in is");
  await minor.getByRole("button", { name: "Create minor item" }).click();
  await expect(page.getByText(`${supply} was added to ${first}.`)).toBeVisible();
  const where = page
    .getByTestId("minor-items")
    .locator("tbody tr", { hasText: supply })
    .locator("td[data-source]")
    .nth(2);
  await expect(where).toHaveText(roomName);
  await expect(where).toHaveAttribute("data-source", "parent_item");
  await expect(where).toHaveClass(/inherited/);

  // The tree, counting this file's items: the regions and the site come at once, and
  // the inside of the site is fetched when it is opened.
  await geography(page);
  await expectCounts(treeRow(page, americas), 3, 2);
  await expectCounts(treeRow(page, central), 3, 2);
  await expectCounts(treeRow(page, site), 3, 2);
  await expect(treeRow(page, building)).toHaveCount(0);
  const inside = page.waitForRequest(
    (request) => request.url().includes("/geography/tree") && request.url().includes("root="),
  );
  await openSite(page, site);
  expect(new URL((await inside).url()).searchParams.get("root")).toBe(
    (pages.get(site) ?? "").split("/").at(-1),
  );
  await expectCounts(treeRow(page, building), 3, 2);
  await expectCounts(treeRow(page, room), 3, 2);
  // The item that is nowhere is beneath the tree, and the numbers add up.
  const tree = page.getByTestId("geography-tree");
  await expectCounts(tree.locator('tr[data-row="unplaced"]'), 1, 1);
  await expectCounts(tree.locator('tr[data-row="totals"]'), 4, 3);
  await expect(tree.locator('tr[data-row="hidden"]')).toHaveCount(0);
  // A site is closed again, and a region too: what is in it leaves the tree.
  await treeRow(page, site)
    .getByRole("button", { name: `Close ${siteName}` })
    .click();
  await expect(treeRow(page, building)).toHaveCount(0);
  await treeRow(page, central)
    .getByRole("button", { name: `Close ${centralName}` })
    .click();
  await expect(treeRow(page, site)).toHaveCount(0);
  await treeRow(page, central)
    .getByRole("button", { name: `Open ${centralName}` })
    .click();
  await expect(treeRow(page, site)).toBeVisible();

  // From a place, the way to the items within it: the item grid, filtered by the server.
  await geography(page, room);
  const hid = (pages.get(room) ?? "").split("/").at(-1);
  await page.getByRole("link", { name: "Items within it, in the grid of items" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Items" })).toBeVisible();
  await expect(page.getByLabel("Filter", { exact: true })).toHaveValue(`location:within:${hid}`);
  await expect(page.getByTestId("grid-total")).toHaveText("3 items");

  // Location and Site are columns of the grid, hidden until they are asked for. The
  // location is the one in force, lighter where it comes from the item above.
  const grid = page.getByTestId("grid-items");
  await expect(grid.locator('[role="columnheader"][col-id="location.name"]')).toHaveCount(0);
  await expect(grid.locator('[role="columnheader"][col-id="site"]')).toHaveCount(0);
  await page.getByText("Columns", { exact: true }).click();
  const columns = page.getByRole("group", { name: "Columns to show" });
  await expect(columns.getByLabel("Location", { exact: true })).not.toBeChecked();
  await expect(columns.getByLabel("Site", { exact: true })).not.toBeChecked();
  await columns.getByLabel("Location", { exact: true }).check();
  await columns.getByLabel("Site", { exact: true }).check();
  // The grid draws only the columns in view: room is made for the ones looked at here.
  for (const column of ["Vendor", "PID", "Serial number", "Health", "Tags", "LDoS"]) {
    await columns.getByLabel(column, { exact: true }).uncheck();
  }
  await page.getByText("Columns", { exact: true }).click();
  const gridRow = (host: string) => grid.locator("[row-id]", { hasText: host });
  await expect(gridRow(second).locator('[col-id="location.name"]')).toHaveText(roomName);
  await expect(gridRow(second).locator('[col-id="location.name"]')).not.toHaveClass(
    /cell-inherited/,
  );
  await expect(gridRow(second).locator('[col-id="site"]')).toHaveText(siteName);
  await expect(gridRow(supply).locator('[col-id="location.name"]')).toHaveText(roomName);
  await expect(gridRow(supply).locator('[col-id="location.name"]')).toHaveClass(/cell-inherited/);
  // The whole path, and where it came from, is what the cell says when it has the focus.
  await gridRow(supply).locator('[col-id="location.name"]').click();
  await expect(page.getByTestId("grid-cell-note")).toHaveText(
    `Location: ${room} · Inherited from the item it is in`,
  );

  await expectClean(page, seen, ["409 POST"]);
});

test("a location is chosen by searching, in a form and in bulk; the reports are by site and by region", async ({
  page,
  account,
}) => {
  test.setTimeout(180_000);
  const seen = await watch(page.context());
  await signIn(page, account);

  // A new item is given a location by searching for it: by the code of its site and a
  // part of its name, and chosen by its path.
  await page.goto("./items");
  await page.getByRole("button", { name: "New item" }).click();
  const form = region(page, "New item");
  await form.getByLabel("Hostname").fill(fourth);
  await expect(form.getByTestId("chosen-location_hid")).toHaveText("No location");
  await chooseLocation(form, `${siteCode} building`, building);
  await expect(form.getByTestId("chosen-location_hid")).toHaveText(building);
  await form.getByRole("button", { name: "Create item" }).click();
  await expect(page.getByRole("heading", { level: 1, name: fourth })).toBeVisible();
  await expect(page.getByTestId("location")).toContainText(building);
  await expect(page.getByTestId("location")).toContainText("Set here");
  await expect(page.getByTestId("site")).toHaveText(siteName);

  // The location half of S18: the switch is moved to another location, and the power
  // supply in it shows the new one, as inherited. Nothing was written to it.
  await openItem(page, first);
  const details = region(page, "Details");
  await expect(details.getByTestId("chosen-location_hid")).toHaveText(room);
  await chooseLocation(details, `${siteCode} building 1`, building);
  await details.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("The item was saved.")).toBeVisible();
  await expect(page.getByTestId("location")).toContainText(building);
  const where = page
    .getByTestId("minor-items")
    .locator("tbody tr", { hasText: supply })
    .locator("td[data-source]")
    .nth(2);
  await expect(where).toHaveText(buildingName);
  await expect(where).toHaveAttribute("data-source", "parent_item");
  await page.getByTestId("minor-items").getByRole("link", { name: supply }).click();
  await expect(page.getByRole("heading", { level: 1, name: supply })).toBeVisible();
  await expect(page.getByTestId("location")).toHaveAttribute("data-source", "parent_item");
  await expect(page.getByTestId("location")).toContainText(building);
  await expect(page.getByTestId("location")).toContainText("From the item it is in");
  await expect(region(page, "Details").getByTestId("chosen-location_hid")).toHaveText(
    "Where the item it is in is",
  );

  // The tree follows: the room has one item left, the building has four.
  await geography(page);
  await openSite(page, site);
  await expectCounts(treeRow(page, room), 1, 1);
  await expectCounts(treeRow(page, building), 4, 3);
  await expectCounts(treeRow(page, americas), 4, 3);
  const tree = page.getByTestId("geography-tree");
  await expectCounts(tree.locator('tr[data-row="unplaced"]'), 1, 1);
  await expectCounts(tree.locator('tr[data-row="totals"]'), 5, 4);

  // The management report is by site unless asked otherwise: a row is labelled by its
  // path, and the blank row is the items that are nowhere.
  await page.goto(`./reports/management?${new URLSearchParams({ filter }).toString()}`);
  await expect(page.getByRole("heading", { level: 1, name: "Management report" })).toBeVisible();
  await expect(page.getByLabel("By", { exact: true })).toHaveValue("site");
  await expect(page.getByLabel("By", { exact: true }).locator("option")).toHaveText([
    "Site",
    "Region",
    "Vendor",
    "Kind",
    "Type",
    "Function",
    "Owner",
    "Tag",
  ]);
  await expect(page.getByRole("heading", { level: 2, name: "By site" })).toBeVisible();
  const paid = page.getByTestId("management-rows").locator("tbody tr");
  await expect(paid).toHaveCount(2);
  await expect(paid.filter({ hasText: site }).locator("td").nth(0)).toHaveText("4");
  await expect(paid.filter({ hasText: site }).locator("td").nth(1)).toHaveText("3");
  await expect(paid.filter({ hasText: "Nowhere: no location" }).locator("td").nth(0)).toHaveText(
    "1",
  );
  await expect(page.getByTestId("total-items")).toHaveText("5");
  // By region, an item is in the row of each region above it, and the totals count it once.
  await page.getByLabel("By", { exact: true }).selectOption("region");
  await expect(paid).toHaveCount(3);
  await expect(paid.filter({ hasText: central }).locator("td").nth(0)).toHaveText("4");
  await expect(
    paid.filter({ has: page.getByRole("rowheader", { name: americas, exact: true }) }),
  ).toHaveCount(1);
  await expect(page.getByTestId("total-items")).toHaveText("5");
  // The summary is by site and by region too.
  await page.goto(`./reports?${new URLSearchParams({ filter, by: "site" }).toString()}`);
  await expect(page.getByRole("heading", { level: 1, name: "Summary" })).toBeVisible();
  const counted = page.getByTestId("summary-rows").locator("tbody tr");
  await expect(counted).toHaveCount(2);
  await expect(counted.filter({ hasText: site }).locator("td").nth(1)).toHaveText("3");
  await page.getByLabel("By", { exact: true }).selectOption("region");
  await expect(counted).toHaveCount(3);

  // A bulk edit sets the location: the item that was nowhere is put in the room.
  await page.goto(`./items?filter=${encodeURIComponent(`hostname:eq:${nowhere}`)}`);
  await expect(page.getByTestId("grid-total")).toHaveText("1 item");
  await page.getByRole("button", { name: "Select all that match" }).click();
  await page.getByRole("button", { name: "Bulk edit" }).click();
  const bulk = page.getByTestId("bulk-edit");
  const fields = await bulk.getByLabel("Field to change").locator("option").allTextContents();
  expect(fields).toContain("Location");
  expect(fields).toContain("Owner");
  await bulk.getByLabel("Field to change").selectOption({ label: "Location" });
  await bulk.getByRole("button", { name: "Add", exact: true }).click();
  const line = bulk.getByRole("group", { name: "Location" });
  await chooseLocation(line, `${siteCode} 102`, room, "Set to");
  await expect(line.getByTestId("chosen-location")).toHaveText(room);
  await bulk.getByRole("button", { name: "Preview the change" }).click();
  await expect(count(page, "updated")).toHaveText("1");
  await bulk.getByRole("button", { name: "Apply 1 item" }).click();
  await expect(page.getByTestId("preview-applied")).toContainText("1 updated");
  await geography(page);
  await expectCounts(page.getByTestId("geography-tree").locator('tr[data-row="unplaced"]'), 0, 0);
  await expectCounts(treeRow(page, americas), 5, 4);

  // A device group that is in one place says where, in its form and on its page.
  await page.goto("./groups");
  await page.getByRole("button", { name: "New group" }).click();
  const newGroup = region(page, "New group");
  await newGroup.getByLabel("Name (required)").fill(group);
  await newGroup.getByLabel("Type").selectOption("custom");
  await chooseLocation(newGroup, `${siteCode} 102`, room);
  await newGroup.getByRole("button", { name: "Create group" }).click();
  await expect(page.getByRole("heading", { level: 1, name: group })).toBeVisible();
  await expect(page.getByTestId("group-location")).toContainText(room);
  await expect(region(page, "Details").getByTestId("chosen-location_hid")).toHaveText(room);

  // A place that still holds something is not retired: the refusal says why.
  await geography(page, room);
  await page.getByRole("button", { name: "Retire location" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Retire location" }).click();
  await expect(region(page, "Retire").locator('.alert-error[data-status="409"]')).toBeVisible();
  await expect(page.getByTestId("place")).toHaveAttribute("data-level", "location");

  // The six kinds of record that 0.5.0 brought are among what a file may hold, in the
  // order they are loaded.
  await page.goto("./import");
  await expect(page.getByLabel("Records").locator("option")).toHaveText([
    "As the file says",
    "Tags",
    "Vendors",
    "Catalog entries",
    "Regions",
    "Sites",
    "Locations",
    "Contacts",
    "Contacts of places",
    "Owners",
    "People of owners",
    "Networks",
    "Items",
    "Device groups",
    "Members of device groups",
    "Addresses",
  ]);

  await expectClean(page, seen, ["409 POST"]);
});

test("S25: a contact on the region and one on the site are both shown on the room, each with its level", async ({
  page,
  account,
}) => {
  test.setTimeout(180_000);
  const seen = await watch(page.context());
  await signIn(page, account);

  // Contacts have a list of their own. Two are made by hand, and two more by a file.
  await main(page).getByRole("link", { name: "Contacts" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Contacts" })).toBeVisible();
  for (const [name, mail, phone] of [
    [dana, danaMail, "+1 555 0100"],
    [receiving, receivingMail, "+1 555 0101"],
  ] as const) {
    await page.goto("./contacts");
    await page.getByRole("button", { name: "New contact" }).click();
    const form = region(page, "New contact");
    await form.getByLabel("Name (required)").fill(name);
    await form.getByLabel("Organization").fill("Example Operations");
    await form.getByLabel("Email").fill(mail);
    await form.getByLabel("Phone").fill(phone);
    await form.getByRole("button", { name: "Create contact" }).click();
    await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
    await expect(page.getByTestId("contact-facts")).toContainText(mail);
    await expect(page.getByText("This contact is assigned nowhere.")).toBeVisible();
  }
  await importFile(
    page,
    "contacts",
    `contacts-${id}.csv`,
    ["name", "email", "phone"],
    [
      [lee, leeMail, "+1 555 0102"],
      [priya, priyaMail, "+1 555 0103"],
    ],
  );
  // The list is the shared grid: filtered by the server, with a link to each contact.
  await page.goto(`./contacts?filter=${encodeURIComponent(`email:contains:${id}@`)}`);
  await expect(page.getByTestId("grid-total")).toHaveText("4 contacts");
  await expect(
    page.getByTestId("grid-contacts").getByRole("link", { name: lee, exact: true }),
  ).toBeVisible();

  // A technical contact on the region at the top, a shipping contact on the site.
  await geography(page, americas);
  await expect(page.getByText("No contact is assigned here.")).toBeVisible();
  await assign(page, "Technical", offered(dana, danaMail), dana);
  await expect(inForce(page, "technical")).toHaveAttribute("data-source", "own");
  await expect(inForce(page, "technical")).toContainText("Set here");
  await geography(page, site);
  await assign(page, "Shipping", offered(receiving, receivingMail), receiving);

  // Where deliveries go: instructions on the region, an address on the site.
  await geography(page, americas);
  const regionDetails = region(page, "Details");
  await regionDetails.getByLabel("Shipping instructions").fill("Dock B, weekdays 08:00 to 15:00");
  await regionDetails.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("The region was saved.")).toBeVisible();
  await geography(page, site);
  const siteDetails = region(page, "Details");
  await siteDetails.getByLabel("Shipping address line 1").fill("100 Example Way");
  await siteDetails.getByLabel("Shipping city").fill("Springfield");
  await siteDetails.getByLabel("Shipping country").fill("US");
  await siteDetails.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("The site was saved.")).toBeVisible();

  // The room has neither of its own: it shows both, each with the level it came from,
  // in the lighter style of an inherited value.
  await geography(page, room);
  const technical = inForce(page, "technical");
  await expect(technical).toHaveAttribute("data-source", "region");
  await expect(technical).toContainText(dana);
  await expect(technical).toContainText(danaMail);
  await expect(technical.locator("td").nth(1)).toHaveText(`From the region ${americas}`);
  await expect(technical.locator("td").nth(0)).toHaveClass(/inherited/);
  const shipping = inForce(page, "shipping");
  await expect(shipping).toHaveAttribute("data-source", "site");
  await expect(shipping).toContainText(receiving);
  await expect(shipping.locator("td").nth(1)).toHaveText(`From the site ${site}`);
  // A role nobody is in says so.
  await expect(inForce(page, "federal")).toHaveAttribute("data-source", "none");
  await expect(inForce(page, "federal")).toContainText("Nobody");
  await expect(page.getByText("No contact is assigned here.")).toBeVisible();
  // The shipping address is the site's, whole, and the instructions are the region's.
  await expect(page.getByTestId("ship-address")).toHaveAttribute("data-source", "site");
  await expect(page.getByTestId("ship-address")).toContainText("100 Example Way, Springfield, US");
  await expect(page.getByTestId("ship-address")).toHaveClass(/inherited/);
  await expect(page.getByTestId("ship-instructions")).toHaveAttribute("data-source", "region");
  await expect(page.getByTestId("ship-instructions")).toContainText("Dock B, weekdays");
  // The level a thing came from is the way to it.
  await technical.getByRole("link", { name: americas, exact: true }).click();
  await expect(page.getByTestId("place-path")).toHaveText(americas);

  // The contact says where it is assigned.
  await page.goto(`./contacts?filter=${encodeURIComponent(`email:eq:${danaMail}`)}`);
  await page.getByTestId("grid-contacts").getByRole("link", { name: dana, exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: dana })).toBeVisible();
  const places = page.getByTestId("contact-places").locator("tbody tr");
  await expect(places).toHaveCount(1);
  await expect(places).toContainText(americas);
  await expect(places).toContainText("Region");
  await expect(places).toContainText("Technical");

  await expectClean(page, seen);
});

test("S26: an override on the building holds when the contact on the region is changed", async ({
  page,
  account,
}) => {
  test.setTimeout(180_000);
  const seen = await watch(page.context());
  await signIn(page, account);

  // A room in another building of the same site, with nothing of its own.
  await geography(page, site);
  await newPlace(page, "New location in it", "location", otherBuilding, { kind: "Building" });
  await newPlace(page, "New location in it", "location", otherRoom, { kind: "Room" });
  await expect(inForce(page, "technical")).toContainText(dana);

  // Building 1 has a technical contact of its own.
  await geography(page, building);
  await assign(page, "Technical", offered(lee, leeMail), lee);
  await expect(inForce(page, "technical")).toHaveAttribute("data-source", "own");
  await geography(page, room);
  await expect(inForce(page, "technical")).toHaveAttribute("data-source", "location");
  await expect(inForce(page, "technical")).toContainText(lee);
  await expect(inForce(page, "technical")).not.toContainText(dana);
  await expect(inForce(page, "technical").locator("td").nth(1)).toHaveText(
    `From the location ${building}`,
  );

  // The one on the region is changed: another contact is added after the first, put
  // before it by its priority, and the first is removed.
  await geography(page, americas);
  await assign(page, "Technical", offered(priya, priyaMail), priya);
  const own = page.getByTestId("own-contacts").locator("tbody tr");
  await expect(own).toHaveCount(2);
  await expect(own.filter({ hasText: priya }).getByTestId("priority")).toHaveText("2");
  const danaRow = own.filter({ hasText: dana });
  await danaRow.getByLabel(`Priority of ${dana} as Technical`).fill("3");
  await danaRow.getByRole("button", { name: "Set priority" }).click();
  await expect(page.getByText(`The priority of ${dana} as Technical is now 3.`)).toBeVisible();
  await expect(own.nth(0)).toContainText(priya);
  await expect(inForce(page, "technical").locator("li").nth(0)).toContainText(priya);
  await own.filter({ hasText: dana }).getByRole("button", { name: "Remove" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Remove contact" }).click();
  await expect(
    page.getByText(`${dana} is no longer a Technical contact of ${americas}.`),
  ).toBeVisible();
  await expect(own).toHaveCount(1);

  // Room 102 keeps the building's; the room in the other building shows the new one.
  await geography(page, room);
  await expect(inForce(page, "technical")).toContainText(lee);
  await expect(inForce(page, "technical")).not.toContainText(priya);
  await geography(page, otherRoom);
  await expect(inForce(page, "technical")).toHaveAttribute("data-source", "region");
  await expect(inForce(page, "technical")).toContainText(priya);
  await expect(inForce(page, "technical")).not.toContainText(dana);
  await expect(inForce(page, "shipping")).toContainText(receiving);

  // "None here, and do not look further up", said on the other building for shipping:
  // the room beneath it has nobody, and says which level said so.
  await geography(page, otherBuilding);
  const form = region(page, "Assign a contact");
  await form.getByLabel("Role").selectOption({ label: "Shipping" });
  await form.getByLabel("None here, and do not look further up").check();
  await expect(form.getByLabel("Contact", { exact: true })).toBeDisabled();
  await form.getByRole("button", { name: "Say there is none" }).click();
  await expect(page.getByText(`${otherBuildingName} now has no Shipping contact`)).toBeVisible();
  await expect(inForce(page, "shipping")).toHaveAttribute("data-stopped", "true");
  await expect(inForce(page, "shipping")).toContainText(
    "None here, and nothing further up is looked at",
  );
  await geography(page, otherRoom);
  await expect(inForce(page, "shipping")).toHaveAttribute("data-stopped", "true");
  await expect(inForce(page, "shipping")).toHaveAttribute("data-source", "location");
  await expect(inForce(page, "shipping")).not.toContainText(receiving);
  await expect(inForce(page, "shipping")).toContainText(`None: the location ${otherBuilding}`);
  // Taken back, the room has the site's again.
  await geography(page, otherBuilding);
  await page
    .getByTestId("own-contacts")
    .getByRole("button", { name: "Look further up again for Shipping" })
    .click();
  await expect(
    page.getByText(`${otherBuildingName} takes its Shipping contacts from above again.`),
  ).toBeVisible();
  await expect(inForce(page, "shipping")).toContainText(receiving);

  await expectClean(page, seen);
});

test("S27: the site is moved to another region, and the paths and the counts follow", async ({
  page,
  account,
}) => {
  test.setTimeout(180_000);
  const seen = await watch(page.context());
  await signIn(page, account);

  // The item in the room, as it is before the move.
  await openItem(page, second);
  const itemPage = new URL(page.url()).pathname;
  await expect(page.getByTestId("location")).toContainText(room);

  // Another region beside Central, with a technical contact of its own.
  await geography(page, americas);
  await newPlace(page, "New region in it", "region", east);
  await assign(page, "Technical", offered(dana, danaMail), dana);
  await geography(page);
  await expectCounts(treeRow(page, central), 5, 4);
  await expectCounts(treeRow(page, east), 0, 0);

  // The move is one change of the site.
  await geography(page, site);
  const moved = page.waitForRequest(
    (request) => request.method() === "PATCH" && request.url().includes("/api/v1/sites/"),
  );
  const move = region(page, "Move");
  await move.getByLabel("Region").selectOption({ label: east });
  await move.getByRole("button", { name: "Move site" }).click();
  await expect(page.getByText(`${siteName} was moved: it is now ${movedSite}.`)).toBeVisible();
  expect(Object.keys((await moved).postDataJSON()).sort()).toEqual(["region_hid", "row_version"]);
  await expect(page.getByTestId("place-path")).toHaveText(movedSite);

  // The tree shows the new paths and the totals of both regions.
  await expectCounts(treeRow(page, east), 5, 4);
  await expectCounts(treeRow(page, central), 0, 0);
  await expectCounts(treeRow(page, americas), 5, 4);
  await expect(treeRow(page, site)).toHaveCount(0);
  await expectCounts(treeRow(page, movedSite), 5, 4);
  await expectCounts(treeRow(page, movedRoom), 2, 2);
  await expect(treeRow(page, room)).toHaveCount(0);

  // What is inherited follows: the room in the other building, which took the technical
  // contact of the region above Central, now has the one of East. The pages of the
  // places are where they were: a place is its HID, whatever its path.
  pages.set(movedRoom, pages.get(room) ?? "");
  await geography(page, movedRoom);
  await expect(inForce(page, "technical")).toContainText(lee);
  await page.goto(`${pages.get(otherRoom)}?${new URLSearchParams({ filter }).toString()}`);
  await expect(page.getByTestId("place-path")).toHaveText(movedOtherRoom);
  await expect(inForce(page, "technical")).toContainText(dana);
  await expect(inForce(page, "technical").locator("td").nth(1)).toHaveText(
    `From the region ${east}`,
  );
  await expect(inForce(page, "shipping")).toContainText(receiving);

  // The item is the record it was, at the address it had, and shows the new path.
  await openItem(page, second);
  expect(new URL(page.url()).pathname).toBe(itemPage);
  await expect(page.getByTestId("location")).toContainText(movedRoom);

  await expectClean(page, seen);
});

test("S28: an item is given to an owner outside the team only with a reason, and is marked", async ({
  page,
  account,
}) => {
  test.setTimeout(180_000);
  const seen = await watch(page.context());
  await signIn(page, account);

  // An owner outside the operations team, with its people.
  await main(page).getByRole("link", { name: "Owners" }).click();
  await page.getByRole("button", { name: "New owner" }).click();
  const newOwner = region(page, "New owner");
  await newOwner.getByLabel("Label").fill(facilities);
  await newOwner.getByLabel("Outside the operations team").check();
  await newOwner.getByLabel("Reason for the exception").fill("Runs the building systems");
  await newOwner.getByRole("button", { name: "Create owner" }).click();
  await expect(page.getByRole("heading", { level: 1, name: facilities })).toBeVisible();
  await expect(page.getByTestId("owner-external")).toBeVisible();

  // The first of its people is the primary; another is added, and made the primary,
  // which makes the first an alternate in the same change.
  await expect(page.getByText("This owner has no people yet.")).toBeVisible();
  const add = region(page, "Add a person");
  await add.getByLabel("Contact").selectOption({ label: offered(dana, danaMail) });
  await add.getByRole("button", { name: "Add person" }).click();
  await expect(page.getByText(`${dana} is now the primary of ${facilities}.`)).toBeVisible();
  await region(page, "Add a person")
    .getByLabel("Contact")
    .selectOption({ label: offered(priya, priyaMail) });
  await region(page, "Add a person").getByRole("button", { name: "Add person" }).click();
  await expect(page.getByText(`${priya} is now an alternate of ${facilities}.`)).toBeVisible();
  const people = page.getByTestId("owner-people").locator("tbody tr");
  await expect(people).toHaveCount(2);
  await expect(people.nth(0)).toContainText(dana);
  await expect(people.nth(0).getByTestId("member-role")).toHaveText("Primary");
  // The primary is not removed while there are others.
  await expect(people.nth(0).getByRole("button", { name: "Remove" })).toHaveCount(0);
  await people
    .filter({ hasText: priya })
    .getByRole("button", { name: `Make primary: ${priya}` })
    .click();
  await expect(page.getByText(`${priya} is now the primary of ${facilities}.`)).toBeVisible();
  await expect(people.nth(0)).toContainText(priya);
  await expect(people.nth(0).getByTestId("member-role")).toHaveText("Primary");
  await expect(people.nth(1).getByTestId("member-role")).toHaveText("Alternate");
  await people.filter({ hasText: dana }).getByRole("button", { name: "Remove" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Remove", exact: true }).click();
  await expect(
    page.getByText(`${dana} is no longer one of the people of ${facilities}.`),
  ).toBeVisible();
  await expect(people).toHaveCount(1);
  // The contact says which owner it is one of the people of.
  await people.getByRole("link", { name: priya }).click();
  await expect(page.getByRole("heading", { level: 1, name: priya })).toBeVisible();
  await expect(page.getByTestId("contact-owners")).toContainText(facilities);
  await expect(page.getByTestId("contact-owners")).toContainText("Primary");

  // The item is given that owner. The form asks for the reason once the owner chosen
  // is outside the team, and says why it asks.
  await openItem(page, second);
  const details = region(page, "Details");
  await expect(details.getByLabel("Reason for the exception")).toHaveCount(0);
  await details.getByLabel("Owner").selectOption({ label: facilities });
  const reason = details.getByLabel("Reason for the exception");
  await expect(reason).toBeVisible();
  await expect(details).toContainText("Asked because this owner is outside the operations team");
  // With no reason it is refused, as the server says it, at the field.
  await details.getByRole("button", { name: "Save" }).click();
  await expect(details.locator('.alert-error[data-status="422"]')).toBeVisible();
  await expect(reason).toHaveAttribute("aria-invalid", "true");
  await expect(page.getByTestId("owner-exception")).toHaveCount(0);
  // With one it is accepted, and the item is marked as an exception, with the reason.
  await reason.fill("In the plant room, looked after with the building systems");
  await details.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("The item was saved.")).toBeVisible();
  await expect(page.getByTestId("owner")).toContainText(facilities);
  await expect(page.getByTestId("owner-exception")).toHaveText("Outside the operations team");
  await expect(page.getByTestId("owner-exception-reason")).toHaveText(
    "In the plant room, looked after with the building systems",
  );
  // The grid finds the exceptions.
  await page.goto(`./items?filter=${encodeURIComponent(`${filter} owner_exception:eq:true`)}`);
  await expect(page.getByTestId("grid-total")).toHaveText("1 item");
  await expect(
    page.getByTestId("grid-items").getByRole("link", { name: second, exact: true }),
  ).toBeVisible();

  await expectClean(page, seen, ["422 PATCH"]);
});
