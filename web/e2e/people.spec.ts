// The browser scenarios of people in release 0.9.3:
//
//   P-172  Every person is a contact, and a user and an operator are each a part one plays.
//          A user is made with its person, a new contact, and shows that contact's name,
//          email and two numbers, on the Users list and on its page, which changes them
//          on the contact; it is given another contact, a new one, or none. A contact
//          says it is a user, and which. An operator is internal where the person behind
//          it is a user and external where not, shows that person's email and numbers and
//          changes them on the contact, and is given a user, another contact or a new
//          person.
//   P-173  An Admin renames a user, who signs in under the new name from then on, and
//          not under the old; a name the rule does not take, or another user's, is
//          refused on the field.
//   P-174  The username of the user a contact is, is told to an Admin alone: another
//          role reads that the contact is a user, and that a label is internal.
//
// They keep to the rules of support.ts: an account of their own, and users, contacts
// and labels of their own with the file's mark in their names, found in every list by
// it. The users the file makes are disabled when it ends. One sign-in fails, on purpose,
// under the old name of the user it renames (rule 6). The scenarios run in order: the
// later ones use the user the first one makes.

import { type Browser, expect, type Locator, type Page } from "@playwright/test";
import { type Headers, make, session } from "./referenceSteps";
import { region } from "./structure";
import { createAccount, expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const suffix = mark("people");
const username = `e2e-${suffix}-ada`;
const renamed = `e2e-${suffix}-ada-r`;
const ada = { name: `Ada Example ${suffix}`, email: `ada.${suffix}@example.org` };
const bo = { name: `Bo Example ${suffix}`, email: `bo.${suffix}@example.org` };
const cy = { name: `Cy Example ${suffix}`, email: `cy.${suffix}@example.org` };
const dee = {
  name: `Dee Example ${suffix}`,
  email: `dee.${suffix}@example.net`,
  phone: "+1 555 0151",
  phone2: "+1 555 0152",
};
const eve = { name: `Eve Example ${suffix}`, email: `eve.${suffix}@example.net` };
const internal = `IN-${suffix}`;
const external = `EX-${suffix}`;

// What the scenarios hand on: the user made, its access code and its page.
const made = { hid: "", accessCode: "", page: "", internal: "", dee: "" };

/** The row of a user on the Users list, found by searching for its username. */
async function userRow(page: Page, name: string): Promise<Locator> {
  await page.goto(`./admin/users?q=${encodeURIComponent(name)}`);
  await expect(page.getByRole("heading", { level: 1, name: "Users" })).toBeVisible();
  const row = page.getByTestId("users").locator(`tr[data-user="${name}"]`);
  await expect(row).toBeVisible();
  return row;
}

/** Choose a contact in a search of the person: type a part of it, and press its button. */
async function choose(within: Locator, field: string, list: string, typed: string, name: string) {
  await within.getByLabel(field, { exact: true }).fill(typed);
  await within
    .getByRole("list", { name: list })
    .getByRole("button", {
      name: new RegExp(`^${name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")} \\(`),
    })
    .click();
}

/** Sign in, in a browser of its own, as a user by a name and a code. */
async function signInElsewhere(browser: Browser, name: string, code: string) {
  const context = await browser.newContext();
  const page = await context.newPage();
  const seen = await watch(context);
  await page.goto("./");
  await page.getByLabel("Username").fill(name);
  await page.getByLabel("Access code").fill(code);
  await page.getByRole("button", { name: "Sign in" }).click();
  return { context, page, seen };
}

test("P-172: a user is made with its person, and shows the contact's name, email and numbers", async ({
  page,
  account,
}) => {
  test.setTimeout(120_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  await page.goto("./admin/users");
  await page.getByRole("button", { name: "New user" }).click();
  const form = region(page, "New user");
  // P-173: the form says what the username is for, and that it can change.
  await expect(form).toContainText("What the person signs in with");
  await expect(form).toContainText("An Admin can change it later.");
  await form.getByLabel("Username").fill(username);
  await expect(form.getByRole("radio", { name: "A new contact" })).toBeChecked();
  const person = form.getByTestId("new-person-new-user");
  await person.getByLabel("Name (required)").fill(ada.name);
  await person.getByLabel("Email").fill(ada.email);
  await person.getByLabel("Organization").fill("Infrastructure Operations");
  await person.getByLabel("Phone", { exact: true }).fill("+1 555 0142");
  await person.getByLabel("Second phone").fill("+1 555 0143");
  await form.getByLabel("Role").selectOption({ label: "View-only" });
  await form.getByRole("button", { name: "Create user" }).click();
  const secret = page.getByRole("region", { name: `Access code for ${username}` });
  await expect(secret).toBeVisible();
  made.accessCode = await secret.getByLabel("Shown once").inputValue();

  // The list shows the contact's name, email and two numbers.
  let row = await userRow(page, username);
  await expect(row.getByTestId("user-name")).toHaveText(ada.name);
  await expect(row.getByTestId("user-email")).toHaveText(ada.email);
  await expect(row.getByTestId("user-phone")).toHaveText("+1 555 0142");
  await expect(row.getByTestId("user-phone2")).toHaveText("+1 555 0143");

  // The page of the user shows them, and changes them on the contact.
  await row.getByRole("link", { name: username, exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: username })).toBeVisible();
  made.page = new URL(page.url()).pathname;
  made.hid = decodeURIComponent(made.page.split("/").at(-1) ?? "");
  const facts = page.getByTestId("user-person");
  await expect(facts.getByRole("link", { name: ada.name, exact: true })).toBeVisible();
  await expect(page.getByTestId("person-email")).toHaveText(ada.email);
  await expect(page.getByTestId("person-phone")).toHaveText("+1 555 0142");
  const details = region(page, "Change the name, email and numbers");
  await details.getByLabel("Second phone").fill("+1 555 0144");
  await details.getByRole("button", { name: "Save on the contact" }).click();
  await expect(page.getByText(`The contact ${ada.name} was saved.`)).toBeVisible();
  await expect(page.getByTestId("person-phone2")).toHaveText("+1 555 0144");
  row = await userRow(page, username);
  await expect(row.getByTestId("user-phone2")).toHaveText("+1 555 0144");

  // The contact says it is this user, and has the number changed there.
  await page.goto(made.page);
  await facts.getByRole("link", { name: ada.name, exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: ada.name })).toBeVisible();
  await expect(page.getByTestId("contact-phone2")).toHaveText("+1 555 0144");
  await expect(page.getByTestId("contact-user")).toContainText(username);
  // The list of contacts marks it as a user, and finds it among the users.
  const filter = `is_user:eq:true name:contains:${suffix}`;
  await page.goto(`./contacts?filter=${encodeURIComponent(filter)}`);
  const grid = page.getByTestId("grid-contacts");
  await expect(grid.locator("[row-id]")).toHaveCount(1);
  await expect(grid.locator('[row-id] [col-id="is_user"]')).toHaveText(username);

  // A new contact with the email of another is refused, on the field.
  await page.goto("./admin/users");
  await page.getByRole("button", { name: "New user" }).click();
  await form.getByLabel("Username").fill(`${username}-2`);
  await person.getByLabel("Name (required)").fill(`Another ${ada.name}`);
  await person.getByLabel("Email").fill(ada.email);
  await form.getByRole("button", { name: "Create user" }).click();
  await expect(person.getByLabel("Email")).toHaveAttribute("aria-invalid", "true");
  await expect(page.getByRole("region", { name: `Access code for ${username}-2` })).toHaveCount(0);
  await expectClean(page, seen, ["409 POST"]);
});

