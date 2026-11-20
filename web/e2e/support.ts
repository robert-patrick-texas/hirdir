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
//      the file's own. The capacity report is of the whole installation: capacity.spec.ts
//      is the one file that writes capacity lines and reads that report, and it compares
//      one reading of the report with another, never a reading with a number; a second
//      file that wrote a capacity line, or changed `weight_per_resource_unit`, could not
//      run beside it. Tests that have to change one of these cannot run beside the
//      others: say so here and in docs/architecture.md before writing them, and give
//      them a project of their own in playwright.config.ts that runs when the others
//      have ended. stale-term.spec.ts is one: it makes a day come by changing the
//      `time_zone` setting, which says what today is for every file, and puts it back.
//      It runs in the project "after the others", which waits for the files of every
//      browser to end, and which Playwright does not run at all when one of them
//      failed; scripts/browser.sh runs each such project with --no-deps, after the
//      others, whatever failed before. A file whose
//      changes are large enough to hold the database's one writer for seconds, as
//      cover-many.spec.ts does with a thousand rows at once, cannot run beside the
//      others either: a sign-in or a save of another file that waits longer than the
//      server's `busy_timeout` is answered Busy. It runs in the project "the writer
//      alone", after the files of every browser and before "after the others".
//   6. Keep failed sign-ins few. They are counted for each address, and every worker
//      comes from the same one: after five in a row from all files together, every
//      sign-in is delayed (docs/architecture.md, "Throttling").
//   7. Hold only scenarios that build on one another. The files are what runs side by
//      side, and the run is as long as its longest file: scenarios that need nothing of
//      each other go in files of their own, each loading what it needs, as
//      minor-items.spec.ts, stack.spec.ts and wireless.spec.ts do with what they share
//      in structure.ts, and the three geography files with what they share in
//      geographySteps.ts.

// 0.7.0, the renewal alert (P-128): whether the banner shows depends on every contract
// of the inventory, so renewal-alert.spec.ts reads what every other file changes, which
// rule 4 forbids beside them. It runs in the project "the alert alone" of
// playwright.config.ts, by itself, after "after the others". Every other file may find
// the banner on its pages, as an account of its own has seen nothing: it is a region
// named "Renewals to act on", and a file looks within its own regions, as it does.

// 0.8.0, the support weight (P-139, P-141, P-155 to P-157): weights.spec.ts sets the six
// defaults and minimums of support weight, which every count of a weight reads (the
// summary, the scoreboard, a vendor's portfolio, an item's page and the capacity report),
// writes staff lines and reads the capacity report, which rule 5 leaves to
// capacity.spec.ts alone, and checks the kept reports, which a change of any other file
// sets aside. It runs in the project "the weights alone" of playwright.config.ts, by
// itself, after "the alert alone"; it notes each setting as it found it and puts it back
// when it ends, and retires the staff lines and the places it made. circuit-costs.spec.ts
// makes circuits with cost lines of its own, filters the report down to them, and runs
// beside the others.

// 0.9.2, the product name and whom to ask (P-168, P-169): product.spec.ts sets
// `product_name`, which the title of every page, the heading of the sign-in page that
// `signIn` looks for and the name of every file that any other file downloads read, and
// the five settings of whom to ask, which the sign-in page lists. It runs in the project
// "the name alone" of playwright.config.ts, by itself, after "the weights alone"; it notes
// each of the six settings as it found them and puts them back however it ends. Every
// other file finds the product named hirdir, its default. menu-bar.spec.ts (P-167)
// changes nothing and runs beside the others.

// 0.9.10, the ceiling (P-265): the scenarios drive the server as hard as the host
// allows, which is what the ceiling is there to refuse, so a run has none. Each worker
// sets `busy_response_ms` and `busy_cpu_percent` to 0 where they are not, as the Admin
// of the environment, before it makes the account of its first file: `withoutCeiling`,
// below. No file but one changes the three settings of the ceiling. busy.spec.ts sets a
// ceiling that any request is past and makes load until the reads are refused, which
// every request of every other file would feel. It runs in the project "the ceiling
// alone" of playwright.config.ts, by itself, after "the name alone"; it notes the three
// settings as it found them and puts them back however it ends. about-load.spec.ts
// reads the server's measures on About and health-mark.spec.ts the mark of health in the
// menu bar (P-270); they change nothing and run beside the others: the health and the
// measures are of the whole server, so neither compares a word or a number of them with
// another. A file that counts on what its page answers may find the mark on it: it is
// in the menu bar, of the test id health-mark, and asks the server nothing.

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

/** A new person, the contact a new account is made with (P-172). */
export interface NewPerson {
  name: string;
  email?: string;
  phone?: string;
  phone2?: string;
}

/**
 * Make an account through the API, as the Admin of the environment: `role` is admin,
 * inventory or viewer, or null for an account that holds no role. 0.9.3: an account is
 * made with no contact, and is shown by its username, unless a file gives it a person,
 * a new contact made with it (P-172).
 */
export async function createAccount(
  api: APIRequestContext,
  username: string,
  role: string | null,
  person?: NewPerson,
): Promise<Account> {
  return asAdmin(api, async (headers) => {
    const created = (await answered(
      await api.post("./api/v1/users", {
        headers,
        data: { username, ...(role ? { role } : {}), ...(person ? { contact: person } : {}) },
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

/** The settings of the ceiling that a run turns off: at 0 a measure is not looked at (P-265). */
const CEILING = ["busy_response_ms", "busy_cpu_percent"];

/**
 * Turn the ceiling off for the run, as the Admin of the environment: the scenarios
 * drive the server hard, and a list answered "busy" is no fault of what they test. A
 * setting that is 0 already is left alone, so a second worker changes nothing; where
 * two workers set one at the same moment, the one refused reads again and finds it done.
 */
async function withoutCeiling(api: APIRequestContext): Promise<void> {
  await asAdmin(api, async (headers) => {
    for (let attempt = 0; attempt < 5; attempt += 1) {
      const settings = (await answered(
        await api.get("./api/v1/settings", { headers }),
        200,
        "the settings were not read",
      )) as Array<{ key: string; value: unknown; row_version: number }>;
      const inForce = settings.filter((one) => CEILING.includes(one.key) && one.value !== 0);
      if (inForce.length === 0) return;
      for (const one of inForce) {
        const response = await api.put(`./api/v1/settings/${one.key}`, {
          headers,
          data: { row_version: one.row_version, value: 0 },
        });
        if (response.status() !== 200 && response.status() !== 409) {
          throw new Error(`${one.key} was not set to 0: ${response.status()}`);
        }
      }
    }
    throw new Error("the ceiling was not turned off: its settings kept changing");
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
      // 0.9.10: no ceiling while the scenarios run (P-265).
      await withoutCeiling(api);
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

/**
 * Sign in on the first page, as the account the spec file has of its own. The page names
 * the product hirdir unless the file has named it otherwise, as product.spec.ts does.
 */
export async function signIn(page: Page, account: Account, product = "hirdir"): Promise<void> {
  await page.goto("./");
  await expect(
    page.getByRole("heading", { level: 1, name: `Sign in to ${product}`, exact: true }),
  ).toBeVisible();
  await page.getByLabel("Username").fill(account.username);
  await page.getByLabel("Access code").fill(account.accessCode);
  await page.getByRole("button", { name: "Sign in" }).click();
  // The access code is hashed at its full cost, on purpose: on a busy host that takes
  // longer than the 5 seconds an expectation waits by default.
  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible({ timeout: 20_000 });
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
