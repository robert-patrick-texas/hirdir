// The browser scenarios of a retired account and of a person retired together, in
// release 0.9.14:
//
//   P-292  A user is active, disabled or retired, said in words. The list of users leaves
//          the retired out; Show › Retired users lists them by themselves, an address of
//          its own, and Export CSV saves what the view shows.
//   P-296  An Admin retires an account and brings it back, with a new access code shown
//          once, no role and no group. A retired account's page offers only its
//          username, its notes and its contact taken away. A username that a retired
//          account has is refused to another, with a link to the retired one.
//   P-291  The pages of a user, a contact and an operator show the chain of the person.
//   P-297  One confirmation says what becomes of each linked record: Retire ticked from
//          the start, and for each label Release, Hand over to, Leave open or Keep. A
//          contact is not retired while its account or a label stands on it. Somebody of
//          the Inventory role retires no account. A refusal by the server stays in the
//          confirmation, and the list is read again.
//   P-298  An Admin alone brings a user, a contact or an operator back.
//
// They keep to the rules of support.ts: an account of their own, and users, contacts and
// operators of their own with the file's mark in their names, found in every list by
// it. The accounts the file makes are disabled, where they are not retired, when it
// ends. Each scenario makes the people it retires.

import { readFile } from "node:fs/promises";
import {
  type APIRequestContext,
  expect,
  type Locator,
  type Page,
  type TestInfo,
} from "@playwright/test";
import { type Headers, make, session } from "./referenceSteps";
import { region } from "./structure";
import { createAccount, expectClean, mark, signIn, test, watch } from "./support";

const suffix = mark("retired");
// Every account the scenarios make, to be put away when they end.
const madeAccounts: string[] = [];

/** One person: a user who is a contact behind one label, or two. */
interface Person {
  user: { hid: string; username: string };
  contact: { hid: string; name: string };
  labels: Array<{ hid: string; label: string }>;
  accessCode: string;
}

/** Make a person through the API: the user, its contact and its labels, by one name. */
async function person(
  request: APIRequestContext,
  headers: Headers,
  key: string,
  options: { labels?: number; role?: string } = {},
): Promise<Person> {
  const username = `e2e-${suffix}-${key}`;
  const name = `${key.charAt(0).toUpperCase()}${key.slice(1)} Example ${suffix}`;
  const answer = await request.post("./api/v1/users", {
    headers,
    data: {
      username,
      contact: { name, email: `${key}.${suffix}@example.net` },
      operator: { label: `${suffix}-${key}` },
      ...(options.role ? { role: options.role } : {}),
    },
  });
  expect(answer.status(), `post /users: ${await answer.text()}`).toBe(201);
  const created = (await answer.json()) as {
    user: { hid: string; username: string; contact: { hid: string; name: string } };
    operator: { hid: string; label: string };
    access_code: string;
  };
  madeAccounts.push(created.user.hid);
  const labels = [{ hid: created.operator.hid, label: created.operator.label }];
  for (let more = 2; more <= (options.labels ?? 1); more += 1) {
    const label = `${suffix}-${key}${more}`;
    const made = await make(request, headers, "/operators", {
      label,
      contact_hid: created.user.contact.hid,
      record_status: "active",
    });
    labels.push({ hid: made.hid, label });
  }
  return {
    user: { hid: created.user.hid, username: created.user.username },
    contact: { hid: created.user.contact.hid, name: created.user.contact.name },
    labels,
    accessCode: created.access_code,
  };
}

/** What the API answers of a record, read as the file's own Admin. */
async function read<T>(request: APIRequestContext, headers: Headers, path: string): Promise<T> {
  const answer = await request.get(`./api/v1${path}`, { headers });
  expect(answer.status(), `get ${path}: ${await answer.text()}`).toBe(200);
  return (await answer.json()) as T;
}

interface Status {
  record_status: string;
}

async function openUser(page: Page, user: { hid: string; username: string }) {
  await page.goto(`./admin/users/${encodeURIComponent(user.hid)}`);
  await expect(page.getByRole("heading", { level: 1, name: user.username })).toBeVisible();
}

async function openContact(page: Page, contact: { hid: string; name: string }) {
  await page.goto(`./contacts/${encodeURIComponent(contact.hid)}`);
  await expect(page.getByRole("heading", { level: 1, name: contact.name })).toBeVisible();
}

async function openOperator(page: Page, operator: { hid: string; label: string }) {
  await page.goto(`./operators/${encodeURIComponent(operator.hid)}`);
  await expect(page.getByTestId("operator-heading")).toContainText(operator.label);
}

