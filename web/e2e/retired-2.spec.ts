// The browser scenarios of a retired account and of a person retired together, in
// release 0.9.14, part two: what the review of the pages found, each held by a scenario.
// They keep to the rules of support.ts, as retired.spec.ts does: an account of the
// file's own, people of its own with the file's mark in their names, each scenario
// making those it retires, and the accounts put away when the file ends.

import { type APIRequestContext, expect, type Locator, type Page } from "@playwright/test";
import { type Headers, make, session } from "./referenceSteps";
import {
  change,
  goAhead,
  type Label,
  labelRow,
  makePerson,
  openContact,
  openOperator,
  openUser,
  type Person,
  putAway,
  read,
  type Status,
} from "./retiredSteps";
import { region } from "./structure";
import { createAccount, expectClean, mark, signIn, test, watch } from "./support";

const suffix = mark("retired-2");
// Every account the scenarios make, to be put away when they end.
const madeAccounts: string[] = [];

/** Make a person of this file's own, and keep its account to put away. */
async function person(
  request: APIRequestContext,
  headers: Headers,
  key: string,
  options: { labels?: number; role?: string } = {},
): Promise<Person> {
  const made = await makePerson(request, headers, suffix, key, options);
  madeAccounts.push(made.user.hid);
  return made;
}

test.beforeEach(async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
});

test.afterAll(async ({ request, accounts }) => {
  await putAway(request, await session(request, await accounts.of("retired-2")), madeAccounts);
});

test("review 1: a new access code is never on show on the page of another account", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(180_000);
  const headers = await session(request, account);
  // Two retired accounts: the one that has a username, and the one that asks for it.
  const has = await createAccount(request, `e2e-${suffix}-has`, null);
  const asks = await createAccount(request, `e2e-${suffix}-asks`, null);
  madeAccounts.push(has.hid, asks.hid);
  for (const one of [has, asks]) await change(request, headers, "post", `/users/${one.hid}/retire`);
  const seen = await watch(page.context());
  await signIn(page, account);

  // From the refusal of the username, by its link, to the account that has it.
  await openUser(page, asks);
  const details = region(page, "Details");
  await details.getByLabel("Username").fill(has.username);
  await details.getByRole("button", { name: "Save", exact: true }).click();
  await details.locator(".alert-error").getByRole("link", { name: has.username }).click();
  await expect(page.getByRole("heading", { level: 1, name: has.username })).toBeVisible();

  // Brought back there: its new code is shown, once.
  await region(page, "Retired").getByRole("button", { name: "Bring back" }).click();
  await page.getByTestId("bring-back-user").getByRole("button", { name: "Bring back" }).click();
  const secret = page.getByTestId("secret-box");
  await expect(
    secret.getByRole("heading", { name: `New access code for ${has.username}` }),
  ).toBeVisible();

  // Back, on the page of the other account, nothing of it is on show.
  await page.goBack();
  await expect(page.getByRole("heading", { level: 1, name: asks.username })).toBeVisible();
  await expect(page.getByTestId("user-state")).toHaveText("Retired");
  await expect(secret).toHaveCount(0);
  await expect(page.getByText(`New access code for ${has.username}`)).toHaveCount(0);
  // And it is not shown again on its own page: once is once.
  await page.goForward();
  await expect(page.getByRole("heading", { level: 1, name: has.username })).toBeVisible();
  await expect(page.getByTestId("user-state")).toHaveText("Active");
  await expect(secret).toHaveCount(0);
  await expectClean(page, seen, ["409 PATCH"]);
});

test("review 2: a retired service account is offered no new token, and its token reads Revoked at once", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(180_000);
  const headers = await session(request, account);
  const username = `e2e-${suffix}-svc`;
  const made = await request.post("./api/v1/users", {
    headers,
    data: { username, is_service_account: true },
  });
  expect(made.status(), await made.text()).toBe(201);
  const service = ((await made.json()) as { user: { hid: string; username: string } }).user;
  madeAccounts.push(service.hid);
  const tokenName = `${suffix}-token`;
  const token = await request.post(`./api/v1/users/${service.hid}/service-tokens`, {
    headers,
    data: { name: tokenName },
  });
  expect(token.status(), "the token is made").toBe(201);
  const seen = await watch(page.context());
  await signIn(page, account);

  await openUser(page, service);
  const tokens = region(page, "Service tokens");
  const row = tokens.locator("tbody tr", { hasText: tokenName });
  await expect(row).toContainText("Active");
  await expect(tokens.locator("form")).toHaveCount(1);

  // Retired: the token is read again and says what the server did, and no form is drawn.
  await region(page, "Retire").getByRole("button", { name: "Retire account" }).click();
  await goAhead(page.getByTestId("retire-person")).click();
  await expect(page.getByText(`${username} was retired.`)).toBeVisible();
  await expect(row).toContainText("Revoked");
  await expect(row.getByRole("button", { name: "Revoke" })).toHaveCount(0);
  await expect(tokens.getByTestId("tokens-retired")).toBeVisible();
  await expect(tokens.locator("form")).toHaveCount(0);
  await expect(tokens.getByRole("heading", { name: "New token" })).toHaveCount(0);
  await expect(tokens.getByLabel("Name", { exact: true })).toHaveCount(0);

  // Brought back: a token can be made again, and the old one stays revoked.
  await region(page, "Retired").getByRole("button", { name: "Bring back" }).click();
  await page.getByTestId("bring-back-user").getByRole("button", { name: "Bring back" }).click();
  await expect(page.getByText(`The service account ${username} is active again`)).toBeVisible();
  await expect(tokens.locator("form")).toHaveCount(1);
  await expect(tokens.getByLabel("Name", { exact: true })).toBeVisible();
  await expect(row).toContainText("Revoked");
  await expectClean(page, seen);
});

