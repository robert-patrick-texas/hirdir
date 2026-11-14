// The operator, in the browser: the one person of the team who looks after an item or a
// device group (D-122).
//
//   A stack is given an operator once. Its switches show it as inherited from the stack,
//   and so does a power supply in one of them. One switch is given an operator of its
//   own, and one is given its own and returned to the one from the stack. The grid has
//   an Operator column, hidden until it is asked for.
//
//   What nobody is assigned to is counted, on a view of this file's items, and found
//   from the first page. A bulk edit assigns the rest. A contact says what it is the
//   operator of.
//
// The file keeps the rules of support.ts. It signs in as an Admin of its own, and its
// mark is in every name it gives a record: the hostnames, the stack, the contacts and
// the files it loads. Every count is read through a filter that keeps this file's items
// and no others; the number on the first page, which is of the whole inventory, is never
// compared with anything. Nothing is changed that another file reads. The addresses are
// of example.net. The two scenarios run in order: the second uses what the first made.

import { expect, type Locator, type Page } from "@playwright/test";
import { count, importFile, main, openItem, pick, region, summary } from "./structure";
import { expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const id = mark("operators");
const prefix = `${id}-`;
const filter = `hostname:prefix:${prefix}`;
// Three switches for a stack, and two routers that are in no group.
const switches = [1, 2, 3].map((place) => `${prefix}sw-0${place}`);
const [first = "", second = "", third = ""] = switches;
const routers = [`${prefix}rtr-01`, `${prefix}rtr-02`];
const supply = `${prefix}sw-01-ps-a`;
const stack = `${prefix}stack`;

// The people of the team who look after them.
const lee = `Lee Marchetti ${id}`;
const leeMail = `lee.marchetti.${id}@example.net`;
const ana = `Ana Okonkwo ${id}`;
const anaMail = `ana.okonkwo.${id}@example.net`;

/** A contact as a search offers it: its name, and its address beside it. */
function offered(name: string, mail: string): string {
  return `${name} (${mail})`;
}

/** Search for a contact in a form's field, by a part of its address, and choose it. */
async function chooseContact(form: Locator, mail: string, label: string, field = "Operator") {
  await form.getByLabel(field, { exact: true }).fill(mail.split("@")[0] ?? mail);
  await form
    .getByRole("list", { name: "Contacts that match" })
    .getByRole("button", { name: label, exact: true })
    .click();
}

/** The operator in force, as the page of an item says it. */
function operator(page: Page): Locator {
  return page.getByTestId("operator");
}

test("a stack is given an operator, and its switches and what is in them have it", async ({
  page,
  account,
}) => {
  test.setTimeout(180_000);
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
    ],
  );
  await importFile(
    page,
    "items",
    `items-${id}.csv`,
    ["hostname"],
    [...switches, ...routers].map((host) => [host]),
  );

  // Nobody is assigned to a switch that has no operator and is in no group.
  await openItem(page, first);
  await expect(operator(page)).toHaveAttribute("data-source", "none");
  await expect(operator(page)).toHaveText("Nobody is assigned");
  await expect(region(page, "Details").getByTestId("operator-note")).toHaveAttribute(
    "data-source",
    "none",
  );

  // The stack, with its three switches, and its operator chosen by searching contacts.
  await main(page).getByRole("link", { name: "Groups" }).click();
  await page.getByRole("button", { name: "New group" }).click();
  const form = region(page, "New group");
  await form.getByLabel("Name (required)").fill(stack);
  await form.getByLabel("Type").selectOption("stack");
  for (const host of switches) {
    await pick(form, "Find an item to add", `${prefix}sw`, host);
  }
  await expect(form.getByTestId("chosen-operator_hid")).toHaveText("None of its own");
  await chooseContact(form, leeMail, offered(lee, leeMail));
  await expect(form.getByTestId("chosen-operator_hid")).toHaveText(offered(lee, leeMail));
  await form.getByRole("button", { name: "Create group" }).click();
  await expect(page.getByRole("heading", { level: 1, name: stack })).toBeVisible();
  const groupPage = new URL(page.url()).pathname;
  // The page of the stack says who looks after it, and that its members have that one.
  await expect(page.getByTestId("group-operator")).toHaveAttribute("data-source", "own");
  await expect(page.getByTestId("group-operator")).toContainText(lee);
  await expect(page.getByTestId("group-operator")).toContainText("Set here");
  await expect(page.getByTestId("group-operator-members")).toContainText(
    "its members have this operator unless they have their own",
  );

  // A switch of the stack shows that operator as inherited: lighter, marked in words,
  // with the stack named and linked. Nothing was written to the switch.
  await openItem(page, first);
  await expect(operator(page)).toHaveAttribute("data-source", "device_group");
  await expect(operator(page)).toContainText(lee);
  await expect(operator(page)).toContainText("Inherited");
  const from = operator(page).getByRole("link", { name: `the stack ${stack}` });
  await expect(from).toBeVisible();
  expect(new URL((await from.getAttribute("href")) ?? "", page.url()).pathname).toBe(groupPage);
  // The form says what applies before anybody is chosen.
  const details = region(page, "Details");
  await expect(details.getByTestId("chosen-operator_hid")).toHaveText("None of its own");
  await expect(details.getByTestId("operator-note")).toHaveAttribute("data-source", "device_group");
  await expect(details.getByTestId("operator-note")).toContainText(
    `${lee}. Inherited from the stack ${stack}.`,
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
  await expect(operator(page)).toContainText(lee);
  await expect(
    operator(page).getByRole("link", { name: "the group of the item it is in" }),
  ).toBeVisible();

  // One switch is looked after by somebody else: it is given an operator of its own.
  await openItem(page, second);
  await chooseContact(region(page, "Details"), anaMail, offered(ana, anaMail));
  await region(page, "Details").getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("The item was saved.")).toBeVisible();
  await expect(operator(page)).toHaveAttribute("data-source", "own");
  await expect(operator(page)).toContainText(ana);
  await expect(operator(page)).toContainText("Set here");
  await expect(operator(page)).not.toContainText("Inherited");
  await expect(region(page, "Details").getByTestId("operator-note")).toHaveCount(0);

  // Another is given its own and returned: cleared, it has the one of the stack again.
  await openItem(page, third);
  await chooseContact(region(page, "Details"), anaMail, offered(ana, anaMail));
  await region(page, "Details").getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("The item was saved.")).toBeVisible();
  await expect(operator(page)).toHaveAttribute("data-source", "own");
  const again = region(page, "Details");
  await expect(again.getByTestId("chosen-operator_hid")).toHaveText(offered(ana, anaMail));
  await again.getByRole("button", { name: "Clear the operator" }).click();
  await expect(again.getByTestId("chosen-operator_hid")).toHaveText("None of its own");
  await again.getByRole("button", { name: "Save" }).click();
  await expect(operator(page)).toHaveAttribute("data-source", "device_group");
  await expect(operator(page)).toContainText(lee);

  // The grid has an Operator column, hidden until it is asked for: the operator in
  // force, lighter where it is inherited, and found by the name of that operator.
  await page.goto(`./items?filter=${encodeURIComponent(filter)}&minor=1`);
  await expect(page.getByTestId("grid-total")).toHaveText("6 items");
  const grid = page.getByTestId("grid-items");
  await expect(grid.locator('[role="columnheader"][col-id="operator.name"]')).toHaveCount(0);
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
      .locator('[col-id="operator.name"]');
  await expect(cell(first)).toHaveText(lee);
  await expect(cell(first)).toHaveClass(/cell-inherited/);
  await expect(cell(supply)).toHaveText(lee);
  await expect(cell(second)).toHaveText(ana);
  await expect(cell(second)).not.toHaveClass(/cell-inherited/);
  await expect(cell(routers[0] ?? "")).toHaveText("");
  // Where it came from is what the cell says when it has the focus.
  await cell(first).click();
  await expect(page.getByTestId("grid-cell-note")).toHaveText(
    `Operator: Inherited from the stack ${stack}`,
  );
  await page.goto(
    `./items?filter=${encodeURIComponent(`${filter} operator.name:eq:${lee}`)}&minor=1`,
  );
  await expect(page.getByTestId("grid-total")).toHaveText("3 items");

  await expectClean(page, seen);
});

