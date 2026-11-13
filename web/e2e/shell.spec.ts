// The browser scenario of release 0.1.0: sign in, find the session in localStorage and no
// cookie anywhere, create a user, survive a reload of a deep link, sign out.
//
// The environment that names the server and the Admin is described in support.ts.
//
// Every address below is relative to the base URL, so the same test runs at the root
// and under a prefix.

import { randomBytes } from "node:crypto";
import { expect, type Page, test } from "@playwright/test";
import { accessCode, expectClean, username, watch } from "./support";

function sessionOf(page: Page): Promise<{ token?: unknown; expires_at?: unknown } | null> {
  return page.evaluate(() => {
    const raw = window.localStorage.getItem("hirdir.session");
    return raw === null ? null : JSON.parse(raw);
  });
}

test("sign in, create a user, reload a deep link, sign out", async ({ page, baseURL }) => {
  expect(username, "set E2E_USERNAME to an Admin").not.toBe("");
  expect(accessCode, "set E2E_ACCESS_CODE to that Admin's access code").not.toBe("");
  expect(baseURL).toBeTruthy();
  const base = new URL(baseURL ?? "");
  const seen = await watch(page.context());

  // Nothing but the sign-in page is shown without a session.
  await page.goto("./");
  await expect(page.getByRole("heading", { level: 1, name: "Sign in to hirdir" })).toBeVisible();
  await expect(page.getByRole("navigation")).toHaveCount(0);
  expect(await sessionOf(page)).toBeNull();

  // The page knows the prefix it is served under.
  expect(new URL(await page.evaluate(() => document.baseURI)).pathname).toBe(base.pathname);

  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Access code").fill(accessCode);
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
  await expect(page.locator(".who-name")).toHaveText(username);
  const session = await sessionOf(page);
  expect(typeof session?.token).toBe("string");
  expect(String(session?.token).length).toBeGreaterThan(20);
  expect(Date.parse(String(session?.expires_at))).toBeGreaterThan(Date.now());

  // Admin → Users.
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Admin" }).click();
  await page
    .getByRole("navigation", { name: "Admin" })
    .getByRole("link", { name: "Users" })
    .click();
  await expect(page.getByRole("heading", { level: 1, name: "Users" })).toBeVisible();
  const usersPath = `${base.pathname}admin/users`;
  expect(new URL(page.url()).pathname).toBe(usersPath);

  // Create a user with a random, made-up name. The access code is shown once.
  const suffix = randomBytes(4).toString("hex");
  const newUser = `e2e-quill-${suffix}`;
  await page.getByRole("button", { name: "New user" }).click();
  const form = page.getByRole("region", { name: "New user" });
  await form.getByLabel("Username").fill(newUser);
  await form.getByLabel("Display name").fill(`Quill Example ${suffix}`);
  await form.getByLabel("Email").fill(`${newUser}@example.org`);
  await form.getByRole("button", { name: "Create user" }).click();

  const secret = page.getByRole("region", { name: `Access code for ${newUser}` });
  await expect(secret).toBeVisible();
  await expect(secret).toContainText("It will not be shown again");
  const code = await secret.getByLabel("Shown once").inputValue();
  expect(code.length).toBeGreaterThanOrEqual(8);
  await expect(secret.getByRole("button", { name: "Copy" })).toBeVisible();
  await expect(page.getByRole("rowheader", { name: newUser })).toBeVisible();

  // Reload the deep link: the same page comes back, still signed in, the code gone.
  await page.reload();
  await expect(page.getByRole("heading", { level: 1, name: "Users" })).toBeVisible();
  expect(new URL(page.url()).pathname).toBe(usersPath);
  await expect(page.locator(".who-name")).toHaveText(username);
  await expect(page.getByRole("rowheader", { name: newUser })).toBeVisible();
  await expect(page.getByText(code, { exact: true })).toHaveCount(0);
  await expect(page.getByRole("region", { name: `Access code for ${newUser}` })).toHaveCount(0);
  expect((await sessionOf(page))?.token).toBe(session?.token);

  // Open the deep link afresh, as from a bookmark.
  await page.goto("./admin/users");
  await expect(page.getByRole("heading", { level: 1, name: "Users" })).toBeVisible();

  // Sign out: the sign-in page returns and the session is gone.
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Sign in to hirdir" })).toBeVisible();
  await expect(page.getByRole("navigation")).toHaveCount(0);
  expect(await sessionOf(page)).toBeNull();
  expect(new URL(page.url()).pathname).toBe(base.pathname);

  // No cookie was set by any response and none exists, nothing was blocked by the content
  // security policy, and nothing went wrong.
  await expectClean(page, seen);
});