test("review 3: a linked record that goes away under the confirmation is read out of it, and the next press goes through", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(180_000);
  const headers = await session(request, account);
  const hugo = await person(request, headers, "hugo");
  const [first] = hugo.labels as [Label];
  const seen = await watch(page.context());
  await signIn(page, account);

  await openUser(page, hugo.user);
  await region(page, "Retire").getByRole("button", { name: "Retire account" }).click();
  const ask = page.getByTestId("retire-person");
  const contactBox = ask.getByRole("checkbox", { name: `Retire the contact ${hugo.contact.name}` });
  await contactBox.uncheck();
  await labelRow(ask, first).getByRole("radio", { name: "Keep", exact: true }).check();
  // Somebody else parts the label from the contact while the confirmation is open.
  await change(request, headers, "patch", `/operators/${first.hid}`, { contact_hid: null });

  // Refused: the list is read again, said in plain words, and what was chosen is kept.
  await goAhead(ask).click();
  await expect(ask.getByTestId("retire-list-changed")).toContainText("have changed");
  await expect(labelRow(ask, first)).toHaveCount(0);
  await expect(contactBox).not.toBeChecked();
  await expect(ask).not.toContainText("linked.");
  expect((await read<Status>(request, headers, `/users/${hugo.user.hid}`)).record_status).toBe(
    "active",
  );
  // The next press is of the list as it is now, and goes through.
  await goAhead(ask).click();
  await expect(
    page.getByText(`${hugo.user.username} was retired. The contact ${hugo.contact.name} stays.`),
  ).toBeVisible();
  await expectClean(page, seen, ["422 POST"]);
});

test("review 3: a label handed over to somebody retired since is refused at its field", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(180_000);
  const headers = await session(request, account);
  const ines = await person(request, headers, "ines");
  const [first] = ines.labels as [Label];
  const samName = `Sam Example ${suffix}`;
  const sam = await make(request, headers, "/contacts", { name: samName, record_status: "active" });
  const seen = await watch(page.context());
  await signIn(page, account);

  await openContact(page, ines.contact);
  await region(page, "Retire").getByRole("button", { name: "Retire contact" }).click();
  const ask = page.getByTestId("retire-person");
  const row = labelRow(ask, first);
  await row.getByRole("radio", { name: "Hand over to", exact: true }).check();
  const field = row.getByLabel(`Person to hand ${first.label} over to`);
  await field.fill(samName);
  await row
    .getByRole("list", { name: "Contacts that match" })
    .getByRole("button", { name: new RegExp(`^${samName}`) })
    .click();
  // The person chosen is retired before the press.
  await change(request, headers, "post", `/contacts/${sam.hid}/retire`);

  await goAhead(ask).click();
  await expect(field).toHaveAttribute("aria-invalid", "true");
  await expect(row.locator(".field-error")).toBeVisible();
  await expect(ask).toBeVisible();
  // Another choice for the label, and it goes through.
  await row.getByRole("radio", { name: "Release", exact: true }).check();
  await goAhead(ask).click();
  await expect(page.getByText(`${ines.contact.name} was retired`, { exact: false })).toBeVisible();
  await expectClean(page, seen, ["422 POST"]);
});