test("what nobody is assigned to is counted and found, and a bulk edit assigns the rest", async ({
  page,
  account,
}) => {
  test.setTimeout(180_000);
  const seen = await watch(page.context());
  await signIn(page, account);

  // The summary of this file's items, by operator: two switches with the one of the
  // stack, one with its own, and the two routers that nobody is assigned to.
  await summary(page, filter, "operator");
  await expect(page.getByLabel("By", { exact: true })).toHaveValue("operator");
  const rows = page.getByTestId("summary-rows").locator("tbody tr");
  await expect(rows).toHaveCount(3);
  await expect(rows.filter({ hasText: lee }).locator("td").nth(1)).toHaveText("2");
  await expect(rows.filter({ hasText: ana }).locator("td").nth(1)).toHaveText("1");
  const nobody = page.getByTestId("summary-rows").locator('tbody tr[data-key=""]');
  await expect(nobody).toContainText("Nobody is assigned");
  await expect(nobody.locator("td").nth(1)).toHaveText("2");
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
  await unassigned.getByRole("link").click();
  await expect(page.getByRole("heading", { level: 1, name: "Items" })).toBeVisible();
  await expect(page.getByLabel("Filter", { exact: true })).toHaveValue(
    "effective.operator_hid:empty:true",
  );

  // A bulk edit assigns the rest: the items of this file that nobody is assigned to.
  await page.goto(
    `./items?filter=${encodeURIComponent(`${filter} effective.operator_hid:empty:true`)}`,
  );
  await expect(page.getByTestId("grid-total")).toHaveText("2 items");
  await page.getByRole("button", { name: "Select all that match" }).click();
  await page.getByRole("button", { name: "Bulk edit" }).click();
  const bulk = page.getByTestId("bulk-edit");
  await bulk.getByLabel("Field to change").selectOption({ label: "Operator" });
  await bulk.getByRole("button", { name: "Add", exact: true }).click();
  const line = bulk.getByRole("group", { name: "Operator" });
  await chooseContact(line, anaMail, offered(ana, anaMail), "Set to");
  await expect(line.getByTestId("chosen-operator")).toHaveText(offered(ana, anaMail));
  await bulk.getByRole("button", { name: "Preview the change" }).click();
  await expect(count(page, "updated")).toHaveText("2");
  await bulk.getByRole("button", { name: "Apply 2 items" }).click();
  await expect(page.getByTestId("preview-applied")).toContainText("2 updated");
  await summary(page, filter, "operator");
  await expect(rows).toHaveCount(2);
  await expect(nobody).toHaveCount(0);
  await expect(rows.filter({ hasText: ana }).locator("td").nth(1)).toHaveText("3");

  // A contact says what it is the operator of, and is the way to it.
  await page.goto(`./contacts?filter=${encodeURIComponent(`email:eq:${leeMail}`)}`);
  await page.getByTestId("grid-contacts").getByRole("link", { name: lee, exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: lee })).toBeVisible();
  const operates = page.getByTestId("contact-operates");
  // The two switches that have it from the stack, and the power supply in one of them.
  await expect(operates.getByRole("link", { name: "3 items" })).toBeVisible();
  await expect(operates.getByRole("link", { name: "1 device group" })).toBeVisible();
  await operates.getByRole("link", { name: "1 device group" }).click();
  await expect(page.getByTestId("grid-total")).toHaveText("1 group");
  await expect(
    page.getByTestId("grid-device-groups").getByRole("link", { name: stack, exact: true }),
  ).toBeVisible();
  // The Operator column of the groups, hidden until it is asked for.
  await page.getByText("Columns", { exact: true }).click();
  const columns = page.getByRole("group", { name: "Columns to show" });
  await expect(columns.getByLabel("Operator", { exact: true })).not.toBeChecked();
  await columns.getByLabel("Operator", { exact: true }).check();
  await page.getByText("Columns", { exact: true }).click();
  await expect(
    page.getByTestId("grid-device-groups").locator("[row-id]").locator('[col-id="operator.name"]'),
  ).toHaveText(lee);

  await expectClean(page, seen);
});