/** The rows of the Users list, searched for this file's users and narrowed as asked. */
async function usersListed(page: Page, query = ""): Promise<Locator> {
  await page.goto(`./admin/users?q=${encodeURIComponent(suffix)}${query}`);
  await expect(page.getByRole("heading", { level: 1, name: "Users" })).toBeVisible();
  const table = page.getByTestId("users");
  await expect(table).toBeVisible();
  return table.locator("tbody tr[data-user]");
}

/** The lines of the users' file that Export CSV saves from the view on show. */
async function exported(page: Page, testInfo: TestInfo, name: string): Promise<string[]> {
  const saved = page.waitForEvent("download");
  await page.getByRole("button", { name: /^Export CSV of the (retired )?users$/ }).click();
  const download = await saved;
  const path = testInfo.outputPath(`${name}-${download.suggestedFilename()}`);
  await download.saveAs(path);
  return (await readFile(path, "utf8")).trimEnd().split(/\r?\n/);
}

/** The page is whole in view at 1280 pixels, with no sideways scroll. */
async function fitsAt1280(page: Page, what: string) {
  await expect
    .poll(
      () =>
        page.evaluate(
          () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
        ),
      { message: `${what} is whole in view at 1280 pixels` },
    )
    .toBe(true);
}

/** The chain of a page: its three parts, as they read. */
function chain(page: Page) {
  const nav = page.getByTestId("chain");
  return {
    nav,
    operators: nav.locator('[data-part="operator"]'),
    contact: nav.locator('[data-part="contact"]'),
    user: nav.locator('[data-part="user"]'),
    here: nav.locator('[data-here="true"]'),
  };
}

/** The row of a label in the confirmation, by its HID. */
function labelRow(dialog: Locator, operator: { hid: string }): Locator {
  return dialog.locator(`[data-row="operator"][data-operator="${operator.hid}"]`);
}

test.beforeEach(async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
});

test.afterAll(async ({ request, accounts }) => {
  // A run leaves no account of its own that can sign in: a retired one cannot already.
  const headers = await session(request, await accounts.of("retired"));
  for (const hid of madeAccounts) {
    const path = `./api/v1/users/${encodeURIComponent(hid)}`;
    const found = await request.get(path, { headers });
    if (found.status() !== 200) continue;
    const user = (await found.json()) as { row_version: number; record_status: string };
    if (user.record_status === "retired") continue;
    await request.patch(path, { headers, data: { disabled: true, row_version: user.row_version } });
  }
});

