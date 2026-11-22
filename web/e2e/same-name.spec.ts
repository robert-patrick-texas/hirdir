// The browser scenarios of a contact's name that another contact has, release 0.9.17
// (P-315):
//
//   A contact may have the name of another, and is saved with a warning. New contact
//   with a name another contact has makes it, and the contact's page says that another
//   contact is named so and that a file tells them apart by the email or the HID, with
//   a link to the contacts of that name, which lists both; a save that changes the name
//   away takes the words away, and one that changes it back brings them back. On the
//   Profile, Save details that sends a name others have says so, of the person, with the
//   same link; a save of another field says nothing of it.
//
// They keep to the rules of support.ts: an account of their own, and a person and
// contacts of their own, each with the file's mark in its name. The person the file
// makes is disabled when it ends.

import { type APIRequestContext, expect, type Page } from "@playwright/test";
import { type Headers, make, session } from "./referenceSteps";
import { region } from "./structure";
import {
  type Account,
  createAccount,
  expectClean,
  mark,
  signIn,
  test,
  titled,
  watch,
} from "./support";

const suffix = mark("same-name");
const shared = titled(`Sam Roe ${suffix}`);

/** The words of the contact's page, and of the Profile, of a name others have. */
function saidOf(page: Page) {
  return page.getByTestId("same-name");
}

/** A record read through the API, as the file's own Admin. */
async function read<T>(request: APIRequestContext, headers: Headers, path: string): Promise<T> {
  const answer = await request.get(`./api/v1${path}`, { headers });
  expect(answer.status(), `get ${path}`).toBe(200);
  return (await answer.json()) as T;
}

/** Disable a person the file made: none is left that can sign in. */
async function disable(request: APIRequestContext, headers: Headers, person: Account) {
  const path = `/users/${encodeURIComponent(person.hid)}`;
  const found = await read<{ row_version: number }>(request, headers, path);
  const answer = await request.patch(`./api/v1${path}`, {
    headers,
    data: { disabled: true, row_version: found.row_version },
  });
  expect(answer.status(), `disable ${person.username}`).toBe(200);
}

test("P-315: a contact with the name of another is made and saved, and its page says how a file tells them apart, with a link to both", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(150_000);
  const seen = await watch(page.context());
  const headers = await session(request, account);
  await make(request, headers, "/contacts", {
    name: shared,
    email: `sam.roe.${suffix}@example.com`,
  });
  await signIn(page, account);

  // New contact with the name: made, and told on its page.
  await page.goto("./contacts");
  await page.getByRole("button", { name: "New contact" }).click();
  const form = region(page, "New contact");
  await form.getByLabel("Name (required)").fill(shared);
  await form.getByLabel("Email").fill(`s.roe.${suffix}@example.net`);
  await form.getByRole("button", { name: "Create contact" }).click();
  await expect(page.getByRole("heading", { level: 1, name: shared })).toBeVisible();
  await expect(saidOf(page)).toContainText(
    `Another contact is named ${shared}: a file tells them apart by the email or the HID.`,
  );
  const here = page.url();

  // A save that names it otherwise takes the words away; one that names it back, as
  // typed in another case, brings them back.
  const details = region(page, "Details");
  await details.getByLabel("Name (required)").fill(titled(`Sam A. Roe ${suffix}`));
  await details.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("The contact was saved.")).toBeVisible();
  await expect(
    page.getByRole("heading", { level: 1, name: titled(`Sam A. Roe ${suffix}`) }),
  ).toBeVisible();
  await expect(saidOf(page)).toHaveCount(0);
  await region(page, "Details").getByLabel("Name (required)").fill(shared.toUpperCase());
  await region(page, "Details").getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: shared.toUpperCase() })).toBeVisible();
  await expect(saidOf(page)).toContainText(`Another contact is named ${shared.toUpperCase()}:`);

  // The link lists the contacts of that name: both.
  await saidOf(page)
    .getByRole("link", { name: `The contacts named ${shared.toUpperCase()}` })
    .click();
  await expect(page).toHaveURL(/\/contacts\?filter=/);
  await expect(page.getByTestId("grid-total")).toHaveText("2 contacts");
  await page.goto(here);
  await expect(saidOf(page)).toBeVisible();

  // The Profile: a person who gives themselves the name, saved with the warning.
  const person = await createAccount(request, `e2e-${suffix}-kim`, "viewer", {
    name: `Kim Lee ${suffix}`,
    email: `kim.lee.${suffix}@example.com`,
  });
  try {
    const context = await page.context().browser()?.newContext();
    if (!context) throw new Error("no browser for a second person");
    const theirs = await context.newPage();
    const seenTheirs = await watch(context);
    await signIn(theirs, person);
    await theirs.goto("./profile");
    const own = region(theirs, "Details");
    await expect(own.getByLabel("Name (required)", { exact: true })).toHaveValue(
      `Kim Lee ${suffix}`,
    );
    // A save of another field says nothing of the name.
    await own.getByLabel("Phone", { exact: true }).fill("+1 555 0100");
    await own.getByRole("button", { name: "Save details", exact: true }).click();
    await expect(own.locator(".alert-ok")).toHaveText("Your details were saved.");
    await expect(saidOf(theirs)).toHaveCount(0);
    await own.getByLabel("Name (required)", { exact: true }).fill(shared);
    await own.getByRole("button", { name: "Save details", exact: true }).click();
    await expect(own.locator(".alert-ok")).toHaveText("Your details were saved.");
    await expect(saidOf(theirs)).toContainText(
      `2 other contacts are named ${shared}: a file tells you apart by your email or your HID.`,
    );
    await expect(
      saidOf(theirs).getByRole("link", { name: `The contacts named ${shared}` }),
    ).toHaveAttribute("href", /\/contacts\?filter=name%3Aeq%3ASam\+Roe\+/);
    await expectClean(theirs, seenTheirs);
    await context.close();
  } finally {
    await disable(request, headers, person);
  }

  await expectClean(page, seen);
});
