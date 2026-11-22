// A browser scenario of release 0.9.17, from the review of the web (review 10): the page
// of a service account and of an agent speaks of what it is, an account that holds
// tokens, and not of a person who signs in: no chain of one person, no sessions, the
// username and Disabled said of tokens, and Retire and Bring back said of tokens revoked
// and none given back (P-316).
//
// It keeps to the rules of support.ts: an account of the file's own, a person, an agent
// and a service account of its own with the file's mark in their names, and the accounts
// put away when the file ends.

import { expect } from "@playwright/test";
import { makeAgent, makePerson } from "./agentSteps";
import { make, session } from "./referenceSteps";
import { goAhead, openUser, putAway } from "./retiredSteps";
import { region } from "./structure";
import { expectClean, mark, signIn, test, watch } from "./support";

const suffix = mark("token-account-words");
const madeAccounts: string[] = [];

test.afterAll(async ({ request, accounts }) => {
  await putAway(
    request,
    await session(request, await accounts.of("token-account-words")),
    madeAccounts,
  );
});

test("review 10: the pages of an agent and of a service account speak of tokens, not of signing in", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 1280, height: 900 });
  const headers = await session(request, account);
  const sam = await makePerson(request, suffix, "sam", "inventory", madeAccounts);
  const agent = await makeAgent(request, headers, suffix, "late", sam, "viewer", madeAccounts);
  const service = (
    (await make(request, headers, "/users", {
      username: `e2e-${suffix}-sync`,
      kind: "service",
    })) as unknown as { user: { hid: string; username: string } }
  ).user;
  madeAccounts.push(service.hid);
  const seen = await watch(page.context());
  await signIn(page, account);

  for (const one of [service, agent]) {
    await openUser(page, one);
    await expect(page.getByTestId("chain")).toHaveCount(0);
    await expect(region(page, "Sessions")).toHaveCount(0);
    const details = region(page, "Details");
    await expect(details).toContainText("What the account is known by");
    await expect(details).toContainText("A disabled account's tokens are refused");
    await expect(details).not.toContainText("sign");
  }

  // Retire, with nothing linked: its tokens are revoked, and none are given back.
  await region(page, "Retire").getByRole("button", { name: "Retire account" }).click();
  const ask = page.getByTestId("retire-person");
  await expect(ask).toContainText(`The tokens of ${agent.username} are revoked`);
  await expect(ask).not.toContainText("access code");
  await goAhead(ask).click();
  await expect(page.getByTestId("user-retired")).toContainText("its tokens are revoked");
  await expect(page.getByTestId("user-retired")).not.toContainText("signs in");
  const retired = region(page, "Retired");
  await expect(retired).toContainText("no token");
  await expect(retired).not.toContainText("access code");

  // New user, of a kind that holds tokens, says the same of the username.
  await page.goto("./admin/users");
  await page.getByRole("button", { name: "New user" }).click();
  const form = region(page, "New user");
  await form.getByRole("group", { name: "Kind" }).getByRole("radio", { name: "Agent" }).check();
  await expect(form).toContainText("What the account is known by");
  await expect(page.getByText("A service account and an agent are no person")).toBeVisible();
  await expectClean(page, seen);
});