test("P-292, P-296: an account is retired, left out of the list until asked for, and brought back", async ({
  page,
  account,
  request,
}, testInfo) => {
  test.setTimeout(240_000);
  const headers = await session(request, account);
  const group = await make(request, headers, "/user-groups", { name: `${suffix}-team` });
  const username = `e2e-${suffix}-lone`;
  const made = await request.post("./api/v1/users", {
    headers,
    data: { username, role: "inventory", group_hids: [group.hid], notes: `Left ${suffix}.` },
  });
  expect(made.status(), await made.text()).toBe(201);
  const lone = ((await made.json()) as { user: { hid: string; username: string } }).user;
  madeAccounts.push(lone.hid);
  const off = await createAccount(request, `e2e-${suffix}-off`, null);
  madeAccounts.push(off.hid);
  const offNow = await read<{ row_version: number }>(request, headers, `/users/${off.hid}`);
  const disabled = await request.patch(`./api/v1/users/${off.hid}`, {
    headers,
    data: { disabled: true, row_version: offNow.row_version },
  });
  expect(disabled.status()).toBe(200);
  const seen = await watch(page.context());
  await signIn(page, account);

  // The list says of each account which it is, in words.
  let rows = await usersListed(page);
  const row = (name: string) => page.getByTestId("users").locator(`tr[data-user="${name}"]`);
  await expect(row(username).getByTestId("user-state")).toHaveText("Active");
  await expect(row(off.username).getByTestId("user-state")).toHaveText("Disabled");

  // Its page: Active, and Retire, which with nothing linked asks plainly.
  await openUser(page, lone);
  await expect(page.getByTestId("user-state")).toHaveText("Active");
  await expect(chain(page).user).toContainText(username);
  await expect(chain(page).contact).toContainText("no contact");
  await expect(chain(page).operators).toContainText("no operator");
  await region(page, "Retire").getByRole("button", { name: "Retire account" }).click();
  const ask = page.getByTestId("retire-person");
  await expect(ask.getByRole("heading", { name: `Retire ${username}?` })).toBeVisible();
  await expect(ask).toContainText(`${username} signs in no longer`);
  await expect(ask.getByTestId("retire-rows")).toHaveCount(0);
  await ask.getByRole("button", { name: "Retire account" }).click();
  await expect(page.getByText(`${username} was retired.`)).toBeVisible();

  // Retired: said at its name and in State, with why the rest is not offered.
  await expect(page.getByTestId("user-state")).toHaveText("Retired");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Retired");
  await expect(page.getByTestId("user-retired")).toContainText(
    "it signs in with nothing, is in no group and holds no role",
  );
  const facts = page.getByTestId("user-facts");
  await expect(facts).toContainText("No role");
  await expect(facts.getByRole("link", { name: `${suffix}-team` })).toHaveCount(0);
  const details = region(page, "Details");
  await expect(details.getByLabel("Username")).toBeVisible();
  await expect(details.getByLabel("Notes")).toBeVisible();
  await expect(details.getByLabel("Disabled")).toHaveCount(0);
  for (const gone of ["Groups", "Access code", "Sessions", "Retire"]) {
    await expect(region(page, gone)).toHaveCount(0);
  }
  await expect(region(page, "Retired").getByRole("button", { name: "Bring back" })).toBeVisible();
  await fitsAt1280(page, "the page of a retired account");

  // The list leaves it out; Retired users lists it by itself, marked, at its own address.
  rows = await usersListed(page);
  await expect(row(off.username)).toBeVisible();
  await expect(row(username)).toHaveCount(0);
  const lines = await exported(page, testInfo, "shown");
  expect(lines[0]).toContain("record_status");
  expect(lines.some((line) => line.startsWith(`${off.username},`))).toBe(true);
  expect(lines.some((line) => line.startsWith(`${username},`))).toBe(false);
  const show = page.getByRole("navigation", { name: "Show users" });
  await show.getByRole("link", { name: "Retired users" }).click();
  await expect(page).toHaveURL(/[?&]retired=only(&|$)/);
  await expect(page).toHaveURL(new RegExp(`[?&]q=${suffix}(&|$)`));
  await expect(show.getByRole("link", { name: "Retired users" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  await expect(page.getByTestId("users")).toHaveAttribute("data-gap", "retired");
  await expect(row(username)).toHaveAttribute("data-state", "Retired");
  await expect(row(username).getByRole("rowheader")).toContainText("Retired");
  await expect(row(username).getByTestId("user-state")).toHaveText("Retired");
  await expect(row(off.username)).toHaveCount(0);
  await expect(rows).toHaveCount(1);
  const retiredLines = await exported(page, testInfo, "retired");
  expect(retiredLines.some((line) => line.startsWith(`${username},`))).toBe(true);
  expect(retiredLines.some((line) => line.startsWith(`${off.username},`))).toBe(false);
  await fitsAt1280(page, "the list of retired users");
  // The address is the view: opened afresh, it lists the retired.
  await page.goto(`./admin/users?retired=only&q=${encodeURIComponent(suffix)}`);
  await expect(row(username)).toBeVisible();

  // Its username stays its own: a new account of that name is refused, with a link to it.
  await page.getByRole("button", { name: "New user" }).click();
  const form = region(page, "New user");
  await form.getByLabel("Username (required)").fill(username);
  await form.getByRole("checkbox", { name: "Also a contact" }).uncheck();
  await form.getByRole("button", { name: "Create user" }).click();
  await expect(form.getByLabel("Username (required)")).toHaveAttribute("aria-invalid", "true");
  const refusal = form.locator(".alert-error");
  await expect(refusal).toContainText(`The retired account ${username} has this username`);
  await expect(refusal).toContainText("rename that account to free the name, or bring it back");
  await refusal.getByRole("link", { name: username }).click();
  await expect(page.getByRole("heading", { level: 1, name: username })).toBeVisible();

  // Renamed, a retired account frees its name; and it is the same account.
  const renamed = `${username}-was`;
  await region(page, "Details").getByLabel("Username").fill(renamed);
  await region(page, "Details").getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: renamed })).toBeVisible();
  await expect(page.getByTestId("user-state")).toHaveText("Retired");

  // Brought back: a new access code, shown once, no role and no group.
  await region(page, "Retired").getByRole("button", { name: "Bring back" }).click();
  const back = page.getByTestId("bring-back-user");
  await expect(back.getByRole("heading", { name: `Bring ${renamed} back?` })).toBeVisible();
  await expect(back).toContainText("It has no role and no group until an Admin gives them");
  await back.getByRole("button", { name: "Bring back" }).click();
  const secret = page.getByTestId("secret-box");
  await expect(
    secret.getByRole("heading", { name: `New access code for ${renamed}` }),
  ).toBeVisible();
  await expect(secret).toContainText("with no role and no group");
  const code = await secret.getByLabel("Shown once").inputValue();
  expect(code.length).toBeGreaterThanOrEqual(12);
  await expect(page.getByTestId("user-state")).toHaveText("Active");
  await expect(page.getByTestId("user-facts")).toContainText("No role");
  await expect(
    region(page, "Groups").getByRole("checkbox", { name: `${suffix}-team` }),
  ).not.toBeChecked();
  await expect(
    region(page, "Retire").getByRole("button", { name: "Retire account" }),
  ).toBeVisible();
  // The new code signs the account in.
  const signedIn = await request.post("./api/v1/auth/sign-in", {
    data: { username: renamed, access_code: code },
  });
  expect(signedIn.status()).toBe(200);
  rows = await usersListed(page);
  await expect(row(renamed).getByTestId("user-state")).toHaveText("Active");
  await expectClean(page, seen, ["409 POST"]);
});

