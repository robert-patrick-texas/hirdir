// The operator, in the browser: a short label with a person behind it, which items,
// device groups and places are given (D-122, D-124).
//
//   Labels are made, one by hand and two by a file. A site is given one, and an item at
//   a location of that site, with no operator of its own or of a group, shows it as
//   inherited from the site. A stack is given another: its switches show it as inherited
//   from the stack, and so does a power supply in one of them. One switch is given a
//   label of its own, and one is given its own and returned to the one from the stack.
//   The grid shows the label as a mark, in a column that is hidden until asked for.
//
//   A label is handed over to another person, and its items show that person at once.
//   It is left open, and its items show it as open. It is released, and its items fall
//   back to the operator of their site; brought back, they have it again.
//
//   What nobody is assigned to is counted, on a view of this file's items, and found
//   from the first page. A bulk edit assigns the rest. A contact says which labels it
//   stands behind.
//
//   The scoreboard, on a view of this file's items: two operators with different loads,
//   the heavier first, with their shares; what nobody is assigned to; what is under an
//   open label; and the operators involved at the site.
//
// The file keeps the rules of support.ts. It signs in as an Admin of its own, and its
// mark is in every name it gives a record: the labels, the hostnames, the stack, the
// places, the contacts and the files it loads. Every count is read through a filter that
// keeps this file's items and no others; the numbers on the first page, which are of the
// whole inventory, are never compared with anything. Nothing is changed that another
// file reads. The addresses are of example.net. The scenarios run in order: the later
// ones use what the earlier ones made.