test("P-172: a user is given another contact, a new one, or none", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(120_000);
  const headers = await session(request, account);
  await make(request, headers, "/contacts", { ...bo, record_status: "active" });
  const seen = await watch(page.context());
  await signIn(page, account);
  await page.goto(made.page);
  const give = region(page, "Another contact, or none");

  // A contact there is, that is no user.
  await expect(give.getByRole("radio", { name: "A contact there is" })).toBeChecked();
  await choose(give, "Contact", "Other contacts that match", `bo.${suffix}`, bo.name);
  await give.getByRole("button", { name: "Give it this contact" }).click();
  const facts = page.getByTestId("user-person");
  await expect(facts.getByRole("link", { name: bo.name, exact: true })).toBeVisible();
  const row = await userRow(page, username);
  await expect(row.getByTestId("user-name")).toHaveText(bo.name);
  await expect(row.getByTestId("user-email")).toHaveText(bo.email);

  // A new contact, made from what is typed.
  await page.goto(made.page);
  await give.getByRole("radio", { name: "A new contact" }).check();
  await give.getByLabel("Name (required)").fill(cy.name);
  await give.getByLabel("Email").fill(cy.email);
  await give.getByLabel("Phone", { exact: true }).fill("+1 555 0145");
  await give.getByRole("button", { name: "Give it this contact" }).click();
  await expect(facts.getByRole("link", { name: cy.name, exact: true })).toBeVisible();
  await expect(page.getByTestId("person-phone")).toHaveText("+1 555 0145");

  // None: the user is shown by its username.
  await give.getByRole("radio", { name: "None", exact: true }).check();
  await give.getByRole("button", { name: "Take its contact away" }).click();
  await expect(facts).toHaveText(
    `${username} has no contact: it is shown by its username until it is given one.`,
  );
  await expect((await userRow(page, username)).getByTestId("user-name")).toHaveText("No contact");
  await expectClean(page, seen);
});