test("P-291, P-297: a contact is retired with its account, one label handed over and one released, and the user brought back", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(240_000);
  const headers = await session(request, account);
  const kim = await person(request, headers, "kim", { labels: 2, role: "inventory" });
  const [first, second] = kim.labels as [Person["labels"][0], Person["labels"][0]];
  const sam = await make(request, headers, "/contacts", {
    name: `Sam Example ${suffix}`,
    email: `sam.${suffix}@example.net`,
    record_status: "active",
  });
  const seen = await watch(page.context());
  await signIn(page, account);

  // The chain, on each of the three pages: operator, contact, user, each a link.
  await openContact(page, kim.contact);
  let links = chain(page);
  await expect(links.operators.getByRole("link", { name: first.label, exact: true })).toBeVisible();
  await expect(
    links.operators.getByRole("link", { name: second.label, exact: true }),
  ).toBeVisible();
  await expect(links.here).toContainText(kim.contact.name);
  await expect(links.user.getByRole("link", { name: kim.user.username })).toBeVisible();
  await fitsAt1280(page, "the page of a contact");
  await links.user.getByRole("link", { name: kim.user.username }).click();
  await expect(page.getByRole("heading", { level: 1, name: kim.user.username })).toBeVisible();
  links = chain(page);
  await expect(links.here).toContainText(kim.user.username);
  await expect(links.contact.getByRole("link", { name: kim.contact.name })).toBeVisible();
  await fitsAt1280(page, "the page of a user");
  await links.operators.getByRole("link", { name: second.label, exact: true }).click();
  await expect(page.getByTestId("operator-heading")).toContainText(second.label);
  links = chain(page);
  await expect(links.here).toContainText(second.label);
  await expect(links.operators.getByRole("link", { name: first.label, exact: true })).toBeVisible();
  await fitsAt1280(page, "the page of an operator");
  await links.contact.getByRole("link", { name: kim.contact.name }).click();
  await expect(page.getByRole("heading", { level: 1, name: kim.contact.name })).toBeVisible();

  // Retire the contact: each linked record listed, Retire ticked from the start.
  await region(page, "Retire").getByRole("button", { name: "Retire contact" }).click();
  const ask = page.getByTestId("retire-person");
  await expect(ask.getByRole("heading", { name: `Retire ${kim.contact.name}?` })).toBeVisible();
  const accountBox = ask.getByRole("checkbox", { name: `Retire the account ${kim.user.username}` });
  // The one rule: with the contact going, the account goes and no label is kept.
  await expect(accountBox).toBeChecked();
  await expect(accountBox).toBeDisabled();
  await expect(ask.locator('[data-row="user"]')).toContainText("Inventory · Active");
  await expect(ask.getByTestId("retire-rule")).toContainText(
    "A contact is not retired while its account or a label stands on it",
  );
  for (const label of kim.labels) {
    const row = labelRow(ask, label);
    await expect(row).toContainText("given to nothing");
    await expect(row.getByRole("radio", { name: "Release", exact: true })).toBeChecked();
    await expect(row.getByRole("radio", { name: "Leave open", exact: true })).toBeVisible();
    await expect(row.getByRole("radio", { name: "Keep", exact: true })).toHaveCount(0);
  }
  await fitsAt1280(page, "the confirmation of a retirement");

  // Hand over to nobody is said at its row, and nothing is sent.
  const handed = labelRow(ask, first);
  await handed.getByRole("radio", { name: "Hand over to", exact: true }).check();
  await ask.getByRole("button", { name: "Retire contact" }).click();
  await expect(handed).toContainText("Choose the person the label is handed over to");
  await expect(ask).toBeVisible();
  // Handed over to Sam; the other released, as it was ticked.
  const to = handed.getByLabel(`Person to hand ${first.label} over to`);
  await to.fill(`Sam Example ${suffix}`);
  await handed
    .getByRole("list", { name: "Contacts that match" })
    .getByRole("button", { name: new RegExp(`^Sam Example ${suffix}`) })
    .click();
  await ask.getByRole("button", { name: "Retire contact" }).click();
  await expect(
    page.getByText(
      `${kim.contact.name} was retired, with the account ${kim.user.username}. ${first.label} was handed over and ${second.label} was released.`,
    ),
  ).toBeVisible();
  await expect(ask).toHaveCount(0);

  // One change did all of it.
  expect((await read<Status>(request, headers, `/users/${kim.user.hid}`)).record_status).toBe(
    "retired",
  );
  expect((await read<Status>(request, headers, `/contacts/${kim.contact.hid}`)).record_status).toBe(
    "retired",
  );
  const firstNow = await read<Status & { contact_hid: string }>(
    request,
    headers,
    `/operators/${first.hid}`,
  );
  expect(firstNow).toMatchObject({ record_status: "active", contact_hid: sam.hid });
  expect((await read<Status>(request, headers, `/operators/${second.hid}`)).record_status).toBe(
    "retired",
  );
  // The chain marks what is retired, and no longer lists the label that went to Sam.
  links = chain(page);
  await expect(links.contact).toContainText("Retired");
  await expect(links.user).toContainText("Retired");
  await expect(links.operators).toContainText("released");
  await expect(links.operators.getByRole("link", { name: first.label, exact: true })).toHaveCount(
    0,
  );

  // The user is brought back with its contact, which is needed, and the label ticked.
  await openUser(page, kim.user);
  await expect(page.getByTestId("user-state")).toHaveText("Retired");
  await region(page, "Retired").getByRole("button", { name: "Bring back" }).click();
  const back = page.getByTestId("bring-back-user");
  const contactBox = back.getByRole("checkbox", {
    name: `Bring back the contact ${kim.contact.name}`,
  });
  await expect(contactBox).toBeChecked();
  await expect(contactBox).toBeDisabled();
  await expect(back).toContainText("the two are brought back together");
  const labelBox = back.getByRole("checkbox", { name: `Bring back the label ${second.label}` });
  await expect(labelBox).not.toBeChecked();
  await labelBox.check();
  await back.getByRole("button", { name: "Bring back" }).click();
  await expect(
    page.getByTestId("secret-box").getByRole("heading", {
      name: `New access code for ${kim.user.username}`,
    }),
  ).toBeVisible();
  await expect(page.getByTestId("user-state")).toHaveText("Active");
  expect((await read<Status>(request, headers, `/contacts/${kim.contact.hid}`)).record_status).toBe(
    "active",
  );
  expect((await read<Status>(request, headers, `/operators/${second.hid}`)).record_status).toBe(
    "active",
  );
  links = chain(page);
  await expect(links.contact).not.toContainText("Retired");
  await expect(
    links.operators.getByRole("link", { name: second.label, exact: true }),
  ).toBeVisible();
  await expectClean(page, seen);
});

