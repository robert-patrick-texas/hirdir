// The browser scenarios of a retired account and of a person retired together, in
// release 0.9.14, part two: what the review of the pages found, each held by a scenario.
// They keep to the rules of support.ts, as retired.spec.ts does: an account of the
// file's own, people of its own with the file's mark in their names, each scenario
// making those it retires, and the accounts put away when the file ends.

import { expect } from "@playwright/test";
import { session } from "./referenceSteps";
import { change, goAhead, openUser, putAway } from "./retiredSteps";
import { region } from "./structure";
import { createAccount, expectClean, mark, signIn, test, watch } from "./support";

const suffix = mark("retired-2");
// Every account the scenarios make, to be put away when they end.
const madeAccounts: string[] = [];

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
