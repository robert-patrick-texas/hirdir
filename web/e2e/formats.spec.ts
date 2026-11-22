// The browser scenarios of the input formats of 0.9.18 (P-293, P-322 (7)):
//
//   An Admin changes `phone_formats` on the Settings page as a list: the two patterns of
//   P-293 added with one press each, one of their own typed, said wrong before it is sent
//   where it is no pattern, moved up and removed, and set. A contact's name, email and
//   numbers are then tidied as a box is left, as something is pasted into it, and as
//   Enter sends the form from it, never at each key: the number in the first pattern that
//   fits its digits, the address in lower case, the name in Title Case; a number with a
//   letter is kept as typed; a box is tidied once, so that a correction stands; and the
//   new person of New user is tidied the same. A paste longer than the field takes is
//   taken whole and said too long, and nothing is sent. With `title_case_names` off, a
//   name is kept as typed. A file's preview shows each value a format writes beside the
//   file's.
//
// How this file keeps to rule 5 of support.ts: it changes `phone_formats`, which every
// telephone number that every other file saves is written in, and `title_case_names`,
// which every name another file types follows. So it runs in the project "the formats
// alone" of playwright.config.ts, by itself, when every other project has ended. It notes
// the two settings as it found them, and puts them back however it ends. What it makes is
// contacts of its own, with its mark in their names.

import type { APIRequestContext, Locator, Page } from "@playwright/test";
import { expect } from "@playwright/test";
import { region } from "./structure";
import { type Account, expectClean, mark, signIn, test, titled, watch } from "./support";

test.describe.configure({ mode: "serial" });

const suffix = mark("formats");
const US = "+1 (###) ###-####";
const PLAIN = "###-###-####";
// The settings this file changes, which it puts back as it found them.
const SETTINGS = ["phone_formats", "title_case_names"] as const;

type Headers = { Authorization: string };

interface Setting {
  key: string;
  value: unknown;
  is_default: boolean;
  row_version: number;
}

async function session(request: APIRequestContext, account: Account): Promise<Headers> {
  const answer = await request.post("./api/v1/auth/sign-in", {
    data: { username: account.username, access_code: account.accessCode },
  });
  expect(answer.status(), "the account of the file signs in through the API").toBe(200);
  const { token } = (await answer.json()) as { token: string };
  return { Authorization: `Bearer ${token}` };
}

async function setting(request: APIRequestContext, headers: Headers, key: string) {
  const answer = await request.get("./api/v1/settings", { headers });
  expect(answer.status(), "get /settings").toBe(200);
  const found = ((await answer.json()) as Setting[]).find((one) => one.key === key);
  if (!found) throw new Error(`there is no setting ${key}`);
  return found;
}

/** Give a setting a value, or its default for null. */
async function put(request: APIRequestContext, headers: Headers, key: string, value: unknown) {
  const { row_version } = await setting(request, headers, key);
  const answer = await request.put(`./api/v1/settings/${key}`, {
    headers,
    data: { row_version, value },
  });
  expect(answer.status(), `put /settings/${key}: ${await answer.text()}`).toBe(200);
}

// The settings as this file found them: null for one at its default.
const found = new Map<string, unknown>();

test.beforeAll(async ({ request, accounts }) => {
  const headers = await session(request, await accounts.of("formats"));
  for (const key of SETTINGS) {
    const now = await setting(request, headers, key);
    found.set(key, now.is_default ? null : now.value);
  }
});

test.afterAll(async ({ request, accounts }) => {
  const headers = await session(request, await accounts.of("formats"));
  for (const key of SETTINGS) {
    const now = await setting(request, headers, key);
    const was = found.get(key) ?? null;
    if (JSON.stringify(now.is_default ? null : now.value) !== JSON.stringify(was)) {
      await put(request, headers, key, was);
    }
  }
});

/** Paste text into a box, as a person does with the keyboard. */
async function paste(page: Page, box: Locator, text: string) {
  await page.evaluate((given) => navigator.clipboard.writeText(given), text);
  await box.focus();
  await page.keyboard.press("ControlOrMeta+V");
}

/** The form of New contact, opened afresh. */
async function newContact(page: Page): Promise<Locator> {
  await page.goto("./contacts");
  await expect(page.getByRole("heading", { level: 1, name: "Contacts" })).toBeVisible();
  await page.getByRole("button", { name: "New contact" }).click();
  return region(page, "New contact");
}

