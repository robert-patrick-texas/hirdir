// The browser scenarios of a person's own profile, release 0.9.14, and of signing in and
// the access code, 0.9.15:
//
//   P-289  The name of who is signed in, in the menu bar, is a link to their profile,
//          reached by the keyboard. The page is for every role: a View-only person
//          changes everything of their own there.
//   P-294  Three parts, each a form of its own, with a button named for it: the details of the contact the person
//          is, the label and the colour of each operator they are behind, and their
//          access code. A refusal is shown at its field with nothing typed lost, an
//          email or a label that another has with that other as a link. Somebody behind
//          two operators has each, one after another; an account with no contact is told
//          so, with whom to ask, and offered its access code alone. What the page does
//          not change it shows as text: the username, the role and the groups.
//   P-295  The access code is changed with the code in hand: two new codes that differ
//          are said at the second before anything is sent, a wrong code in hand and a
//          new one that is too short each at its box. Changed, the page stays signed in,
//          another session of the person has ended, and the old code signs in no longer.
//   P-299  An account that holds no role does not sign in (0.9.15, which takes away what
//          0.9.14 let it do on the page): the right code is refused, told plainly, apart
//          from a wrong code, with whom to ask; given a role again, it signs in.
//   P-300  Generate fills both new boxes with a code the server made, in clear; it is
//          changed to with the code in hand and shown once; the same code again is
//          refused by the server at New access code.
//
// They keep to the rules of support.ts: every account the scenarios sign in as is made
// for this file, with its mark in its name, as are the contacts, the labels and the
// group, and each scenario disables the accounts it made when it ends. Three sign-ins
// fail on purpose (rule 6): a wrong code in hand, which the server counts as one, the old
// code after the change, and a wrong code after the refusal of an account with no role,
// which the server counts as a success. The setting `access_code_min_length` is read at
// its default, 12, which no file changes; whom to ask is nobody's on a scratch inventory,
// and no file but product.spec.ts sets it, so the scenario of an account with no contact
// answers `GET /about` to its own page with a team to ask, and the scenario of an account
// with no role answers its sign-in with one.

import { type APIRequestContext, expect, type Locator, type Page } from "@playwright/test";
import { type Headers, make, session } from "./referenceSteps";
import { region } from "./structure";
import { type Account, createAccount, expectClean, mark, signIn, test, watch } from "./support";

const suffix = mark("profile");

/** The link of who is signed in, in the menu bar. */
function who(page: Page): Locator {
  return page.getByRole("banner").locator("a.who-name");
}

/** How much wider than the window the page is, in pixels: none, where nothing scrolls sideways. */
function wider(page: Page): Promise<number> {
  return page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
}

/** A record read through the API, as the file's own Admin. */
async function read<T>(request: APIRequestContext, headers: Headers, path: string): Promise<T> {
  const answer = await request.get(`./api/v1${path}`, { headers });
  expect(answer.status(), `get ${path}`).toBe(200);
  return (await answer.json()) as T;
}

/** The contact of a user the file made with a person. */
async function contactOf(
  request: APIRequestContext,
  headers: Headers,
  account: Account,
): Promise<string> {
  const user = await read<{ contact: { hid: string } | null }>(
    request,
    headers,
    `/users/${encodeURIComponent(account.hid)}`,
  );
  expect(user.contact, `${account.username} has a contact`).not.toBeNull();
  return user.contact?.hid ?? "";
}

/** Disable the accounts a scenario made: none is left that can sign in. */
async function disable(request: APIRequestContext, headers: Headers, accounts: Account[]) {
  for (const account of accounts) {
    const path = `./api/v1/users/${encodeURIComponent(account.hid)}`;
    const found = await request.get(path, { headers });
    const { row_version } = (await found.json()) as { row_version: number };
    const answer = await request.patch(path, { headers, data: { row_version, disabled: true } });
    expect(answer.status(), `${account.username} is disabled`).toBe(200);
  }
}

/** Open the profile from the menu bar, as a person does. */
async function openProfile(page: Page) {
  await who(page).click();
  await expect(page.getByRole("heading", { level: 1, name: "Profile", exact: true })).toBeVisible();
  await expect(page).toHaveURL(/\/profile$/);
}