test("P-173: an Admin renames a user, who signs in under the new name and not the old", async ({
  page,
  account,
  browser,
}) => {
  test.setTimeout(120_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  await page.goto(made.page);
  const details = region(page, "Details");
  const field = details.getByLabel("Username");

  // A name the rule does not take, and another user's, are refused on the field.
  await field.fill("not a name");
  await details.getByRole("button", { name: "Save", exact: true }).click();
  await expect(field).toHaveAttribute("aria-invalid", "true");
  await field.fill(account.username.toUpperCase());
  await details.getByRole("button", { name: "Save", exact: true }).click();
  await expect(field).toHaveAttribute("aria-invalid", "true");
  await expect(page.getByRole("heading", { level: 1, name: username })).toBeVisible();

  // Renamed: the same user, by its HID, under its new name.
  await field.fill(renamed);
  await details.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: renamed })).toBeVisible();
  expect(new URL(page.url()).pathname).toBe(made.page);
  await expect(await userRow(page, renamed)).toBeVisible();

  // The person signs in under the new name, with the same code, and not under the old.
  const now = await signInElsewhere(browser, renamed, made.accessCode);
  await expect(now.page.getByRole("navigation", { name: "Main" })).toBeVisible({
    timeout: 20_000,
  });
  await expect(now.page.locator(".who-name")).toHaveText(renamed);
  await expectClean(now.page, now.seen);
  await now.context.close();
  const then = await signInElsewhere(browser, username, made.accessCode);
  await expect(then.page.getByRole("navigation", { name: "Main" })).toHaveCount(0);
  await expect(then.page.locator(".alert-error")).toBeVisible({ timeout: 20_000 });
  await expectClean(then.page, then.seen, ["401 POST"]);
  await then.context.close();
  await expectClean(page, seen, ["422 PATCH", "409 PATCH"]);
});

