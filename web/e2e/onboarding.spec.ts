// The browser scenarios of a new person in one step, in release 0.9.13:
//
//   P-280  Each list says who is a user, a contact and an operator, as links, and finds
//          the gaps: the users with no contact and with no operator, the contacts that
//          are no user and that stand behind no operator, each an address of its own.
//   P-281  A user has notes, given when it is made, shown on the list, changed on its
//          page.
//   P-282  A user's groups are ticked and unticked on its page, each at once, and given
//          when it is made.
//   P-283  One Create makes a new engineer: the user, the contact, the operator with its
//          colour, the role and two groups. A refusal is shown at its field, with nothing
//          typed lost. A service account has neither a contact nor an operator.
//   P-284  Make an operator, in one press, from a user's page and from a contact's.
//   P-288  An Admin saves the users as a CSV file.
//
// They keep to the rules of support.ts: an account of their own, and users, contacts,
// operators and groups of their own with the file's mark in their names, found in every
// list by it. The users the file makes are disabled when it ends. The scenarios run in
// order: the later ones use the groups and the users the earlier ones make.

import { readFile } from "node:fs/promises";
import { expect, type Locator, type Page } from "@playwright/test";
import { type Headers, make, session } from "./referenceSteps";
import { region } from "./structure";
import { createAccount, expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const suffix = mark("onboarding");
const networkName = `${suffix}-network`;
const serversName = `${suffix}-servers`;
const engineer = {
  username: `e2e-${suffix}-eng`,
  name: `Eng Example ${suffix}`,
  email: `eng.${suffix}@example.net`,
  notes: `For the network team, asked for by Example Person ${suffix}.`,
};
// What the scenarios hand on: the groups made, the users made, and their pages.
const made = {
  network: "",
  servers: "",
  users: [] as string[],
  gus: { hid: "", username: "" },
  engineer: "",
};

/** The page of a user, by its HID. */
async function openUser(page: Page, hid: string, username: string) {
  await page.goto(`./admin/users/${encodeURIComponent(hid)}`);
  await expect(page.getByRole("heading", { level: 1, name: username })).toBeVisible();
}

/** The New user form, opened on the Users list. */
async function newUserForm(page: Page): Promise<Locator> {
  await page.goto("./admin/users");
  await page.getByRole("button", { name: "New user" }).click();
  return region(page, "New user");
}

/** The box of a group in the New user form, whose name says what the group grants. */
function groupBox(form: Locator, name: string): Locator {
  return form.getByRole("checkbox", { name: new RegExp(`^${name} \\(grants `) });
}

/**
 * The gaps of a grid follow its own filter (P-280): on a gap, changed in the Filter box
 * to another gap's filter, then to one that is no gap's, the mark follows; a press of
 * the first gap, at the same address, starts the grid on it again.
 */
async function gapsFollowTheGrid(
  page: Page,
  show: Locator,
  gaps: { pressed: string; filter: string; other: string; otherFilter: string },
) {
  const filterBox = page.getByLabel("Filter", { exact: true });
  const marked = (name: string) => show.getByRole("link", { name, exact: true });
  await expect(filterBox).toHaveValue(gaps.filter);
  await expect(marked(gaps.pressed)).toHaveAttribute("aria-current", "page");
  const apply = async (filter: string) => {
    await filterBox.fill(filter);
    await page.getByRole("button", { name: "Apply", exact: true }).click();
  };
  await apply(gaps.otherFilter);
  await expect(marked(gaps.pressed)).not.toHaveAttribute("aria-current", "page");
  await expect(marked(gaps.other)).toHaveAttribute("aria-current", "page");
  await apply(`${gaps.otherFilter} ${gaps.filter}`);
  await expect(show.locator('[aria-current="page"]')).toHaveCount(0);
  await marked(gaps.pressed).click();
  await expect(filterBox).toHaveValue(gaps.filter);
  await expect(marked(gaps.pressed)).toHaveAttribute("aria-current", "page");
}

/** The rows of the Users list, searched for this file's users and narrowed as asked. */
async function usersListed(page: Page, query: string): Promise<Locator> {
  await page.goto(`./admin/users?q=${encodeURIComponent(suffix)}${query}`);
  await expect(page.getByRole("heading", { level: 1, name: "Users" })).toBeVisible();
  const table = page.getByTestId("users");
  await expect(table).toBeVisible();
  return table.locator("tbody tr[data-user]");
}

test("P-282: a user's groups are ticked and unticked on its page, each at once", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(120_000);
  const headers = await session(request, account);
  made.network = (await make(request, headers, "/user-groups", { name: networkName })).hid;
  made.servers = (await make(request, headers, "/user-groups", { name: serversName })).hid;
  await make(request, headers, "/role-grants", { group_hid: made.network, role: "inventory" });
  const goneName = `${suffix}-gone`;
  const gone = await make(request, headers, "/user-groups", { name: goneName });
  const gus = await createAccount(request, `e2e-${suffix}-gus`, null, {
    name: `Gus Example ${suffix}`,
  });
  made.users.push(gus.hid);
  made.gus = { hid: gus.hid, username: gus.username };
  const seen = await watch(page.context());
  await signIn(page, account);
  await openUser(page, gus.hid, gus.username);
  const boxes = page.getByTestId("user-groups");
  const box = (name: string) => boxes.getByRole("checkbox", { name, exact: true });
  const facts = page.getByTestId("user-facts");

  // Each group there is has a box, with what it grants.
  await expect(boxes.locator(`[data-group="${networkName}"]`)).toContainText("grants Inventory");
  await expect(boxes.locator(`[data-group="${serversName}"]`)).toContainText("grants nothing");
  await expect(box(networkName)).not.toBeChecked();

  // Ticked: in the group at once, and holding the role it grants.
  await box(networkName).check();
  await expect(facts.getByRole("link", { name: networkName })).toBeVisible();
  await expect(facts).toContainText("Inventory");
  // Unticked: out of it, and the role with it.
  await box(networkName).uncheck();
  await expect(facts.getByRole("link", { name: networkName })).toHaveCount(0);
  await expect(facts).toContainText("No role");

  // Pressed twice while its request is held back: one request, and the box as asked first.
  let sent = 0;
  const held = `**/api/v1/user-groups/${made.servers}/members/**`;
  await page.route(held, async (route) => {
    sent += 1;
    await new Promise((resolve) => setTimeout(resolve, 1500));
    await route.continue();
  });
  await box(serversName).click();
  await expect(boxes.locator(`[data-group="${serversName}"]`)).toContainText("Adding…");
  await box(serversName).click();
  await expect(box(serversName)).toBeChecked();
  await expect(facts.getByRole("link", { name: serversName })).toBeVisible();
  await expect(boxes.locator(`[data-group="${serversName}"]`)).not.toContainText("Adding…");
  expect(sent).toBe(1);
  await page.unroute(held);

  // Refused, as for a group deleted since the page was read: the page says by its name
  // that the group is gone, and its box is taken away, without a reload.
  const answer = await request.delete(`./api/v1/user-groups/${gone.hid}`, { headers });
  expect(answer.status()).toBe(204);
  await box(goneName).click();
  await expect(boxes.getByTestId("groups-gone")).toHaveText(
    `The group ${goneName} is gone: it was deleted after this was read, and its box is taken away.`,
  );
  await expect(box(goneName)).toHaveCount(0);
  await expect(boxes).not.toContainText(gone.hid);
  await expect(box(serversName)).toBeChecked();
  // The page read again has no box for it, and the user is in the one group ticked.
  await page.reload();
  await expect(box(serversName)).toBeChecked();
  await expect(box(goneName)).toHaveCount(0);
  await expectClean(page, seen, ["404 PUT"]);
});

