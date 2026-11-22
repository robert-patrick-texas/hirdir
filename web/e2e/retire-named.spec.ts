// The browser scenarios of release 0.9.17, P-314 (1): the button that confirms a
// retirement of a person's records names each record it changes, by what it is and what
// it is known by, as the ticks stand: `Release KL and retire contact Kim Lee`, `Release
// KL, hand KM to Sam Roe, and retire account klee and contact Kim Lee`, a label left open
// `leave KL open`; a record kept is not named; and on a window of 360 pixels the button
// wraps onto more lines rather than shortening.
//
// They keep to the rules of support.ts: an account of the file's own, people of its own
// with the file's mark in their names, and the accounts put away when the file ends.

import { type APIRequestContext, expect } from "@playwright/test";
import { type Headers, session } from "./referenceSteps";
import {
  goAhead,
  type Label,
  labelRow,
  makePerson,
  openOperator,
  openUser,
  type Person,
  putAway,
  read,
  type Status,
} from "./retiredSteps";
import { region } from "./structure";
import { expectClean, mark, signIn, test, watch } from "./support";

const suffix = mark("retire-named");
// Every account the scenarios make, to be put away when they end.
const madeAccounts: string[] = [];

async function person(
  request: APIRequestContext,
  headers: Headers,
  key: string,
  options: { labels?: number } = {},
): Promise<Person> {
  const made = await makePerson(request, headers, suffix, key, options);
  madeAccounts.push(made.user.hid);
  return made;
}

test.beforeEach(async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
});

test.afterAll(async ({ request, accounts }) => {
  await putAway(request, await session(request, await accounts.of("retire-named")), madeAccounts);
});

test("P-314: the button names each record it changes, as the ticks stand, and the press does it", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(180_000);
  const headers = await session(request, account);
  const kim = await person(request, headers, "kim", { labels: 2 });
  const sam = await person(request, headers, "sam");
  const [first, second] = kim.labels as [Label, Label];
  const seen = await watch(page.context());
  await signIn(page, account);
  const ask = page.getByTestId("retire-person");
  const go = goAhead(ask);
  const contactBox = ask.getByRole("checkbox", { name: `Retire the contact ${kim.contact.name}` });
  const accountBox = ask.getByRole("checkbox", { name: `Retire the account ${kim.user.username}` });
  const other = labelRow(ask, second);
  const both = `retire account ${kim.user.username} and contact ${kim.contact.name}`;

  // As it opens on a label: the other label released, the account and the contact retired.
  await openOperator(page, first);
  await region(page, "Release").getByRole("button", { name: "Release", exact: true }).click();
  await expect(go).toHaveText(`Release ${first.label} and ${second.label}, and ${both}`);
  // Handed over: to nobody yet, then to the person chosen, by their name.
  await other.getByRole("radio", { name: "Hand over to", exact: true }).check();
  await expect(go).toHaveText(`Release ${first.label}, hand ${second.label} over, and ${both}`);
  await other.getByLabel(`Person to hand ${second.label} over to`).fill(sam.contact.name);
  await other
    .getByRole("list", { name: "Contacts that match" })
    .getByRole("button", { name: new RegExp(`^${sam.contact.name}`) })
    .click();
  await expect(go).toHaveText(
    `Release ${first.label}, hand ${second.label} to ${sam.contact.name}, and ${both}`,
  );
  // Left open.
  await other.getByRole("radio", { name: "Leave open", exact: true }).check();
  await expect(go).toHaveText(`Release ${first.label}, leave ${second.label} open, and ${both}`);
  // The contact kept: the account alone is retired; then a label kept is not named.
  await contactBox.uncheck();
  await expect(go).toHaveText(
    `Release ${first.label}, leave ${second.label} open, and retire account ${kim.user.username}`,
  );
  await other.getByRole("radio", { name: "Keep", exact: true }).check();
  await expect(go).toHaveText(`Release ${first.label} and retire account ${kim.user.username}`);
  await accountBox.uncheck();
  await expect(go).toHaveText(`Release ${first.label}`);
  await ask.getByRole("button", { name: "Cancel" }).click();

  // On the page of the account, it comes first; a label handed over is named with its
  // person, and the notice after the press names that person too.
  await openUser(page, kim.user);
  await region(page, "Retire").getByRole("button", { name: "Retire account" }).click();
  await expect(go).toHaveText(
    `Retire account ${kim.user.username} and contact ${kim.contact.name}, and release ${first.label} and ${second.label}`,
  );
  await other.getByRole("radio", { name: "Hand over to", exact: true }).check();
  await other.getByLabel(`Person to hand ${second.label} over to`).fill(sam.contact.name);
  await other
    .getByRole("list", { name: "Contacts that match" })
    .getByRole("button", { name: new RegExp(`^${sam.contact.name}`) })
    .click();
  const said = `Retire account ${kim.user.username} and contact ${kim.contact.name}, release ${first.label}, and hand ${second.label} to ${sam.contact.name}`;
  await expect(go).toHaveText(said);
  await go.click();
  await expect(ask).toHaveCount(0);
  await expect(
    page.getByText(`${second.label} was handed over to ${sam.contact.name}`),
  ).toBeVisible();
  // What the button said is what was done.
  for (const [path, status] of [
    [`/users/${kim.user.hid}`, "retired"],
    [`/contacts/${kim.contact.hid}`, "retired"],
    [`/operators/${first.hid}`, "retired"],
    [`/operators/${second.hid}`, "active"],
  ] as const) {
    expect((await read<Status>(request, headers, path)).record_status).toBe(status);
  }
  expect(
    (await read<{ contact_hid: string | null }>(request, headers, `/operators/${second.hid}`))
      .contact_hid,
  ).toBe(sam.contact.hid);
  await expectClean(page, seen);
});

test("P-314: on a window of 360 pixels the button wraps onto more lines, and is said in full", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(120_000);
  const headers = await session(request, account);
  const lou = await person(request, headers, "lou", { labels: 3 });
  const [first, second, third] = lou.labels as [Label, Label, Label];
  const seen = await watch(page.context());
  await signIn(page, account);
  await page.setViewportSize({ width: 360, height: 800 });
  await openUser(page, lou.user);
  await region(page, "Retire").getByRole("button", { name: "Retire account" }).click();
  const ask = page.getByTestId("retire-person");
  await labelRow(ask, third).getByRole("radio", { name: "Leave open", exact: true }).check();
  const go = goAhead(ask);
  const words = `Retire account ${lou.user.username} and contact ${lou.contact.name}, release ${first.label} and ${second.label}, and leave ${third.label} open`;
  await expect(go).toHaveText(words);
  await go.scrollIntoViewIfNeeded();
  // Within the dialog, and so within the window, on more lines than one.
  const button = await go.boundingBox();
  const dialog = await ask.boundingBox();
  const line = await go.evaluate((element) =>
    Number.parseFloat(getComputedStyle(element).lineHeight),
  );
  expect(button && dialog).toBeTruthy();
  if (!button || !dialog) return;
  expect(button.x).toBeGreaterThanOrEqual(dialog.x);
  expect(button.x + button.width).toBeLessThanOrEqual(dialog.x + dialog.width + 0.5);
  expect(button.height).toBeGreaterThan(line * 1.5);
  // Nothing of it is cut off, and the dialog stands in the window and does not scroll
  // sideways.
  expect(await go.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  expect(dialog.x).toBeGreaterThanOrEqual(0);
  expect(dialog.x + dialog.width).toBeLessThanOrEqual(360);
  expect(await ask.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  await ask.getByRole("button", { name: "Cancel" }).click();
  await expectClean(page, seen);
});
