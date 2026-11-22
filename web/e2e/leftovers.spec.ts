// The browser scenarios of the small leftovers of 0.9.17 (P-311):
//
//   A label of 40 characters, as long as a label may be, stays inside the colour
//   picker's sample on a window 360 pixels wide: on the form of a new operator, on the
//   Details of an operator, and on the Profile of the person behind it. The page scrolls
//   nowhere sideways.
//
// They keep to the rules of support.ts: an account of their own, and a person, a
// contact and the labels of their own, each with the file's mark in its name. The person
// the file makes is disabled when it ends.

import { type APIRequestContext, expect, type Locator, type Page } from "@playwright/test";
import { type Headers, make, session } from "./referenceSteps";
import { region } from "./structure";
import { type Account, createAccount, expectClean, mark, signIn, test, watch } from "./support";

const suffix = mark("leftovers");

/** A label of `length` characters that holds the file's mark: 40 is the most a label has. */
function longLabel(tail: string, length = 40): string {
  const start = `${suffix}-${tail}-`;
  return `${start}${"w".repeat(Math.max(0, length - start.length))}`.slice(0, length);
}

/** The colour picker of a form. */
function picker(form: Locator): Locator {
  return form.getByRole("group", { name: "Colour", exact: true });
}

/**
 * Where the sample of a picker ends, beside where the picker and the window end, and
 * whether the page scrolls sideways: the sample is inside both, and, where `page` is
 * asked, nothing scrolls. The page of an operator scrolls at 360 pixels by its facts,
 * its HID and its times, which are no part of the picker: it is not asked of it.
 */
async function sampleFits(colour: Locator, label: string, page = true): Promise<void> {
  const sample = colour.locator(".colour-sample");
  await expect(sample).toHaveText(label);
  const found = await colour.evaluate((fieldset) => {
    const shown = fieldset.querySelector(".colour-sample");
    const right = (element: Element | null) => element?.getBoundingClientRect().right ?? 0;
    return {
      sample: right(shown),
      picker: right(fieldset),
      window: document.documentElement.clientWidth,
      scrolls: document.documentElement.scrollWidth > document.documentElement.clientWidth,
      own: fieldset.scrollWidth > fieldset.clientWidth,
      // What runs past the window, where something does: said with the failure.
      past: [...document.querySelectorAll("main *")]
        .filter(
          (part) => part.getBoundingClientRect().right > document.documentElement.clientWidth + 0.5,
        )
        .slice(-3)
        .map(
          (part) =>
            `${part.tagName.toLowerCase()}.${part.className}: ${(part.textContent ?? "").slice(0, 60)}`,
        ),
    };
  });
  expect(found.sample, "the sample ends inside the picker").toBeLessThanOrEqual(found.picker + 0.5);
  expect(found.picker, "the picker ends inside the window").toBeLessThanOrEqual(found.window + 0.5);
  expect(found.own, "nothing of the picker is cut off").toBe(false);
  if (!page) return;
  expect(found.scrolls, `the page scrolls nowhere sideways: ${found.past.join(" | ")}`).toBe(false);
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

async function narrow(page: Page): Promise<void> {
  await page.setViewportSize({ width: 360, height: 800 });
}

test("P-311: a label of 40 characters stays inside the colour picker's sample at 360 pixels, on the Operators forms and on the Profile", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(180_000);
  const seen = await watch(page.context());
  const headers = await session(request, account);
  await signIn(page, account);
  await narrow(page);

  // A new operator: the sample shows the label as it is typed.
  const label = longLabel("new");
  expect(label).toHaveLength(40);
  await page.goto("./operators");
  await page.getByRole("button", { name: "New operator" }).click();
  const form = region(page, "New operator");
  await form.getByLabel("Label (required)").fill(label);
  await sampleFits(picker(form), label);
  await form.getByRole("radio", { name: "Nobody: an open assignment", exact: true }).check();
  await form.getByRole("button", { name: "Create operator" }).click();
  await expect(page.getByTestId("operator-heading")).toContainText(label);

  // Its Details: the same picker, with the label it has.
  const details = region(page, "Details");
  await sampleFits(picker(details), label, false);

  // The Profile of a person behind a label as long.
  const person = await createAccount(request, `e2e-${suffix}-kim`, "viewer", {
    name: `Kim Lee ${suffix}`,
    email: `kim.lee.${suffix}@example.com`,
  });
  try {
    const user = await read<{ contact: { hid: string } }>(
      request,
      headers,
      `/users/${encodeURIComponent(person.hid)}`,
    );
    const own = longLabel("kim");
    await make(request, headers, "/operators", { label: own, contact_hid: user.contact.hid });
    const context = await page.context().browser()?.newContext();
    if (!context) throw new Error("no browser for a second person");
    const theirs = await context.newPage();
    const seenTheirs = await watch(context);
    await signIn(theirs, person);
    await narrow(theirs);
    await theirs.goto("./profile");
    const part = theirs.getByTestId("profile-operator");
    await expect(part.getByRole("heading", { level: 3 })).toContainText(own);
    await sampleFits(picker(part), own);
    await expectClean(theirs, seenTheirs);
    await context.close();
  } finally {
    await disable(request, headers, person);
  }

  await expectClean(page, seen);
});