test("P-283: a new engineer is made by one Create, and read on the three lists", async ({
  page,
  account,
}) => {
  test.setTimeout(180_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  const form = await newUserForm(page);

  // A person is a contact and an operator from the start.
  await expect(form.getByRole("checkbox", { name: "Also a contact" })).toBeChecked();
  await expect(form.getByRole("checkbox", { name: "Also an operator" })).toBeChecked();
  await expect(form.getByRole("radio", { name: "A new contact" })).toBeChecked();
  // The colour is the next that no operator has, the label the username as it is typed.
  const colour = form.getByRole("textbox", { name: "Colour" });
  await expect(colour).toHaveValue(/^#[0-9a-f]{6}$/);
  const label = form.getByLabel("Label", { exact: true });
  await form.getByLabel("Username").fill(engineer.username);
  await expect(label).toHaveValue(engineer.username);
  const person = form.getByTestId("new-person-new-user");
  await person.getByLabel("Name (required)").fill(engineer.name);
  await person.getByLabel("Email").fill(engineer.email);
  await form.getByLabel("Role").selectOption({ label: "Inventory" });
  await groupBox(form, networkName).check();
  await groupBox(form, serversName).check();
  await form.getByLabel("Notes").fill(engineer.notes);
  const chosen = await colour.inputValue();
  await form.getByRole("button", { name: "Create user" }).click();

  // The access code, and a link to each of the three records made.
  await expect(
    page.getByRole("region", { name: `Access code for ${engineer.username}` }),
  ).toBeVisible();
  const madeWith = page.getByTestId("user-made");
  await expect(madeWith.getByRole("link")).toHaveCount(3);
  await expect(madeWith.getByRole("link").first()).toHaveText(engineer.username);
  await expect(madeWith.getByRole("link", { name: engineer.name, exact: true })).toBeVisible();
  const operator = madeWith.locator(".operator-mark");
  await expect(operator).toHaveText(engineer.username);
  await expect(operator.locator(".operator-dot")).toHaveAttribute(
    "style",
    new RegExp(`background-color: ${rgbOf(chosen)}`),
  );
  // The operator's page, reached from there, says it was just made.
  await operator.getByRole("link").click();
  await expect(page.getByTestId("operator-heading")).toContainText(engineer.username);
  await expect(page.getByText(`Operator ${engineer.username} was created.`)).toBeVisible();

  // The Users list: the contact and the operator, each a link, the role, both groups, the
  // notes; every column in view on a screen 1280 pixels wide, Notes cut short to its
  // column with the whole of them on hover.
  await page.setViewportSize({ width: 1280, height: 800 });
  const rows = await usersListed(page, "");
  const table = page.getByTestId("users");
  expect(
    await table.evaluate((element) => {
      const box = element.closest(".scroll") ?? element;
      return box.scrollWidth <= box.clientWidth;
    }),
    "the list of users fits its box at 1280 pixels",
  ).toBe(true);
  await expect(table.getByRole("columnheader", { name: "Notes" })).toBeInViewport({ ratio: 1 });
  const row = rows.and(page.locator(`[data-user="${engineer.username}"]`));
  await expect(row.getByTestId("user-name").getByRole("link")).toHaveText(engineer.name);
  await expect(row.getByTestId("user-operators").getByRole("link")).toHaveText(engineer.username);
  await expect(row).toContainText("Inventory");
  await expect(row.getByRole("link", { name: networkName })).toBeVisible();
  await expect(row.getByRole("link", { name: serversName })).toBeVisible();
  await expect(row.getByTestId("user-notes")).toHaveText(engineer.notes);
  await expect(row.getByTestId("user-notes")).toHaveAttribute("title", engineer.notes);
  await expect(row.getByTestId("user-email")).toHaveText(engineer.email);
  await row.getByRole("rowheader").getByRole("link").click();
  made.engineer = new URL(page.url()).pathname;
  made.users.push(decodeURIComponent(made.engineer.split("/").at(-1) ?? ""));
  await expect(page.getByTestId("user-operators").getByRole("link")).toHaveText(engineer.username);
  await expect(page.getByTestId("user-operators").getByRole("button")).toHaveCount(0);
  await expect(page.getByTestId("user-notes")).toHaveText(engineer.notes);

  // The Contacts list: the user, and the operator it stands behind, as a link.
  await page.goto(`./contacts?filter=${encodeURIComponent(`email:eq:${engineer.email}`)}`);
  const grid = page.getByTestId("grid-contacts");
  await expect(grid.locator("[row-id]")).toHaveCount(1);
  await expect(grid.locator('[row-id] [col-id="is_user"]')).toHaveText(engineer.username);
  await expect(grid.locator('[row-id] [col-id="is_operator"]')).toHaveText(engineer.username);

  // The Operators list: internal, the person behind it a user.
  await page.goto(`./operators?filter=${encodeURIComponent(`label:eq:${engineer.username}`)}`);
  const operators = page.getByTestId("grid-operators");
  await expect(operators.locator("[row-id]")).toHaveCount(1);
  await expect(operators.locator('[row-id] [col-id="scope"]')).toHaveText("Internal");

  // The notes are changed on the user's page, and cleared.
  await page.goto(made.engineer);
  const details = region(page, "Details");
  await details.getByLabel("Notes").fill("Until the end of the project.");
  await details.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByTestId("user-notes")).toHaveText("Until the end of the project.");
  await details.getByLabel("Notes").fill("");
  await details.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByTestId("user-notes")).toHaveText("—");
  await expectClean(page, seen);
});

