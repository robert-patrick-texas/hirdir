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
//   S28  An owner outside the team is made with no reason, which is refused, then with
//        one; an item given to it is marked as an exception, with the owner's reason.
//
// On the way: the location half of S18, a minor item that is where the item it is in is;
// the Location and Site columns of the item grid; a location chosen by searching, in the
// form of an item, of a device group and of a bulk edit; the reports by site and by
// region; the people of an owner; the six new kinds of record on the Import page; and,
// a place and an item that are not brought back into what is retired; and, last, a
// shipping address typed once on a region, inherited, taken from the street address
// with one tick, overridden, and the override taken back (D-115, D-116); and the plan of
// a new site: spares and a stack given a planned location in a draft site, which move
// in by themselves when the site is made active, the switches of the stack with it
// (D-125, D-127, D-129).
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
import { count, importFile, main, openGroup, openItem, pick, region } from "./structure";
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
const fifth = `${prefix}sw-05`;

// What the last scenario retires: a region with a region in it, and a location with an
// item in it, in the site where it is by then.
const west = path(americas, `West ${id}`);
const coast = path(west, `Coast ${id}`);
const closetName = `Closet ${id}`;
const closet = path(movedSite, closetName);

// The shipping address that is typed once: a region that has one, a site that inherits
// it, a site whose deliveries go to its own door, and a site with another destination.
const north = path(americas, `North ${id}`);
const sharing = path(north, `Depot A ${id}`);
const ownDoor = path(north, `Depot B ${id}`);
const elsewhere = path(north, `Depot C ${id}`);

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
// Why that owner is outside the team: said on the owner, and found by on the items.
const why = `Runs the building systems ${id}`;
const whyNow = `Runs the plant rooms ${id}`;

// The plan of a new site: a store room where two spares and a stack of two switches
// are, and a site that is still a draft, with a room that they are meant for. One
// switch has the store room as its own location, and one has no location of its own.
const stagingSite = path(americas, `Staging ${id}`);
const store = path(stagingSite, `Store ${id}`);
const annexName = `Annex ${id}`;
const annex = path(americas, annexName);
const annexRoomName = `Comms room ${id}`;
const annexRoom = path(annex, annexRoomName);
const sparePrefix = `spare-${id}-`;
const spareFilter = `hostname:prefix:${sparePrefix}`;
const spares = [`${sparePrefix}01`, `${sparePrefix}02`];
const plannedStack = `Stack ${id} annex`;
const stackPrefix = `stk-${id}-`;
const stackSwitches = [`${stackPrefix}1`, `${stackPrefix}2`];

