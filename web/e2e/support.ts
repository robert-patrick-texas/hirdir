// What the browser scenarios share: where the server is, the account and the names each
// spec file has of its own, and the watch for what no run may hold.
//
//   E2E_BASE_URL      where the app is served (default http://127.0.0.1:8715/)
//   E2E_USERNAME      an Admin
//   E2E_ACCESS_CODE   that Admin's access code
//   E2E_WORKERS       how many spec files run at once (default: as many as the host has
//                     free, see playwright.config.ts)
//
// The spec files run side by side, one worker to a file, against one server and in one
// inventory. The tests of one file run in order, in the one worker. A spec file is safe
// beside the others when it keeps to these rules, and a new one must:
//
//   1. Take `test` from this file, not from @playwright/test, and sign in with
//      `signIn(page, account)`. `account` is an Admin made for the file alone, by the
//      Admin of the environment, through the API, when the file's first test starts. The
//      Admin of the environment never signs in in a browser, and no file changes it.
//   2. Do to accounts only what it does to its own: a new access code, sessions ended,
//      a role granted or taken away and an account disabled all end the sessions or the
//      rights of every test that is signed in as that account. A file that needs a
//      second account makes it, in Admin → Users as shell.spec.ts does or with
//      `createAccount`, and names it with its mark.
//   3. Put `mark("<name of the file>")` in every name it gives a record: a vendor, a PID,
//      a host name, a serial number, an owner, a group, a network, a file it imports.
//      The mark holds the file's name, so no two files make the same name, and a random
//      part, so the file can be run again on the same server.
//   4. Read nothing that another file changes. No total of the whole inventory (Home, a
//      report with no filter) is compared with a number; a grid or a report is filtered
//      down to the file's own records before its rows are counted; and in a list that
//      every file writes to (the past imports, the users, the audit trail) the file
//      looks at its own rows, found by its mark or by its account, never at "the first
//      row". A paged list is searched or filtered for the row before the row is
//      expected on the page.
//   5. Change nothing that another file reads: the settings (items.spec.ts and
//      stack.spec.ts read the stack discount), the lists of choices and the lifecycle
//      rules (items.spec.ts, minor-items.spec.ts and stack.spec.ts move items, give
//      reasons and set conditions from them), and any record or account that is not
//      the file's own. Tests that have to change one of these cannot run beside the
//      others: say so here and in docs/architecture.md before writing them, and give
//      them a project of their own in playwright.config.ts that runs when the others
//      have ended.
//   6. Keep failed sign-ins few. They are counted for each address, and every worker
//      comes from the same one: after five in a row from all files together, every
//      sign-in is delayed (docs/architecture.md, "Throttling").
//   7. Hold only scenarios that build on one another. The files are what runs side by
//      side, and the run is as long as its longest file: scenarios that need nothing of
//      each other go in files of their own, each loading what it needs, as
//      minor-items.spec.ts, stack.spec.ts and wireless.spec.ts do with what they share
//      in structure.ts.

import { randomBytes } from "node:crypto";
import { basename } from "node:path";
import {
  type APIRequestContext,
  type APIResponse,
  type BrowserContext,
  test as base,
  expect,
  type Page,
} from "@playwright/test";

const adminName = process.env.E2E_USERNAME ?? "";
const adminCode = process.env.E2E_ACCESS_CODE ?? "";

/** An account that a spec file has of its own. */
export interface Account {
  hid: string;
  username: string;
  accessCode: string;
}

/**
 * The mark of one spec file on the names of what it makes, as in `items-3fa9c1`: the name
 * of the file, and a random part that a file may give when it needs it for itself.
 */
export function mark(file: string, random: string = randomBytes(3).toString("hex")): string {
  return `${file}-${random}`;
}

/**
 * The answer of the API, which must be the one expected. What the server said is told
 * only when it is not: a good answer may hold a token or an access code.
 */
