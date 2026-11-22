// A browser scenario of release 0.9.17, from the review of the web (review 3): an agent
// put in a group that grants Admin, by Add on the group's page, is refused in the
// server's words, at the member chosen, with no name of a field before them (P-316).
//
// It keeps to the rules of support.ts: an account of the file's own, a person, an agent
// and a group of its own with the file's mark in their names, and the accounts put away
// when the file ends. The group grants Admin and holds nobody.

import { expect } from "@playwright/test";
import { makeAgent, makePerson } from "./agentSteps";
import { make, session } from "./referenceSteps";
import { putAway } from "./retiredSteps";
import { region } from "./structure";
import { expectClean, mark, signIn, test, watch } from "./support";

const suffix = mark("agent-group-add");
const madeAccounts: string[] = [];

test.afterAll(async ({ request, accounts }) => {
  await putAway(
    request,
    await session(request, await accounts.of("agent-group-add")),
    madeAccounts,
  );
});

test("review 3: an agent added to a group that grants Admin is refused in the server's words, at the member", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 1280, height: 900 });
  const headers = await session(request, account);
  const sam = await makePerson(request, suffix, "sam", "inventory", madeAccounts);
  const agent = await makeAgent(request, headers, suffix, "bot", sam, "viewer", madeAccounts);
  const group = await make(request, headers, "/user-groups", { name: `${suffix}-admins` });
  await make(request, headers, "/role-grants", { group_hid: group.hid, role: "admin" });
  const seen = await watch(page.context());
  await signIn(page, account);

  await page.goto(`./admin/groups/${encodeURIComponent(group.hid)}`);
  const members = region(page, "Members");
  await members.getByLabel("Add a member").selectOption({ value: agent.hid });
  await members.getByRole("button", { name: "Add", exact: true }).click();
  await expect(members).toContainText("never Admin");
  await expect(members.getByLabel("Add a member")).toHaveAttribute("aria-invalid", "true");
  await expect(page.getByRole("main")).not.toContainText("user_hid");
  await expect(members.getByRole("link", { name: agent.username })).toHaveCount(0);
  await expectClean(page, seen, ["409 PUT"]);
});