test("P-172: an operator is internal or external, with its person's email and numbers", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(180_000);
  const headers: Headers = await session(request, account);
  // A user with a contact of its own, made through the API with its person.
  const deeUser = await createAccount(request, `e2e-${suffix}-dee`, null, dee);
  const seen = await watch(page.context());
  await signIn(page, account);

  // Behind one label, a user: internal, with that person's email, numbers and user.
  await page.goto("./operators");
  await page.getByRole("button", { name: "New operator" }).click();
  let form = region(page, "New operator");
  await form.getByLabel("Label (required)").fill(internal);
  await form.getByRole("radio", { name: "A user", exact: true }).check();
  await choose(form, "User", "Users that match", `dee.${suffix}`, dee.name);
  await form.getByRole("button", { name: "Create operator" }).click();
  await expect(page.getByTestId("operator-heading")).toContainText(internal);
  await expect(page.getByTestId("operator-scope")).toHaveAttribute("data-scope", "internal");
  await expect(page.getByTestId("operator-scope")).toContainText("Internal");
  await expect(page.getByTestId("operator-email")).toHaveText(dee.email);
  await expect(page.getByTestId("operator-numbers")).toHaveText("+1 555 0151 · +1 555 0152");
  await expect(page.getByTestId("operator-user")).toContainText(deeUser.username);
  made.internal = new URL(page.url()).pathname;
  made.dee =
    (await page
      .getByTestId("operator-person")
      .getByRole("link", { name: dee.name })
      .getAttribute("href")) ?? "";

  // Behind another, a new person, who is made a contact: external.
  await page.goto("./operators");
  await page.getByRole("button", { name: "New operator" }).click();
  form = region(page, "New operator");
  await form.getByLabel("Label (required)").fill(external);
  await form.getByRole("radio", { name: "A new person", exact: true }).check();
  await form.getByLabel("Name (required)").fill(eve.name);
  await form.getByLabel("Email").fill(eve.email);
  await form.getByLabel("Phone", { exact: true }).fill("+1 555 0161");
  await form.getByLabel("Second phone").fill("+1 555 0162");
  await form.getByRole("button", { name: "Create operator" }).click();
  await expect(page.getByTestId("operator-heading")).toContainText(external);
  await expect(page.getByTestId("operator-scope")).toHaveAttribute("data-scope", "external");
  await expect(page.getByTestId("operator-numbers")).toHaveText("+1 555 0161 · +1 555 0162");
  await expect(page.getByTestId("operator-user")).toHaveCount(0);
  const externalPage = new URL(page.url()).pathname;

  // The person's number is changed there, on the contact.
  const numbers = region(page, "The person's email and numbers");
  await numbers.getByLabel("Phone", { exact: true }).fill("+1 555 0163");
  await numbers.getByRole("button", { name: "Save on the contact" }).click();
  await expect(page.getByTestId("operator-numbers")).toHaveText("+1 555 0163 · +1 555 0162");
  await page.getByTestId("operator-person").getByRole("link", { name: eve.name }).click();
  await expect(page.getByRole("heading", { level: 1, name: eve.name })).toBeVisible();
  await expect(page.getByTestId("contact-facts")).toContainText("+1 555 0163");
  await expect(page.getByTestId("contact-user")).toContainText("None");
  await expect(page.getByTestId("contact-operators")).toContainText("Behind 1 operator");

  // The list shows each as internal or external, with the person's email and numbers, and
  // finds them by it.
  const grid = page.getByTestId("grid-operators");
  const cell = (column: string) => grid.locator(`[row-id] [col-id="${column}"]`);
  const listed = async (filter: string, count: number) => {
    await page.goto(`./operators?filter=${encodeURIComponent(filter)}`);
    await expect(grid.locator("[row-id]")).toHaveCount(count);
  };
  await listed(`label:contains:${suffix}`, 2);
  await listed(`label:eq:${internal}`, 1);
  await expect(cell("scope")).toHaveText("Internal");
  await expect(cell("contact.email")).toHaveText(dee.email);
  await listed(`label:eq:${external}`, 1);
  await expect(cell("scope")).toHaveText("External");
  await expect(cell("contact.phone")).toHaveText("+1 555 0163");
  await expect(cell("contact.phone2")).toHaveText("+1 555 0162");
  await listed(`scope:eq:external label:contains:${suffix}`, 1);
  await expect(cell("label")).toContainText(external);

  // Handed over to the user, the external label is internal; left open, it is neither.
  await page.goto(externalPage);
  const hand = region(page, "Hand over, or leave open");
  await expect(hand.getByRole("radio", { name: "A user", exact: true })).toBeChecked();
  await choose(hand, "User", "Users that match", `dee.${suffix}`, dee.name);
  await hand.getByRole("button", { name: "Hand over", exact: true }).click();
  await expect(page.getByText(`${external} was handed over to ${dee.name}.`)).toBeVisible();
  await expect(page.getByTestId("operator-scope")).toHaveAttribute("data-scope", "internal");
  await hand.getByRole("button", { name: "Leave open" }).click();
  await expect(page.getByText(`${external} is left open`)).toBeVisible();
  await expect(page.getByTestId("operator-scope")).toHaveAttribute("data-scope", "");
  await expect(page.getByTestId("operator-scope")).toContainText("nobody is behind it");
  await expectClean(page, seen);

  // The users the file made are disabled: none is left that can sign in.
  for (const hid of [made.hid, deeUser.hid]) {
    const read = await request.get(`./api/v1/users/${hid}`, { headers });
    const { row_version } = (await read.json()) as { row_version: number };
    const answer = await request.patch(`./api/v1/users/${hid}`, {
      headers,
      data: { row_version, disabled: true },
    });
    expect(answer.status()).toBe(200);
  }
});

test("P-174: an account that is no Admin reads that a contact is a user, and not which", async ({
  account,
  browser,
  request,
}) => {
  test.setTimeout(120_000);
  const headers = await session(request, account);
  const clerk = await createAccount(request, `e2e-${suffix}-ivy`, "inventory");
  const { context, page, seen } = await signInElsewhere(browser, clerk.username, clerk.accessCode);
  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible({ timeout: 20_000 });

  // The contact is marked as a user, by no username; the label it stands behind is
  // internal, and names no user.
  await page.goto(`.${made.dee.replace(/^.*?\/contacts\//, "/contacts/")}`);
  await expect(page.getByRole("heading", { level: 1, name: dee.name })).toBeVisible();
  await expect(page.getByTestId("contact-user")).toHaveText(
    "A user: this person signs in to hirdir",
  );
  await page.goto(`.${made.internal.replace(/^.*?\/operators\//, "/operators/")}`);
  await expect(page.getByTestId("operator-scope")).toHaveAttribute("data-scope", "internal");
  await expect(page.getByTestId("operator-user")).toHaveCount(0);
  const filter = `is_user:eq:true name:contains:${suffix}`;
  await page.goto(`./contacts?filter=${encodeURIComponent(filter)}`);
  const grid = page.getByTestId("grid-contacts");
  await expect(grid.locator("[row-id]")).toHaveCount(1);
  await expect(grid.locator('[row-id] [col-id="is_user"]')).toHaveText("A user");
  await expectClean(page, seen);
  await context.close();

  const read = await request.get(`./api/v1/users/${clerk.hid}`, { headers });
  const { row_version } = (await read.json()) as { row_version: number };
  const answer = await request.patch(`./api/v1/users/${clerk.hid}`, {
    headers,
    data: { row_version, disabled: true },
  });
  expect(answer.status()).toBe(200);
});