test("P-289: the name in the menu bar leads to the profile by the keyboard, and an account with no contact is told so, with whom to ask, and offered its access code alone", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 1280, height: 800 });
  const headers = await session(request, account);
  const clerk = await createAccount(request, `e2e-${suffix}-noc`, "inventory");
  const seen = await watch(page.context());
  // Whom to ask is nobody's on a scratch inventory: this page is answered a team.
  await page.route("**/api/v1/about", async (route) => {
    const answer = await route.fetch();
    const about = (await answer.json()) as Record<string, unknown>;
    await route.fulfill({
      response: answer,
      json: {
        ...about,
        help: {
          organization: "Example Network Team",
          email: "netops@example.com",
          phone: "+1 555 0100",
          url: null,
        },
      },
    });
  });
  await signIn(page, clerk);

  // The name is a link, and reads as one: by its role, its name and where it leads.
  const link = page.getByRole("banner").getByRole("link", { name: clerk.username, exact: true });
  await expect(link).toHaveAttribute("href", /\/profile$/);
  await expect(link).toHaveAttribute("title", "Your profile");
  await expect(who(page)).toHaveText(clerk.username);

  // By the keyboard: Tab comes to it after the menu and the mark of health, and Enter opens it.
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "About" }).focus();
  for (let press = 0; press < 4; press += 1) {
    await page.keyboard.press("Tab");
    if (await link.evaluate((node) => node === document.activeElement)) break;
  }
  await expect(link).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/profile$/);
  await expect(page.getByRole("heading", { level: 1, name: "Profile", exact: true })).toBeVisible();
  await expect(page).toHaveTitle("Profile · hirdir");
  await expect(page.locator("main")).toBeFocused();
  await expect(link).toHaveAttribute("aria-current", "page");

  // What the page does not change, as text.
  const facts = page.getByTestId("profile-facts");
  await expect(facts.locator("dd").nth(0)).toHaveText(clerk.username);
  await expect(facts.locator("dd").nth(1)).toHaveText("Inventory");
  await expect(facts.locator("dd").nth(2)).toHaveText("—");
  await expect(facts.getByRole("textbox")).toHaveCount(0);
  await expect(facts.getByRole("link")).toHaveCount(0);

  // No contact: said so, with whom to ask, and neither Details nor an operator.
  const none = page.getByTestId("profile-no-contact");
  await expect(none).toContainText("You have no contact. Ask an Admin to give you one.");
  await expect(none.getByTestId("help-organization")).toHaveText("Example Network Team");
  await expect(none.getByRole("link", { name: "netops@example.com" })).toHaveAttribute(
    "href",
    "mailto:netops@example.com",
  );
  await expect(none.getByRole("link", { name: "+1 555 0100" })).toHaveAttribute(
    "href",
    "tel:+15550100",
  );
  await expect(region(page, "Details")).toHaveCount(0);
  await expect(page.getByTestId("profile-operators")).toHaveCount(0);
  await expect(page.getByTestId("profile-no-operator")).toHaveCount(0);

  // The access code alone: its three boxes, masked, each named for a password manager.
  const code = region(page, "Access code");
  await expect(page.getByRole("main").locator("form")).toHaveCount(1);
  for (const [label, name, complete] of [
    ["Access code you have (required)", "current_access_code", "current-password"],
    ["New access code (required)", "access_code", "new-password"],
    ["New access code again (required)", "access_code_again", "new-password"],
  ] as const) {
    const box = code.getByLabel(label, { exact: true });
    await expect(box).toHaveAttribute("type", "password");
    await expect(box).toHaveAttribute("name", name);
    await expect(box).toHaveAttribute("autocomplete", complete);
  }
  await expect(code.locator('input[name="username"]')).toHaveAttribute("autocomplete", "username");
  await expect(code.locator('input[name="username"]')).toHaveValue(clerk.username);
  await expect(code.locator('input[name="username"]')).toBeHidden();
  // The least length, as the setting says it, and what a change ends.
  await expect(code.getByTestId("profile-code-words")).toHaveText(
    "At least 12 characters. Your other sessions end when it is changed; this one stays signed in.",
  );

  // Too many wrong codes: the page says how long to wait and holds the button, and when the
  // wait is over the words are taken away with it. The refusal is answered to this page
  // alone: five wrong codes would delay the sign-ins of every file beside this one.
  await page.route("**/api/v1/auth/me/access-code", (route) =>
    route.fulfill({
      status: 429,
      contentType: "application/problem+json",
      headers: { "Retry-After": "2" },
      body: JSON.stringify({
        type: "about:blank",
        title: "Too many attempts",
        status: 429,
        detail: "wait before the next attempt",
      }),
    }),
  );
  const saveCode = code.getByRole("button", { name: "Change access code", exact: true });
  const current = code.getByLabel("Access code you have (required)", { exact: true });
  await current.fill("a code of some length");
  await code.getByLabel("New access code (required)", { exact: true }).fill("another long code");
  await code
    .getByLabel("New access code again (required)", { exact: true })
    .fill("another long code");
  await saveCode.click();
  const wait = code.locator(".alert-error");
  await expect(wait).toHaveAttribute("data-status", "429");
  await expect(wait).toHaveText("Too many attempts. Try again in 2 seconds.");
  await expect(saveCode).toBeDisabled();
  // A refusal that is about no box has the keyboard on its words, the button being held.
  await expect(code.getByTestId("profile-said")).toBeFocused();
  await expect(saveCode).toBeEnabled({ timeout: 10_000 });
  await expect(wait).toHaveCount(0);
  // Nothing typed is lost by it.
  await expect(current).toHaveValue("a code of some length");
  await page.unroute("**/api/v1/auth/me/access-code");

  // Whole in view at 1280 pixels, and at 360, with nothing to scroll sideways.
  expect(await wider(page), "wider than a window of 1280").toBeLessThanOrEqual(0);
  await page.setViewportSize({ width: 360, height: 740 });
  await expect(saveCode).toBeVisible();
  expect(await wider(page), "wider than a window of 360").toBeLessThanOrEqual(0);

  await expectClean(page, seen, ["429 POST"]);
  await disable(request, headers, [clerk]);
});