test("P-288: an Admin saves the users as a CSV file, its header as the file is read", async ({
  page,
  account,
}, testInfo) => {
  test.setTimeout(120_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  await page.goto("./admin/users");
  const saved = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export CSV of the users" }).click();
  const download = await saved;
  expect(download.suggestedFilename()).toMatch(/^hirdir-users-.*\.csv$/);
  const path = testInfo.outputPath(download.suggestedFilename());
  await download.saveAs(path);
  const lines = (await readFile(path, "utf8")).trimEnd().split(/\r?\n/);
  expect(lines[0]).toBe(
    "username,name,email,phone,phone2,role,groups,operators,kind,state,record_status,last_sign_in_at,notes",
  );
  // The engineer's row: its person, the role in force, both groups and its operator.
  const row = lines.find((line) => line.startsWith(`${engineer.username},`)) ?? "";
  for (const part of [engineer.name, engineer.email, "inventory", networkName, serversName]) {
    expect(row).toContain(part);
  }
  // 0.9.14: and its record status, which a retired account alone has otherwise (P-296).
  expect(row).toContain(",person,enabled,active,");
  await expect(page.getByText(`Exported to ${download.suggestedFilename()}.`)).toBeVisible();
  await expectClean(page, seen);
});

test("P-283: each refusal is shown at its field, with nothing typed lost", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(180_000);
  const headers = await session(request, account);
  const takenLabel = `${suffix}-taken`;
  await make(request, headers, "/operators", { label: takenLabel, record_status: "active" });
  const takenEmail = `taken.${suffix}@example.net`;
  await make(request, headers, "/contacts", {
    name: `Taken Example ${suffix}`,
    email: takenEmail,
    record_status: "active",
  });
  const lateName = `${suffix}-late`;
  const late = await make(request, headers, "/user-groups", { name: lateName });
  const seen = await watch(page.context());
  await signIn(page, account);
  const form = await newUserForm(page);
  const username = `e2e-${suffix}-ref`;
  const person = form.getByTestId("new-person-new-user");
  await form.getByLabel("Username").fill(username);
  await person.getByLabel("Name (required)").fill(`Ref Example ${suffix}`);
  await person.getByLabel("Email").fill(takenEmail);
  await form.getByLabel("Role").selectOption({ label: "View-only" });
  await groupBox(form, serversName).check();
  await groupBox(form, lateName).check();
  await form.getByLabel("Notes").fill("Kept through every refusal.");
  const create = form.getByRole("button", { name: "Create user" });
  const intact = async () => {
    await expect(form.getByLabel("Username")).toHaveValue(username);
    await expect(person.getByLabel("Name (required)")).toHaveValue(`Ref Example ${suffix}`);
    await expect(form.getByLabel("Role")).toHaveValue("viewer");
    await expect(groupBox(form, serversName)).toBeChecked();
    await expect(form.getByLabel("Notes")).toHaveValue("Kept through every refusal.");
    await expect(page.getByRole("region", { name: `Access code for ${username}` })).toHaveCount(0);
  };

  // A value that is no colour: said at the picker, as typed, and nothing sent.
  const colourBox = form.getByRole("textbox", { name: "Colour" });
  const shown = await colourBox.inputValue();
  await colourBox.fill("rubbish");
  await create.click();
  await expect(colourBox).toHaveAttribute("aria-invalid", "true");
  await expect(colourBox).toHaveValue("rubbish");
  await intact();
  await colourBox.fill(shown);

  // The email of another contact: at the email.
  await create.click();
  await expect(person.getByLabel("Email")).toHaveAttribute("aria-invalid", "true");
  await intact();
  await person.getByLabel("Email").fill(`ref.${suffix}@example.net`);

  // The label of another operator: at the label, with the operator that has it.
  const label = form.getByLabel("Label", { exact: true });
  await label.fill(takenLabel);
  await create.click();
  await expect(label).toHaveAttribute("aria-invalid", "true");
  await expect(form.getByRole("link", { name: takenLabel })).toBeVisible();
  await intact();
  // A label that is no label: at the label.
  await label.fill(`${suffix};x`);
  await create.click();
  await expect(label).toHaveAttribute("aria-invalid", "true");
  await intact();
  await label.fill("");

  // A group deleted since the form was read: the whole refused, and the form says by its
  // name that the group is gone, its box taken away, the other group still ticked.
  const gone = await request.delete(`./api/v1/user-groups/${late.hid}`, { headers });
  expect(gone.status()).toBe(204);
  await create.click();
  const groups = form.getByRole("group", { name: "Groups" });
  await expect(groups.locator(".field-error")).toHaveText(
    `The group ${lateName} is gone: it was deleted after this was read, and its box is taken away.`,
  );
  await expect(groupBox(form, lateName)).toHaveCount(0);
  await intact();

  // Nothing of the refused was made: no such user, no operator of its name.
  const users = await request.get(`./api/v1/users?q=${encodeURIComponent(username)}`, { headers });
  expect(((await users.json()) as { total: number }).total).toBe(0);

  // Put right, it is made, with the username as the label of its operator.
  await create.click();
  await expect(page.getByRole("region", { name: `Access code for ${username}` })).toBeVisible();
  await expect(page.getByTestId("user-made").locator(".operator-mark")).toHaveText(username);
  const madeUser = page.getByTestId("user-made").getByRole("link").first();
  made.users.push(
    decodeURIComponent((await madeUser.getAttribute("href"))?.split("/").at(-1) ?? ""),
  );
  await expectClean(page, seen, ["409 POST", "409 POST", "422 POST", "422 POST"]);
});

