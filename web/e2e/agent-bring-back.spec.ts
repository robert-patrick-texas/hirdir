// A browser scenario of release 0.9.17, from the review of the web (review 6): Bring back
// of an agent whose person was retired while the dialog was open is refused; the refusal
// names that person as the one it was answerable to, the agent's person is read again,
// and the dialog asks for another before Bring back can be pressed again (P-316).
//
// It keeps to the rules of support.ts: an account of the file's own, people and an agent
// of its own with the file's mark in their names, and the accounts put away when the
// file ends.

import { expect } from "@playwright/test";
import { choosePerson, makeAgent, makePerson } from "./agentSteps";
import { session } from "./referenceSteps";
import { change, openUser, putAway, read } from "./retiredSteps";
import { region } from "./structure";
import { expectClean, mark, signIn, test, watch } from "./support";

const suffix = mark("agent-bring-back");
const madeAccounts: string[] = [];

test.afterAll(async ({ request, accounts }) => {
  await putAway(
    request,
    await session(request, await accounts.of("agent-bring-back")),
    madeAccounts,
  );
});

test("review 6: Bring back of an agent whose person was retired meanwhile asks for another person", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 1280, height: 900 });
  const headers = await session(request, account);
  const rex = await makePerson(request, suffix, "rex", "inventory", madeAccounts);
  const sam = await makePerson(request, suffix, "sam", "inventory", madeAccounts);
  const agent = await makeAgent(request, headers, suffix, "bot", rex, "viewer", madeAccounts);
  await change(request, headers, "post", `/users/${agent.hid}/retire`);
  const seen = await watch(page.context());
  await signIn(page, account);

  await openUser(page, agent);
  await region(page, "Retired").getByRole("button", { name: "Bring back" }).click();
  const ask = page.getByTestId("bring-back-user");
  await expect(ask.getByText(`${rex.name}, as before`)).toBeVisible();
  // Rex is retired while the dialog is open.
  await change(request, headers, "post", `/users/${rex.hid}/retire`, {
    linked: { contact: "retire" },
  });
  const go = ask.getByRole("button", { name: "Bring back" });
  await go.click();
  // The refusal names rex as the person it was answerable to, not as a duplicate.
  await expect(ask).not.toContainText("The user that has it");
  await expect(ask.getByRole("link", { name: rex.username })).toBeVisible();
  // Read again: rex is offered no longer, and another is asked for first.
  await expect(ask).not.toContainText(`${rex.name}, as before`);
  await expect(ask).toContainText(`${rex.username} is retired`);
  await expect(go).toBeDisabled();
  await choosePerson(page, "Answerable to", sam.name);
  await expect(go).toBeEnabled();
  await go.click();
  await expect(ask).toHaveCount(0);
  const back = await read<{ record_status: string; answerable: { hid: string } | null }>(
    request,
    headers,
    `/users/${agent.hid}`,
  );
  expect(back.record_status).toBe("active");
  expect(back.answerable?.hid).toBe(sam.hid);
  await expectClean(page, seen, ["409 POST"]);
});
