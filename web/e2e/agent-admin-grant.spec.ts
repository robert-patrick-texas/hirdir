// A browser scenario of release 0.9.17, from the review of the web (review 4): Admin
// granted under Roles to a group that holds an agent is refused, and the agents the
// server names are said as the agents of the group, each a link, and not as what runs on
// an item (P-316).
//
// It keeps to the rules of support.ts: an account of the file's own, a person, an agent
// and a group of its own with the file's mark in their names, and the accounts put away
// when the file ends.

import { expect } from "@playwright/test";
import { makeAgent, makePerson } from "./agentSteps";
import { make, session } from "./referenceSteps";
import { putAway } from "./retiredSteps";
import { region } from "./structure";
import { expectClean, mark, signIn, test, watch } from "./support";

const suffix = mark("agent-admin-grant");
const madeAccounts: string[] = [];

test.afterAll(async ({ request, accounts }) => {
  await putAway(
    request,
    await session(request, await accounts.of("agent-admin-grant")),
    madeAccounts,
  );
});

test("review 4: Admin granted to a group that holds an agent is refused, the agent named as the group's", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 1280, height: 900 });
  const headers = await session(request, account);
  const sam = await makePerson(request, suffix, "sam", "inventory", madeAccounts);
  const agent = await makeAgent(request, headers, suffix, "bot", sam, "viewer", madeAccounts);
  const group = await make(request, headers, "/user-groups", { name: `${suffix}-ops` });
  const put = await request.put(
    `./api/v1/user-groups/${encodeURIComponent(group.hid)}/members/${encodeURIComponent(agent.hid)}`,
    { headers },
  );
  expect(put.ok(), `the agent is put in the group: ${await put.text()}`).toBe(true);
  const seen = await watch(page.context());
  await signIn(page, account);

  await page.goto("./admin/roles");
  const grant = region(page, "Grant a role");
  await grant.getByLabel("Role").selectOption({ label: "Admin" });
  await grant.getByRole("radio", { name: "A group" }).check();
  await grant.getByLabel("Group", { exact: true }).selectOption({ value: group.hid });
  await grant.getByRole("button", { name: "Grant role" }).click();
  await expect(grant).toContainText("never Admin");
  await expect(grant).not.toContainText("What runs on it");
  await expect(grant).toContainText("The agent in the group:");
  await expect(grant.getByRole("link", { name: agent.username })).toHaveAttribute(
    "href",
    new RegExp(`/admin/users/${agent.hid}$`),
  );
  await expectClean(page, seen, ["409 POST"]);
});
