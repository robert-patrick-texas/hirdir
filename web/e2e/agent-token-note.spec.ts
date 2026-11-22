// A browser scenario of release 0.9.17, from the review of the web (review 9): a token
// made for an agent whose person lost their last role after the agent's page was read
// says, where it is shown once, that it is refused, as the server refuses it (P-314,
// P-316): the account is read again when the token is made.
//
// It keeps to the rules of support.ts: an account of the file's own, a person and an
// agent of its own with the file's mark in their names, and the accounts put away when
// the file ends. Neither signs in.

import { expect } from "@playwright/test";
import { makeAgent, makePerson } from "./agentSteps";
import { session } from "./referenceSteps";
import { openUser, putAway, read } from "./retiredSteps";
import { region } from "./structure";
import { expectClean, mark, signIn, test, watch } from "./support";

const suffix = mark("agent-token-note");
const madeAccounts: string[] = [];

test.afterAll(async ({ request, accounts }) => {
  await putAway(
    request,
    await session(request, await accounts.of("agent-token-note")),
    madeAccounts,
  );
});

test("review 9: a token made after the person's last role went says it is refused", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 1280, height: 900 });
  const headers = await session(request, account);
  const kit = await makePerson(request, suffix, "kit", "inventory", madeAccounts);
  const agent = await makeAgent(request, headers, suffix, "bot", kit, "inventory", madeAccounts);
  const seen = await watch(page.context());
  await signIn(page, account);

  await openUser(page, agent);
  // Elsewhere, kit's one role is taken away while the page is open.
  const held = await read<{ grants: Array<{ hid: string }> }>(
    request,
    headers,
    `/users/${kit.hid}`,
  );
  for (const grant of held.grants) {
    const gone = await request.delete(`./api/v1/role-grants/${grant.hid}`, { headers });
    expect(gone.status(), `delete grant: ${await gone.text()}`).toBe(204);
  }
  const tokens = region(page, "Tokens");
  await tokens.getByLabel("Name (required)").fill(`${suffix}-run`);
  await tokens.getByRole("button", { name: "Create token" }).click();
  await expect(page.getByTestId("secret-box")).toContainText(
    `This token is refused while ${kit.username} holds no role`,
  );
  await expectClean(page, seen);
});
