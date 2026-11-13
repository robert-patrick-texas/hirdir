// What the browser scenarios share: who signs in, and the watch for what no run may hold.
//
//   E2E_BASE_URL      where the app is served (default http://127.0.0.1:8715/)
//   E2E_USERNAME      an Admin
//   E2E_ACCESS_CODE   that Admin's access code

import { type BrowserContext, expect, type Page } from "@playwright/test";

export const username = process.env.E2E_USERNAME ?? "";
export const accessCode = process.env.E2E_ACCESS_CODE ?? "";

export interface Watch {
  cookies: string[];
  console: string[];
  violations: string[];
  failures: string[];
  pending: Promise<void>[];
}

/** Record everything a run must be free of, on every page of the context. */
export async function watch(context: BrowserContext): Promise<Watch> {
  const seen: Watch = { cookies: [], console: [], violations: [], failures: [], pending: [] };
  context.on("response", (response) => {
    seen.pending.push(
      response
        .headersArray()
        .then((headers) => {
          for (const header of headers) {
            if (header.name.toLowerCase() === "set-cookie") {
              seen.cookies.push(`${response.url()}: ${header.value}`);
            }
          }
        })
        .catch(() => {
          // The page moved on before the headers were read: nothing to record.
        }),
    );
    if (response.status() >= 400) {
      seen.failures.push(`${response.status()} ${response.request().method()} ${response.url()}`);
    }
  });
  context.on("console", (message) => {
    if (message.type() === "error" || /content security policy/i.test(message.text())) {
      seen.console.push(`${message.type()}: ${message.text()}`);
    }
  });
  context.on("weberror", (error) => {
    seen.console.push(`uncaught: ${error.error().message}`);
  });
  await context.exposeFunction("__reportViolation", (text: string) => {
    seen.violations.push(text);
  });
  await context.addInitScript(() => {
    document.addEventListener("securitypolicyviolation", (event) => {
      const report = (window as unknown as { __reportViolation: (text: string) => void })
        .__reportViolation;
      report(`${event.violatedDirective} blocked ${event.blockedURI || "inline"}`);
    });
  });
  return seen;
}

/** Sign in on the first page, as the Admin the environment names. */
export async function signIn(page: Page): Promise<void> {
  expect(username, "set E2E_USERNAME to an Admin").not.toBe("");
  expect(accessCode, "set E2E_ACCESS_CODE to that Admin's access code").not.toBe("");
  await page.goto("./");
  await expect(page.getByRole("heading", { level: 1, name: "Sign in to hirdir" })).toBeVisible();
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Access code").fill(accessCode);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
  await expect(page.locator(".who-name")).toHaveText(username);
}

/**
 * No cookie was set, nothing was blocked by the content security policy, and nothing
 * went wrong but the refusals the scenario asked for, each named as `409 PATCH`.
 */
export async function expectClean(page: Page, seen: Watch, refusals: string[] = []): Promise<void> {
  await Promise.all(seen.pending);
  expect(seen.cookies, "responses that set a cookie").toEqual([]);
  expect(await page.evaluate(() => document.cookie)).toBe("");
  expect(await page.context().cookies()).toEqual([]);
  expect(seen.violations, "content security policy violations").toEqual([]);
  expect(
    seen.failures.map((failure) => failure.split(" ").slice(0, 2).join(" ")),
    `failed requests: ${seen.failures.join(", ")}`,
  ).toEqual(refusals);
  // Some browsers report each refused request on the console as well. Nothing else may be there.
  const unexpected = seen.console.filter((line) => !/Failed to load resource/.test(line));
  expect(unexpected, "console errors").toEqual([]);
  expect(seen.console.length, "refusals on the console").toBeLessThanOrEqual(refusals.length);
}