test("P-322: Admin → Settings changes the patterns of a telephone number as a list", async ({
  page,
  account,
}) => {
  test.setTimeout(120_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  await page.goto("./admin/settings");
  await expect(page.getByRole("heading", { level: 1, name: "Settings" })).toBeVisible();
  const row = page.getByTestId("settings").locator('tr[data-setting="phone_formats"]');
  await expect(page.getByTestId("default-phone_formats")).toHaveText("—");
  await row.getByRole("button", { name: "Change phone_formats" }).click();
  const form = page.getByTestId("setting-form");
  await expect(form.getByTestId("no-patterns")).toHaveText(
    "No pattern: every number is kept as typed.",
  );

  // The two patterns of P-293, each with one press; once in the list, not again.
  await form.getByRole("button", { name: `Add ${PLAIN}` }).click();
  await form.getByRole("button", { name: `Add ${US}` }).click();
  await expect(form.getByRole("button", { name: `Add ${PLAIN}` })).toBeDisabled();
  const patterns = form.getByTestId("patterns").getByRole("listitem");
  await expect(patterns).toHaveCount(2);
  await expect(patterns.nth(0)).toContainText(`${PLAIN} writes 555-010-0123`);
  await expect(patterns.nth(1)).toContainText(`${US} writes +1 (555) 010-0123`);

  // One of the Admin's own: said wrong before it is sent, then taken, then removed.
  const own = form.getByLabel("Add a pattern of your own");
  await own.fill("# # #");
  await form.getByRole("button", { name: "Add", exact: true }).click();
  await expect(own).toHaveAttribute("aria-invalid", "true");
  await expect(form).toContainText("A pattern has a # for each digit, four at least.");
  await own.fill("+44 #### ######");
  await own.press("Enter");
  await expect(patterns).toHaveCount(3);
  await expect(patterns.nth(2)).toContainText("+44 #### ###### writes +44 5550 100123");
  await form.getByRole("button", { name: "Remove +44 #### ######" }).click();
  await expect(patterns).toHaveCount(2);

  // The order is the order they are tried: the US pattern first.
  await form.getByRole("button", { name: `Move ${US} up` }).click();
  await expect(patterns.nth(0)).toContainText(US);
  await form.getByRole("button", { name: "Set", exact: true }).click();
  await expect(page.getByText(`phone_formats was set to ${US}, ${PLAIN}.`)).toBeVisible();
  await expect(page.getByTestId("value-phone_formats")).toHaveText(`${US}, ${PLAIN}`);
  await expectClean(page, seen);
});

test("P-322: a contact's name, email and numbers are tidied as a box is left or pasted into, once", async ({
  page,
  account,
}) => {
  test.setTimeout(120_000);
  const seen = await watch(page.context());
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
  await signIn(page, account);
  let form = await newContact(page);
  const name = form.getByLabel("Name (required)");
  const email = form.getByLabel("Email");
  const phone = form.getByLabel("Phone", { exact: true });
  const phone2 = form.getByLabel("Second phone");
  const organization = form.getByLabel("Organization");

  // Nothing at each key: tidied as the box is left.
  await name.pressSequentially(`ada o'lee-roe ${suffix}`);
  await expect(name).toHaveValue(`ada o'lee-roe ${suffix}`);
  await email.click();
  await expect(name).toHaveValue(titled(`Ada O'Lee-Roe ${suffix}`));
  await email.fill(`Ada.Roe.${suffix}@Example.ORG`);
  await phone.click();
  await expect(email).toHaveValue(`ada.roe.${suffix}@example.org`);
  await phone.fill("5550100123");
  await organization.click();
  await expect(phone).toHaveValue("+1 (555) 010-0123");
  // A box with no format is left as typed.
  await organization.fill("example operations");
  await phone2.click();
  await expect(organization).toHaveValue("example operations");

  // A paste is tidied at once, before the box is left; one with a letter is kept.
  await paste(page, phone2, "1 555 010 0124\n");
  await expect(phone2).toHaveValue("+1 (555) 010-0124");
  await phone2.fill("");
  await paste(page, phone2, "555 0100 x12");
  await expect(phone2).toHaveValue("555 0100 x12");

  // Tidied once: the person's own correction stands.
  const corrected = `Ada O'Lee-roe ${titled(suffix)}`;
  await name.fill(corrected);
  await email.click();
  await expect(name).toHaveValue(corrected);

  await form.getByRole("button", { name: "Create contact" }).click();
  await expect(page.getByRole("heading", { level: 1, name: corrected })).toBeVisible();
  const facts = page.getByTestId("contact-facts");
  await expect(facts).toContainText(`ada.roe.${suffix}@example.org`);
  await expect(facts).toContainText("+1 (555) 010-0123");
  await expect(page.getByTestId("contact-phone2")).toHaveText("555 0100 x12");

  // Enter sends the form without leaving the box: what was typed is tidied first.
  form = await newContact(page);
  await form.getByLabel("Name (required)").fill(`rex example ${suffix}`);
  await form.getByLabel("Name (required)").press("Enter");
  await expect(
    page.getByRole("heading", { level: 1, name: titled(`Rex Example ${suffix}`) }),
  ).toBeVisible();

  // A paste longer than the field takes is taken whole, said too long, and not sent.
  form = await newContact(page);
  await form.getByLabel("Name (required)").fill(titled(`Long Example ${suffix}`));
  const long = `${"5".repeat(40)} ext. 1234567890`;
  await paste(page, form.getByLabel("Phone", { exact: true }), long);
  await expect(form.getByLabel("Phone", { exact: true })).toHaveValue(long);
  await expect(form).toContainText(`At most 50 characters: this has ${long.length}.`);
  await form.getByRole("button", { name: "Create contact" }).click();
  await expect(form.getByLabel("Phone", { exact: true })).toHaveAttribute("aria-invalid", "true");
  await expect(page.getByRole("heading", { level: 1, name: "Contacts" })).toBeVisible();

  // The new person of New user is tidied the same.
  await page.goto("./admin/users");
  await page.getByRole("button", { name: "New user" }).click();
  const person = region(page, "New user").getByTestId("new-person-new-user");
  await person.getByLabel("Name (required)").fill(`quinn example ${suffix}`);
  await person.getByLabel("Phone", { exact: true }).fill("555.010.0125");
  await person.getByLabel("Email").click();
  await expect(person.getByLabel("Name (required)")).toHaveValue(titled(`Quinn Example ${suffix}`));
  await expect(person.getByLabel("Phone", { exact: true })).toHaveValue("+1 (555) 010-0125");
  await expectClean(page, seen);
});

test("P-322: a file's preview shows each value a format writes beside the file's", async ({
  page,
  account,
}) => {
  test.setTimeout(90_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  await page.goto("./import");
  await expect(page.getByRole("heading", { level: 1, name: "Import" })).toBeVisible();
  const rows = [
    ["name", "email", "phone", "phone2"],
    [`Sam Roe ${suffix}`, `Sam.Roe.${suffix}@Example.NET`, "1 555 010 0126", "555 0100 x12"],
  ];
  await page.getByLabel("File", { exact: true }).setInputFiles({
    name: `contacts-${suffix}.csv`,
    mimeType: "text/csv",
    buffer: Buffer.from(rows.map((row) => `${row.join(",")}\n`).join(""), "utf8"),
  });
  await expect(page.getByLabel("Records")).toHaveValue("contacts");
  await page.getByRole("button", { name: "Preview", exact: true }).click();
  await expect(page.getByTestId("import-job")).toHaveAttribute("data-status", "previewed", {
    timeout: 20_000,
  });
  const changes = page.locator("ul.changes");
  await expect(changes.locator('li[data-field="phone"]')).toHaveText(
    "phone: (blank) → +1 (555) 010-0126 (in the file: 1 555 010 0126)",
  );
  await expect(changes.locator('li[data-field="email"]')).toHaveText(
    `email: (blank) → sam.roe.${suffix}@example.net (in the file: Sam.Roe.${suffix}@Example.NET)`,
  );
  // A number with a letter is kept as the file has it: no format wrote it.
  await expect(changes.locator('li[data-field="phone2"]')).toHaveText(
    "phone2: (blank) → 555 0100 x12",
  );
  await expectClean(page, seen);
});

test("P-322: with title_case_names off, a name is kept as typed", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(90_000);
  const headers = await session(request, account);
  await put(request, headers, "title_case_names", false);
  const seen = await watch(page.context());
  await signIn(page, account);
  const form = await newContact(page);
  const name = form.getByLabel("Name (required)");
  await name.fill(`kim lee ${suffix}`);
  await form.getByLabel("Email").click();
  await expect(name).toHaveValue(`kim lee ${suffix}`);
  await form.getByRole("button", { name: "Cancel" }).click();
  await put(request, headers, "title_case_names", null);
  await expectClean(page, seen);
});