async function answered(response: APIResponse, status: number, what: string): Promise<unknown> {
  if (response.status() !== status) {
    throw new Error(`${what}: ${response.status()} ${await response.text()}`);
  }
  return response.json();
}

/** What is sent to the API as the Admin of the environment, who signs in for it. */
async function asAdmin<T>(
  api: APIRequestContext,
  send: (headers: { Authorization: string }) => Promise<T>,
): Promise<T> {
  expect(adminName, "set E2E_USERNAME to an Admin").not.toBe("");
  expect(adminCode, "set E2E_ACCESS_CODE to that Admin's access code").not.toBe("");
  const session = (await answered(
    await api.post("./api/v1/auth/sign-in", {
      data: { username: adminName, access_code: adminCode },
    }),
    200,
    `${adminName}, the Admin of the environment, did not sign in`,
  )) as { token: string };
  return send({ Authorization: `Bearer ${session.token}` });
}

/**
 * Make an account through the API, as the Admin of the environment: `role` is admin,
 * inventory or viewer, or null for an account that holds no role.
 */
export async function createAccount(
  api: APIRequestContext,
  username: string,
  role: string | null,
): Promise<Account> {
  return asAdmin(api, async (headers) => {
    const created = (await answered(
      await api.post("./api/v1/users", {
        headers,
        data: { username, email: `${username}@example.org`, ...(role ? { role } : {}) },
      }),
      201,
      `the account ${username} was not made`,
    )) as { user: { hid: string; username: string }; access_code: string };
    return {
      hid: created.user.hid,
      username: created.user.username,
      accessCode: created.access_code,
    };
  });
}

/** Disable an account, which ends its sessions: a run leaves none behind that can sign in. */
async function disableAccount(api: APIRequestContext, account: Account): Promise<void> {
  await asAdmin(api, async (headers) => {
    const path = `./api/v1/users/${encodeURIComponent(account.hid)}`;
    const found = (await answered(
      await api.get(path, { headers }),
      200,
      `the account ${account.username} was not read`,
    )) as { row_version: number };
    await answered(
      await api.patch(path, { headers, data: { disabled: true, row_version: found.row_version } }),
      200,
      `the account ${account.username} was not disabled`,
    );
  });
}

interface Fixtures {
  /** The Admin that the spec file of the test has of its own. */
  account: Account;
}

interface WorkerFixtures {
  /** The accounts of the spec files a worker runs: one for each file, made when first asked for. */
  accounts: { of: (file: string) => Promise<Account> };
}

export const test = base.extend<Fixtures, WorkerFixtures>({
  accounts: [
    async ({ playwright }, use, workerInfo) => {
      // The requests are sent from here and not from a page: they are no part of what a
      // test watches. The API is beside the app, under the same prefix.
      const api = await playwright.request.newContext({
        baseURL: workerInfo.project.use.baseURL,
        ignoreHTTPSErrors: true,
      });
      const made = new Map<string, Promise<Account>>();
      await use({
        of(file) {
          let account = made.get(file);
          if (account === undefined) {
            account = createAccount(api, `e2e-${mark(file)}`, "admin");
            made.set(file, account);
          }
          return account;
        },
      });
      // The worker has run its files: their accounts are disabled.
      for (const account of await Promise.allSettled(made.values())) {
        if (account.status === "fulfilled") await disableAccount(api, account.value);
      }
      await api.dispose();
    },
    { scope: "worker" },
  ],
  account: async ({ accounts }, use, testInfo) => {
    await use(await accounts.of(basename(testInfo.file).replace(/\.spec\.ts$/, "")));
  },
});

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

/** Sign in on the first page, as the account the spec file has of its own. */
export async function signIn(page: Page, account: Account): Promise<void> {
  await page.goto("./");
  await expect(page.getByRole("heading", { level: 1, name: "Sign in to hirdir" })).toBeVisible();
  await page.getByLabel("Username").fill(account.username);
  await page.getByLabel("Access code").fill(account.accessCode);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
  await expect(page.locator(".who-name")).toHaveText(account.username);
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