test("P-294, P-295: a View-only person changes their details, their operator and their access code, each refusal at its field with nothing typed lost", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(300_000);
  await page.setViewportSize({ width: 1280, height: 800 });
  const headers = await session(request, account);
  const kim = {
    name: `Kim Example ${suffix}`,
    email: `kim.${suffix}@example.org`,
    phone: "+1 555 0111",
    phone2: "+1 555 0112",
  };
  const viewer = await createAccount(request, `e2e-${suffix}-kim`, "viewer", kim);
  const contact = await contactOf(request, headers, viewer);
  const label = `KL-${suffix}`;
  const operator = await make(request, headers, "/operators", {
    label,
    contact_hid: contact,
    colour: "#1f6feb",
    record_status: "active",
  });
  // Another person and another label, whose email and label are theirs alone.
  const sam = { name: `Sam Example ${suffix}`, email: `sam.${suffix}@example.org` };
  const other = await make(request, headers, "/contacts", { ...sam, record_status: "active" });
  const taken = `TK-${suffix}`;
  const takenOperator = await make(request, headers, "/operators", {
    label: taken,
    record_status: "active",
  });
  // A group the person is in, which the page names and does not change.
  const groupName = `${suffix}-readers`;
  const group = await make(request, headers, "/user-groups", { name: groupName });
  const joined = await request.put(
    `./api/v1/user-groups/${encodeURIComponent(group.hid)}/members/${encodeURIComponent(viewer.hid)}`,
    { headers },
  );
  expect(joined.ok(), "the person is put in the group").toBe(true);

  const seen = await watch(page.context());
  await signIn(page, viewer);
  await expect(who(page)).toHaveAttribute("title", `${kim.name}: your profile`);
  await openProfile(page);

  const facts = page.getByTestId("profile-facts");
  await expect(facts.locator("dd").nth(0)).toHaveText(viewer.username);
  await expect(facts.locator("dd").nth(1)).toHaveText("View-only");
  await expect(facts.locator("dd").nth(2)).toHaveText(groupName);

  // --- Details: the contact's, filled from it.
  const details = region(page, "Details");
  const name = details.getByLabel("Name (required)", { exact: true });
  const email = details.getByLabel("Email", { exact: true });
  const phone = details.getByLabel("Phone", { exact: true });
  const phone2 = details.getByLabel("Second phone", { exact: true });
  const organization = details.getByLabel("Organization", { exact: true });
  const saveDetails = details.getByRole("button", { name: "Save details", exact: true });
  await expect(name).toHaveValue(kim.name);
  await expect(email).toHaveValue(kim.email);
  await expect(phone).toHaveValue(kim.phone);
  await expect(phone2).toHaveValue(kim.phone2);
  await expect(organization).toHaveValue("");
  await expect(saveDetails).toBeDisabled();

  // An email that another contact has: refused at the field, that contact a link, and
  // everything typed with it kept.
  const renamed = `Kim A. Example ${suffix}`;
  await name.fill(renamed);
  await email.fill(sam.email);
  await phone2.fill("+1 555 0113");
  await organization.fill("Example Networks");
  await saveDetails.click();
  await expect(details.locator(".alert-error")).toHaveAttribute("data-status", "409");
  await expect(email).toHaveAttribute("aria-invalid", "true");
  await expect(email).toBeFocused();
  await expect(details.locator(".field-error")).toHaveCount(1);
  await expect(
    details.locator(".alert-error").getByRole("link", { name: sam.name }),
  ).toHaveAttribute("href", new RegExp(`/contacts/${other.hid}$`));
  await expect(name).toHaveValue(renamed);
  await expect(email).toHaveValue(sam.email);
  await expect(phone2).toHaveValue("+1 555 0113");
  await expect(organization).toHaveValue("Example Networks");
  // Nothing was changed: the menu bar says the name as it was.
  await expect(who(page)).toHaveAttribute("title", `${kim.name}: your profile`);

  // A name left blank is refused at its field, and the rest stays as typed.
  await name.fill("");
  await email.fill(kim.email);
  await saveDetails.click();
  await expect(details.locator(".alert-error")).toHaveAttribute("data-status", "422");
  await expect(name).toHaveAttribute("aria-invalid", "true");
  await expect(name).toBeFocused();
  await expect(email).not.toHaveAttribute("aria-invalid", "true");
  await expect(organization).toHaveValue("Example Networks");
  await expect(phone2).toHaveValue("+1 555 0113");

  // Put right, it is saved: said so, and the name shows in the menu bar at once.
  const mail = `kim.a.${suffix}@example.org`;
  await name.fill(renamed);
  await email.fill(mail);
  await saveDetails.click();
  await expect(details.locator(".alert-ok")).toHaveText("Your details were saved.");
  await expect(who(page)).toHaveAttribute("title", `${renamed}: your profile`);
  await expect(who(page)).toHaveText(viewer.username);
  await expect(saveDetails).toBeDisabled();
  // The first page welcomes the person by it, with nothing read again.
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Home" }).click();
  await expect(page.getByRole("heading", { level: 1, name: `Welcome, ${renamed}` })).toBeVisible();

  // Read back: the page loaded anew shows what was saved, and so does the contact.
  await page.goto("./profile");
  await expect(name).toHaveValue(renamed);
  await expect(email).toHaveValue(mail);
  await expect(phone).toHaveValue(kim.phone);
  await expect(phone2).toHaveValue("+1 555 0113");
  await expect(organization).toHaveValue("Example Networks");
  const stored = await read<Record<string, unknown>>(request, headers, `/contacts/${contact}`);
  expect(stored).toMatchObject({
    name: renamed,
    email: mail,
    phone: kim.phone,
    phone2: "+1 555 0113",
    organization: "Example Networks",
  });

  // --- Operator: the one label the person is behind, with its colour.
  const operators = region(page, "Operator");
  await expect(page.getByTestId("profile-operator")).toHaveCount(1);
  let part = region(page, label);
  await expect(part.getByRole("link", { name: label, exact: true })).toHaveAttribute(
    "href",
    new RegExp(`/operators/${operator.hid}$`),
  );
  const labelBox = operators.getByLabel("Label (required)", { exact: true });
  const colour = operators.getByRole("group", { name: "Colour", exact: true });
  const colourBox = colour.getByRole("textbox", { name: "Colour", exact: true });
  const saveOperator = operators.getByRole("button", { name: /^Save K[LA]-/ });
  await expect(labelBox).toHaveValue(label);
  await expect(colourBox).toHaveValue("#1f6feb");
  // The label on show beside the chip, as the lists show it.
  await expect(colour.locator(".colour-sample")).toHaveText(label);

  // A label that another operator has: refused at the field, that operator a link, and
  // the colour chosen with it kept.
  const swatch = colour.locator(".colour-swatch").nth(11);
  const chosen = (await swatch.getAttribute("data-colour")) ?? "";
  expect(chosen).toMatch(/^#[0-9a-f]{6}$/);
  await swatch.click();
  await expect(colourBox).toHaveValue(chosen);
  await labelBox.fill(taken);
  await expect(colour.locator(".colour-sample")).toHaveText(taken);
  await saveOperator.click();
  await expect(operators.locator(".alert-error")).toHaveAttribute("data-status", "409");
  await expect(labelBox).toHaveAttribute("aria-invalid", "true");
  await expect(
    operators.locator(".alert-error").getByRole("link", { name: taken, exact: true }),
  ).toHaveAttribute("href", new RegExp(`/operators/${takenOperator.hid}$`));
  await expect(labelBox).toHaveValue(taken);
  await expect(colourBox).toHaveValue(chosen);

  // Another label, and the colour: saved, said so, and the heading takes the new label.
  const relabelled = `KA-${suffix}`;
  await labelBox.fill(relabelled);
  await saveOperator.click();
  await expect(operators.locator(".alert-ok")).toHaveText(`The operator ${relabelled} was saved.`);
  part = region(page, relabelled);
  await expect(part.getByRole("link", { name: relabelled, exact: true })).toBeVisible();
  await expect(colour.getByTestId(/-chip$/)).toHaveAttribute("data-colour", chosen);
  // Read back, here and on the operator's own page.
  await page.goto("./profile");
  await expect(labelBox).toHaveValue(relabelled);
  await expect(colourBox).toHaveValue(chosen);
  await part.getByRole("link", { name: relabelled, exact: true }).click();
  await expect(page.getByTestId("operator-heading")).toContainText(relabelled);
  await expect(page.getByTestId("operator-colour")).toHaveAttribute("data-colour", chosen);

  // Whole in view at 1280 pixels, and at 360, with nothing to scroll sideways.
  await openProfile(page);
  await expect(colour.locator(".colour-swatch")).toHaveCount(64);
  expect(await wider(page), "wider than a window of 1280").toBeLessThanOrEqual(0);
  await page.setViewportSize({ width: 360, height: 740 });
  await expect(saveDetails).toBeVisible();
  await expect(colour.locator(".colour-swatch").last()).toBeVisible();
  expect(await wider(page), "wider than a window of 360").toBeLessThanOrEqual(0);
  await page.setViewportSize({ width: 1280, height: 800 });

  // --- Access code. Another session of the person, to be ended by the change.
  const elsewhere = await session(request, viewer);
  const code = region(page, "Access code");
  const current = code.getByLabel("Access code you have (required)", { exact: true });
  const wanted = code.getByLabel("New access code (required)", { exact: true });
  const again = code.getByLabel("New access code again (required)", { exact: true });
  const saveCode = code.getByRole("button", { name: "Change access code", exact: true });
  const fresh = `Violet-heron-${suffix}`;
  let sent = 0;
  page.on("request", (asked) => {
    if (asked.url().endsWith("/auth/me/access-code")) sent += 1;
  });

  // Two new codes that differ: said at the second, and nothing is sent.
  await current.fill(viewer.accessCode);
  await wanted.fill(fresh);
  await again.fill(`${fresh}x`);
  await saveCode.click();
  await expect(again).toHaveAttribute("aria-invalid", "true");
  await expect(again).toBeFocused();
  await expect(code.locator(".field-error")).toHaveText(
    "The two new codes differ. Type the same code in both.",
  );
  expect(sent, "nothing is sent while the two new codes differ").toBe(0);

  // A wrong code in hand: at its box, with the three boxes as typed.
  await again.fill(fresh);
  await current.fill("not the code in hand");
  await saveCode.click();
  await expect(code.locator(".alert-error")).toHaveAttribute("data-status", "422");
  await expect(current).toHaveAttribute("aria-invalid", "true");
  await expect(current).toBeFocused();
  await expect(wanted).not.toHaveAttribute("aria-invalid", "true");
  await expect(current).toHaveValue("not the code in hand");
  await expect(wanted).toHaveValue(fresh);
  await expect(again).toHaveValue(fresh);

  // A new code that is too short: at its box, saying the length.
  await current.fill(viewer.accessCode);
  await wanted.fill("too short");
  await again.fill("too short");
  await saveCode.click();
  await expect(code.locator(".alert-error")).toHaveAttribute("data-status", "422");
  await expect(wanted).toHaveAttribute("aria-invalid", "true");
  await expect(code.locator(".field-error")).toContainText("12");
  await expect(current).not.toHaveAttribute("aria-invalid", "true");
  await expect(current).toHaveValue(viewer.accessCode);
  await expect(wanted).toHaveValue("too short");
  // Nothing was changed by either: the other session is alive.
  expect((await request.get("./api/v1/auth/me", { headers: elsewhere })).status()).toBe(200);

  // Changed: said so, the boxes emptied, and the page as it was, still signed in.
  await wanted.fill(fresh);
  await again.fill(fresh);
  await saveCode.click();
  await expect(code.locator(".alert-ok")).toHaveText(
    "Your access code is changed. Your other sessions have ended.",
  );
  await expect(current).toHaveValue("");
  await expect(wanted).toHaveValue("");
  await expect(again).toHaveValue("");
  expect(sent).toBe(3);
  // The keyboard is on the words that say so: the boxes and the button it could have
  // been on were held while the change was sent.
  await expect(code.getByTestId("profile-said")).toBeFocused();
  await expect(code.getByTestId("profile-said")).toHaveText(
    "Your access code is changed. Your other sessions have ended.",
  );
  await expect(page.getByRole("heading", { level: 1, name: "Profile", exact: true })).toBeVisible();
  await expect(name).toHaveValue(renamed);
  // The session in hand goes on: the page changes something more, and is loaded anew.
  await organization.fill("Example Networks East");
  await saveDetails.click();
  await expect(details.locator(".alert-ok")).toHaveText("Your details were saved.");
  await page.reload();
  await expect(page.getByRole("heading", { level: 1, name: "Profile", exact: true })).toBeVisible();
  await expect(organization).toHaveValue("Example Networks East");
  await expect(who(page)).toHaveText(viewer.username);

  // The other session has ended; the old code signs in no longer, and the new one does.
  expect((await request.get("./api/v1/auth/me", { headers: elsewhere })).status()).toBe(401);
  const old = await request.post("./api/v1/auth/sign-in", {
    data: { username: viewer.username, access_code: viewer.accessCode },
  });
  expect(old.status(), "the old code signs in no longer").toBe(401);
  const now = await request.post("./api/v1/auth/sign-in", {
    data: { username: viewer.username, access_code: fresh },
  });
  expect(now.status(), "the new code signs in").toBe(200);

  await expectClean(page, seen, ["409 PATCH", "422 PATCH", "409 PATCH", "422 POST", "422 POST"]);
  await disable(request, headers, [viewer]);
});