/** Opened and closed by Escape, and by its first button, the focus is back on what opened it. */
async function focusComesBack(page: Page, opener: Locator, dialog: Locator, cancel: string) {
  await opener.click();
  await expect(dialog).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(opener).toBeFocused();
  await opener.click();
  await dialog.getByRole("button", { name: cancel, exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await expect(opener).toBeFocused();
}

test("review 4: the focus is back on its button when a confirmation is closed", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(180_000);
  const headers = await session(request, account);
  const jon = await person(request, headers, "jon");
  const [first] = jon.labels as [Label];
  const seen = await watch(page.context());
  await signIn(page, account);
  const ask = page.getByTestId("retire-person");

  await openUser(page, jon.user);
  await focusComesBack(
    page,
    region(page, "Retire").getByRole("button", { name: "Retire account" }),
    ask,
    "Cancel",
  );
  await openContact(page, jon.contact);
  await focusComesBack(
    page,
    region(page, "Retire").getByRole("button", { name: "Retire contact" }),
    ask,
    "Cancel",
  );
  await openOperator(page, first);
  await focusComesBack(
    page,
    region(page, "Release").getByRole("button", { name: "Release", exact: true }),
    ask,
    "Cancel",
  );

  // Bring back, of an account retired with the rest kept.
  await change(request, headers, "post", `/users/${jon.user.hid}/retire`, {
    linked: { contact: "keep", operators: [{ hid: first.hid, action: "keep" }] },
  });
  await openUser(page, jon.user);
  await focusComesBack(
    page,
    region(page, "Retired").getByRole("button", { name: "Bring back" }),
    page.getByTestId("bring-back-user"),
    "Cancel",
  );
  await expectClean(page, seen);
});

test("review 5: Bring back says that the contact is back already, where somebody else brought it back", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(180_000);
  const headers = await session(request, account);
  const kat = await person(request, headers, "kat");
  const [first] = kat.labels as [Label];
  // Retired together: the account, the contact, the label released.
  await change(request, headers, "post", `/contacts/${kat.contact.hid}/retire`, {
    linked: { user: "retire", operators: [{ hid: first.hid, action: "retire" }] },
  });
  const seen = await watch(page.context());
  await signIn(page, account);

  await openUser(page, kat.user);
  await region(page, "Retired").getByRole("button", { name: "Bring back" }).click();
  const back = page.getByTestId("bring-back-user");
  const contactBox = back.getByRole("checkbox", {
    name: `Bring back the contact ${kat.contact.name}`,
  });
  await expect(contactBox).toBeChecked();
  // Somebody else brings the contact back while the confirmation is open.
  await change(request, headers, "patch", `/contacts/${kat.contact.hid}`, {
    record_status: "active",
  });

  // Refused, and said why in plain words: the contact is back already.
  await back.getByRole("button", { name: "Bring back" }).click();
  await expect(back.getByTestId("bring-back-changed")).toContainText(
    `The contact ${kat.contact.name} is back already`,
  );
  await expect(contactBox).toHaveCount(0);
  await expect(back).not.toContainText("linked.");
  await expect(page.getByTestId("secret-box")).toHaveCount(0);
  // Pressed again, the account is brought back.
  await back.getByRole("button", { name: "Bring back" }).click();
  await expect(
    page.getByTestId("secret-box").getByRole("heading", {
      name: `New access code for ${kat.user.username}`,
    }),
  ).toBeVisible();
  await expectClean(page, seen, ["422 POST"]);
});

test("review 7: Reload in a confirmation that is stale keeps it open, with what was chosen", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(180_000);
  const headers = await session(request, account);
  const lia = await person(request, headers, "lia", { labels: 2 });
  const [first, second] = lia.labels as [Label, Label];
  const samName = `Sal Example ${suffix}`;
  await make(request, headers, "/contacts", { name: samName, record_status: "active" });
  const seen = await watch(page.context());
  await signIn(page, account);

  await openContact(page, lia.contact);
  await region(page, "Retire").getByRole("button", { name: "Retire contact" }).click();
  const ask = page.getByTestId("retire-person");
  const handed = labelRow(ask, first);
  await handed.getByRole("radio", { name: "Hand over to", exact: true }).check();
  await handed.getByLabel(`Person to hand ${first.label} over to`).fill(samName);
  await handed
    .getByRole("list", { name: "Contacts that match" })
    .getByRole("button", { name: new RegExp(`^${samName}`) })
    .click();
  await labelRow(ask, second).getByRole("radio", { name: "Leave open", exact: true }).check();
  // Somebody else changes the contact while the confirmation is open.
  await change(request, headers, "patch", `/contacts/${lia.contact.hid}`, {
    notes: `Changed under the confirmation ${suffix}.`,
  });

  await goAhead(ask).click();
  await expect(ask).toContainText("This record has changed");
  await ask.getByRole("button", { name: "Reload" }).click();
  // Read again where it stands: still open, nothing chosen lost.
  await expect(ask).not.toContainText("This record has changed");
  await expect(ask).toBeVisible();
  await expect(handed.getByRole("radio", { name: "Hand over to", exact: true })).toBeChecked();
  await expect(handed.getByTestId(`chosen-hand_over_${first.hid}`)).toContainText(samName);
  await expect(
    labelRow(ask, second).getByRole("radio", { name: "Leave open", exact: true }),
  ).toBeChecked();
  await goAhead(ask).click();
  await expect(
    page.getByText(
      `${lia.contact.name} was retired, with the account ${lia.user.username}. ${first.label} was handed over and ${second.label} was left open.`,
    ),
  ).toBeVisible();
  await expectClean(page, seen, ["409 POST"]);
});