import { readFile } from "node:fs/promises";
import { expect, type Locator, type Page } from "@playwright/test";
import { count, importFile, main, openItem, pick, region, summary } from "./structure";
import { expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const id = mark("operators");
const prefix = `${id}-`;
const filter = `hostname:prefix:${prefix}`;
// Three switches for a stack, a router in the room, and a router that is nowhere.
const switches = [1, 2, 3].map((place) => `${prefix}sw-0${place}`);
const [first = "", second = "", third = ""] = switches;
const placed = `${prefix}rtr-01`;
const nowhere = `${prefix}rtr-02`;
const supply = `${prefix}sw-01-ps-a`;
const stack = `${prefix}stack`;

// The places: a site with an operator, and a room in it with none.
const regionPath = `Region ${id}`;
const sitePath = `${regionPath} > Site ${id}`;
const roomPath = `${sitePath} > Room ${id}`;

// The people of the team, and the labels that stand for them.
const lee = `Lee Marchetti ${id}`;
const leeMail = `lee.marchetti.${id}@example.net`;
const ana = `Ana Okonkwo ${id}`;
const anaMail = `ana.okonkwo.${id}@example.net`;
const mio = `Mio Tanaka ${id}`;
const mioMail = `mio.tanaka.${id}@example.net`;
// A label is at most forty characters: a short code, and the mark.
const core = `NE1-${id}`;
const edge = `NE2-${id}`;
const local = `SITE-${id}`;

// The scoreboard: a model with a support weight, and items of it in production, three
// under one label, one under another and one that nobody is assigned to.
const scoreVendor = `Example Networks ${id}`;
const scorePid = `EN-SCORE-${id}`;
const scorePrefix = `${prefix}score-`;
const scoreFilter = `hostname:prefix:${scorePrefix}`;

// The pages of what is made, as they are made.
const pages = new Map<string, string>();

/** A contact as a search offers it: its name, and its address beside it. */
function offered(name: string, mail: string): string {
  return `${name} (${mail})`;
}

/** Search for an operator in a form's field, by its label, and choose it as it is offered. */
async function chooseOperator(form: Locator, label: string, person: string, field = "Operator") {
  await form.getByLabel(field, { exact: true }).fill(label);
  await form
    .getByRole("list", { name: "Operators that match" })
    .getByRole("button", { name: `${label} · ${person}`, exact: true })
    .click();
}

/** The operator in force, as the page of an item says it, and the mark within it. */
function operator(page: Page): Locator {
  return page.getByTestId("operator");
}

function markIn(within: Locator, label: string): Locator {
  return within.locator(".operator-mark", { hasText: label });
}

/** Make a place with one of the buttons of the Geography page, by its path. */
async function newPlace(
  page: Page,
  button: string,
  what: "region" | "site" | "location",
  path: string,
  operatorOf?: { label: string; person: string },
) {
  await page.getByRole("button", { name: button, exact: true }).click();
  const form = region(page, `New ${what}`);
  await form.getByLabel("Name (required)").fill(path.split(" > ").at(-1) ?? "");
  if (operatorOf) await chooseOperator(form, operatorOf.label, operatorOf.person);
  await form.getByRole("button", { name: `Create ${what}` }).click();
  await expect(page.getByTestId("place-path")).toHaveText(path);
  pages.set(path, `.${new URL(page.url()).pathname.replace(/^.*(?=\/geography\/)/, "")}`);
}

/** Open the page of an operator from the list, by its label, released ones among them. */
async function openOperator(page: Page, label: string) {
  await page.goto(`./operators?filter=${encodeURIComponent(`label:eq:${label}`)}`);
  await page.getByLabel("Include archived").check();
  await page.getByTestId("grid-operators").getByRole("link", { name: label, exact: true }).click();
  await expect(page.getByTestId("operator-heading")).toContainText(label);
}

test("labels are made; a site, a stack and a switch are given one, and what is beneath has it", async ({
  page,
  account,
}) => {
  test.setTimeout(240_000);
  const seen = await watch(page.context());
  await signIn(page, account);

  await importFile(
    page,
    "contacts",
    `contacts-${id}.csv`,
    ["name", "email"],
    [
      [lee, leeMail],
      [ana, anaMail],
      [mio, mioMail],
    ],
  );

  // A label is made on the Operators page: short, with a colour, and a person behind it
  // who is chosen by searching contacts.
  await main(page).getByRole("link", { name: "Operators" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Operators" })).toBeVisible();
  await page.getByRole("button", { name: "New operator" }).click();
  const form = region(page, "New operator");
  await form.getByLabel("Label (required)").fill(core);
  await form.getByLabel("Colour").fill("#1f6feb");
  await form.getByLabel("Person behind it", { exact: true }).fill(leeMail.split("@")[0] ?? "");
  await form
    .getByRole("list", { name: "Contacts that match" })
    .getByRole("button", { name: offered(lee, leeMail), exact: true })
    .click();
  await form.getByRole("button", { name: "Create operator" }).click();
  await expect(page.getByTestId("operator-heading")).toContainText(core);
  await expect(page.getByTestId("operator-person")).toContainText(lee);
  await expect(page.getByTestId("operator-person")).toHaveAttribute("data-open", "false");
  pages.set(core, new URL(page.url()).pathname);
  // Two more come by a file: a label names its person by the email address, or nobody.
  await importFile(
    page,
    "operators",
    `operators-${id}.csv`,
    ["label", "colour", "contact"],
    [
      [edge, "#2da44e", anaMail],
      [local, "", leeMail],
    ],
  );
  // The list shows the labels, each with the person behind it.
  await page.goto(`./operators?filter=${encodeURIComponent(`label:contains:${id}`)}`);
  await expect(page.getByTestId("grid-total")).toHaveText("3 operators");
  const list = page.getByTestId("grid-operators");
  await expect(
    list.locator("[row-id]", { hasText: edge }).locator('[col-id="contact.name"]'),
  ).toHaveText(ana);

  // A site with an operator, chosen by its label, and a room in it with none.
  await main(page).getByRole("link", { name: "Geography" }).click();
  await newPlace(page, "New region", "region", regionPath);
  await newPlace(page, "New site in it", "site", sitePath, { label: local, person: lee });
  const siteOperator = page.getByTestId("place-operator");
  await expect(siteOperator).toHaveAttribute("data-standing", "own");
  await expect(markIn(siteOperator, local)).toBeVisible();
  await expect(siteOperator).toContainText("Set here");
  await newPlace(page, "New location in it", "location", roomPath);
  // The room has the site's, as inherited, with the same marks as a shipping address.
  const roomOperator = page.getByTestId("place-operator");
  await expect(roomOperator).toHaveAttribute("data-standing", "inherited");
  await expect(markIn(roomOperator, local)).toBeVisible();
  await expect(roomOperator).toContainText(`Inherited from the site ${sitePath}`);
  await expect(region(page, "Details").getByTestId("place-operator-note")).toHaveAttribute(
    "data-standing",
    "inherited",
  );

  await importFile(
    page,
    "items",
    `items-${id}.csv`,
    ["hostname", "location"],
    [...switches.map((host) => [host, roomPath]), [placed, roomPath], [nowhere, ""]],
  );

  // An item with no operator of its own, in no group, has the one of where it is: here
  // the site's, since the room has none. A new device is never nobody's.
  await openItem(page, placed);
  await expect(operator(page)).toHaveAttribute("data-source", "site");
  await expect(markIn(operator(page), local)).toBeVisible();
  await expect(operator(page)).toContainText(lee);
  await expect(operator(page)).toContainText("Inherited");
  await expect(operator(page).getByRole("link", { name: `the site ${sitePath}` })).toBeVisible();
  // An item that is nowhere, with none, is nobody's.
  await openItem(page, nowhere);
  await expect(operator(page)).toHaveAttribute("data-source", "none");
  await expect(operator(page)).toHaveText("Nobody is assigned");

  // The stack, with its three switches, and its operator chosen by the label.
  await main(page).getByRole("link", { name: "Groups" }).click();
  await page.getByRole("button", { name: "New group" }).click();
  const group = region(page, "New group");
  await group.getByLabel("Name (required)").fill(stack);
  await group.getByLabel("Type").selectOption("stack");
  for (const host of switches) {
    await pick(group, "Find an item to add", `${prefix}sw`, host);
  }
  await expect(group.getByTestId("chosen-operator_hid")).toHaveText("None of its own");
  await chooseOperator(group, core, lee);
  await expect(group.getByTestId("chosen-operator_hid")).toHaveText(`${core} · ${lee}`);
  await group.getByRole("button", { name: "Create group" }).click();
  await expect(page.getByRole("heading", { level: 1, name: stack })).toBeVisible();
  const groupPage = new URL(page.url()).pathname;
  await expect(page.getByTestId("group-operator")).toHaveAttribute("data-source", "own");
  await expect(markIn(page.getByTestId("group-operator"), core)).toBeVisible();
  await expect(page.getByTestId("group-operator-members")).toContainText(
    "its members have this operator unless they have their own",
  );

  // A switch of the stack shows that label as inherited from the stack, which comes
  // before the place it is at. The mark is the label, a link to the operator, with the
  // person beside it.
  await openItem(page, first);
  await expect(operator(page)).toHaveAttribute("data-source", "device_group");
  const shown = markIn(operator(page), core);
  await expect(shown).toHaveAttribute("data-open", "false");
  expect(
    new URL((await shown.getByRole("link").getAttribute("href")) ?? "", page.url()).pathname,
  ).toBe(pages.get(core));
  await expect(operator(page)).toContainText(lee);
  const from = operator(page).getByRole("link", { name: `the group ${stack}` });
  await expect(from).toBeVisible();
  expect(new URL((await from.getAttribute("href")) ?? "", page.url()).pathname).toBe(groupPage);
  const details = region(page, "Details");
  await expect(details.getByTestId("chosen-operator_hid")).toHaveText("None of its own");
  await expect(details.getByTestId("operator-note")).toHaveAttribute("data-source", "device_group");
  await expect(details.getByTestId("operator-note")).toContainText(
    `Inherited from the group ${stack}`,
  );

  // A power supply in that switch has it too, from the stack of the switch it is in.
  await region(page, "Minor items").getByRole("button", { name: "Add a minor item" }).click();
  const minor = region(page, "New minor item");
  await minor.getByLabel("Hostname").fill(supply);
  await minor.getByLabel("Position").fill("PS-A");
  await minor.getByRole("button", { name: "Create minor item" }).click();
  await expect(page.getByText(`${supply} was added to ${first}.`)).toBeVisible();
  await page.getByTestId("minor-items").getByRole("link", { name: supply }).click();
  await expect(page.getByRole("heading", { level: 1, name: supply })).toBeVisible();
  await expect(operator(page)).toHaveAttribute("data-source", "device_group");
  await expect(markIn(operator(page), core)).toBeVisible();
  await expect(operator(page).getByRole("link", { name: `the group ${stack}` })).toBeVisible();

  // One switch is looked after by somebody else: it is given a label of its own.
  await openItem(page, second);
  await chooseOperator(region(page, "Details"), edge, ana);
  await region(page, "Details").getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("The item was saved.")).toBeVisible();
  await expect(operator(page)).toHaveAttribute("data-source", "own");
  await expect(markIn(operator(page), edge)).toBeVisible();
  await expect(operator(page)).toContainText("Set here");
  await expect(operator(page)).not.toContainText("Inherited");
  await expect(region(page, "Details").getByTestId("operator-note")).toHaveCount(0);

  // Another is given its own and returned: cleared, it has the one of the stack again.
  await openItem(page, third);
  await chooseOperator(region(page, "Details"), edge, ana);
  await region(page, "Details").getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("The item was saved.")).toBeVisible();
  await expect(operator(page)).toHaveAttribute("data-source", "own");
  const again = region(page, "Details");
  await expect(again.getByTestId("chosen-operator_hid")).toHaveText(`${edge} · ${ana}`);
  await again.getByRole("button", { name: "Clear the operator" }).click();
  await expect(again.getByTestId("chosen-operator_hid")).toHaveText("None of its own");
  await again.getByRole("button", { name: "Save" }).click();
  await expect(operator(page)).toHaveAttribute("data-source", "device_group");
  await expect(markIn(operator(page), core)).toBeVisible();

  // The grid has an Operator column, hidden until it is asked for: the label in force
  // as a mark, lighter where it is inherited, and found by that label.
  await page.goto(`./items?filter=${encodeURIComponent(filter)}&minor=1`);
  await expect(page.getByTestId("grid-total")).toHaveText("6 items");
  const grid = page.getByTestId("grid-items");
  await expect(grid.locator('[role="columnheader"][col-id="operator.label"]')).toHaveCount(0);
  await page.getByText("Columns", { exact: true }).click();
  const columns = page.getByRole("group", { name: "Columns to show" });
  await expect(columns.getByLabel("Operator", { exact: true })).not.toBeChecked();
  await columns.getByLabel("Operator", { exact: true }).check();
  // The grid draws only the columns in view: room is made for the one looked at here.
  for (const column of ["Vendor", "PID", "Serial number", "Health", "Tags", "LDoS"]) {
    await columns.getByLabel(column, { exact: true }).uncheck();
  }
  await page.getByText("Columns", { exact: true }).click();
  const cell = (host: string) =>
    grid
      .locator("[row-id]", { has: page.getByRole("link", { name: host, exact: true }) })
      .locator('[col-id="operator.label"]');
  await expect(cell(first)).toHaveText(core);
  await expect(cell(first)).toHaveClass(/cell-inherited/);
  await expect(cell(first).getByRole("link", { name: core })).toBeVisible();
  await expect(cell(supply)).toHaveText(core);
  await expect(cell(second)).toHaveText(edge);
  await expect(cell(second)).not.toHaveClass(/cell-inherited/);
  await expect(cell(placed)).toHaveText(local);
  await expect(cell(nowhere)).toHaveText("");
  // The person behind the label, and where it came from, is what the cell says when it
  // is pointed at.
  await cell(placed).hover();
  await expect(page.locator(".ag-tooltip")).toHaveText(
    `${lee} · Inherited from the site ${sitePath}`,
  );
  await page.goto(
    `./items?filter=${encodeURIComponent(`${filter} operator.label:eq:${core}`)}&minor=1`,
  );
  await expect(page.getByTestId("grid-total")).toHaveText("3 items");

  await expectClean(page, seen);
});

test("a label is handed over, left open, released and brought back, and its items follow at once", async ({
  page,
  account,
}) => {
  test.setTimeout(240_000);
  const seen = await watch(page.context());
  await signIn(page, account);

  // The label of the stack says what it is on: two switches and a power supply have it
  // from the stack, which is given it as its own.
  await openOperator(page, core);
  const on = page.getByTestId("operator-on");
  await expect(on.getByRole("link", { name: "3 items" })).toBeVisible();
  await expect(on.getByRole("link", { name: "1 device group" })).toBeVisible();

  // A new hire takes over: another person is put behind the label, in one place, and
  // every item the label is on shows that person at once. Nothing is written to them.
  const hand = region(page, "Hand over, or leave open");
  await hand.getByLabel("Hand over to", { exact: true }).fill(mioMail.split("@")[0] ?? "");
  await hand
    .getByRole("list", { name: "Contacts that match" })
    .getByRole("button", { name: offered(mio, mioMail), exact: true })
    .click();
  await hand.getByRole("button", { name: "Hand over", exact: true }).click();
  await expect(page.getByText(`${core} was handed over to ${mio}.`)).toBeVisible();
  await expect(page.getByTestId("operator-person")).toContainText(mio);
  await openItem(page, first);
  await expect(markIn(operator(page), core)).toBeVisible();
  await expect(operator(page)).toContainText(mio);
  await expect(operator(page)).not.toContainText(lee);
  await expect(operator(page)).toHaveAttribute("data-source", "device_group");

  // The person is away: the label is left open. What it is on still shows it, as open.
  await openOperator(page, core);
  await region(page, "Hand over, or leave open")
    .getByRole("button", { name: "Leave open" })
    .click();
  await expect(page.getByText(`${core} is left open`)).toBeVisible();
  await expect(page.getByTestId("operator-person")).toHaveAttribute("data-open", "true");
  await expect(page.getByTestId("operator-heading")).toContainText("open");
  await openItem(page, first);
  await expect(markIn(operator(page), core)).toHaveAttribute("data-open", "true");
  await expect(markIn(operator(page), core)).toContainText("open");
  await expect(operator(page)).not.toContainText(mio);
  // The item list finds what is under an open label, and the first page is the way there.
  await page.goto(
    `./items?filter=${encodeURIComponent(`${filter} operator.is_open:eq:true`)}&minor=1`,
  );
  await expect(page.getByTestId("grid-total")).toHaveText("3 items");
  await page.goto("./");
  const open = page.getByTestId("open-assignments");
  await expect(open).toContainText(/\d+ components? (is|are) under an open label/);
  await open.getByRole("link").click();
  await expect(page.getByLabel("Filter", { exact: true })).toHaveValue("operator.is_open:eq:true");

  // The label is released: it stands for nothing, and each item it was on has the
  // operator of the next level up. The switches are in the room, whose site has one.
  await openOperator(page, core);
  await page.getByRole("button", { name: "Release", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("the operator of the next level up");
  await page.getByRole("dialog").getByRole("button", { name: "Release", exact: true }).click();
  await expect(page.getByText(`${core} was released.`)).toBeVisible();
  await expect(page.getByTestId("operator-heading")).toContainText("released");
  await openItem(page, first);
  await expect(operator(page)).toHaveAttribute("data-source", "site");
  await expect(markIn(operator(page), local)).toBeVisible();
  await expect(operator(page).getByRole("link", { name: `the site ${sitePath}` })).toBeVisible();
  // The list of operators leaves a released label out until Include archived is on.
  // The switch is remembered for each reader, and was turned on above to reach the label.
  await page.goto(`./operators?filter=${encodeURIComponent(`label:eq:${core}`)}`);
  await page.getByLabel("Include archived").uncheck();
  await expect(page.getByTestId("grid-total")).toHaveText("No operators");
  await page.getByLabel("Include archived").check();
  await expect(page.getByTestId("grid-total")).toHaveText("1 operator");
  // A released label is not offered to a form.
  await openItem(page, nowhere);
  await region(page, "Details").getByLabel("Operator", { exact: true }).fill(core);
  await expect(region(page, "Details").getByText("No operator matches.")).toBeVisible();

  // Brought back, the label is on what it was on again: still open, until somebody is
  // put behind it.
  await openOperator(page, core);
  await region(page, "Released").getByRole("button", { name: "Bring back" }).click();
  await expect(page.getByText(`${core} is back`)).toBeVisible();
  await openItem(page, first);
  await expect(operator(page)).toHaveAttribute("data-source", "device_group");
  await expect(markIn(operator(page), core)).toHaveAttribute("data-open", "true");

  await expectClean(page, seen);
});

test("what nobody is assigned to is counted and found, and a bulk edit assigns the rest", async ({
  page,
  account,
}) => {
  test.setTimeout(180_000);
  const seen = await watch(page.context());
  await signIn(page, account);

  // The summary of this file's items, by operator. Each row is the mark of a label: two
  // switches under the label of the stack, one with its own, the router that has the
  // site's, and the router that nobody is assigned to.
  await summary(page, filter, "operator");
  await expect(page.getByLabel("By", { exact: true })).toHaveValue("operator");
  const table = page.getByTestId("summary-rows");
  const rows = table.locator("tbody tr");
  await expect(rows).toHaveCount(4);
  const row = (label: string) =>
    rows.filter({ has: page.locator(".operator-mark", { hasText: label }) });
  await expect(row(core).locator("td").nth(1)).toHaveText("2");
  await expect(row(core)).toContainText("open");
  await expect(row(edge).locator("td").nth(1)).toHaveText("1");
  await expect(row(edge)).toContainText(ana);
  await expect(row(local).locator("td").nth(1)).toHaveText("1");
  const nobody = table.locator('tbody tr[data-key=""]');
  await expect(nobody).toContainText("Nobody is assigned");
  await expect(nobody.locator("td").nth(1)).toHaveText("1");
  // The management report is by operator too.
  await page.goto(
    `./reports/management?${new URLSearchParams({ filter, by: "operator" }).toString()}`,
  );
  await expect(page.getByTestId("management-rows").locator('tbody tr[data-key=""]')).toContainText(
    "Nobody is assigned",
  );

  // The first page says how many components nobody is assigned to, in the whole
  // inventory, and is the way to them. The number is not this file's to compare.
  await page.goto("./");
  const unassigned = page.getByTestId("unassigned");
  await expect(unassigned).toContainText(/\d+ components? ha(s|ve) no operator/);
  await unassigned.getByRole("link").first().click();
  await expect(page.getByRole("heading", { level: 1, name: "Items" })).toBeVisible();
  await expect(page.getByLabel("Filter", { exact: true })).toHaveValue(
    "effective.operator_hid:empty:true",
  );

  // A bulk edit assigns the rest: the item of this file that nobody is assigned to.
  await page.goto(
    `./items?filter=${encodeURIComponent(`${filter} effective.operator_hid:empty:true`)}`,
  );
  await expect(page.getByTestId("grid-total")).toHaveText("1 item");
  await page.getByRole("button", { name: "Select all that match" }).click();
  await page.getByRole("button", { name: "Bulk edit" }).click();
  const bulk = page.getByTestId("bulk-edit");
  await bulk.getByLabel("Field to change").selectOption({ label: "Operator" });
  await bulk.getByRole("button", { name: "Add", exact: true }).click();
  const line = bulk.getByRole("group", { name: "Operator" });
  await chooseOperator(line, edge, ana, "Set to");
  await expect(line.getByTestId("chosen-operator")).toHaveText(`${edge} · ${ana}`);
  await bulk.getByRole("button", { name: "Preview the change" }).click();
  await expect(count(page, "updated")).toHaveText("1");
  await bulk.getByRole("button", { name: "Apply 1 item" }).click();
  await expect(page.getByTestId("preview-applied")).toContainText("1 updated");
  await summary(page, filter, "operator");
  await expect(rows).toHaveCount(3);
  await expect(nobody).toHaveCount(0);
  await expect(row(edge).locator("td").nth(1)).toHaveText("2");

  // A contact says which labels it stands behind, as their marks.
  await page.goto(`./contacts?filter=${encodeURIComponent(`email:eq:${anaMail}`)}`);
  await page.getByTestId("grid-contacts").getByRole("link", { name: ana, exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: ana })).toBeVisible();
  const behind = page.getByTestId("contact-operators");
  await expect(behind).toContainText("Behind 1 operator");
  await markIn(behind, edge).getByRole("link").click();
  await expect(page.getByTestId("operator-heading")).toContainText(edge);
  // The label says what it is on, and is the way to the groups and places given it.
  await openOperator(page, local);
  await expect(
    page.getByTestId("operator-places").getByRole("link", { name: sitePath, exact: true }),
  ).toBeVisible();
  // The Operator column of the groups, hidden until it is asked for.
  await page.goto(`./groups?filter=${encodeURIComponent(`name:eq:${stack}`)}`);
  await expect(page.getByTestId("grid-total")).toHaveText("1 group");
  await page.getByText("Columns", { exact: true }).click();
  const columns = page.getByRole("group", { name: "Columns to show" });
  await expect(columns.getByLabel("Operator", { exact: true })).not.toBeChecked();
  await columns.getByLabel("Operator", { exact: true }).check();
  await page.getByText("Columns", { exact: true }).click();
  await expect(
    page.getByTestId("grid-device-groups").locator("[row-id]").locator('[col-id="operator.label"]'),
  ).toContainText(core);

  await expectClean(page, seen);
});

test("the scoreboard: who looks after how much, and where", async ({ page, account }, testInfo) => {
  test.setTimeout(180_000);
  const seen = await watch(page.context());
  await signIn(page, account);

  // A model with a support weight of 1.50, and five items of it in production: three
  // under the label that Ana is behind, one under the label that is open, and one that
  // nobody is assigned to and that is nowhere.
  await importFile(
    page,
    "catalog_entries",
    `catalog-entries-${id}.csv`,
    ["vendor", "pid", "support_weight"],
    [[scoreVendor, scorePid, "1.50"]],
  );
  const item = (place: number, label: string, location: string) => [
    scoreVendor,
    scorePid,
    `SC${id.toUpperCase()}0${place}`,
    `${scorePrefix}0${place}`,
    "Prod",
    label,
    location,
  ];
  await importFile(
    page,
    "items",
    `items-${id}-score.csv`,
    ["vendor", "pid", "serial_number", "hostname", "lifecycle_state", "operator", "location"],
    [
      item(1, edge, roomPath),
      item(2, edge, roomPath),
      item(3, edge, roomPath),
      item(4, core, roomPath),
      item(5, "", ""),
    ],
  );

  // The scoreboard is a tab of the reports, and the first page is a way to it.
  await page.goto("./");
  await page.getByTestId("scoreboard-link").click();
  await expect(page.getByRole("heading", { level: 1, name: "Scoreboard" })).toBeVisible();
  await expect(
    page.getByRole("navigation", { name: "Reports" }).getByRole("link", { name: "Scoreboard" }),
  ).toHaveAttribute("aria-current", "page");
  await page.goto(
    `./reports/scoreboard?${new URLSearchParams({ filter: scoreFilter }).toString()}`,
  );

  // The operators, the most support weight first: 4.50 before 1.50, each with its share
  // of the 7.50 in view. A weight is written with or without the zero that says nothing.
  const operators = page.getByTestId("score-operators");
  const ranked = operators.locator("tbody tr");
  await expect(ranked).toHaveCount(2);
  await expect(ranked.nth(0)).toHaveAttribute("data-label", edge);
  await expect(ranked.nth(1)).toHaveAttribute("data-label", core);
  const heavier = ranked.nth(0);
  await expect(markIn(heavier, edge)).toBeVisible();
  await expect(heavier).toContainText(ana);
  await expect(heavier.locator('[data-measure="components"]')).toHaveText("3");
  await expect(heavier.locator('[data-measure="nodes"]')).toHaveText("3");
  await expect(heavier.locator('[data-measure="items"]')).toHaveText("3");
  await expect(heavier.locator('[data-measure="weight"]')).toHaveText(/^4\.50?$/);
  await expect(heavier.locator('[data-measure="share"] .share-text')).toHaveText("60%");
  await expect(heavier.getByRole("meter")).toHaveAttribute("value", "60");
  const lighter = ranked.nth(1);
  await expect(markIn(lighter, core)).toHaveAttribute("data-open", "true");
  await expect(lighter.locator('[data-measure="components"]')).toHaveText("1");
  await expect(lighter.locator('[data-measure="share"] .share-text')).toHaveText("20%");
  // What nobody is assigned to is set apart beneath, and what is under an open label is said.
  const nobody = page.getByTestId("score-nobody");
  await expect(nobody).toContainText("Nobody is assigned");
  await expect(nobody.locator('[data-measure="components"]')).toHaveText("1");
  await expect(nobody.locator('[data-measure="weight"]')).toHaveText(/^1\.50?$/);
  await expect(page.getByTestId("score-open")).toContainText(
    "Under 1 label that nobody is behind for now: 1 component, 1 item",
  );

  // The sites: the one site, with the operators involved there and how much each has,
  // the heavier first; and the item that is nowhere beneath, which is nobody's.
  const sites = page.getByTestId("score-sites");
  const site = sites.locator("tbody tr");
  await expect(site).toHaveCount(1);
  await expect(site).toHaveAttribute("data-path", sitePath);
  await expect(site.locator('[data-measure="components"]')).toHaveText("4");
  await expect(site.locator('[data-measure="weight"]')).toHaveText(/^6(\.00?)?$/);
  const there = site.getByTestId("involved").locator("li");
  await expect(there).toHaveCount(2);
  await expect(markIn(there.nth(0), edge)).toBeVisible();
  await expect(there.nth(0)).toContainText("3 components");
  await expect(markIn(there.nth(1), core)).toBeVisible();
  await expect(there.nth(1)).toContainText("1 component");
  const nowhereRow = page.getByTestId("score-nowhere");
  await expect(nowhereRow.locator('[data-measure="components"]')).toHaveText("1");
  await expect(nowhereRow.getByTestId("involved")).toHaveText(/Nobody is assigned · 1 component/);

  // A table is saved as a file, from what the page holds, in the order it is shown.
  const saved = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export CSV of the operators" }).click();
  const download = await saved;
  expect(download.suggestedFilename()).toBe("hirdir-scoreboard-operators.csv");
  const path = testInfo.outputPath(download.suggestedFilename());
  await download.saveAs(path);
  const lines = (await readFile(path, "utf8")).trimEnd().split("\r\n");
  expect(lines).toHaveLength(4);
  expect(lines[0]).toContain("operator,person,open,components");
  expect(lines[1]).toContain(`,${edge},${ana},false,3,3,3,`);
  expect(lines[2]).toContain(`,${core},,true,1,1,1,`);
  expect(lines[3]).toMatch(/^,,,,1,1,1,/);

  // Each row is the way to its items, and a site to its place.
  await heavier.getByRole("link", { name: "items" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Items" })).toBeVisible();
  await expect(page.getByTestId("grid-total")).toHaveText("3 items");
  await page.goto(
    `./reports/scoreboard?${new URLSearchParams({ filter: scoreFilter }).toString()}`,
  );
  await page.getByTestId("score-sites").getByRole("link", { name: sitePath, exact: true }).click();
  await expect(page.getByTestId("place-path")).toHaveText(sitePath);

  await expectClean(page, seen);
});