test("P-294: a person behind two operators has each, one after another, and changes one alone; behind none, the page says so", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(180_000);
  await page.setViewportSize({ width: 1280, height: 800 });
  const headers = await session(request, account);
  const lee = await createAccount(request, `e2e-${suffix}-lee`, "inventory", {
    name: `Lee Example ${suffix}`,
  });
  const contact = await contactOf(request, headers, lee);
  // Made last first: the page lists them by their labels.
  // The second is as long as a label may be, 40 characters.
  const second = `Y2${"W".repeat(37 - suffix.length)}-${suffix}`;
  const first = `Y1-${suffix}`;
  expect(second).toHaveLength(40);
  const made: Record<string, string> = {};
  for (const [label, colour] of [
    [second, "#d4a72c"],
    [first, "#1f6feb"],
  ] as const) {
    made[label] = (
      await make(request, headers, "/operators", {
        label,
        contact_hid: contact,
        colour,
        record_status: "active",
      })
    ).hid;
  }
  // A person with a contact and no operator.
  const ola = await createAccount(request, `e2e-${suffix}-ola`, "viewer", {
    name: `Ola Example ${suffix}`,
  });

  const seen = await watch(page.context());
  await signIn(page, lee);
  await openProfile(page);
  const operators = region(page, "Operators");
  const parts = page.getByTestId("profile-operator");
  await expect(parts).toHaveCount(2);
  await expect(parts.nth(0)).toHaveAttribute("data-operator", made[first] ?? "");
  await expect(parts.nth(1)).toHaveAttribute("data-operator", made[second] ?? "");
  // Each a form of its own, with a Save of its own that is named for it, and the page
  // has no two buttons of one name.
  await expect(operators).toBeVisible();
  const one = region(page, first);
  const two = region(page, second);
  const saveOne = one.getByRole("button", { name: `Save ${first}`, exact: true });
  const saveTwo = two.getByRole("button", { name: `Save ${second}`, exact: true });
  await expect(saveOne).toHaveCount(1);
  await expect(saveTwo).toHaveCount(1);
  const names = await page.getByRole("main").getByRole("button").allTextContents();
  expect(names.filter((name) => name.startsWith("Save") || name.startsWith("Change"))).toEqual([
    "Save details",
    `Save ${first}`,
    `Save ${second}`,
    "Change access code",
  ]);
  await expect(one.getByLabel("Label (required)", { exact: true })).toHaveValue(first);
  await expect(two.getByLabel("Label (required)", { exact: true })).toHaveValue(second);
  const colourOf = (part: Locator) =>
    part
      .getByRole("group", { name: "Colour", exact: true })
      .getByRole("textbox", { name: "Colour", exact: true });
  await expect(colourOf(one)).toHaveValue("#1f6feb");
  await expect(colourOf(two)).toHaveValue("#d4a72c");

  // The second is given another colour, typed: it is saved, and the first is as it was.
  await colourOf(two).fill("#8250DF");
  await expect(saveOne).toBeDisabled();
  await saveTwo.click();
  await expect(two.locator(".alert-ok")).toHaveText(`The operator ${second} was saved.`);
  await expect(one.locator(".alert-ok")).toHaveCount(0);
  await page.goto("./profile");
  await expect(colourOf(two)).toHaveValue("#8250df");
  await expect(colourOf(one)).toHaveValue("#1f6feb");
  const stored = await read<{ colour: string; label: string }>(
    request,
    headers,
    `/operators/${made[second]}`,
  );
  expect(stored).toMatchObject({ label: second, colour: "#8250df" });
  expect(await wider(page), "wider than a window of 1280").toBeLessThanOrEqual(0);
  // At 360 pixels the longest label fits, in its heading and on its button.
  await page.setViewportSize({ width: 360, height: 740 });
  await expect(saveTwo).toBeVisible();
  expect(await wider(page), "wider than a window of 360").toBeLessThanOrEqual(0);
  await page.setViewportSize({ width: 1280, height: 800 });
  await expectClean(page, seen);

  // Behind none: no such part, and a line that says so, under the details.
  const context = await page.context().browser()?.newContext();
  if (!context) throw new Error("no browser for a second person");
  const page2 = await context.newPage();
  const seen2 = await watch(context);
  await signIn(page2, ola);
  await openProfile(page2);
  await expect(region(page2, "Details")).toBeVisible();
  await expect(page2.getByTestId("profile-no-operator")).toHaveText("You are behind no operator.");
  await expect(page2.getByTestId("profile-operators")).toHaveCount(0);
  await expect(region(page2, "Access code")).toBeVisible();
  await expectClean(page2, seen2);
  await context.close();

  await disable(request, headers, [lee, ola]);
});