// A room that is rebuilt: the room in use, and beside it a draft under the name of the
// project, which takes the real name at the end.
const worksSite = path(americas, `Works ${id}`);
const oldRoomName = `Room 7 ${id}`;
const oldRoom = path(worksSite, oldRoomName);
const projectName = `PRJ-0042 ${id}`;
const projectRoom = path(worksSite, projectName);
const retiredName = `z-${oldRoomName}`;
const livePrefix = `live-${id}-`;
const liveHosts = [`${livePrefix}01`, `${livePrefix}02`];
const freshHost = `fresh-${id}-01`;

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
  more: { code?: string; kind?: string; status?: string } = {},
) {
  await page.getByRole("button", { name: button, exact: true }).click();
  const form = region(page, `New ${what}`);
  await form.getByLabel("Name (required)").fill(place.split(" > ").at(-1) ?? "");
  if (more.code) await form.getByLabel("Code", { exact: true }).fill(more.code);
  if (more.kind) await form.getByLabel("Kind").selectOption({ label: more.kind });
  if (more.status) await form.getByLabel("Record status").selectOption({ label: more.status });
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
  await expect(page.getByTestId("region")).toHaveText(centralName);
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
  await expect(columns.getByLabel("Region", { exact: true })).not.toBeChecked();
  await columns.getByLabel("Region", { exact: true }).check();
  // The grid draws only the columns in view: room is made for the ones looked at here.
  for (const column of [
    "Vendor",
    "PID",
    "Serial number",
    "Disposition",
    "Expected online",
    "Health",
    "Tags",
    "LDoS",
  ]) {
    await columns.getByLabel(column, { exact: true }).uncheck();
  }
  await page.getByText("Columns", { exact: true }).click();
  const gridRow = (host: string) => grid.locator("[row-id]", { hasText: host });
  await expect(gridRow(second).locator('[col-id="location.name"]')).toHaveText(roomName);
  await expect(gridRow(second).locator('[col-id="location.name"]')).not.toHaveClass(
    /cell-inherited/,
  );
  await expect(gridRow(second).locator('[col-id="site"]')).toHaveText(siteName);
  // The region is the one the site is in, by its name.
  await expect(gridRow(second).locator('[col-id="region"]')).toHaveText(centralName);
  await expect(gridRow(supply).locator('[col-id="region"]')).toHaveClass(/cell-inherited/);
  await expect(gridRow(supply).locator('[col-id="location.name"]')).toHaveText(roomName);
  await expect(gridRow(supply).locator('[col-id="location.name"]')).toHaveClass(/cell-inherited/);
  // The whole path, and where it came from, is what the cell says when it has the focus.
  await gridRow(supply).locator('[col-id="location.name"]').click();
  await expect(page.getByTestId("grid-cell-note")).toHaveText(
    `Location: ${room} · Inherited from the item ${first}`,
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
  await expect(page.getByTestId("location")).toContainText("Inherited from the item");
  await expect(
    page.getByTestId("location").getByRole("link", { name: `the item ${first}` }),
  ).toBeVisible();
  // Its form shows what it has from above, before a location of its own is chosen.
  await expect(region(page, "Details").getByTestId("chosen-location_hid")).toHaveText(
    "None of its own",
  );
  await expect(region(page, "Details").getByTestId("location-note")).toContainText(
    `It is in ${building}, from the item ${first}`,
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
    "Operator",
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
    "Contacts",
    "Operators",
    "Regions",
    "Sites",
    "Locations",
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
  await expect(technical.locator("td").nth(1)).toHaveText(`Inherited from the region ${americas}`);
  await expect(technical.locator("td").nth(0)).toHaveClass(/inherited/);
  const shipping = inForce(page, "shipping");
  await expect(shipping).toHaveAttribute("data-source", "site");
  await expect(shipping).toContainText(receiving);
  await expect(shipping.locator("td").nth(1)).toHaveText(`Inherited from the site ${site}`);
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
    `Inherited from the location ${building}`,
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
  pages.set(movedSite, pages.get(site) ?? "");
  await geography(page, movedRoom);
  await expect(inForce(page, "technical")).toContainText(lee);
  await page.goto(`${pages.get(otherRoom)}?${new URLSearchParams({ filter }).toString()}`);
  await expect(page.getByTestId("place-path")).toHaveText(movedOtherRoom);
  await expect(inForce(page, "technical")).toContainText(dana);
  await expect(inForce(page, "technical").locator("td").nth(1)).toHaveText(
    `Inherited from the region ${east}`,
  );
  await expect(inForce(page, "shipping")).toContainText(receiving);

  // The item is the record it was, at the address it had, and shows the new path.
  await openItem(page, second);
  expect(new URL(page.url()).pathname).toBe(itemPage);
  await expect(page.getByTestId("location")).toContainText(movedRoom);

  await expectClean(page, seen);
});

test("S28: an owner outside the team says why, once, and what is given to it is marked with that", async ({
  page,
  account,
}) => {
  test.setTimeout(180_000);
  const seen = await watch(page.context());
  await signIn(page, account);

  // An owner outside the operations team says why it is one. With no reason it is
  // refused, as the server says it, at the field; with one it is accepted.
  await main(page).getByRole("link", { name: "Owners" }).click();
  await page.getByRole("button", { name: "New owner" }).click();
  const newOwner = region(page, "New owner");
  await newOwner.getByLabel("Label").fill(facilities);
  await newOwner.getByLabel("Outside the operations team").check();
  await newOwner.getByRole("button", { name: "Create owner" }).click();
  await expect(newOwner.locator('.alert-error[data-status="422"]')).toBeVisible();
  await expect(newOwner.getByLabel("Reason for the exception")).toHaveAttribute(
    "aria-invalid",
    "true",
  );
  await newOwner.getByLabel("Reason for the exception").fill(why);
  await newOwner.getByRole("button", { name: "Create owner" }).click();
  await expect(page.getByRole("heading", { level: 1, name: facilities })).toBeVisible();
  await expect(page.getByTestId("owner-external")).toBeVisible();
  // Its page says that this reason is what everything it has shows.
  await expect(page.getByTestId("owner-reason")).toHaveText(why);
  await expect(page.getByTestId("owner-reason-shown")).toContainText(
    "every item and group that has this owner is marked as an exception",
  );
  const ownerPage = page.url();

  // The first of its people is the primary; another is added, and made the primary,
  // which makes the first an alternate in the same change.
  await expect(page.getByText("This owner has no people yet.")).toBeVisible();
  const add = region(page, "Add a person");
  await add.getByLabel("Contact").selectOption({ label: offered(dana, danaMail) });
  await add.getByRole("button", { name: "Add person" }).click();
  await expect(page.getByText(`${dana} is now the primary of ${facilities}.`)).toBeVisible();
  // The owner is read again, and the form with it: the next person is chosen after that.
  await expect(page.getByTestId("owner-people").locator("tbody tr")).toHaveCount(1);
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

  // The item is given that owner, and nothing more is asked: the form has no input for
  // a reason, and says of the owner chosen that it is outside the team, and why.
  await openItem(page, second);
  const details = region(page, "Details");
  await expect(details.getByLabel("Reason for the exception")).toHaveCount(0);
  await expect(details).not.toContainText("This owner is outside the operations team");
  await details.getByLabel("Owner").selectOption({ label: facilities });
  await expect(details.getByLabel("Reason for the exception")).toHaveCount(0);
  await expect(details).toContainText("This owner is outside the operations team");
  await expect(details).toContainText(`Its reason: ${why}.`);
  await details.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("The item was saved.")).toBeVisible();
  // It is marked as an exception, with the owner's reason, read-only, and the way to
  // where that reason is changed.
  await expect(page.getByTestId("owner")).toContainText(facilities);
  await expect(page.getByTestId("owner-exception")).toHaveText("Outside the operations team");
  await expect(page.getByTestId("owner-exception-reason")).toHaveText(why);
  const itemPage = page.url();

  // A bulk edit gives an owner outside the team like any other, with no reason beside it.
  await page.goto(`./items?filter=${encodeURIComponent(`hostname:eq:${fourth}`)}`);
  await expect(page.getByTestId("grid-total")).toHaveText("1 item");
  await page.getByRole("button", { name: "Select all that match" }).click();
  await page.getByRole("button", { name: "Bulk edit" }).click();
  const bulk = page.getByTestId("bulk-edit");
  await bulk.getByLabel("Field to change").selectOption({ label: "Owner" });
  await bulk.getByRole("button", { name: "Add", exact: true }).click();
  const line = bulk.getByRole("group", { name: "Owner" });
  await line.getByLabel("Set to").selectOption({ label: facilities });
  await expect(bulk.getByLabel("Reason for the exception")).toHaveCount(0);
  await bulk.getByRole("button", { name: "Preview the change" }).click();
  await expect(count(page, "updated")).toHaveText("1");
  await bulk.getByRole("button", { name: "Apply 1 item" }).click();
  await expect(page.getByTestId("preview-applied")).toContainText("1 updated");

  // A device group that is given that owner is marked in the same way, and the list of
  // groups finds it by that.
  await page.goto(`./groups?filter=${encodeURIComponent(`name:eq:${group}`)}`);
  await page.getByTestId("grid-device-groups").getByRole("link", { name: group }).click();
  await expect(page.getByRole("heading", { level: 1, name: group })).toBeVisible();
  await expect(page.getByTestId("group-owner-exception")).toHaveCount(0);
  const groupDetails = region(page, "Details");
  await groupDetails.getByLabel("Owner").selectOption({ label: facilities });
  await groupDetails.getByRole("button", { name: "Save" }).click();
  await expect(page.getByTestId("group-owner-exception")).toHaveText("Outside the operations team");
  await expect(page.getByTestId("group-owner-exception-reason")).toHaveText(why);
  await page.goto(
    `./groups?filter=${encodeURIComponent(`name:eq:${group} owner_exception:eq:true`)}`,
  );
  await expect(page.getByTestId("grid-total")).toHaveText("1 group");

  // The reason is changed where the owner is defined, once, and what has the owner
  // shows the new one at once: nothing was written to the item.
  await page.goto(itemPage);
  await page
    .getByTestId("owner-exception-reason")
    .locator("..")
    .getByRole("link", { name: "the page of the owner" })
    .click();
  await expect(page.getByRole("heading", { level: 1, name: facilities })).toBeVisible();
  expect(page.url()).toBe(ownerPage);
  const ownerDetails = region(page, "Details");
  await ownerDetails.getByLabel("Reason for the exception").fill(whyNow);
  await ownerDetails.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("The owner was saved.")).toBeVisible();
  await page.goto(itemPage);
  await expect(page.getByTestId("owner-exception-reason")).toHaveText(whyNow);

  // The grid finds the exceptions, and finds them by the owner's reason. The reason is
  // a column, hidden until it is asked for.
  await page.goto(`./items?filter=${encodeURIComponent(`${filter} owner_exception:eq:true`)}`);
  await expect(page.getByTestId("grid-total")).toHaveText("2 items");
  await page.goto(`./items?filter=${encodeURIComponent(`owner_exception_reason:eq:${whyNow}`)}`);
  await expect(page.getByTestId("grid-total")).toHaveText("2 items");
  const grid = page.getByTestId("grid-items");
  await expect(grid.getByRole("link", { name: second, exact: true })).toBeVisible();
  await expect(grid.getByRole("link", { name: fourth, exact: true })).toBeVisible();
  await page.getByText("Columns", { exact: true }).click();
  const columns = page.getByRole("group", { name: "Columns to show" });
  await columns.getByLabel("Reason for the exception", { exact: true }).check();
  for (const column of ["Vendor", "PID", "Serial number", "Health", "Tags", "LDoS"]) {
    await columns.getByLabel(column, { exact: true }).uncheck();
  }
  await page.getByText("Columns", { exact: true }).click();
  await expect(
    grid.locator("[row-id]", { hasText: second }).locator('[col-id="owner_exception_reason"]'),
  ).toHaveText(whyNow);

  await expectClean(page, seen, ["422 POST"]);
});

