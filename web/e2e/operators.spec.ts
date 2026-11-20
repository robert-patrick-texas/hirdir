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
import { count, importFile, main, openItem, pick, region, summary, whenApplied } from "./structure";
import { createAccount, expectClean, mark, signIn, test, watch } from "./support";

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
  // who is chosen by searching contacts. 0.9.3: the person is a contact that is no user
  // here, so the label is external (P-172).
  await main(page).getByRole("link", { name: "Operators" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Operators" })).toBeVisible();
  await page.getByRole("button", { name: "New operator" }).click();
  const form = region(page, "New operator");
  await form.getByLabel("Label (required)").fill(core);
  // 0.9.13: the colour is typed in the picker's box, which takes any #rrggbb (P-285).
  await form.getByLabel("Colour", { exact: true }).fill("#1f6feb");
  await form.getByRole("radio", { name: "Another contact", exact: true }).check();
  await form.getByLabel("Contact", { exact: true }).fill(leeMail.split("@")[0] ?? "");
  await form
    .getByRole("list", { name: "Other contacts that match" })
    .getByRole("button", { name: offered(lee, leeMail), exact: true })
    .click();
  await form.getByRole("button", { name: "Create operator" }).click();
  await expect(page.getByTestId("operator-heading")).toContainText(core);
  await expect(page.getByTestId("operator-person")).toContainText(lee);
  await expect(page.getByTestId("operator-person")).toHaveAttribute("data-open", "false");
  await expect(page.getByTestId("operator-scope")).toHaveAttribute("data-scope", "external");
  await expect(page.getByTestId("operator-email")).toHaveText(leeMail);
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
  // 0.9.8: each member chosen for a stack has the box of a member that joins, ticked
  // (P-244); these keep their own names, by which this file finds them.
  for (const host of switches) {
    await group
      .getByRole("group", { name: host })
      .getByLabel("It takes the stack's name and place")
      .uncheck();
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

  // The grid has an Operator column, shown from the start: the label in force as a
  // mark, lighter where it is inherited, and found by that label.
  await page.goto(`./items?filter=${encodeURIComponent(filter)}&minor=1`);
  await expect(page.getByTestId("grid-total")).toHaveText("6 items");
  const grid = page.getByTestId("grid-items");
  await page.getByText("Columns", { exact: true }).click();
  const columns = page.getByRole("group", { name: "Columns to show" });
  await expect(columns.getByLabel("Operator", { exact: true })).toBeChecked();
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
  await hand.getByRole("radio", { name: "Another contact", exact: true }).check();
  await hand.getByLabel("Contact", { exact: true }).fill(mioMail.split("@")[0] ?? "");
  await hand
    .getByRole("list", { name: "Other contacts that match" })
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
  await expect(page.getByTestId("operator-scope")).toHaveAttribute("data-scope", "");
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
  await expect(row(core).locator('[data-measure="components"]')).toHaveText("2");
  await expect(row(core)).toContainText("open");
  await expect(row(edge).locator('[data-measure="components"]')).toHaveText("1");
  await expect(row(edge)).toContainText(ana);
  await expect(row(local).locator('[data-measure="components"]')).toHaveText("1");
  const nobody = table.locator('tbody tr[data-key=""]');
  await expect(nobody).toContainText("Nobody is assigned");
  await expect(nobody.locator('[data-measure="components"]')).toHaveText("1");
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
  await whenApplied(page, 1);
  await summary(page, filter, "operator");
  await expect(rows).toHaveCount(3);
  await expect(nobody).toHaveCount(0);
  await expect(row(edge).locator('[data-measure="components"]')).toHaveText("2");

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
    page.getByTestId("operator-tree").getByRole("link", { name: sitePath, exact: true }),
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
  // 0.9.4: the page counts three tables at once, the groups among them; on a busy host that
  // takes longer than the 5 seconds an expectation waits by default.
  await expect(ranked).toHaveCount(3, { timeout: 20_000 });
  await expect(ranked.nth(0)).toHaveAttribute("data-label", edge);
  await expect(ranked.nth(1)).toHaveAttribute("data-label", core);
  await expect(operators.getByRole("columnheader", { name: "Support weight" })).toHaveAttribute(
    "aria-sort",
    "descending",
  );
  const heavier = ranked.nth(0);
  await expect(markIn(heavier, edge)).toBeVisible();
  await expect(heavier).toContainText(ana);
  await expect(heavier.locator('[data-measure="components"]')).toHaveText("3");
  await expect(heavier.locator('[data-measure="nodes"]')).toHaveText("3");
  await expect(heavier.locator('[data-measure="items"]')).toHaveText("3");
  await expect(heavier.locator('[data-measure="weight"]')).toHaveText(/^4\.50?$/);
  await expect(heavier.locator('[data-measure="share"] .share-text')).toHaveText("60%");
  // The share has a bar of the whole beside it, which a screen reader does not read.
  const shareBar = heavier.locator('[data-measure="share"] .bar');
  await expect(shareBar).toHaveAttribute("aria-hidden", "true");
  await expect(shareBar.locator(".bar-fill")).toHaveAttribute("style", /inline-size: 60%/);
  const lighter = ranked.nth(1);
  await expect(markIn(lighter, core)).toHaveAttribute("data-open", "true");
  await expect(lighter.locator('[data-measure="components"]')).toHaveText("1");
  await expect(lighter.locator('[data-measure="share"] .share-text')).toHaveText("20%");
  // P-178, P-180: a rank by the column the table is sorted by, 1 for the most, and a bar
  // beside each count as long as it is to the largest of its column, read by nobody.
  const rankHead = operators.getByRole("columnheader", { name: "Rank", exact: true });
  await expect(rankHead).toHaveAttribute("data-rank-by", "weight");
  await expect(page.getByTestId("rank-note").first()).toContainText(
    "Ranked by support weight, 1 for the most",
  );
  await expect(heavier.locator('[data-measure="rank"]')).toHaveText("1");
  await expect(lighter.locator('[data-measure="rank"]')).toHaveText("2");
  const weightBar = (row: Locator) => row.locator('[data-measure="weight"] .bar');
  await expect(weightBar(heavier)).toHaveAttribute("aria-hidden", "true");
  await expect(weightBar(heavier).locator(".bar-fill")).toHaveAttribute(
    "style",
    /inline-size: 100%/,
  );
  await expect(weightBar(lighter).locator(".bar-fill")).toHaveAttribute(
    "style",
    /inline-size: 33\.33%/,
  );
  // What nobody is assigned to is a row like the others, here the last by its weight,
  // and what is under an open label is said.
  const nobody = page.getByTestId("score-nobody");
  await expect(ranked.nth(2)).toHaveAttribute("data-testid", "score-nobody");
  await expect(nobody).toContainText("Nobody is assigned");
  await expect(nobody.locator('[data-measure="components"]')).toHaveText("1");
  await expect(nobody.locator('[data-measure="weight"]')).toHaveText(/^1\.50?$/);
  // The blank row has no rank, and its count is drawn as any other.
  await expect(nobody.locator('[data-measure="rank"]')).toHaveText("");
  await expect(weightBar(nobody).locator(".bar-fill")).toHaveAttribute(
    "style",
    /inline-size: 33\.33%/,
  );
  await expect(page.getByTestId("score-open")).toContainText(
    "Under 1 label that nobody is behind for now: 1 component, 1 item",
  );

  // The sites: the one site, with the operators involved there and how much each has,
  // the heavier first; and the item that is nowhere, a row like the others, which is
  // nobody's.
  const sites = page.getByTestId("score-sites");
  await expect(sites.locator("tbody tr")).toHaveCount(2);
  const site = sites.locator("tbody tr").first();
  await expect(site).toHaveAttribute("data-path", sitePath);
  await expect(site.locator('[data-measure="components"]')).toHaveText("4");
  await expect(site.locator('[data-measure="weight"]')).toHaveText(/^6(\.00?)?$/);
  // 0.9.5: the operators involved are a number, with the list behind it (P-196).
  await expect(site.getByTestId("involved-count")).toHaveText("2 operators");
  await site.getByTestId("involved-count").click();
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

  // A header sorts the table by its column, and another click turns the order round.
  // What nobody is assigned to sorts with the others, and the file follows the order.
  const byComponents = operators.getByRole("button", { name: "Components", exact: true });
  await byComponents.click();
  await expect(operators.getByRole("columnheader", { name: "Components" })).toHaveAttribute(
    "aria-sort",
    "ascending",
  );
  await expect(operators.getByRole("columnheader", { name: "Support weight" })).toHaveAttribute(
    "aria-sort",
    "none",
  );
  await expect(ranked.nth(2)).toHaveAttribute("data-label", edge);
  await expect(ranked.nth(0)).toHaveAttribute("data-label", core);
  await expect(ranked.nth(1)).toHaveAttribute("data-testid", "score-nobody");
  // The rank follows the column: by components, 1 for the most whichever way the order
  // runs, and the blank row still has none.
  await expect(rankHead).toHaveAttribute("data-rank-by", "components");
  await expect(ranked.nth(2).locator('[data-measure="rank"]')).toHaveText("1");
  await expect(ranked.nth(0).locator('[data-measure="rank"]')).toHaveText("2");
  await expect(ranked.nth(1).locator('[data-measure="rank"]')).toHaveText("");
  await expect(page.getByTestId("rank-note").first()).toHaveAttribute("data-rank-by", "components");
  const savedAgain = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export CSV of the operators" }).click();
  const sortedPath = testInfo.outputPath("sorted-operators.csv");
  await (await savedAgain).saveAs(sortedPath);
  const sorted = (await readFile(sortedPath, "utf8")).trimEnd().split("\r\n");
  expect(sorted[1]).toContain(`,${core},,true,1,1,1,`);
  expect(sorted[2]).toMatch(/^,,,,1,1,1,/);
  expect(sorted[3]).toContain(`,${edge},${ana},false,3,3,3,`);
  await byComponents.click();
  await expect(operators.getByRole("columnheader", { name: "Components" })).toHaveAttribute(
    "aria-sort",
    "descending",
  );
  await expect(ranked.nth(0)).toHaveAttribute("data-label", edge);
  // By the name each row shows, without regard to case.
  await operators.getByRole("button", { name: "Operator", exact: true }).click();
  await expect(operators.getByRole("columnheader", { name: "Operator" })).toHaveAttribute(
    "aria-sort",
    "ascending",
  );

  // Each row is the way to its items, and a site to its place.
  await operators
    .locator(`tbody tr[data-label="${edge}"]`)
    .getByRole("link", { name: "items" })
    .click();
  await expect(page.getByRole("heading", { level: 1, name: "Items" })).toBeVisible();
  await expect(page.getByTestId("grid-total")).toHaveText("3 items");
  await page.goto(
    `./reports/scoreboard?${new URLSearchParams({ filter: scoreFilter }).toString()}`,
  );
  await page.getByTestId("score-sites").getByRole("link", { name: sitePath, exact: true }).click();
  await expect(page.getByTestId("place-path")).toHaveText(sitePath);

  await expectClean(page, seen);
});

test("0.9.13: an operator made for a user takes its username and the next colour, reads details first, and the list says the user behind each and finds the gaps", async ({
  page,
  account,
  request,
  browser,
}) => {
  test.setTimeout(180_000);
  // A member of the team who signs in, a View-only user whose contact is a person.
  const person = `Example Person ${id}`;
  const personMail = `example.person.${id}@example.net`;
  const member = await createAccount(request, `e2e-${id}-ops`, "viewer", {
    name: person,
    email: personMail,
  });
  const seen = await watch(page.context());
  await signIn(page, account);

  // New operator: the colour starts at the next that no operator has, one of the 32 of
  // the slider; which one depends on every operator there is, so it is not named here.
  await page.goto("./operators");
  await page.getByRole("button", { name: "New operator" }).click();
  const form = region(page, "New operator");
  const colour = form.getByRole("group", { name: "Colour", exact: true });
  const box = colour.getByRole("textbox", { name: "Colour", exact: true });
  await expect(box).toHaveValue(/^#[0-9a-f]{6}$/);
  await expect(colour.locator(".colour-slider")).toHaveAttribute("data-none", "false");
  await expect(colour.locator('.colour-swatch[aria-pressed="true"]')).toHaveAttribute(
    "data-colour",
    await box.inputValue(),
  );

  // A label typed by hand is kept when a user is chosen.
  const label = form.getByLabel("Label (required)");
  const chooseUser = async () => {
    await form.getByRole("radio", { name: "A user", exact: true }).check();
    await form.getByLabel("User", { exact: true }).fill(personMail.split("@")[0] ?? "");
    await form
      .getByRole("list", { name: "Users that match" })
      .getByRole("button", {
        name: `${offered(person, personMail)}, user ${member.username}`,
        exact: true,
      })
      .click();
  };
  await label.fill(`Hand ${id}`);
  await chooseUser();
  await expect(form.getByTestId("chosen-new-operator-user")).toContainText(person);
  await expect(label).toHaveValue(`Hand ${id}`);
  // Blank, the label is filled with the username of the user chosen.
  await label.fill("");
  await form.getByRole("radio", { name: "Another contact", exact: true }).check();
  await chooseUser();
  await expect(label).toHaveValue(member.username);
  // The colour is one press, beside the label as the lists will show it.
  await colour.getByRole("button", { name: "violet, shade 5 of 8, #9964e5", exact: true }).click();
  await expect(box).toHaveValue("#9964e5");
  await expect(colour.locator(".colour-sample")).toHaveText(member.username);
  await form.getByRole("button", { name: "Create operator" }).click();
  await expect(page.getByTestId("operator-heading")).toContainText(member.username);
  await expect(page.getByTestId("operator-scope")).toHaveAttribute("data-scope", "internal");
  await expect(page.getByTestId("operator-colour")).toHaveText("#9964e5");
  await expect(page.getByTestId("operator-user").getByRole("link")).toHaveText(member.username);

  // Its page reads Details first, above the person's email and numbers.
  const sections = await page
    .getByRole("main")
    .getByRole("heading", { level: 2 })
    .allTextContents();
  expect(sections.indexOf("Details")).toBeGreaterThan(-1);
  expect(sections.indexOf("Details")).toBeLessThan(
    sections.indexOf("The person's email and numbers"),
  );
  // Its colour is changed on the slider, by the keyboard, and saved.
  const details = region(page, "Details");
  const again = details.getByRole("group", { name: "Colour", exact: true });
  await again.getByRole("slider", { name: "Colour, Slider of 32", exact: true }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(again.getByRole("textbox", { name: "Colour", exact: true })).toHaveValue("#7e4ac2");
  await details.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("The operator was saved.")).toBeVisible();
  await expect(page.getByTestId("operator-colour")).toHaveText("#7e4ac2");

  // The list says the user behind each operator, a link to its page for an Admin, and
  // that there is none; Show leads to the gaps, each one press away, as the grid's own
  // filter, to which this file's mark is added before anything is counted.
  await page.goto(`./operators?filter=${encodeURIComponent(`label:contains:${id}`)}`);
  await expect(page.getByTestId("grid-total")).toHaveText("4 operators");
  const list = page.getByTestId("grid-operators");
  const userOf = (name: string) =>
    list.locator("[row-id]", { hasText: name }).locator('[col-id="user"]');
  await expect(userOf(member.username).getByRole("link")).toHaveText(member.username);
  await expect(userOf(edge)).toHaveText("no user");
  const show = page.getByRole("navigation", { name: "Show operators" });
  const filterBox = page.getByLabel("Filter", { exact: true });
  const narrowed = async (gap: string, filter: string, total: string) => {
    await show.getByRole("link", { name: gap, exact: true }).click();
    await expect(filterBox).toHaveValue(filter);
    await expect(show.getByRole("link", { name: gap, exact: true })).toHaveAttribute(
      "aria-current",
      "page",
    );
    await filterBox.fill(`${filter} label:contains:${id}`);
    await page.getByRole("button", { name: "Apply", exact: true }).click();
    await expect(page.getByTestId("grid-total")).toHaveText(total);
  };
  await narrowed("No user behind it", "scope:ne:internal", "3 operators");
  await expect(list.locator("[row-id]", { hasText: member.username })).toHaveCount(0);
  await narrowed("Nobody behind it", "is_open:eq:true", "1 operator");
  await expect(list.locator("[row-id]", { hasText: core })).toHaveCount(1);
  await show.getByRole("link", { name: "Every operator", exact: true }).click();
  await expect(filterBox).toHaveValue("");
  await page.goto(`./operators?filter=${encodeURIComponent(`label:contains:${id}`)}`);
  await userOf(member.username).getByRole("link").click();
  await expect(page).toHaveURL(/\/admin\/users\//);
  await expectClean(page, seen);

  // For View-only the user is named in plain words: the page of a user is an Admin's.
  const context = await browser.newContext();
  const viewer = await context.newPage();
  const viewed = await watch(context);
  await signIn(viewer, member);
  await viewer.goto(`./operators?filter=${encodeURIComponent(`label:eq:${member.username}`)}`);
  const cell = viewer.getByTestId("grid-operators").locator("[row-id]").locator('[col-id="user"]');
  await expect(cell).toHaveText(member.username);
  await expect(cell.getByRole("link")).toHaveCount(0);
  await expectClean(viewer, viewed);
  await context.close();
});
