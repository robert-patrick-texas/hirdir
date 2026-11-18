// The browser scenarios of release 0.5.0 of an owner outside the team, and the plan of a
// new site:
//
//   S28  An owner outside the team is made with no reason, which is refused, then with
//        one; an item given to it is marked as an exception, with the owner's reason.
//
// On the way: the people of an owner; and then the plan of a new site: spares and a
// stack given a planned location in a draft site, which move in by themselves when the
// site is made active, the switches of the stack with it (D-125, D-127, D-129). The stack
// is given the owner outside the team, and its switches have it from the stack.
//
// These were the later scenarios of geography.spec.ts until they were to run beside it
// (rule 7 of support.ts): this file lays out for itself the region, and loads the people,
// the items and the group, that it took from the scenarios before them there. What the
// files of places do alike is in geographySteps.ts.
//
// The file keeps the rules of support.ts. It signs in as an Admin of its own, and its
// mark is in every name it gives a record: the places, the hostnames, the contacts, the
// owner, the groups and the files it loads. The file's name, and so the mark, holds no
// word that a label it looks for holds: a form that lists the switches of a stack labels
// each input by its hostname, and `getByLabel("Owner")` would find "owners" in them.
// Every count is read through a filter that keeps this file's items and no others.
// Nothing is changed that another file reads: no setting, no list of choices, no
// account. The addresses are of example.net and the numbers of the range kept for
// fiction. The scenarios build on one another and run in order: the plan gives the stack
// the owner that S28 made.

import { expect } from "@playwright/test";
import { chooseLocation, expectCounts, offered, places, treeRow } from "./geographySteps";
import {
  count,
  importFile,
  main,
  openGroup,
  openItem,
  pick,
  region,
  whenApplied,
} from "./structure";
import { expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const id = mark("geography-plans");

const path = (...names: string[]) => names.join(" > ");
// The region at the top, where the new site and the store room are.
const americas = `Americas ${id}`;

// The items, and the filter that keeps them and no others.
const prefix = `${id}-`;
const filter = `hostname:prefix:${prefix}`;
const second = `${prefix}sw-02`;
const fourth = `${prefix}sw-04`;
const group = `${prefix}closet`;

// The people.
const dana = `Dana Whitfield ${id}`;
const danaMail = `dana.whitfield.${id}@example.net`;
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

// The places as they are made, and the Geography page counting this file's items.
const { pages, geography, newPlace } = places(filter);

test("S28: an owner outside the team says why, once, and what is given to it is marked with that", async ({
  page,
  account,
}) => {
  test.setTimeout(180_000);
  const seen = await watch(page.context());
  await signIn(page, account);

  // What the scenario needs of what came before it in geography.spec.ts, under names of
  // this file: a region at the top, two people, two items and a device group.
  await geography(page);
  await newPlace(page, "New region", "region", americas);
  await importFile(
    page,
    "contacts",
    `contacts-${id}.csv`,
    ["name", "email", "phone"],
    [
      [dana, danaMail, "+1 555 0100"],
      [priya, priyaMail, "+1 555 0103"],
    ],
  );
  await importFile(page, "items", `items-${id}.csv`, ["hostname"], [[second], [fourth]]);
  await importFile(
    page,
    "device_groups",
    `device-groups-${id}.csv`,
    ["name", "type"],
    [[group, "custom"]],
  );

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
  await whenApplied(page, 1);

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
  await whenApplied(page, 2);

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