test("what is retired is not brought back into what is retired", async ({ page, account }) => {
  test.setTimeout(180_000);
  const seen = await watch(page.context());
  await signIn(page, account);

  /** Retire the place on show. */
  async function retirePlace(what: "region" | "location") {
    await page.getByRole("button", { name: `Retire ${what}` }).click();
    await page
      .getByRole("dialog")
      .getByRole("button", { name: `Retire ${what}` })
      .click();
    await expect(page.getByText(`The ${what} was retired.`)).toBeVisible();
  }

  // A region with a region in it. Both are retired, the inner one first.
  await geography(page, americas);
  await newPlace(page, "New region in it", "region", west);
  await newPlace(page, "New region in it", "region", coast);
  await retirePlace("region");
  await geography(page, west);
  await retirePlace("region");
  // They have left the tree, and are still reached by their own addresses.
  await expect(treeRow(page, west)).toHaveCount(0);

  // The inner one is not brought back while the one it is in is retired: the refusal
  // says which to bring back first, in words.
  await geography(page, coast);
  const retired = region(page, "Retired");
  await retired.getByRole("button", { name: "Bring back as active" }).click();
  await expect(retired.locator('.alert-error[data-status="422"]')).toBeVisible();
  await expect(retired).toContainText(`Bring West ${id} back first: it is retired.`);
  await expect(retired).not.toContainText("record_status");
  await geography(page, west);
  await region(page, "Retired").getByRole("button", { name: "Bring back as active" }).click();
  await expect(page.getByText("The region is active again.")).toBeVisible();
  await geography(page, coast);
  await region(page, "Retired").getByRole("button", { name: "Bring back as active" }).click();
  await expect(page.getByText("The region is active again.")).toBeVisible();
  await expect(treeRow(page, coast)).toBeVisible();

  // An item in a location, the item retired and then the location.
  await geography(page, movedSite);
  await newPlace(page, "New location in it", "location", closet, { kind: "Room" });
  await page.goto("./items");
  await page.getByRole("button", { name: "New item" }).click();
  const form = region(page, "New item");
  await form.getByLabel("Hostname").fill(fifth);
  await chooseLocation(form, `${siteCode} closet`, closet);
  await form.getByRole("button", { name: "Create item" }).click();
  await expect(page.getByRole("heading", { level: 1, name: fifth })).toBeVisible();
  const itemPage = page.url();
  await page.getByRole("button", { name: "Retire item" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Retire item" }).click();
  await expect(page.getByText("The item was retired.")).toBeVisible();
  await geography(page, closet);
  await retirePlace("location");

  // The item is not brought back into the retired location. The refusal says what to
  // do, and the page offers it: another location, or none, with the same change.
  await page.goto(itemPage);
  await expect(page.getByRole("heading", { level: 1, name: fifth })).toBeVisible();
  const gone = region(page, "Retired");
  await expect(page.getByTestId("bring-back-elsewhere")).toHaveCount(0);
  await gone.getByRole("button", { name: "Bring back as active" }).click();
  await expect(gone.locator('.alert-error[data-status="422"]')).toBeVisible();
  await expect(gone).toContainText(`${closetName}, where the item was, is retired`);
  await expect(gone).toContainText("Give the item another location, or none, with the change.");
  const elsewhere = page.getByTestId("bring-back-elsewhere");
  await expect(elsewhere.getByTestId("chosen-location_hid")).toHaveText("No location");
  await chooseLocation(elsewhere, `${siteCode} 102`, movedRoom, "Another location");
  await expect(elsewhere.getByTestId("chosen-location_hid")).toHaveText(movedRoom);
  await elsewhere.getByRole("button", { name: "Bring back there" }).click();
  await expect(page.getByText("The item is active again.")).toBeVisible();
  await expect(page.getByTestId("location")).toContainText(movedRoom);
  await expect(page.getByTestId("region")).toHaveText(eastName);

  await expectClean(page, seen, ["422 PATCH", "422 PATCH"]);
});

test("a shipping address is typed once: inherited, the street address by a tick, or an override", async ({
  page,
  account,
}) => {
  test.setTimeout(180_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  const address = () => page.getByTestId("ship-address");

  // A region with a shipping address. A region has no street address, and so no tick.
  await geography(page, americas);
  await page.getByRole("button", { name: "New region in it", exact: true }).click();
  const newRegion = region(page, "New region");
  await expect(newRegion.getByLabel("Deliveries go to the street address")).toHaveCount(0);
  await newRegion.getByLabel("Name (required)").fill(north.split(" > ").at(-1) ?? "");
  await newRegion.getByLabel("Shipping address line 1").fill("100 Example Way");
  await newRegion.getByLabel("Shipping city").fill("Springfield");
  await newRegion.getByRole("button", { name: "Create region" }).click();
  await expect(page.getByTestId("place-path")).toHaveText(north);
  pages.set(north, `.${new URL(page.url()).pathname.replace(/^.*(?=\/geography\/)/, "")}`);
  // It is the region's own, and no level above has one.
  await expect(address()).toHaveAttribute("data-standing", "own");
  await expect(address()).toContainText("100 Example Way, Springfield");
  await expect(address()).toContainText("Set here");

  // A site in it that shares the destination: the form says what it will inherit before
  // anything is typed, and nothing is typed.
  await page.getByRole("button", { name: "New site in it", exact: true }).click();
  const before = region(page, "New site").getByTestId("shipping-note");
  await expect(before).toHaveAttribute("data-standing", "inherited");
  await expect(before).toContainText("100 Example Way, Springfield");
  await expect(before).toContainText(`It will be inherited from ${north}`);
  await region(page, "New site").getByRole("button", { name: "Cancel" }).click();
  await newPlace(page, "New site in it", "site", sharing);
  // On its page the address is seen to be inherited: marked in words, lighter, with
  // the level it came from as a link.
  await expect(address()).toHaveAttribute("data-standing", "inherited");
  await expect(address()).toHaveClass(/inherited/);
  await expect(address()).toContainText("100 Example Way, Springfield");
  await expect(address()).toContainText(`Inherited from the region ${north}`);
  await expect(address().getByRole("link", { name: north, exact: true })).toBeVisible();
  await expect(address().getByRole("button")).toHaveCount(0);
  // The form shows it read-only above the empty inputs.
  const sharingForm = region(page, "Details");
  const note = sharingForm.getByTestId("shipping-note");
  await expect(note).toHaveAttribute("data-standing", "inherited");
  await expect(note).toContainText(`Inherited from ${north}`);
  await expect(note).toContainText("Enter an address here, or tick the box, to override it.");
  await expect(sharingForm.getByLabel("Shipping address line 1")).toHaveValue("");
  // The tick needs a street address: without one it is refused, at the tick.
  const tick = sharingForm.getByLabel("Deliveries go to the street address");
  await tick.check();
  await expect(sharingForm.getByLabel("Shipping address line 1")).toHaveCount(0);
  await expect(sharingForm.getByLabel("Shipping instructions")).toBeVisible();
  await sharingForm.getByRole("button", { name: "Save" }).click();
  await expect(sharingForm.locator('.alert-error[data-status="422"]')).toBeVisible();
  await expect(tick).toHaveAttribute("aria-invalid", "true");
  await sharingForm.getByRole("button", { name: "Undo changes" }).click();
  await expect(address()).toHaveAttribute("data-standing", "inherited");

  // A site whose deliveries go to its own door: the street address is typed once, and
  // one tick makes it the shipping address. The shipping inputs are not offered.
  await geography(page, north);
  await page.getByRole("button", { name: "New site in it", exact: true }).click();
  const door = region(page, "New site");
  await door.getByLabel("Name (required)").fill(ownDoor.split(" > ").at(-1) ?? "");
  await door.getByLabel("Address line 1", { exact: true }).fill("200 Example Road");
  await door.getByLabel("City", { exact: true }).fill("Shelbyville");
  await door.getByLabel("Deliveries go to the street address").check();
  await expect(door.getByLabel("Shipping address line 1")).toHaveCount(0);
  await expect(door.getByLabel("Shipping city")).toHaveCount(0);
  await door.getByRole("button", { name: "Create site" }).click();
  await expect(page.getByTestId("place-path")).toHaveText(ownDoor);
  await expect(page.getByTestId("ship-same-as-address")).toHaveText("Go to the street address");
  await expect(address()).toHaveAttribute("data-same-as-address", "true");
  await expect(address()).toContainText("200 Example Road, Shelbyville");
  await expect(address()).toContainText("it is the street address, by the tick");
  // It is the site's own where the region has one too: an override, and marked so.
  await expect(address()).toHaveAttribute("data-standing", "override");
  await expect(address()).toContainText("Overrides");
  await expect(address().getByRole("link", { name: north, exact: true })).toBeVisible();

  // A site with another destination: the operator overrides what the region has.
  await geography(page, north);
  await newPlace(page, "New site in it", "site", elsewhere);
  await expect(address()).toHaveAttribute("data-standing", "inherited");
  const form = region(page, "Details");
  await form.getByLabel("Shipping address line 1").fill("300 Example Avenue");
  await form.getByLabel("Shipping city").fill("Capital City");
  await form.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("The site was saved.")).toBeVisible();
  await expect(address()).toHaveAttribute("data-standing", "override");
  await expect(address()).not.toHaveClass(/inherited/);
  await expect(address()).toContainText("300 Example Avenue, Capital City");
  await expect(address()).toContainText("Set here");
  await expect(address()).toContainText("Overrides");
  await expect(address().getByRole("link", { name: north, exact: true })).toBeVisible();
  await expect(region(page, "Details").getByTestId("shipping-note")).toHaveAttribute(
    "data-standing",
    "override",
  );
  // The site that shares the region's destination is as it was.
  await geography(page, sharing);
  await expect(address()).toContainText("100 Example Way, Springfield");

  // Ticked on a site that has a shipping address of its own, that address is cleared
  // with the tick, in the same change, so that nothing has to be emptied by hand.
  await geography(page, elsewhere);
  const again = region(page, "Details");
  await again.getByLabel("Address line 1", { exact: true }).fill("301 Example Avenue");
  await again.getByLabel("Deliveries go to the street address").check();
  const sent = page.waitForRequest(
    (request) => request.method() === "PATCH" && request.url().includes("/api/v1/sites/"),
  );
  await again.getByRole("button", { name: "Save" }).click();
  expect((await sent).postDataJSON()).toMatchObject({
    ship_same_as_address: true,
    ship_address1: null,
    ship_city: null,
  });
  await expect(page.getByText("The site was saved.")).toBeVisible();
  await expect(address()).toHaveAttribute("data-same-as-address", "true");
  await expect(address()).toContainText("301 Example Avenue");
  await expect(address()).toHaveAttribute("data-standing", "override");

  // The override is taken back with one action: the site inherits again.
  await address()
    .getByRole("button", { name: `Use the address from ${north} again` })
    .click();
  await expect(
    page.getByText(`${elsewhere.split(" > ").at(-1)} has the shipping address of ${north} again.`),
  ).toBeVisible();
  await expect(address()).toHaveAttribute("data-standing", "inherited");
  await expect(address()).toHaveAttribute("data-same-as-address", "false");
  await expect(address()).toContainText("100 Example Way, Springfield");
  await expect(address()).toContainText(`Inherited from the region ${north}`);
  await expect(page.getByTestId("ship-same-as-address")).toHaveCount(0);

  // The contacts of a role are marked in the same way: the technical contact of the
  // region at the top is inherited here, and one assigned here overrides it.
  await expect(inForce(page, "technical")).toHaveAttribute("data-standing", "inherited");
  await expect(inForce(page, "technical").locator("td").nth(1)).toContainText("Inherited");
  await assign(page, "Technical", offered(lee, leeMail), lee);
  await expect(inForce(page, "technical")).toHaveAttribute("data-standing", "override");
  await expect(inForce(page, "technical").locator("td").nth(1)).toHaveText(
    `Set here Overrides ${americas}`,
  );
  await expect(inForce(page, "federal")).toHaveAttribute("data-standing", "none");

  await expectClean(page, seen, ["422 PATCH"]);
});

test("a new site is planned: spares and a stack are given a planned location there, and move in when it is made active", async ({
  page,
  account,
}) => {
  test.setTimeout(240_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  const [spare = "", other = ""] = spares;
  // The first switch is put in the store room itself; the second has no location of
  // its own.
  const [placedSwitch = "", looseSwitch = ""] = stackSwitches;
  /** The Geography page counting the spares, drafts among the places, with one place chosen. */
  const planning = async (place: string) => {
    const query = new URLSearchParams({ filter: spareFilter, drafts: "1" });
    await page.goto(`${pages.get(place)}?${query.toString()}`);
    await expect(page.getByTestId("place-path")).toHaveText(place);
  };

  // A store room in a site that is in use, and a site that is still a draft, with the
  // room the equipment is meant for.
  await geography(page, americas);
  await newPlace(page, "New site in it", "site", stagingSite);
  await newPlace(page, "New location in it", "location", store, { kind: "Room" });
  await geography(page, americas);
  await newPlace(page, "New site in it", "site", annex, { status: "Draft" });
  // A draft place is made active by an action of its own, which asks first: its form
  // does not offer the status.
  await expect(region(page, "Make active")).toBeVisible();
  await expect(region(page, "Details").getByLabel("Record status")).toHaveCount(0);
  await expect(page.getByTestId("planned-here")).toContainText("Nothing is planned for this site");
  // With nothing planned the action says so, and still asks. It is not gone ahead with.
  await region(page, "Make active").getByRole("button", { name: "Make site active" }).click();
  await expect(page.getByTestId("activation-text")).toHaveText(
    `Nothing is planned for ${annexName}: making it active moves nothing.`,
  );
  await page.getByRole("dialog").getByRole("button", { name: "Cancel" }).click();
  await newPlace(page, "New location in it", "location", annexRoom, { kind: "Room" });

  // Two spares and one switch in the store room, and a switch that is nowhere yet.
  await importFile(
    page,
    "items",
    `items-${id}-spares.csv`,
    ["hostname", "location"],
    [...spares.map((host) => [host, store]), [placedSwitch, store], [looseSwitch, ""]],
  );

  // A bulk edit gives both spares a planned location. Only a place that is not in use
  // yet is offered: the room of the draft site is, the store room is not.
  await page.goto(`./items?filter=${encodeURIComponent(spareFilter)}`);
  await expect(page.getByTestId("grid-total")).toHaveText("2 items");
  await page.getByRole("button", { name: "Select all that match" }).click();
  await page.getByRole("button", { name: "Bulk edit" }).click();
  const bulk = page.getByTestId("bulk-edit");
  await bulk.getByLabel("Field to change").selectOption({ label: "Planned location" });
  await bulk.getByRole("button", { name: "Add", exact: true }).click();
  const line = bulk.getByRole("group", { name: "Planned location" });
  await expect(line).toContainText("Only a place that is not in use yet is offered");
  await line.getByLabel("Set to", { exact: true }).fill(`Store ${id}`);
  await expect(line.getByText("No location matches.")).toBeVisible();
  await chooseLocation(line, annexRoomName, annexRoom, "Set to");
  await expect(line.getByTestId("chosen-planned_location")).toHaveText(annexRoom);
  await bulk.getByRole("button", { name: "Preview the change" }).click();
  await expect(count(page, "updated")).toHaveText("2");
  await bulk.getByRole("button", { name: "Apply 2 items" }).click();
  await expect(page.getByTestId("preview-applied")).toContainText("2 updated");

  // The spares are where they were, and say where they are going: a plan of their own.
  await openItem(page, spare);
  const itemPage = page.url();
  await expect(page.getByTestId("location")).toContainText(store);
  await expect(page.getByTestId("planned-location")).toHaveText(
    `Planned for ${annexRoom}, when that place is made active`,
  );
  await expect(page.getByTestId("planned-location")).toHaveAttribute("data-source", "own");
  await expect(region(page, "Details").getByTestId("chosen-planned_location_hid")).toHaveText(
    annexRoom,
  );

  // The stack is in the store room, and is planned for the new room, in its form. Its
  // switches are not planned one by one: a plan for the stack is a plan for them.
  await page.goto("./groups");
  await page.getByRole("button", { name: "New group" }).click();
  const newGroup = region(page, "New group");
  await newGroup.getByLabel("Name (required)").fill(plannedStack);
  await newGroup.getByLabel("Type").selectOption("stack");
  for (const host of stackSwitches) {
    await pick(newGroup, "Find an item to add", stackPrefix, host);
  }
  await chooseLocation(newGroup, `Store ${id}`, store);
  await chooseLocation(newGroup, annexRoomName, annexRoom, "Planned location");
  // It is given an owner too, the one outside the team: its switches have none.
  await newGroup.getByLabel("Owner").selectOption({ label: facilities });
  await newGroup.getByRole("button", { name: "Create group" }).click();
  await expect(page.getByRole("heading", { level: 1, name: plannedStack })).toBeVisible();
  await expect(page.getByTestId("group-location")).toContainText(store);
  await expect(page.getByTestId("group-location")).toHaveAttribute("data-source", "own");
  await expect(page.getByTestId("group-planned-location")).toHaveText(
    `Planned for ${annexRoom}, when that place is made active`,
  );
  // The page says what its members have from it, and how many have their own.
  await expect(page.getByTestId("group-location-members")).toContainText(
    "its members with no location of their own are where it is",
  );
  await expect(page.getByTestId("members-own-location")).toContainText(
    "1 of its members has a location of its own, as an override",
  );
  await expect(page.getByTestId("group-planned-members")).toContainText(
    "its members with no plan of their own go with it",
  );
  await expect(page.getByTestId("members-own-planned")).toContainText(
    "none of its members has a plan of its own",
  );
  await expect(page.getByTestId("plan-members")).toHaveCount(0);
  await page.getByTestId("members-own-location").getByRole("link").click();
  await expect(page.getByTestId("grid-total")).toHaveText("1 item");
  await expect(
    page.getByTestId("grid-items").getByRole("link", { name: placedSwitch, exact: true }),
  ).toBeVisible();

  // The switch with no location of its own is where the stack is, and both switches
  // have the plan of the stack: inherited, lighter, with the stack named and linked.
  await openItem(page, looseSwitch);
  await expect(page.getByTestId("location")).toContainText(store);
  await expect(page.getByTestId("location")).toHaveAttribute("data-source", "device_group");
  await expect(page.getByTestId("location")).toContainText("Inherited");
  await expect(
    page.getByTestId("location").getByRole("link", { name: `the group ${plannedStack}` }),
  ).toBeVisible();
  // It has the owner of the stack in the same way, and is an exception by that owner.
  await expect(page.getByTestId("owner")).toHaveAttribute("data-source", "device_group");
  await expect(page.getByTestId("owner")).toContainText(facilities);
  await expect(page.getByTestId("owner")).toContainText("Inherited");
  await expect(
    page.getByTestId("owner").getByRole("link", { name: `the group ${plannedStack}` }),
  ).toBeVisible();
  await expect(page.getByTestId("owner-exception")).toHaveText("Outside the operations team");
  await expect(page.getByTestId("planned-location")).toHaveText(
    `Planned for ${annexRoom}, when that place is made active`,
  );
  await expect(page.getByTestId("planned-location")).toHaveAttribute("data-source", "device_group");
  // Its form shows what it has from the stack, and that a choice here overrides it.
  const looseDetails = region(page, "Details");
  await expect(looseDetails.getByTestId("chosen-location_hid")).toHaveText("None of its own");
  await expect(looseDetails.getByTestId("location-note")).toContainText(
    `It is in ${store}, from the group ${plannedStack}`,
  );
  await expect(looseDetails.getByTestId("planned-note")).toContainText(
    `It is planned for ${annexRoom}, from the group ${plannedStack}`,
  );
  await expect(looseDetails.getByTestId("owner-note")).toContainText(
    `${facilities}, from the group ${plannedStack}`,
  );
  // The switch in the store room has that as its own, an override, and the plan of the
  // stack all the same.
  await openItem(page, placedSwitch);
  const switchPage = page.url();
  await expect(page.getByTestId("location")).toContainText(store);
  await expect(page.getByTestId("location")).toHaveAttribute("data-source", "own");
  await expect(page.getByTestId("planned-location")).toHaveAttribute("data-source", "device_group");
  await expect(region(page, "Details").locator('[data-field="location_hid"]')).toContainText(
    "Clear it and save, and the item is where its group is again.",
  );

  // The spares are counted in the store room. The draft site holds nothing yet, and
  // shows what is planned for it as two numbers: the items, here the spares that the
  // filter keeps, and the groups. On its page every item planned for it is counted, the
  // switches among them, and the stack apart.
  await planning(annex);
  await expectCounts(treeRow(page, stagingSite), 2, 2);
  await expectCounts(treeRow(page, annex), 0, 0);
  await expect(treeRow(page, annex).getByTestId("planned")).toHaveText("2 items planned");
  await expect(treeRow(page, annex).getByTestId("planned-groups")).toHaveText(
    "1 device group planned",
  );
  await expect(treeRow(page, stagingSite).getByTestId("planned")).toHaveCount(0);
  const here = page.getByTestId("planned-here");
  await expect(here.getByTestId("planned-count")).toHaveText("4 items");
  await expect(here.getByTestId("planned-groups")).toHaveText("1 device group");
  const listed = here.getByTestId("planned-items").locator("tbody tr");
  await expect(listed).toHaveCount(4);
  await expect(listed.filter({ hasText: spare })).toContainText(store);
  await expect(listed.filter({ hasText: other })).toBeVisible();
  await expect(listed.filter({ hasText: looseSwitch })).toContainText(store);
  // The groups planned for the place are a filter of the group grid.
  await here.getByTestId("planned-groups").click();
  await expect(page.getByTestId("grid-total")).toHaveText("1 group");
  await expect(
    page.getByTestId("grid-device-groups").getByRole("link", { name: plannedStack, exact: true }),
  ).toBeVisible();

  // The site is made active. The action asks first, and says what it does, with both
  // numbers and that the members go with their group.
  await planning(annex);
  await region(page, "Make active").getByRole("button", { name: "Make site active" }).click();
  // The numbers are the server's, read when the question opens: what would be there,
  // and how many records are written to. The switch with no location of its own goes
  // with the stack and is not written to: four records, of five that move.
  const asks = page.getByTestId("activation-text");
  await expect(asks).toHaveAttribute("data-items", "4");
  await expect(asks).toHaveAttribute("data-groups", "1");
  await expect(asks).toHaveAttribute("data-changed", "4");
  await expect(asks).toHaveAttribute("data-moves", "true");
  await expect(asks).toHaveText(
    `Making ${annexName} active moves 4 items and 1 device group that are planned for it into it. 4 records are changed, each with the move in its history; what has no location of its own goes with its group and is not written to.`,
  );
  await page.getByRole("dialog").getByRole("button", { name: "Make site active" }).click();
  await expect(
    page.getByText(
      `${annexName} is active. What was planned for it is there now: 4 items and 1 device group.`,
    ),
  ).toBeVisible();
  // The page shows the spares as being there: nobody moved them one by one.
  await expectCounts(treeRow(page, annex), 2, 2);
  await expectCounts(treeRow(page, stagingSite), 0, 0);
  await expect(treeRow(page, annex).getByTestId("planned")).toHaveCount(0);
  await expect(treeRow(page, annex).getByTestId("planned-groups")).toHaveCount(0);
  await expectCounts(treeRow(page, annexRoom), 2, 2);
  await expect(region(page, "Make active")).toHaveCount(0);
  await expect(page.getByTestId("planned-here")).toHaveCount(0);

  // Each spare is in the new room, with the plan gone and the move in its history.
  await page.goto(itemPage);
  await expect(page.getByRole("heading", { level: 1, name: spare })).toBeVisible();
  await expect(page.getByTestId("location")).toContainText(annexRoom);
  await expect(page.getByTestId("planned-location")).toHaveCount(0);
  // The newest entry of its history is that change: the location given, the plan cleared.
  const moved = region(page, "History").locator("tbody").first();
  await expect(moved.getByRole("cell", { name: "location_hid", exact: true })).toBeVisible();
  await expect(
    moved.getByRole("cell", { name: "planned_location_hid", exact: true }),
  ).toBeVisible();
  await openItem(page, other);
  await expect(page.getByTestId("location")).toContainText(annexRoom);

  // The stack is in the room, and so are its switches, which went with it. The one
  // that was put in the store room gave that up in the same change, which is in its
  // history: it is where the stack is now. The other was never written to.
  await openGroup(page, plannedStack);
  await expect(page.getByTestId("group-location")).toContainText(annexRoom);
  await expect(page.getByTestId("group-planned-location")).toHaveCount(0);
  await expect(page.getByTestId("members-own-location")).toContainText(
    "none of its members has a location of its own",
  );
  await page.goto(switchPage);
  await expect(page.getByRole("heading", { level: 1, name: placedSwitch })).toBeVisible();
  await expect(page.getByTestId("location")).toContainText(annexRoom);
  await expect(page.getByTestId("location")).toHaveAttribute("data-source", "device_group");
  await expect(page.getByTestId("planned-location")).toHaveCount(0);
  // The newest entry of its history is the location of its own, given up.
  const gaveUp = region(page, "History").locator("tbody").first();
  await expect(gaveUp.getByRole("cell", { name: "location_hid", exact: true })).toBeVisible();
  // It had no plan of its own: none is cleared.
  await expect(gaveUp.getByRole("cell", { name: "planned_location_hid", exact: true })).toHaveCount(
    0,
  );
  await openItem(page, looseSwitch);
  await expect(page.getByTestId("location")).toContainText(annexRoom);
  await expect(page.getByTestId("location")).toHaveAttribute("data-source", "device_group");
  await expect(page.getByTestId("planned-location")).toHaveCount(0);

  await expectClean(page, seen);
});

test("a room is rebuilt under a project name: a draft beside it, the cut-over, the old room renamed out of the way, the real name taken", async ({
  page,
  account,
}) => {
  test.setTimeout(180_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  const liveFilter = `hostname:prefix:${livePrefix}`;
  const [live = ""] = liveHosts;

  // The room in use, and beside it the workspace: a draft under the name of the project.
  await geography(page, americas);
  await newPlace(page, "New site in it", "site", worksSite);
  await newPlace(page, "New location in it", "location", oldRoom, { kind: "Room" });
  await geography(page, worksSite);
  await newPlace(page, "New location in it", "location", projectRoom, {
    kind: "Room",
    status: "Draft",
  });
  await importFile(
    page,
    "items",
    `items-${id}-live.csv`,
    ["hostname", "location"],
    liveHosts.map((host) => [host, oldRoom]),
  );

  // New equipment is given the draft room as its location, not only as a plan: the
  // form of a new item offers a draft place, and marks it.
  await page.goto("./items");
  await page.getByRole("button", { name: "New item" }).click();
  const form = region(page, "New item");
  await form.getByLabel("Hostname").fill(freshHost);
  await form.getByLabel("Location", { exact: true }).fill(projectName);
  const offered = form.getByRole("list", { name: "Locations that match" });
  await expect(offered.getByRole("listitem")).toContainText("Draft");
  await offered.getByRole("button", { name: projectRoom, exact: true }).click();
  await expect(form.getByTestId("chosen-location_hid")).toHaveText(projectRoom);
  await form.getByRole("button", { name: "Create item" }).click();
  await expect(page.getByRole("heading", { level: 1, name: freshHost })).toBeVisible();
  await expect(page.getByTestId("location")).toContainText(projectRoom);
  await expect(page.getByTestId("location")).toHaveAttribute("data-source", "own");

  // What is live in the old room is planned for the new one, by one bulk edit.
  await page.goto(`./items?filter=${encodeURIComponent(liveFilter)}`);
  await expect(page.getByTestId("grid-total")).toHaveText("2 items");
  await page.getByRole("button", { name: "Select all that match" }).click();
  await page.getByRole("button", { name: "Bulk edit" }).click();
  const bulk = page.getByTestId("bulk-edit");
  await bulk.getByLabel("Field to change").selectOption({ label: "Planned location" });
  await bulk.getByRole("button", { name: "Add", exact: true }).click();
  const line = bulk.getByRole("group", { name: "Planned location" });
  await chooseLocation(line, projectName, projectRoom, "Set to");
  await bulk.getByRole("button", { name: "Preview the change" }).click();
  await expect(count(page, "updated")).toHaveText("2");
  await bulk.getByRole("button", { name: "Apply 2 items" }).click();
  await expect(page.getByTestId("preview-applied")).toContainText("2 updated");

  // The cut-over is one change: the new room is made active, and what was planned for
  // it is there.
  await page.goto(
    `${pages.get(projectRoom)}?${new URLSearchParams({ filter: liveFilter, drafts: "1" }).toString()}`,
  );
  await expect(page.getByTestId("place-path")).toHaveText(projectRoom);
  await region(page, "Make active").getByRole("button", { name: "Make location active" }).click();
  await expect(page.getByTestId("activation-text")).toContainText(
    `Making ${projectName} active moves 2 items that are planned for it into it.`,
  );
  await page.getByRole("dialog").getByRole("button", { name: "Make location active" }).click();
  await expect(
    page.getByText(`${projectName} is active. What was planned for it is there now: 2 items.`),
  ).toBeVisible();
  await expectCounts(treeRow(page, projectRoom), 2, 2);
  await expectCounts(treeRow(page, oldRoom), 0, 0);

  // The old room, now empty, is retired. It keeps its name.
  await geography(page, oldRoom);
  await page.getByRole("button", { name: "Retire location" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Retire location" }).click();
  await expect(page.getByText("The location was retired.")).toBeVisible();

  // So the new room is refused the real name for now: the refusal is at the name, in
  // words.
  await geography(page, projectRoom);
  const details = region(page, "Details");
  await details.getByLabel("Name (required)").fill(oldRoomName);
  await details.getByRole("button", { name: "Save" }).click();
  await expect(details.locator('.alert-error[data-status="409"]')).toBeVisible();
  await expect(details.locator(".field-error")).toContainText("a location there has it");
  await expect(page.getByTestId("place-path")).toHaveText(projectRoom);

  // The retired room is still opened, and is renamed out of the way: its name is all
  // that is changed of it, and it stays retired.
  await geography(page, oldRoom);
  await expect(region(page, "Details")).toHaveCount(0);
  const rename = region(page, "Rename");
  await rename.getByLabel("Name (required)").fill(retiredName);
  await rename.getByRole("button", { name: "Rename" }).click();
  await expect(page.getByText("The location was renamed.")).toBeVisible();
  await expect(page.getByTestId("place-path")).toHaveText(path(worksSite, retiredName));
  await expect(region(page, "Retired")).toBeVisible();

  // The new room takes the real name, and what is in it is shown under that path:
  // nothing was written to an item.
  await geography(page, projectRoom);
  await region(page, "Details").getByLabel("Name (required)").fill(oldRoomName);
  await region(page, "Details").getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("The location was saved.")).toBeVisible();
  await expect(page.getByTestId("place-path")).toHaveText(oldRoom);
  await openItem(page, live);
  await expect(page.getByTestId("location")).toContainText(oldRoom);
  await expect(page.getByTestId("planned-location")).toHaveCount(0);
  await openItem(page, freshHost);
  await expect(page.getByTestId("location")).toContainText(oldRoom);

  await expectClean(page, seen, ["409 PATCH"]);
});

test("the audit list is sorted by the server over all of it, and paging keeps the order", async ({
  page,
  account,
}) => {
  const seen = await watch(page.context());
  await signIn(page, account);
  await page.goto("./audit");
  await expect(page.getByRole("heading", { level: 1, name: "Audit" })).toBeVisible();
  const table = page.locator("table.audit");
  await expect(table.locator("tbody tr").first()).toBeVisible();
  // The scenarios above wrote more events than one page holds.
  const pager = page.getByRole("navigation", { name: /^Pages of/ });
  const next = pager.getByRole("button", { name: "Next" });
  await expect(next).toBeEnabled();

  /** The request for the events in an order: `sort` as the address carries it. */
  const asked = (sort: string, more = "") =>
    page.waitForResponse((response) => {
      const url = new URL(response.url());
      return (
        url.pathname.endsWith("/api/v1/audit-events") &&
        url.searchParams.get("sort") === sort &&
        url.search.includes(more)
      );
    });
  /** What the cells of one column say, down the page on show. */
  const cells = async (header: string) => {
    const headers = await table.locator("thead th").allTextContents();
    const at = headers.findIndex((text) => text.trim().startsWith(header));
    expect(at, `the column ${header}`).toBeGreaterThanOrEqual(0);
    const texts = await table.locator(`tbody tr > *:nth-child(${at + 1})`).allTextContents();
    return texts.map((text) => text.trim().toLowerCase());
  };

  // A click on a header asks the server for the whole list in that order: the page on
  // show is not sorted by itself. The header says which column and which way.
  let answer = asked("action");
  await table.getByRole("button", { name: "Action", exact: true }).click();
  expect((await answer).status()).toBe(200);
  const actionHeader = table.getByRole("columnheader", { name: "Action" });
  await expect(actionHeader).toHaveAttribute("aria-sort", "ascending");
  await expect(async () => {
    const actions = await cells("Action");
    expect(actions.length).toBeGreaterThan(1);
    expect(actions).toEqual([...actions].sort());
  }).toPass();
  const firstAscending = (await cells("Action"))[0];

  // The next page is asked for in the same order, and the header still says so.
  answer = asked("action", "offset=");
  await next.click();
  expect((await answer).status()).toBe(200);
  await expect(actionHeader).toHaveAttribute("aria-sort", "ascending");
  await expect(async () => {
    const actions = await cells("Action");
    expect(actions).toEqual([...actions].sort());
    // What the second page begins with does not come before what the first began with.
    expect((actions[0] ?? "") >= (firstAscending ?? "")).toBe(true);
  }).toPass();

  // Another click turns the order round, over the whole list, from the first page.
  answer = asked("-action");
  await table.getByRole("button", { name: "Action", exact: true }).click();
  const turned = await answer;
  expect(turned.status()).toBe(200);
  expect(new URL(turned.url()).searchParams.get("offset") ?? "0").toBe("0");
  await expect(actionHeader).toHaveAttribute("aria-sort", "descending");
  await expect(async () => {
    const actions = await cells("Action");
    expect(actions).toEqual([...actions].sort().reverse());
  }).toPass();

  // What the page composes from a list of changes is not sorted by the server: with
  // more events than a page holds, its header is plain.
  await expect(table.getByRole("button", { name: "What changed", exact: true })).toHaveCount(0);

  await expectClean(page, seen);
});