test("P-297: a label is released with the rest kept, and an account retired with its contact kept and a label left open", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(240_000);
  const headers = await session(request, account);
  const lee = await person(request, headers, "lee", { labels: 2 });
  const [first, second] = lee.labels as [Person["labels"][0], Person["labels"][0]];
  const seen = await watch(page.context());
  await signIn(page, account);

  // From the page of a label: the contact unticked, the account and the other label kept.
  await openOperator(page, first);
  await region(page, "Release").getByRole("button", { name: "Release", exact: true }).click();
  let ask = page.getByTestId("retire-person");
  const contactBox = ask.getByRole("checkbox", { name: `Retire the contact ${lee.contact.name}` });
  const accountBox = ask.getByRole("checkbox", { name: `Retire the account ${lee.user.username}` });
  const other = labelRow(ask, second);
  await expect(contactBox).toBeChecked();
  await expect(accountBox).toBeDisabled();
  await expect(other.getByRole("radio", { name: "Keep", exact: true })).toHaveCount(0);
  await contactBox.uncheck();
  // With the contact kept, the account and a label are kept or not, as chosen.
  await expect(accountBox).toBeEnabled();
  await accountBox.uncheck();
  await other.getByRole("radio", { name: "Keep", exact: true }).check();
  await expect(other).toContainText(`${lee.contact.name} stays behind the label`);
  // Ticked again, the contact takes the account with it, and Keep is gone.
  await contactBox.check();
  await expect(accountBox).toBeChecked();
  await expect(other.getByRole("radio", { name: "Release", exact: true })).toBeChecked();
  await contactBox.uncheck();
  await accountBox.uncheck();
  await other.getByRole("radio", { name: "Keep", exact: true }).check();
  await ask.getByRole("button", { name: "Release", exact: true }).click();
  await expect(
    page.getByText(
      `${first.label} was released. The account ${lee.user.username}, the contact ${lee.contact.name} and the label ${second.label} stay.`,
    ),
  ).toBeVisible();
  expect((await read<Status>(request, headers, `/operators/${first.hid}`)).record_status).toBe(
    "retired",
  );
  for (const kept of [
    `/users/${lee.user.hid}`,
    `/contacts/${lee.contact.hid}`,
    `/operators/${second.hid}`,
  ]) {
    expect((await read<Status>(request, headers, kept)).record_status).toBe("active");
  }

  // From the page of the account: the contact kept, the label left open.
  await openUser(page, lee.user);
  await region(page, "Retire").getByRole("button", { name: "Retire account" }).click();
  ask = page.getByTestId("retire-person");
  // The released label is asked nothing: it is retired already.
  await expect(labelRow(ask, first)).toHaveCount(0);
  await ask.getByRole("checkbox", { name: `Retire the contact ${lee.contact.name}` }).uncheck();
  const open = labelRow(ask, second);
  await open.getByRole("radio", { name: "Leave open", exact: true }).check();
  await ask.getByRole("button", { name: "Retire account" }).click();
  await expect(
    page.getByText(
      `${lee.user.username} was retired. ${second.label} was left open. The contact ${lee.contact.name} stays.`,
    ),
  ).toBeVisible();
  expect((await read<Status>(request, headers, `/users/${lee.user.hid}`)).record_status).toBe(
    "retired",
  );
  expect((await read<Status>(request, headers, `/contacts/${lee.contact.hid}`)).record_status).toBe(
    "active",
  );
  expect(
    await read<Status & { contact_hid: string | null }>(
      request,
      headers,
      `/operators/${second.hid}`,
    ),
  ).toMatchObject({ record_status: "active", contact_hid: null });
  // A retired account stands behind no label that is not released, and none is made for it.
  const marks = page.getByTestId("user-operators");
  await expect(marks.locator(".operator-mark")).toHaveCount(1);
  await expect(marks).toContainText("released");
  await expect(marks.getByRole("button", { name: "Make an operator" })).toHaveCount(0);
  await expectClean(page, seen);
});

