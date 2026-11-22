// The browser scenarios of release 0.9.17, P-307 and P-314 (4): a user's page says each
// role the account holds and where it comes from, of its own or through which group, a
// link, beside the highest, and the list of users says the same; and before an Admin
// revokes an account's own grant, takes it out of a group, revokes a group's grant or
// deletes a group, the confirmation says whom the change leaves with no role, that each
// is signed out at once, from the roles and where they come from.
//
// They keep to the rules of support.ts: an account of the file's own, accounts and groups
// of its own with the file's mark in their names, and the accounts put away when the file
// ends. None of the accounts it makes signs in.

import { expect, type Page } from "@playwright/test";
import { make, session } from "./referenceSteps";
import { openUser, putAway, read } from "./retiredSteps";
import { region } from "./structure";
import { createAccount, expectClean, mark, signIn, test, watch } from "./support";

const suffix = mark("roles-from");
const madeAccounts: string[] = [];

test.beforeEach(async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
});

test.afterAll(async ({ request, accounts }) => {
  await putAway(request, await session(request, await accounts.of("roles-from")), madeAccounts);
});

/** The open dialog of the page: a closed one is not on show. */
function asked(page: Page) {
  return page.getByRole("dialog");
}

interface Held {
  role: string | null;
  grants: Array<{ hid: string; role: string; group: { hid: string; name: string } | null }>;
}

test("P-307: a user's page, and the list, say each role it holds and where it comes from", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(120_000);
  const headers = await session(request, account);
  const teamName = `${suffix}-team`;
  const team = await make(request, headers, "/user-groups", { name: teamName });
  await make(request, headers, "/role-grants", { group_hid: team.hid, role: "inventory" });
  const kim = await createAccount(
    request,
    `e2e-${suffix}-kim`,
    "viewer",
    { name: `Kim Example ${suffix}` },
    [team.hid],
  );
  madeAccounts.push(kim.hid);
  const seen = await watch(page.context());
  await signIn(page, account);

  // The highest, and beneath it each role and from where, the highest first.
  await openUser(page, kim);
  const role = page.getByTestId("user-role");
  await expect(role).toContainText("Inventory");
  const sources = page.getByTestId("role-sources").getByRole("listitem");
  await expect(sources).toHaveCount(2);
  await expect(sources.nth(0)).toHaveText(`Inventory, through ${teamName}`);
  await expect(sources.nth(0).getByRole("link", { name: teamName })).toHaveAttribute(
    "href",
    new RegExp(`/admin/groups/${team.hid}$`),
  );
  await expect(sources.nth(1)).toContainText("View-only, of its own");
  // A grant of its own is revoked here; a group's is not.
  await expect(sources.nth(1).getByRole("button", { name: "Revoke View-only" })).toBeVisible();
  await expect(sources.nth(0).getByRole("button")).toHaveCount(0);

  // The list says the same, the group a link.
  await page.goto(`./admin/users?q=${encodeURIComponent(kim.username)}`);
  const cell = page
    .getByTestId("users")
    .locator(`tbody tr[data-user="${kim.username}"]`)
    .getByTestId("user-role");
  await expect(cell).toContainText("Inventory");
  await expect(cell).toContainText(`Inventory through ${teamName}; View-only of its own`);
  await expect(cell.getByRole("link", { name: teamName })).toHaveAttribute(
    "href",
    new RegExp(`/admin/groups/${team.hid}$`),
  );
  await expectClean(page, seen);
});