test("P-299: an account that holds no role is refused at sign-in with the right code, told so plainly with whom to ask, and signs in once given one", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(150_000);
  await page.setViewportSize({ width: 1280, height: 800 });
  const headers = await session(request, account);
  // A person made holding the role of a group, as a person is made with one, and taken
  // out of the group: it holds none.
  const team = await make(request, headers, "/user-groups", { name: `${suffix}-viewers` });
  await make(request, headers, "/role-grants", { group_hid: team.hid, role: "viewer" });
  const pat = { name: `Pat Example ${suffix}`, email: `pat.${suffix}@example.org` };
  const person = await createAccount(request, `e2e-${suffix}-pat`, null, pat, [team.hid]);
  const membership = `./api/v1/user-groups/${team.hid}/members/${encodeURIComponent(person.hid)}`;
  const out = await request.delete(membership, { headers });
  expect(out.status(), "taken out of the group").toBe(204);

  const seen = await watch(page.context());
  await page.goto("./");
  await expect(
    page.getByRole("heading", { level: 1, name: "Sign in to hirdir", exact: true }),
  ).toBeVisible();
  const username = page.getByLabel("Username");
  const code = page.getByLabel("Access code");
  const press = page.getByRole("button", { name: "Sign in" });
  await username.fill(person.username);
  await code.fill(person.accessCode);
  await press.click();

  // Said plainly, apart from the refusal of a wrong code, with the server's words; nobody
  // to ask is set on a scratch inventory, so an Admin is named. Nothing is kept: the code
  // box is emptied and the username stays as typed.
  const told = page.getByTestId("no-role");
  await expect(told.getByRole("heading", { name: "This account holds no role" })).toBeVisible();
  // Announced as it comes, as the refusal of a wrong code is (review).
  await expect(page.getByRole("alert", { name: "This account holds no role" })).toBeVisible();
  await expect(told).toContainText(
    "This account holds no role, and so cannot sign in: an Admin gives it one.",
  );
  await expect(told).toContainText("Ask an Admin of hirdir to give it one.");
  await expect(page.locator(".alert-error")).toHaveCount(0);
  await expect(username).toHaveValue(person.username);
  await expect(code).toHaveValue("");
  await expect(page.getByRole("navigation", { name: "Main" })).toHaveCount(0);

  // Where the server names whom to ask, the page lists them, each that is set. The
  // answer is given a team here: no file but product.spec.ts sets one (rule 5).
  await page.route("**/api/v1/auth/sign-in", async (route) => {
    const answer = await route.fetch();
    const body = (await answer.json()) as Record<string, unknown>;
    body.help = {
      organization: `Example Network Tools ${suffix}`,
      email: "tools@example.net",
      phone: null,
      url: null,
    };
    await route.fulfill({ response: answer, json: body });
  });
  await code.fill(person.accessCode);
  await press.click();
  const asked = told.getByTestId("whom-to-ask");
  await expect(asked.getByTestId("help-organization")).toHaveText(
    `Example Network Tools ${suffix}`,
  );
  await expect(asked.getByTestId("help-email").getByRole("link")).toHaveText("tools@example.net");
  await expect(asked.getByTestId("help-phone")).toHaveCount(0);
  await expect(told).toContainText("Ask the team that runs hirdir to give it one:");
  await page.unroute("**/api/v1/auth/sign-in");

  // A wrong code is said as before, and not as this (one failed sign-in, rule 6).
  await code.fill(`${person.accessCode}-wrong`);
  await press.click();
  await expect(page.locator(".alert-error")).toHaveAttribute("data-status", "401");
  await expect(told).toHaveCount(0);

  // Given a role again, through the group, it signs in.
  const back = await request.put(membership, { headers });
  expect(back.status(), "put back in the group").toBeLessThan(300);
  await signIn(page, person);
  await expect(who(page)).toHaveText(person.username);

  await expectClean(page, seen, ["403 POST", "403 POST", "401 POST"]);
  await disable(request, headers, [person]);
});