test("P-280: a service account and a person with no contact, and the gaps of each list", async ({
  page,
  account,
}) => {
  test.setTimeout(180_000);
  const seen = await watch(page.context());
  await signIn(page, account);

  // A service account has neither box.
  let form = await newUserForm(page);
  const service = `e2e-${suffix}-svc`;
  await form.getByLabel("Username").fill(service);
  await form.getByRole("checkbox", { name: "Service account" }).check();
  await expect(form.getByRole("checkbox", { name: "Also a contact" })).toHaveCount(0);
  await expect(form.getByRole("checkbox", { name: "Also an operator" })).toHaveCount(0);
  await form.getByLabel("Notes").fill("Reads the inventory for a report.");
  await form.getByRole("button", { name: "Create user" }).click();
  await expect(page.getByText(`The service account ${service} was created.`)).toBeVisible();
  await expect(page.getByTestId("user-made").getByRole("link")).toHaveCount(1);
  const serviceLink = page.getByTestId("user-made").getByRole("link", { name: service });
  made.users.push(
    decodeURIComponent((await serviceLink.getAttribute("href"))?.split("/").at(-1) ?? ""),
  );

  // A person with no contact: unticking the contact unticks the operator, which needs one.
  form = await newUserForm(page);
  const nobody = `e2e-${suffix}-nob`;
  await form.getByLabel("Username").fill(nobody);
  const contactBox = form.getByRole("checkbox", { name: "Also a contact" });
  const operatorBox = form.getByRole("checkbox", { name: "Also an operator" });
  await contactBox.uncheck();
  await expect(operatorBox).not.toBeChecked();
  await expect(form.getByTestId("new-person-new-user")).toHaveCount(0);
  // Ticking the operator ticks the contact again; both are unticked for this one.
  await operatorBox.check();
  await expect(contactBox).toBeChecked();
  await contactBox.uncheck();
  await form.getByRole("button", { name: "Create user" }).click();
  const code = page.getByRole("region", { name: `Access code for ${nobody}` });
  await expect(code).toBeVisible();
  const nobodyLink = page.getByTestId("user-made").getByRole("link", { name: nobody });
  made.users.push(
    decodeURIComponent((await nobodyLink.getAttribute("href"))?.split("/").at(-1) ?? ""),
  );

  // 0.9.15: the list leaves blank what there is not, no contact and no operator, of a
  // person and of the service account alike, whose Kind says what it is (P-302).
  let rows = await usersListed(page, "");
  const of = (name: string) => rows.and(page.locator(`[data-user="${name}"]`));
  await expect(of(nobody).getByTestId("user-name")).toHaveText("");
  await expect(of(nobody).getByTestId("user-operators")).toHaveText("");
  await expect(of(made.gus.username).getByTestId("user-operators")).toHaveText("");
  await expect(of(service).getByTestId("user-name")).toHaveText("");
  await expect(of(service).getByTestId("user-operators")).toHaveText("");

  // Show, with the users with no contact: an address of its own, the search kept. Until
  // a gap is chosen, the list is of every user, and says so.
  const show = page.getByRole("navigation", { name: "Show users" });
  await expect(show.getByRole("link", { name: "Every user" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  await show.getByRole("link", { name: "Users with no contact" }).click();
  await expect(page).toHaveURL(/[?&]contact=none/);
  await expect(page).toHaveURL(new RegExp(`[?&]q=${suffix}`));
  await expect(show.getByRole("link", { name: "Users with no contact" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  rows = page.getByTestId("users").locator("tbody tr[data-user]");
  await expect(rows).toHaveCount(1);
  await expect(of(nobody)).toBeVisible();
  // And with no operator: the person with no contact and the one behind none.
  await show.getByRole("link", { name: "Users with no operator" }).click();
  await expect(page).toHaveURL(/[?&]operator=none/);
  await expect(rows).toHaveCount(2);
  await expect(of(nobody)).toBeVisible();
  await expect(of(made.gus.username)).toBeVisible();
  // The address opened afresh, as a colleague would, is the same list.
  const sent = page.url();
  await page.goto("./admin/users");
  await page.goto(sent);
  await expect(page.getByTestId("users").locator("tbody tr[data-user]")).toHaveCount(2);
  await show.getByRole("link", { name: "Every user" }).click();
  await expect(page.getByTestId("users").locator("tbody tr[data-user]")).toHaveCount(5);

  // The Contacts list: Show, with those that are no user and those behind no operator.
  await page.goto("./contacts");
  const contactsShow = page.getByRole("navigation", { name: "Show contacts" });
  // A plain visit, with no filter in the address, is of every contact, and says so.
  await expect(contactsShow.getByRole("link", { name: "Every contact" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  await contactsShow.getByRole("link", { name: "Contacts behind no operator" }).click();
  await expect(page).toHaveURL(/filter=is_operator%3Aeq%3Afalse/);
  await expect(
    contactsShow.getByRole("link", { name: "Contacts behind no operator" }),
  ).toHaveAttribute("aria-current", "page");
  // The grid's own filter changed: the gap is marked only while it is the gap's, and a
  // press of a gap starts the grid on it again, though the address is the same.
  await gapsFollowTheGrid(page, contactsShow, {
    pressed: "Contacts behind no operator",
    filter: "is_operator:eq:false",
    other: "Contacts that are no user",
    otherFilter: "is_user:eq:false",
  });
  // The same on the list of operators.
  await page.goto(`./operators?filter=${encodeURIComponent("is_open:eq:true")}`);
  await gapsFollowTheGrid(page, page.getByRole("navigation", { name: "Show operators" }), {
    pressed: "Nobody behind it",
    filter: "is_open:eq:true",
    other: "No user behind it",
    otherFilter: "scope:ne:internal",
  });
  const grid = page.getByTestId("grid-contacts");
  const narrowed = async (filter: string) => {
    await page.goto(`./contacts?filter=${encodeURIComponent(filter)}`);
    return grid.locator("[row-id]");
  };
  // Behind no operator: Gus, and the contact that was taken; not the engineer nor the
  // user made after the refusals, who each stand behind one.
  let found = await narrowed(`is_operator:eq:false name:contains:${suffix}`);
  await expect(found).toHaveCount(2);
  const names = grid.locator('[row-id] [col-id="name"]');
  expect((await names.allTextContents()).sort()).toEqual(
    [`Gus Example ${suffix}`, `Taken Example ${suffix}`].sort(),
  );
  // No user: the contact that was taken alone.
  found = await narrowed(`is_user:eq:false name:contains:${suffix}`);
  await expect(found).toHaveCount(1);
  await expect(names).toHaveText(`Taken Example ${suffix}`);
  // Neither: both cells blank, as the other two lists leave theirs (P-302).
  await expect(grid.locator('[row-id] [col-id="is_user"]')).toHaveText("");
  await expect(grid.locator('[row-id] [col-id="is_operator"]')).toHaveText("");
  await expectClean(page, seen);
});

test("P-284: an operator is made in one press, from a user's page and from a contact's", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(180_000);
  const headers: Headers = await session(request, account);
  const hal = `Hal Example ${suffix}`;
  const halContact = await make(request, headers, "/contacts", {
    name: hal,
    record_status: "active",
  });
  const long = `An example person of a name far too long for a label ${suffix}`;
  const longContact = await make(request, headers, "/contacts", {
    name: long,
    record_status: "active",
  });
  // 0.9.14: a contact is no longer retired under its account or a label (P-291), so a
  // user whose contact is retired, and its open label, are not made here: what the
  // pages say of one left so before 0.9.14 is held by the tests of `briefMark`, and a
  // person retired together by retired.spec.ts.
  // A contact behind one operator, which is then released, the contact kept.
  const joEmail = `jo.${suffix}@example.net`;
  const jo = await make(request, headers, "/contacts", {
    name: `Jo Example ${suffix}`,
    email: joEmail,
    record_status: "active",
  });
  const joOperator = await make(request, headers, "/operators", {
    label: `${suffix}-jo`,
    contact_hid: jo.hid,
    record_status: "active",
  });
  const joRead = await request.get(`./api/v1/operators/${joOperator.hid}`, { headers });
  const released = await request.post(`./api/v1/operators/${joOperator.hid}/retire`, {
    headers,
    data: {
      row_version: ((await joRead.json()) as { row_version: number }).row_version,
      linked: { contact: "keep" },
    },
  });
  expect(released.status()).toBe(200);
  const seen = await watch(page.context());
  await signIn(page, account);

  // The Contacts list marks a released label so.
  await page.goto(`./contacts?filter=${encodeURIComponent(`email:eq:${joEmail}`)}`);
  const contacts = page.getByTestId("grid-contacts");
  await expect(contacts.locator("[row-id]")).toHaveCount(1);
  await expect(contacts.locator('[row-id] [col-id="is_operator"]')).toHaveText(
    `${suffix}-jo (released)`,
  );
  await expect(contacts.locator('[row-id] [col-id="is_user"]')).toHaveText("");

  // From a user's page: its username as the label, pressed twice while held back, once sent.
  await openUser(page, made.gus.hid, made.gus.username);
  const operators = page.getByTestId("user-operators");
  await expect(operators).toContainText("no operator");
  let posted = 0;
  await page.route("**/api/v1/operators", async (route) => {
    if (route.request().method() === "POST") {
      posted += 1;
      await new Promise((resolve) => setTimeout(resolve, 1500));
    }
    await route.continue();
  });
  const press = operators.getByRole("button", { name: "Make an operator" });
  await press.click();
  await press.click({ force: true }).catch(() => undefined);
  await expect(page.getByTestId("operator-heading")).toContainText(made.gus.username);
  await expect(page.getByTestId("operator-scope")).toHaveAttribute("data-scope", "internal");
  expect(posted).toBe(1);
  await page.unroute("**/api/v1/operators");
  await openUser(page, made.gus.hid, made.gus.username);
  await expect(operators.getByRole("link", { name: made.gus.username })).toBeVisible();
  await expect(operators.getByRole("button", { name: "Make an operator" })).toHaveCount(0);

  // From a contact's page, its name as the label, the colour asked for when pressed even
  // when that answer is slow.
  await page.route("**/api/v1/colours", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 1000));
    await route.continue();
  });
  await page.goto(`./contacts/${encodeURIComponent(halContact.hid)}`);
  const marks = page.getByTestId("contact-operator-marks");
  await expect(marks).toContainText("no operator");
  await marks.getByRole("button", { name: "Make an operator" }).click();
  await expect(page.getByTestId("operator-heading")).toContainText(hal);
  await expect(page.getByText(`Operator ${hal} was created.`)).toBeVisible();
  await expect(page.getByTestId("operator-scope")).toHaveAttribute("data-scope", "external");
  await page.unroute("**/api/v1/colours");

  // A name that is no label: no press that must fail, but the label and the colour open
  // at once, the fault said in plain words, and nothing sent until it is put right.
  await page.goto(`./contacts/${encodeURIComponent(longContact.hid)}`);
  await expect(marks.getByRole("button", { name: "Make an operator" })).toHaveCount(0);
  const label = marks.getByLabel("Label (required)");
  await expect(label).toHaveAttribute("aria-invalid", "true");
  await expect(label).toHaveValue(long);
  await expect(marks.locator(".field-error").first()).toContainText(
    `A label is at most 40 characters, and this one has ${long.length}`,
  );
  await expect(marks.getByRole("textbox", { name: "Colour" })).toHaveValue(/^#[0-9a-f]{6}$/);
  await marks.getByRole("button", { name: "Make the operator" }).click();
  await expect(label).toHaveValue(long);
  await label.fill(`${suffix}-long`);
  await expect(label).not.toHaveAttribute("aria-invalid", "true");
  await marks.getByRole("button", { name: "Make the operator" }).click();
  await expect(page.getByTestId("operator-heading")).toContainText(`${suffix}-long`);
  await page.getByTestId("operator-person").getByRole("link", { name: long }).click();
  await expect(marks.getByRole("link", { name: `${suffix}-long` })).toBeVisible();
  await expect(marks.getByRole("button", { name: "Make an operator" })).toHaveCount(0);
  await expectClean(page, seen);

  // The users the file made are disabled: none is left that can sign in.
  for (const hid of made.users) {
    const read = await request.get(`./api/v1/users/${hid}`, { headers });
    const { row_version } = (await read.json()) as { row_version: number };
    const answer = await request.patch(`./api/v1/users/${hid}`, {
      headers,
      data: { row_version, disabled: true },
    });
    expect(answer.status()).toBe(200);
  }
});

/** A colour as `#rrggbb`, as a browser writes it in a style: `rgb(r, g, b)`. */
function rgbOf(hex: string): string {
  const [r, g, b] = [1, 3, 5].map((at) => Number.parseInt(hex.slice(at, at + 2), 16));
  return `rgb\\(${r}, ${g}, ${b}\\)`;
}
