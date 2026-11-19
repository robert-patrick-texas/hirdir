// The browser scenario of a server past its ceiling, of 0.9.10 (P-262, P-265, P-266):
//
//   An Admin sets the ceiling to the smallest values it takes, and requests keep the
//   server past it. A list then says that the server is busy and to try again in five
//   seconds, in the page's own words, with its button Try again; so do a report and the
//   first page, each refusal with a Try again of its own; and none of them is a page
//   that could not be drawn. About still answers: it says that the server is busy and by
//   which measure, with the ceiling in force, counts the answers of busy, and marks on
//   its graph the steps in which they were given. A save still goes through: the Admin
//   sets one measure of the ceiling to 0 on the Settings page, which a busy server still
//   shows. With the ceiling put back, one press of Try again loads the list and takes
//   every refusal off the page; past the ceiling once more and back, one press under a
//   refusal of the scoreboard fills its tables. About then says the server is not busy,
//   the marks of when it was still on its graph.
//
// How this file keeps to rule 5 of support.ts: it changes `busy_response_ms`,
// `busy_cpu_percent` and `busy_over_seconds`, which every request of every file feels,
// and keeps the server past them. So it runs in the project "the ceiling alone" of
// playwright.config.ts, by itself, when every other project has ended. It notes the
// three settings as it found them, and puts them back however it ends. The requests that
// keep the server busy are real ones, of its own account, for the settings: a route a
// busy server always answers, so each is answered and measured.