test("P-300: Generate on the profile fills both new boxes with a code made by the server, shown in clear, accepted with the code in hand and shown once; the same code again is refused at its field", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(150_000);
  await page.setViewportSize({ width: 1280, height: 800 });
  const headers = await session(request, account);
  const quin = { name: `Quin Example ${suffix}`, email: `quin.${suffix}@example.org` };
  const person = await createAccount(request, `e2e-${suffix}-quin`, "viewer", quin);

  const seen = await watch(page.context());
  await signIn(page, person);
  await openProfile(page);
  const part = region(page, "Access code");
  const current = part.getByLabel("Access code you have (required)", { exact: true });
  const wanted = part.getByLabel("New access code (required)", { exact: true });
  const again = part.getByLabel("New access code again (required)", { exact: true });
  const save = part.getByRole("button", { name: "Change access code", exact: true });
  await expect(wanted).toHaveAttribute("type", "password");

  // Generate: both new boxes hold the made code, in clear, at least as long as the
  // setting asks, 12 at its default; nothing is saved yet.
  await part.getByRole("button", { name: "Generate", exact: true }).click();
  await expect(wanted).not.toHaveValue("");
  const made = await wanted.inputValue();
  expect(made.length, "a made code is at least as long as the setting asks").toBeGreaterThanOrEqual(
    12,
  );
  await expect(again).toHaveValue(made);
  await expect(wanted).toHaveAttribute("type", "text");
  await expect(again).toHaveAttribute("type", "text");
  const before = await request.post("./api/v1/auth/sign-in", {
    data: { username: person.username, access_code: person.accessCode },
  });
  expect(before.status(), "nothing is saved by Generate").toBe(200);

  // The code in hand is still asked for: changed with it, the made code is shown once,
  // with Copy, and the boxes are emptied and masked again.
  await current.fill(person.accessCode);
  await save.click();
  await expect(part.locator(".alert-ok")).toHaveText(
    "Your access code is changed. Your other sessions have ended.",
  );
  const secret = part.getByTestId("secret-box");
  await expect(secret.getByRole("heading", { name: "Your new access code" })).toBeVisible();
  await expect(secret.getByLabel("Shown once")).toHaveValue(made);
  await expect(secret.getByRole("button", { name: "Copy" })).toBeVisible();
  await expect(wanted).toHaveValue("");
  await expect(wanted).toHaveAttribute("type", "password");
  await secret.getByRole("button", { name: "Done" }).click();
  await expect(secret).toHaveCount(0);
  const now = await request.post("./api/v1/auth/sign-in", {
    data: { username: person.username, access_code: made },
  });
  expect(now.status(), "the made code signs in").toBe(200);

  // The same code again: refused by the server at New access code, in its words, with
  // the three boxes as typed and the page signed in still.
  await current.fill(made);
  await wanted.fill(made);
  await again.fill(made);
  await save.click();
  await expect(wanted).toHaveAttribute("aria-invalid", "true");
  await expect(part.locator(".field-error")).toHaveText("this is the access code you have now");
  await expect(current).toHaveValue(made);
  await expect(wanted).toHaveValue(made);
  await page.reload();
  await expect(page.getByRole("heading", { level: 1, name: "Profile", exact: true })).toBeVisible();
  await expect(who(page)).toHaveText(person.username);

  await expectClean(page, seen, ["422 POST"]);
  await disable(request, headers, [person]);
});
