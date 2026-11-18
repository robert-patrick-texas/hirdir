// The browser scenarios of release 0.5.0 of a shipping address typed once, and of a room
// rebuilt: a shipping address typed once on a region, inherited, taken from the street
// address with one tick, overridden, and the override taken back (D-115, D-116), and the
// technical contact of the region marked in the same way; then a room rebuilt under the
// name of a project, as a draft beside the room in use, with the cut-over, the old room
// renamed out of the way and the real name taken.
//
// These were the later scenarios of geography.spec.ts until they were to run beside it
// (rule 7 of support.ts): this file lays out for itself the region, and loads the people
// and the technical contact of the region, that it took from the scenarios before them
// there. What the files of places do alike is in geographySteps.ts.
//
// The file keeps the rules of support.ts. It signs in as an Admin of its own, and its
// mark is in every name it gives a record: the places, the hostnames, the contacts and
// the files it loads. Every count is read through a filter that keeps this file's items
// and no others. Nothing is changed that another file reads: no setting, no list of
// choices, no account. The addresses are of example.net and the numbers of the range
// kept for fiction. The two scenarios need nothing of each other but the region at the
// top, which the first lays out.

import { expect } from "@playwright/test";
import {
  assign,
  chooseLocation,
  expectCounts,
  inForce,
  offered,
  places,
  treeRow,
} from "./geographySteps";
import { count, importFile, openItem, region, whenApplied } from "./structure";
import { expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const id = mark("geography-shipping");

const path = (...names: string[]) => names.join(" > ");
// The region at the top, whose technical contact a site inherits.
const americas = `Americas ${id}`;

// The items, and the filter that keeps them and no others.
const filter = `hostname:prefix:${id}-`;

// The shipping address that is typed once: a region that has one, a site that inherits
// it, a site whose deliveries go to its own door, and a site with another destination.
const north = path(americas, `North ${id}`);
const sharing = path(north, `Depot A ${id}`);
const ownDoor = path(north, `Depot B ${id}`);
const elsewhere = path(north, `Depot C ${id}`);

// The people.
const lee = `Lee Okafor ${id}`;
const leeMail = `lee.okafor.${id}@example.net`;
const priya = `Priya Raman ${id}`;
const priyaMail = `priya.raman.${id}@example.net`;

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

// The places as they are made, and the Geography page counting this file's items.
const { pages, remember, geography, newPlace } = places(filter);

test("a shipping address is typed once: inherited, the street address by a tick, or an override", async ({
  page,
  account,
}) => {
  test.setTimeout(180_000);
  const seen = await watch(page.context());
  await signIn(page, account);

  // What the scenario needs of what came before it in geography.spec.ts, under names of
  // this file: a region at the top with a technical contact of its own, and another
  // person to assign.
  await geography(page);
  await newPlace(page, "New region", "region", americas);
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
  await geography(page, americas);
  await assign(page, "Technical", offered(priya, priyaMail), priya);
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
  remember(page, north);
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
  await whenApplied(page, 2);

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