import { type APIRequestContext, expect, type Page } from "@playwright/test";
import { type Account, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const suffix = mark("busy");
const vendor = `Example Networks ${suffix}`;
const pid = `EN-B-24-${suffix}`;
const hostname = `site7-sw-${suffix}`;
const list = `./items?filter=${encodeURIComponent(`hostname:eq:${hostname}`)}`;

const BUSY = "The server is busy and did not answer this. Try again in 5 seconds.";
// The smallest values the settings take: any request takes longer than a millisecond,
// and a server that answers ten a second uses more than a hundredth of a processor.
const LOWEST = { busy_over_seconds: 5, busy_response_ms: 1, busy_cpu_percent: 1 } as const;
const SETTINGS = Object.keys(LOWEST) as Array<keyof typeof LOWEST>;

type Headers = { Authorization: string };

/** Sign in through the API as the account of the file, for what is done there. */
async function session(request: APIRequestContext, account: Account): Promise<Headers> {
  const answer = await request.post("./api/v1/auth/sign-in", {
    data: { username: account.username, access_code: account.accessCode },
  });
  expect(answer.status(), "the account of the file signs in through the API").toBe(200);
  const { token } = (await answer.json()) as { token: string };
  return { Authorization: `Bearer ${token}` };
}

async function send<T = { hid: string }>(
  request: APIRequestContext,
  headers: Headers,
  method: "post" | "put",
  path: string,
  data: unknown,
  status = method === "post" ? 201 : 200,
): Promise<T> {
  const answer = await request[method](`./api/v1${path}`, { headers, data });
  expect(answer.status(), `${method} ${path}: ${await answer.text()}`).toBe(status);
  return (await answer.json()) as T;
}

async function read<T>(request: APIRequestContext, headers: Headers, path: string): Promise<T> {
  const answer = await request.get(`./api/v1${path}`, { headers });
  expect(answer.status(), `get ${path}`).toBe(200);
  return (await answer.json()) as T;
}

interface Setting {
  key: string;
  value: unknown;
  is_default: boolean;
  row_version: number;
}

async function setting(request: APIRequestContext, headers: Headers, key: string) {
  const all = await read<Setting[]>(request, headers, "/settings");
  const found = all.find((one) => one.key === key);
  if (!found) throw new Error(`there is no setting ${key}`);
  return found;
}

/** Give a setting a value, or its default for null. */
async function put(request: APIRequestContext, headers: Headers, key: string, value: unknown) {
  const { row_version } = await setting(request, headers, key);
  await send(request, headers, "put", `/settings/${key}`, { row_version, value });
}

/** Whether the server says it is busy: `ok`, `busy` or `very_busy`. */
async function stateOf(request: APIRequestContext, headers: Headers): Promise<string> {
  return (await read<{ state: string }>(request, headers, "/about/load")).state;
}

/**
 * Keep the server answering: ten requests a second for the settings, which a busy server
 * always answers, so that each is measured. Returns the means to stop, which waits for
 * those that are out.
 */
function drive(request: APIRequestContext, headers: Headers): () => Promise<void> {
  const out = new Set<Promise<unknown>>();
  const timer = setInterval(() => {
    const one = request.get("./api/v1/settings", { headers }).catch(() => undefined);
    out.add(one);
    void one.finally(() => out.delete(one));
  }, 100);
  return async () => {
    clearInterval(timer);
    await Promise.all(out);
  };
}

/** Try again beneath the refusal of the rows of a list. */
function listAgain(page: Page) {
  return page.locator("main .grid-retry").getByRole("button", { name: "Try again", exact: true });
}

/** Try again within the refusal of any other read of a page. */
function readAgain(page: Page) {
  return page.locator("main .alert-error").getByRole("button", { name: "Try again", exact: true });
}

/**
 * Every refusal the page shows is the words of a busy server, there is one at least, and
 * each has its Try again: within it, or beneath it for the rows of a list.
 */
async function saysBusy(page: Page, where: string): Promise<void> {
  const refusals = page.locator("main .alert-error");
  const words = page.locator("main .alert-error > p:first-child");
  await expect(words.first(), where).toHaveText(BUSY, { timeout: 15_000 });
  await expect(async () => {
    for (const text of await words.allTextContents()) expect(text, where).toBe(BUSY);
    const buttons = (await readAgain(page).count()) + (await listAgain(page).count());
    expect(buttons, `${where}: a Try again for each refusal`).toBe(await refusals.count());
  }).toPass({ timeout: 10_000 });
  await expect(page.locator("main .alert-error:not([data-busy])"), where).toHaveCount(0);
  // A busy answer is never a page that could not be drawn.
  await expect(page.getByTestId("fault"), where).toHaveCount(0);
  await expect(page.getByRole("navigation", { name: "Main" }), where).toBeVisible();
}

// The settings as this file found them: null for one at its default.
const found = new Map<string, unknown>();

test.beforeAll(async ({ request, accounts }) => {
  const headers = await session(request, await accounts.of("busy"));
  for (const key of SETTINGS) {
    const now = await setting(request, headers, key);
    found.set(key, now.is_default ? null : now.value);
  }
  // One item of its own, for a list to hold.
  const maker = await send(request, headers, "post", "/vendors", { name: vendor });
  const model = await send(request, headers, "post", "/catalog-entries", {
    vendor_hid: maker.hid,
    pid,
  });
  await send(request, headers, "post", "/items", { catalog_entry_hid: model.hid, hostname });
});

/** Put the three settings back as they were found. */
async function putBack(request: APIRequestContext, headers: Headers): Promise<void> {
  for (const key of SETTINGS) {
    if (!found.has(key)) continue;
    const now = await setting(request, headers, key);
    const was = found.get(key) ?? null;
    if ((now.is_default ? null : now.value) !== was) await put(request, headers, key, was);
  }
}

test.afterAll(async ({ request, accounts }) => {
  await putBack(request, await session(request, await accounts.of("busy")));
});

test("a server past its ceiling says so on a list and on About, still takes a save, and answers the list again with the ceiling put back", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(300_000);
  const seen = await watch(page.context());
  const headers = await session(request, account);
  await signIn(page, account);

  // With no ceiling, as the run has it, the list is answered.
  await page.goto(list);
  await expect(page.getByTestId("grid-total")).toHaveText("1 item", { timeout: 20_000 });

  // The ceiling at the lowest it goes, and requests that keep the server past it.
  for (const key of SETTINGS) await put(request, headers, key, LOWEST[key]);
  const stop = drive(request, headers);
  try {
    await expect
      .poll(() => stateOf(request, headers), { timeout: 30_000, intervals: [500] })
      .not.toBe("ok");

    // A list says that the server is busy, in the page's words, and offers to try again.
    await page.goto(list);
    await saysBusy(page, "the list of items");
    const again = listAgain(page);
    await expect(again).toBeVisible();
    await expect(page.locator("main .alert-error").first()).toHaveAttribute("data-status", "503");
    // Asked again of a server that is still busy, it says so again.
    await again.click();
    await saysBusy(page, "the list of items, tried again");

    // So do a report and the first page.
    await page.goto("./reports");
    await saysBusy(page, "the summary");
    await page.goto("./reports/scoreboard");
    await saysBusy(page, "the scoreboard");
    await page.goto("./");
    await saysBusy(page, "the first page");

    // About still answers: the state and by which measure, with the ceiling in force.
    await page.goto("./about");
    await expect(page.getByTestId("about-software")).toContainText("hirdir");
    const state = page.getByTestId("load-state");
    await expect(state).toHaveAttribute("data-state", /^(busy|very_busy)$/);
    await expect(state).toContainText(/^(Busy|Very busy)\. /);
    await expect(state).toContainText("answered at once that the server is busy");
    await expect(state).toContainText("Past its ceiling:");
    await expect(state).not.toContainText("No ceiling is set");
    const measures = page.getByTestId("load-measures");
    await expect(measures.locator("thead")).toContainText("over the last 5 seconds");
    await expect(measures.locator('tr[data-past="true"]').first()).toContainText(
      "Past its ceiling",
    );
    await expect(page.getByTestId("load-ceiling-response_ms")).toHaveText("1 ms");
    await expect(page.getByTestId("load-ceiling-cpu_percent")).toHaveText("1%");
    // The answers of busy are counted, and the steps they were given in are marked.
    await expect(page.getByTestId("load-count-busy")).toHaveText(/^[1-9][\d,]*$/);
    await expect(page.getByTestId("load-busy-mark").first()).toBeAttached();
    const steps = page.getByTestId("load-busy-steps");
    await expect(steps).toContainText(/An answer of busy was given in [1-9]\d* of the graph's/);
    await expect(steps).toContainText(/the last at \d\d:\d\d:\d\d \S+\./);
    const marked = Number(await steps.getAttribute("data-steps"));
    expect(marked).toBeGreaterThan(0);
    await expect(
      page.getByRole("img", { name: /The server's last 10 minutes/ }),
    ).toHaveAccessibleDescription(/An answer of busy was given in [1-9]/);
    // And it goes on answering: the numbers are read again, and are not stale.
    const since = page.getByTestId("load-since");
    const at = await since.getAttribute("data-at");
    await expect(since).not.toHaveAttribute("data-at", at ?? "", { timeout: 8_000 });
    await expect(since).toHaveAttribute("data-stale", "false");
    await expect(page.getByTestId("fault")).toHaveCount(0);

    // A save still goes through: the Admin sets one measure of the ceiling to 0, on the
    // Settings page, which a busy server still shows.
    await page.goto("./admin/settings");
    const row = page.getByTestId("settings").locator('tr[data-setting="busy_cpu_percent"]');
    await expect(page.getByTestId("value-busy_cpu_percent")).toHaveText("1");
    expect(await stateOf(request, headers), "the server when the save is sent").not.toBe("ok");
    await row.getByRole("button", { name: "Change busy_cpu_percent" }).click();
    const form = page.getByTestId("setting-form");
    await form.getByLabel("New value").fill("0");
    await form.getByRole("button", { name: "Set", exact: true }).click();
    await expect(page.getByText("busy_cpu_percent was set to 0.")).toBeVisible();
    await expect(page.getByTestId("value-busy_cpu_percent")).toHaveText("0");
    // Nothing was refused but what a busy server does not answer: the kept reports,
    // which the page lists beneath the settings, once every read is refused.
    await expect(page.locator("main .alert-error:not([data-busy])")).toHaveCount(0);
    await expect(page.getByTestId("fault")).toHaveCount(0);

    // Still past the other measure, the list still says busy.
    await expect
      .poll(() => stateOf(request, headers), { timeout: 15_000, intervals: [500] })
      .not.toBe("ok");
    await page.goto(list);
    await saysBusy(page, "the list of items, before the ceiling is put back");

    // The ceiling put back: Try again loads the list, and nothing says busy.
    await putBack(request, headers);
    await expect
      .poll(() => stateOf(request, headers), { timeout: 15_000, intervals: [500] })
      .toBe("ok");
    const anyAgain = page.locator("main").getByRole("button", { name: "Try again", exact: true });
    await expect(page.locator("main .alert-error > p:first-child").first()).toHaveText(BUSY);
    // One press asks again for the rows and for whatever else of the page was refused.
    await listAgain(page).click();
    await expect(page.getByTestId("grid-total")).toHaveText("1 item", { timeout: 20_000 });
    await expect(page.locator("main .alert-error")).toHaveCount(0);
    await expect(anyAgain).toHaveCount(0);

    // A report is asked again from under its refusal. Past the ceiling once more, the
    // scoreboard says busy; with the ceiling put back, one press fills every table.
    for (const key of SETTINGS) await put(request, headers, key, LOWEST[key]);
    await expect
      .poll(() => stateOf(request, headers), { timeout: 30_000, intervals: [500] })
      .not.toBe("ok");
    await page.goto("./reports/scoreboard");
    await saysBusy(page, "the scoreboard, once more");
    await expect(readAgain(page).first()).toBeVisible();
    await putBack(request, headers);
    await expect
      .poll(() => stateOf(request, headers), { timeout: 15_000, intervals: [500] })
      .toBe("ok");
    await readAgain(page).first().click();
    await expect(page.locator("main .alert-error")).toHaveCount(0, { timeout: 20_000 });
    await expect(anyAgain).toHaveCount(0);
    await expect(page.getByTestId("fault")).toHaveCount(0);
  } finally {
    await stop();
    await putBack(request, headers);
  }

  // About says the server is not busy, and its graph still marks when it was.
  await page.goto("./about");
  await expect(page.getByTestId("load-state")).toHaveAttribute("data-state", "ok");
  await expect(page.getByTestId("load-state")).toContainText("Not busy.");
  await expect(page.getByTestId("load-busy-mark").first()).toBeAttached();
  await expect(page.getByTestId("load-count-busy")).toHaveText(/^[1-9][\d,]*$/);

  // No cookie, nothing blocked, and nothing went wrong but the answers of busy.
  await Promise.all(seen.pending);
  expect(seen.cookies, "responses that set a cookie").toEqual([]);
  expect(seen.violations, "content security policy violations").toEqual([]);
  expect(seen.failures.length, "answers of busy to the page").toBeGreaterThan(0);
  for (const failure of seen.failures) expect(failure).toMatch(/^503 (GET|POST) /);
  expect(
    seen.console.filter((line) => !/Failed to load resource/.test(line)),
    "console errors",
  ).toEqual([]);
});