test("P-314: a change that takes the last role from an account says so before, and one that does not says nothing", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(180_000);
  const headers = await session(request, account);
  const onlyName = `${suffix}-only`;
  const only = await make(request, headers, "/user-groups", { name: onlyName });
  await make(request, headers, "/role-grants", { group_hid: only.hid, role: "viewer" });
  const person = (key: string) => ({ name: `${key} Example ${suffix}` });
  // Through the group alone; of its own and through the group; of its own alone.
  const lee = await createAccount(request, `e2e-${suffix}-lee`, null, person("Lee"), [only.hid]);
  const mia = await createAccount(request, `e2e-${suffix}-mia`, null, person("Mia"), [only.hid]);
  const both = await createAccount(request, `e2e-${suffix}-both`, "viewer", person("Bo"), [
    only.hid,
  ]);
  const own = await createAccount(request, `e2e-${suffix}-own`, "viewer", person("Ova"));
  madeAccounts.push(lee.hid, mia.hid, both.hid, own.hid);
  const seen = await watch(page.context());
  await signIn(page, account);

  // The box of the one group that gives lee a role asks first, and Cancel changes nothing.
  await openUser(page, lee);
  const box = region(page, "Groups").getByRole("checkbox", { name: onlyName });
  // Pressed, it asks first: the box stays as it is until the change is confirmed.
  await box.click();
  await expect(asked(page)).toContainText(`Take ${lee.username} out of ${onlyName}?`);
  await expect(asked(page).getByTestId("no-role-left")).toHaveText(
    `${lee.username} will hold no role and be signed out.`,
  );
  await asked(page).getByRole("button", { name: "Cancel" }).click();
  await expect(asked(page)).toHaveCount(0);
  await expect(box).toBeChecked();
  expect((await read<Held>(request, headers, `/users/${lee.hid}`)).role).toBe("viewer");
  // Taken out when it is confirmed.
  await box.click();
  await asked(page)
    .getByRole("button", { name: `Take ${lee.username} out` })
    .click();
  await expect(box).not.toBeChecked();
  await expect(page.getByTestId("user-role")).toContainText("No role");
  expect((await read<Held>(request, headers, `/users/${lee.hid}`)).role).toBeNull();

  // A grant of its own revoked where a group still gives a role: nothing said of it.
  await openUser(page, both);
  await page.getByRole("button", { name: "Revoke View-only" }).click();
  await expect(asked(page)).toContainText(`Take View-only back from ${both.username}?`);
  await expect(asked(page).getByTestId("no-role-left")).toHaveCount(0);
  await asked(page).getByRole("button", { name: "Cancel" }).click();
  // Where it is the only one, it is said.
  await openUser(page, own);
  await page.getByRole("button", { name: "Revoke View-only" }).click();
  await expect(asked(page).getByTestId("no-role-left")).toHaveText(
    `${own.username} will hold no role and be signed out.`,
  );
  await asked(page).getByRole("button", { name: "Cancel" }).click();
  expect((await read<Held>(request, headers, `/users/${own.hid}`)).role).toBe("viewer");

  // On the group's page: its grant revoked names mia, not both, who keeps a role.
  await page.goto(`./admin/groups/${encodeURIComponent(only.hid)}`);
  await expect(page.getByRole("heading", { level: 1, name: onlyName })).toBeVisible();
  const grants = region(page, "Roles it grants");
  await grants.getByRole("button", { name: "Revoke View-only" }).click();
  await expect(asked(page).getByTestId("no-role-left")).toHaveText(
    `${mia.username} will hold no role and be signed out.`,
  );
  await asked(page).getByRole("button", { name: "Cancel" }).click();
  // Remove asks first of mia, and takes both out at once.
  const members = region(page, "Members");
  await members.getByRole("button", { name: `Remove ${mia.username}` }).click();
  await expect(asked(page).getByTestId("no-role-left")).toHaveText(
    `${mia.username} will hold no role and be signed out.`,
  );
  await asked(page).getByRole("button", { name: "Cancel" }).click();
  await members.getByRole("button", { name: `Remove ${both.username}` }).click();
  await expect(asked(page)).toHaveCount(0);
  await expect(page.getByText(`${both.username} was removed from ${onlyName}.`)).toBeVisible();
  await expect(members.getByRole("link", { name: both.username })).toHaveCount(0);
  // Deleting the group says it too.
  await region(page, "Delete").getByRole("button", { name: "Delete group" }).click();
  await expect(asked(page).getByTestId("no-role-left")).toHaveText(
    `${mia.username} will hold no role and be signed out.`,
  );
  await asked(page).getByRole("button", { name: "Cancel" }).click();

  // Under Roles, the group's grant says it as well.
  await page.goto("./admin/roles");
  const row = page.locator("tbody tr").filter({ hasText: onlyName });
  await row.getByRole("button", { name: "Revoke" }).click();
  await expect(asked(page).getByTestId("no-role-left")).toHaveText(
    `${mia.username} will hold no role and be signed out.`,
  );
  await asked(page).getByRole("button", { name: "Cancel" }).click();
  expect((await read<Held>(request, headers, `/users/${mia.hid}`)).role).toBe("viewer");
  await expectClean(page, seen);
});
