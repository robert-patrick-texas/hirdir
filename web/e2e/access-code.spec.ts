// The browser scenarios of an access code made by the server, on the two forms where an
// Admin types one for somebody else, release 0.9.15 (P-300):
//
//   New user      Generate beside Access code puts a code the server made in the box; the
//                 person is made with it, shown once, and it signs them in.
//   A user's page Generate under Access code puts one in New access code; Reset access
//                 code sets it, shown once, and it signs the account in.
//
// Each code is at least as long as the setting `access_code_min_length` asks, read at its
// default, 12, which no file changes. They keep to the rules of support.ts: an account of
// their own, and the users they make with the file's mark in their names, disabled when
// the file ends.

import type { APIRequestContext, Locator } from "@playwright/test";
import { expect } from "@playwright/test";
import { type Headers, session } from "./referenceSteps";
import { region } from "./structure";
import { createAccount, expectClean, mark, signIn, test, watch } from "./support";

const suffix = mark("access-code");
const made: string[] = [];

test.describe.configure({ mode: "serial" });

test.afterAll(async ({ request, accounts }) => {
  const headers = await session(request, await accounts.of("access-code"));
  for (const hid of made) await disable(request, headers, hid);
});

/** Disable an account the file made: none is left that can sign in. */
async function disable(request: APIRequestContext, headers: Headers, hid: string) {
  const path = `./api/v1/users/${encodeURIComponent(hid)}`;
  const found = await request.get(path, { headers });
  const { row_version } = (await found.json()) as { row_version: number };
  const answer = await request.patch(path, { headers, data: { row_version, disabled: true } });
  expect(answer.status(), `${hid} is disabled`).toBe(200);
}

/**
 * Generate stands beside its box, level with it and a few pixels from its right edge;
 * at a phone's width it goes under the box (review of 0.9.15).
 */
async function besideItsBox(box: Locator, button: Locator, narrow = false) {
  const a = await box.boundingBox();
  const b = await button.boundingBox();
  if (!a || !b) throw new Error("the box or Generate is not drawn");
  if (narrow) {
    expect(b.y, "Generate is under the box").toBeGreaterThanOrEqual(a.y + a.height);
    return;
  }
  const gap = b.x - (a.x + a.width);
  expect(gap, "Generate is just right of the box").toBeGreaterThanOrEqual(0);
  expect(gap, "Generate is just right of the box").toBeLessThanOrEqual(16);
  expect(b.y, "Generate is level with the box").toBeLessThan(a.y + a.height);
  expect(b.y + b.height, "Generate is level with the box").toBeGreaterThan(a.y);
}

/** Whether a username signs in with a code, through the API. */
async function signsIn(request: APIRequestContext, username: string, code: string) {
  const answer = await request.post("./api/v1/auth/sign-in", {
    data: { username, access_code: code },
  });
  return answer.status();
}

test("New user: Generate puts a made code in the box, and the person is made with it", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(120_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  await page.goto("./admin/users");
  await page.getByRole("button", { name: "New user" }).click();
  const form = region(page, "New user");
  const username = `e2e-${suffix}-ren`;
  await form.getByLabel("Username (required)").fill(username);
  await form.getByRole("checkbox", { name: "Also a contact" }).uncheck();
  await form.getByLabel("Role").selectOption({ label: "View-only" });
  const box = form.getByLabel("Access code");
  await expect(box).toHaveValue("");
  await besideItsBox(box, form.getByRole("button", { name: "Generate", exact: true }));
  await expect(form).toContainText("Leave empty, or press Generate, to have one made.");
  await form.getByRole("button", { name: "Generate", exact: true }).click();
  await expect(box).not.toHaveValue("");
  const code = await box.inputValue();
  expect(code.length, "as long as the setting asks at the least").toBeGreaterThanOrEqual(12);

  await form.getByRole("button", { name: "Create user" }).click();
  const secret = page.getByRole("region", { name: `Access code for ${username}` });
  await expect(secret).toBeVisible();
  await expect(secret.getByLabel("Shown once")).toHaveValue(code);
  const link = page.getByTestId("user-made").getByRole("link", { name: username });
  made.push(decodeURIComponent((await link.getAttribute("href"))?.split("/").at(-1) ?? ""));
  expect(await signsIn(request, username, code), "the made code signs the person in").toBe(200);
  await expectClean(page, seen);
});

test("A user's page: Generate puts a made code in New access code, and Reset access code sets it", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(120_000);
  const user = await createAccount(request, `e2e-${suffix}-sol`, "viewer");
  made.push(user.hid);
  const seen = await watch(page.context());
  await signIn(page, account);
  await page.goto(`./admin/users/${encodeURIComponent(user.hid)}`);
  await expect(page.getByRole("heading", { level: 1, name: user.username })).toBeVisible();

  const section = region(page, "Access code");
  const box = section.getByLabel("New access code");
  const generate = section.getByRole("button", { name: "Generate", exact: true });
  await besideItsBox(box, generate);
  await page.setViewportSize({ width: 390, height: 800 });
  await besideItsBox(box, generate, true);
  await page.setViewportSize({ width: 1280, height: 720 });
  await section.getByRole("button", { name: "Generate", exact: true }).click();
  await expect(box).not.toHaveValue("");
  const code = await box.inputValue();
  expect(code.length, "as long as the setting asks at the least").toBeGreaterThanOrEqual(12);
  // Nothing is saved until Reset access code is pressed.
  expect(await signsIn(request, user.username, user.accessCode)).toBe(200);

  await section.getByRole("button", { name: "Reset access code" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Reset access code" }).click();
  const secret = page.getByTestId("secret-box");
  await expect(
    secret.getByRole("heading", { name: `New access code for ${user.username}` }),
  ).toBeVisible();
  await expect(secret.getByLabel("Shown once")).toHaveValue(code);
  expect(await signsIn(request, user.username, code), "the made code signs it in").toBe(200);
  await expectClean(page, seen);
});