test("P-297, P-298: somebody of the Inventory role retires no account, and brings no person back", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(240_000);
  const headers = await session(request, account);
  const ops = await createAccount(request, `e2e-${suffix}-ops`, "inventory");
  madeAccounts.push(ops.hid);
  const max = await person(request, headers, "max", { labels: 2 });
  const [first, second] = max.labels as [Person["labels"][0], Person["labels"][0]];
  // A contact that is retired already, and a label that is released.
  const gone = await make(request, headers, "/contacts", {
    name: `Gone Example ${suffix}`,
    record_status: "active",
  });
  const released = await make(request, headers, "/operators", {
    label: `${suffix}-gone`,
    record_status: "active",
  });
  for (const path of [`/contacts/${gone.hid}`, `/operators/${released.hid}`]) {
    const now = await read<{ row_version: number }>(request, headers, path);
    const retired = await request.post(`./api/v1${path}/retire`, {
      headers,
      data: { row_version: now.row_version },
    });
    expect(retired.status(), await retired.text()).toBe(200);
  }
  const seen = await watch(page.context());
  await signIn(page, ops);

  // The chain names the account as text: its page is an Admin's.
  await openContact(page, max.contact);
  const links = chain(page);
  await expect(links.user).toContainText(max.user.username);
  await expect(links.user.getByRole("link")).toHaveCount(0);

  // The contact of an account is not retired by this role: the dialog says whom to ask.
  await region(page, "Retire").getByRole("button", { name: "Retire contact" }).click();
  let ask = page.getByTestId("retire-person");
  await expect(ask.getByTestId("retire-blocked")).toContainText(
    `An Admin retires an account, and a contact is not retired while its account stands on it. Ask an Admin to retire ${max.user.username} with this contact.`,
  );
  await expect(ask.getByRole("button", { name: "Retire contact" })).toHaveCount(0);
  await ask.getByRole("button", { name: "Close" }).click();
  await expect(ask).toHaveCount(0);

  // A label is released: the account shown unticked, and so the contact stays.
  await openOperator(page, first);
  await region(page, "Release").getByRole("button", { name: "Release", exact: true }).click();
  ask = page.getByTestId("retire-person");
  const accountBox = ask.getByRole("checkbox", { name: `Retire the account ${max.user.username}` });
  const contactBox = ask.getByRole("checkbox", { name: `Retire the contact ${max.contact.name}` });
  await expect(accountBox).not.toBeChecked();
  await expect(accountBox).toBeDisabled();
  await expect(ask.locator('[data-row="user"]')).toContainText(
    `An Admin retires an account: ${max.user.username} stays, and so its contact stays.`,
  );
  await expect(contactBox).not.toBeChecked();
  await expect(contactBox).toBeDisabled();
  const other = labelRow(ask, second);
  await expect(other.getByRole("radio", { name: "Release", exact: true })).toBeChecked();
  await other.getByRole("radio", { name: "Keep", exact: true }).check();
  await ask.getByRole("button", { name: "Release", exact: true }).click();
  await expect(page.getByText(`${first.label} was released.`, { exact: false })).toBeVisible();
  for (const kept of [
    `/users/${max.user.hid}`,
    `/contacts/${max.contact.hid}`,
    `/operators/${second.hid}`,
  ]) {
    expect((await read<Status>(request, headers, kept)).record_status).toBe("active");
  }

  // Released, it is brought back by an Admin alone: the page says so, and has no button.
  await expect(region(page, "Released").getByTestId("admin-brings-back")).toHaveText(
    "An Admin brings a person back: ask one to bring this label back.",
  );
  await expect(region(page, "Released").getByRole("button")).toHaveCount(0);
  await openOperator(page, { hid: released.hid, label: `${suffix}-gone` });
  await expect(region(page, "Released").getByTestId("admin-brings-back")).toBeVisible();
  await openContact(page, { hid: gone.hid, name: `Gone Example ${suffix}` });
  await expect(region(page, "Retired").getByTestId("admin-brings-back")).toHaveText(
    "An Admin brings a person back: ask one to bring this contact back.",
  );
  await expect(region(page, "Retired").getByRole("button")).toHaveCount(0);
  await expectClean(page, seen);
});