test("review 8: Take its contact away, of a retired account, asks first", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(180_000);
  const headers = await session(request, account);
  const mia = await person(request, headers, "mia");
  const [first] = mia.labels as [Label];
  await change(request, headers, "post", `/users/${mia.user.hid}/retire`, {
    linked: { contact: "keep", operators: [{ hid: first.hid, action: "keep" }] },
  });
  const seen = await watch(page.context());
  await signIn(page, account);

  await openUser(page, mia.user);
  const take = region(page, "Take its contact away");
  const facts = page.getByTestId("user-person");
  await take.getByRole("button", { name: "Take its contact away" }).click();
  const ask = page.getByRole("dialog");
  await expect(ask).toContainText("is given no contact again until it is brought back");
  // Cancelled, nothing is changed.
  await ask.getByRole("button", { name: "Cancel" }).click();
  await expect(facts.getByRole("link", { name: mia.contact.name })).toBeVisible();
  expect(
    (await read<{ contact: unknown }>(request, headers, `/users/${mia.user.hid}`)).contact,
  ).not.toBeNull();
  // Confirmed, the contact is taken away.
  await take.getByRole("button", { name: "Take its contact away" }).click();
  await ask.getByRole("button", { name: "Take its contact away" }).click();
  await expect(facts).toContainText("has no contact");
  await expectClean(page, seen);
});

test("review 9: the button that confirms says what it will do, as the ticks stand", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(180_000);
  const headers = await session(request, account);
  const noa = await person(request, headers, "noa", { labels: 2 });
  const [first, second] = noa.labels as [Label, Label];
  const seen = await watch(page.context());
  await signIn(page, account);
  const ask = page.getByTestId("retire-person");
  const go = goAhead(ask);
  const contactBox = ask.getByRole("checkbox", { name: `Retire the contact ${noa.contact.name}` });
  const accountBox = ask.getByRole("checkbox", { name: `Retire the account ${noa.user.username}` });

  // On the page of a label: Release, as it opens, retires the account, the contact and
  // the other label too, and the button says so.
  await openOperator(page, first);
  await region(page, "Release").getByRole("button", { name: "Release", exact: true }).click();
  await expect(go).toHaveText(`Release ${first.label} and retire 3 more`);
  await contactBox.uncheck();
  await expect(go).toHaveText(`Release ${first.label} and retire 2 more`);
  await accountBox.uncheck();
  await expect(go).toHaveText(`Release ${first.label} and retire 1 more`);
  const other = labelRow(ask, second);
  // A label handed over or left open is not retired: it is not counted.
  await other.getByRole("radio", { name: "Leave open", exact: true }).check();
  await expect(go).toHaveText(`Release ${first.label} only`);
  await other.getByRole("radio", { name: "Keep", exact: true }).check();
  await expect(go).toHaveText(`Release ${first.label} only`);
  await contactBox.check();
  await expect(go).toHaveText(`Release ${first.label} and retire 3 more`);
  await ask.getByRole("button", { name: "Cancel" }).click();

  // The same manner on the page of the account and of the contact.
  await openUser(page, noa.user);
  await region(page, "Retire").getByRole("button", { name: "Retire account" }).click();
  await expect(go).toHaveText(`Retire ${noa.user.username} and 3 more`);
  await contactBox.uncheck();
  await labelRow(ask, first).getByRole("radio", { name: "Keep", exact: true }).check();
  await other.getByRole("radio", { name: "Keep", exact: true }).check();
  await expect(go).toHaveText(`Retire ${noa.user.username} only`);
  await ask.getByRole("button", { name: "Cancel" }).click();
  await openContact(page, noa.contact);
  await region(page, "Retire").getByRole("button", { name: "Retire contact" }).click();
  await expect(go).toHaveText(`Retire ${noa.contact.name} and 3 more`);
  await other.getByRole("radio", { name: "Leave open", exact: true }).check();
  await expect(go).toHaveText(`Retire ${noa.contact.name} and 2 more`);

  // The press does what the button said: the account, and one label released.
  await go.click();
  await expect(page.getByText(`${noa.contact.name} was retired`, { exact: false })).toBeVisible();
  for (const [path, status] of [
    [`/users/${noa.user.hid}`, "retired"],
    [`/operators/${first.hid}`, "retired"],
    [`/operators/${second.hid}`, "active"],
  ] as const) {
    expect((await read<Status>(request, headers, path)).record_status).toBe(status);
  }
  await expectClean(page, seen);
});
