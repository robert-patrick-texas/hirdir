// The browser scenarios of release 0.9.17, P-314 (2) and (3): Show, on the list of
// users, offers Active users, every account that is not retired, a disabled one among
// them, beside Retired users, with the words above the grid that say so; and a token made
// for an account that holds no role says, where it is shown once, that it is refused
// until the account holds a role.
//
// They keep to the rules of support.ts: an account of the file's own, accounts and a
// group of its own with the file's mark in their names, and the accounts put away when
// the file ends.

import { expect } from "@playwright/test";
import { make, session } from "./referenceSteps";
import { change, openUser, putAway } from "./retiredSteps";
import { region } from "./structure";
import { createAccount, expectClean, mark, signIn, test, watch } from "./support";

const suffix = mark("users-active");
const madeAccounts: string[] = [];

test.beforeEach(async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
});

test.afterAll(async ({ request, accounts }) => {
  await putAway(request, await session(request, await accounts.of("users-active")), madeAccounts);
});

test("P-314: Show offers Active users, every account that is not retired, beside Retired users", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(120_000);
  const headers = await session(request, account);
  const [on, off, gone] = await Promise.all(
    ["on", "off", "gone"].map((key) => createAccount(request, `e2e-${suffix}-${key}`, "viewer")),
  );
  if (!on || !off || !gone) throw new Error("the accounts were not made");
  madeAccounts.push(on.hid, off.hid, gone.hid);
  await change(request, headers, "patch", `/users/${off.hid}`, { disabled: true });
  await change(request, headers, "post", `/users/${gone.hid}/retire`);
  const seen = await watch(page.context());
  await signIn(page, account);

  await page.goto(`./admin/users?q=${encodeURIComponent(suffix)}`);
  const show = page.getByRole("navigation", { name: "Show users" });
  const active = show.getByRole("link", { name: "Active users", exact: true });
  await expect(active).toHaveAttribute("aria-current", "page");
  await expect(show.getByRole("link", { name: "Every user" })).toHaveCount(0);
  await expect(
    page.getByText("Active users are every account that is not retired, those disabled among them"),
  ).toBeVisible();
  const rows = page.getByTestId("users").locator("tbody tr[data-user]");
  const row = (name: string) => rows.and(page.locator(`[data-user="${name}"]`));
  await expect(rows).toHaveCount(2);
  await expect(row(on.username).getByTestId("user-state")).toHaveText("Active");
  await expect(row(off.username).getByTestId("user-state")).toHaveText("Disabled");
  await expect(row(gone.username)).toHaveCount(0);

  // Retired users, and back: the link keeps the search.
  await show.getByRole("link", { name: "Retired users", exact: true }).click();
  await expect(rows).toHaveCount(1);
  await expect(row(gone.username)).toBeVisible();
  await active.click();
  await expect(page).not.toHaveURL(/[?&]retired=/);
  await expect(page).toHaveURL(new RegExp(`[?&]q=${suffix}`));
  await expect(rows).toHaveCount(2);
  await expectClean(page, seen);
});

test("P-314: a token made for an account that holds no role says it is refused until it holds one", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(120_000);
  const headers = await session(request, account);
  const group = await make(request, headers, "/user-groups", { name: `${suffix}-readers` });
  await make(request, headers, "/role-grants", { group_hid: group.hid, role: "viewer" });
  const service = async (key: string, role: string | null) => {
    const answer = await request.post("./api/v1/users", {
      headers,
      data: {
        username: `e2e-${suffix}-${key}`,
        is_service_account: true,
        ...(role ? { role } : {}),
      },
    });
    expect(answer.status(), `post /users: ${await answer.text()}`).toBe(201);
    const made = (await answer.json()) as { user: { hid: string; username: string } };
    madeAccounts.push(made.user.hid);
    return made.user;
  };
  const bare = await service("bare", null);
  const reader = await service("reader", "viewer");
  const seen = await watch(page.context());
  await signIn(page, account);

  // Made with no role: the token is shown once, with the words that it waits for one.
  await openUser(page, bare);
  const tokens = region(page, "Service tokens");
  await tokens.getByLabel("Name (required)").fill(`${suffix}-sync`);
  await tokens.getByRole("button", { name: "Create token" }).click();
  const secret = page.getByTestId("secret-box");
  await expect(
    secret.getByRole("heading", { name: `Token ${suffix}-sync for ${bare.username}` }),
  ).toBeVisible();
  const waits = secret.getByText(
    `${bare.username} holds no role, so this token is refused until it holds one`,
  );
  await expect(waits).toBeVisible();
  // Put in a group that grants View-only, on the same page: the token works now, and the
  // words go, the token still on show.
  await region(page, "Groups")
    .getByRole("checkbox", { name: `${suffix}-readers` })
    .check();
  await expect(page.getByTestId("user-facts")).toContainText("View-only");
  await expect(waits).toHaveCount(0);
  await expect(secret.getByRole("textbox")).not.toHaveValue("");

  // An account that holds a role is told nothing of it.
  await openUser(page, reader);
  await tokens.getByLabel("Name (required)").fill(`${suffix}-read`);
  await tokens.getByRole("button", { name: "Create token" }).click();
  await expect(
    secret.getByRole("heading", { name: `Token ${suffix}-read for ${reader.username}` }),
  ).toBeVisible();
  await expect(secret).not.toContainText("holds no role");
  await expectClean(page, seen);
});