test("P-297: a refusal by the server stays in the confirmation, and the list is read again", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(240_000);
  const headers = await session(request, account);
  const ann = await person(request, headers, "ann", { labels: 1 });
  const [first] = ann.labels as [Person["labels"][0]];
  const seen = await watch(page.context());
  await signIn(page, account);

  // The confirmation is open, the label handed on to be kept, when a second label is made.
  await openUser(page, ann.user);
  await region(page, "Retire").getByRole("button", { name: "Retire account" }).click();
  const ask = page.getByTestId("retire-person");
  await ask.getByRole("checkbox", { name: `Retire the contact ${ann.contact.name}` }).uncheck();
  await labelRow(ask, first).getByRole("radio", { name: "Keep", exact: true }).check();
  const late = `${suffix}-ann-late`;
  const second = await make(request, headers, "/operators", {
    label: late,
    contact_hid: ann.contact.hid,
    record_status: "active",
  });

  // Refused: nothing was said of the new label. It is named, and listed, ticked.
  await ask.getByRole("button", { name: "Retire account" }).click();
  await expect(ask.locator(".alert-error")).toBeVisible();
  await expect(
    ask.getByTestId("problem-depends-on").getByRole("link", { name: late }),
  ).toBeVisible();
  const added = labelRow(ask, second);
  await expect(added.getByRole("radio", { name: "Release", exact: true })).toBeChecked();
  // Nothing chosen is lost.
  await expect(
    ask.getByRole("checkbox", { name: `Retire the contact ${ann.contact.name}` }),
  ).not.toBeChecked();
  await expect(
    labelRow(ask, first).getByRole("radio", { name: "Keep", exact: true }),
  ).toBeChecked();
  expect((await read<Status>(request, headers, `/users/${ann.user.hid}`)).record_status).toBe(
    "active",
  );

  // Said, the one request goes through.
  await added.getByRole("radio", { name: "Leave open", exact: true }).check();
  await ask.getByRole("button", { name: "Retire account" }).click();
  await expect(
    page.getByText(
      `${ann.user.username} was retired. ${late} was left open. The contact ${ann.contact.name} and the label ${first.label} stay.`,
    ),
  ).toBeVisible();
  expect((await read<Status>(request, headers, `/users/${ann.user.hid}`)).record_status).toBe(
    "retired",
  );
  await expectClean(page, seen, ["409 POST"]);
});

test("P-296: who acted, on the Audit page, still offers a retired account, marked", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(180_000);
  const headers = await session(request, account);
  // An account that did something, signed in, and was then retired.
  const made = await createAccount(request, `e2e-${suffix}-eve`, "viewer");
  madeAccounts.push(made.hid);
  await session(request, made);
  const now = await read<{ row_version: number }>(request, headers, `/users/${made.hid}`);
  const retired = await request.post(`./api/v1/users/${made.hid}/retire`, {
    headers,
    data: { row_version: now.row_version },
  });
  expect(retired.status(), await retired.text()).toBe(200);
  const seen = await watch(page.context());
  await signIn(page, account);

  await page.goto("./audit");
  const who = page.getByLabel("Who", { exact: true });
  const marked = `${made.username} (retired)`;
  await expect(who.locator("option", { hasText: marked })).toHaveCount(1);
  // An account that is not retired is offered by its username alone.
  await expect(who.locator("option", { hasText: account.username })).toHaveText(account.username);
  await who.selectOption({ label: marked });
  await page.getByRole("button", { name: "Filter", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`[?&]actor_hid=${made.hid}(&|$)`));
  // What it did is still there: every event on show is its own.
  const rows = page.locator("table.audit tbody tr");
  await expect(rows.first()).toBeVisible();
  for (const cell of await rows.locator("td:nth-child(2)").all()) {
    await expect(cell).toHaveText(made.username);
  }
  // The address is the filter: opened afresh, the choice is still the retired account.
  await page.reload();
  await expect(who).toHaveValue(made.hid);
  await expectClean(page, seen);
});

// To be run once both server lanes are in: the rule arrives with the server of the
// profile lane (P-295). Until the server has the setting, the scenario is skipped.
test("P-295: an access code typed for somebody else is held to the least length, said at its field", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(180_000);
  const headers = await session(request, account);
  const settings = await read<Array<{ key: string; value: unknown }>>(
    request,
    headers,
    "/settings",
  );
  const least = settings.find((one) => one.key === "access_code_min_length")?.value;
  test.skip(typeof least !== "number", "the server has no access_code_min_length yet");
  const length = Number(least);
  const short = "x".repeat(length - 1);
  const long = `${suffix}-code`.padEnd(length, "x");
  const hint = `One typed here has at least ${length} characters.`;
  const username = `e2e-${suffix}-code`;
  const seen = await watch(page.context());
  await signIn(page, account);

  // New user: the form says the length, and a shorter code is refused at its field.
  await page.goto("./admin/users");
  await page.getByRole("button", { name: "New user" }).click();
  const form = region(page, "New user");
  await expect(form).toContainText(hint);
  await form.getByLabel("Username (required)").fill(username);
  await form.getByRole("checkbox", { name: "Also a contact" }).uncheck();
  const typed = form.getByLabel("Access code");
  await typed.fill(short);
  await form.getByRole("button", { name: "Create user" }).click();
  await expect(typed).toHaveAttribute("aria-invalid", "true");
  await expect(form).toContainText(`at least ${length} characters`);
  // Nothing typed is lost.
  await expect(typed).toHaveValue(short);
  await expect(form.getByLabel("Username (required)")).toHaveValue(username);
  await typed.fill(long);
  await form.getByRole("button", { name: "Create user" }).click();
  await expect(
    page.getByTestId("secret-box").getByRole("heading", { name: `Access code for ${username}` }),
  ).toBeVisible();
  await page.getByTestId("user-made").getByRole("link", { name: username }).click();
  await expect(page.getByRole("heading", { level: 1, name: username })).toBeVisible();
  madeAccounts.push(new URL(page.url()).pathname.split("/").pop() ?? "");

  // Its page: the same under New access code, and one left empty is still generated.
  const section = region(page, "Access code");
  await expect(section).toContainText(hint);
  const wanted = section.getByLabel("New access code");
  await wanted.fill(short);
  await section.getByRole("button", { name: "Reset access code" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Reset access code" }).click();
  await expect(wanted).toHaveAttribute("aria-invalid", "true");
  await expect(wanted).toHaveValue(short);
  await expect(page.getByTestId("secret-box")).toHaveCount(0);
  await wanted.fill("");
  await section.getByRole("button", { name: "Reset access code" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Reset access code" }).click();
  await expect(
    page
      .getByTestId("secret-box")
      .getByRole("heading", { name: `New access code for ${username}` }),
  ).toBeVisible();
  await expectClean(page, seen, ["422 POST", "422 POST"]);
});
