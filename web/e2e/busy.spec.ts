// The browser scenario of a server past its ceiling, of 0.9.10 (P-262, P-265, P-266,
// P-270 to P-273):
//
//   An Admin sets a ceiling of time that any request is past. On a quiet server the mark
//   of the menu bar then turns to its red, a square, and says that answers are slower
//   than the ceiling: not that the server is busy, since with few requests nothing is
//   refused. About says the same, and that the requests are too few to be load; it lists
//   the slowest requests, each by its route as a pattern with who asked, and the people
//   who are active; and a list still loads.
//   With requests enough to be load, the list says that the server is busy and to try
//   again in five seconds, in the page's own words, with its button Try again; so do a
//   report and the first page, each refusal with a Try again of its own; and none of
//   them is a page that could not be drawn. The mark says that the server is busy and
//   what it does not answer. About still answers: it says what is refused, with the
//   ceiling in force, counts the answers of busy, and marks on its graph the steps in
//   which they were given. A save still goes through: the Admin changes a setting of the
//   ceiling on the Settings page, which a busy server still shows. With the ceiling put
//   back, one press of Try again loads the list and takes every refusal off the page;
//   past the ceiling once more and back, one press under a refusal of the scoreboard
//   fills its tables. About then refuses nothing, the marks of when it did still on its
//   graph.
//
// How this file keeps to rule 5 of support.ts: it changes `busy_response_ms`,
// `busy_cpu_percent` and `busy_over_seconds`, which every request of every file feels,
// and keeps the server past them. So it runs in the project "the ceiling alone" of
// playwright.config.ts, by itself, when every other project has ended. It notes the
// three settings as it found them, and puts them back however it ends. The requests that
// make the load are real ones, of its own account, reading its own vendor: a read, which
// is what the server decides by. A server that refuses its reads takes none of them
// into its measure, so it refuses for as long as the reads it took before stay in it,
// which is the time the measure reaches back: the scenario makes that two minutes, so
// that all it looks at while the server refuses falls within one such stretch.

import { type APIRequestContext, expect, type Page } from "@playwright/test";
import { main as menuBar } from "./structure";
import { type Account, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const suffix = mark("busy");
const vendor = `Example Networks ${suffix}`;
const pid = `EN-B-24-${suffix}`;
const hostname = `site7-sw-${suffix}`;
const list = `./items?filter=${encodeURIComponent(`hostname:eq:${hostname}`)}`;

const BUSY = "The server is busy and did not answer this. Try again in 5 seconds.";
const SLOWER = "Answers are slower than the server's ceiling.";
const BUSY_READS =
  "The server is busy: lists and everything else that only reads are not answered for now.";
const UNREFUSED =
  "Nothing is refused for it: it is not the reads that are slow, or there are too few of them for it to be load.";
// A ceiling of a millisecond, which any request is past; the processor is not looked at,
// so that what is refused is for time alone. The measure reaches back ten seconds while
// the server is quiet, so that a short rest empties it, and two minutes under load.
const QUIET_SECONDS = 10;
const LOAD_SECONDS = 120;
const lowest = (over: number) =>
  ({ busy_over_seconds: over, busy_response_ms: 1, busy_cpu_percent: 0 }) as const;
const SETTINGS = ["busy_over_seconds", "busy_response_ms", "busy_cpu_percent"] as const;

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

/** What the server refuses now: `nothing`, `long` or `reads`. */
async function refusing(request: APIRequestContext, headers: Headers): Promise<string> {
  return (await read<{ refusing: string }>(request, headers, "/about/load")).refusing;
}

/** Give the three settings of the ceiling its lowest, read over so many seconds. */
async function setCeiling(request: APIRequestContext, headers: Headers, over: number) {
  const values = lowest(over);
  for (const key of SETTINGS) await put(request, headers, key, values[key]);
}

// The vendor this file makes, which its load reads.
let vendorHid = "";

/**
 * Make load: ten reads a second of this file's own vendor, each answered while the
 * server takes reads and refused at once while it does not. Returns the means to stop,
 * which waits for those that are out.
 */
function drive(request: APIRequestContext, headers: Headers): () => Promise<void> {
  const out = new Set<Promise<unknown>>();
  const timer = setInterval(() => {
    const one = request
      .get(`./api/v1/vendors/${encodeURIComponent(vendorHid)}`, { headers })
      .catch(() => undefined);
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
  vendorHid = maker.hid;
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

test("past its ceiling a quiet server is said to be slow and a loaded one busy: the mark, About, a list refused, a save taken, and Try again once the ceiling is put back", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(420_000);
  const seen = await watch(page.context());
  const headers = await session(request, account);
  await signIn(page, account);
  const healthMark = page.getByTestId("health-mark");

  // With no ceiling, as the run has it, the list is answered and nothing is refused.
  await page.goto(list);
  await expect(page.getByTestId("grid-total")).toHaveText("1 item", { timeout: 20_000 });
  await expect(healthMark).toHaveAttribute("data-refusing", "nothing");

  // ---- few requests: red, and nothing refused ------------------------------------------
  // A ceiling any request is past. The page then asks nothing for longer than the measure
  // reaches back, so that what it asks next is all there is in it.
  await setCeiling(request, headers, QUIET_SECONDS);
  await page.waitForTimeout((QUIET_SECONDS + 1) * 1000);

  // About is opened: one request of the measure, slower than a millisecond. The next
  // answer the page gets says so, and the mark with it.
  await menuBar(page).getByRole("link", { name: "About", exact: true }).click();
  await expect(healthMark).toHaveAttribute("data-health", "busy", { timeout: 8_000 });
  await expect(healthMark).toHaveAttribute("data-refusing", "nothing");
  // It says slow, in words, and not busy: nothing is refused.
  await expect(healthMark).toHaveAccessibleName(`Server health: ${SLOWER}`);
  await expect(healthMark).toHaveAttribute(
    "title",
    `${SLOWER} Nothing is refused. About shows the server's measures.`,
  );
  await expect(healthMark.locator('svg[data-shape="busy"] rect')).toHaveCount(1);
  const health = page.getByTestId("load-health");
  await expect(health).toHaveAttribute("data-health", "busy");
  await expect(health).toHaveAttribute("data-refusing", "nothing");
  await expect(page.getByTestId("load-health-words")).toHaveText(SLOWER);
  await expect(health).toContainText("It is read from how long requests take.");
  await expect(page.getByTestId("load-few")).toHaveText(UNREFUSED);
  await expect(health).not.toContainText(/server is busy/i);
  await expect(page.getByTestId("load-ceiling-response_ms")).toHaveText("1 ms");
  await expect(page.getByTestId("load-ceiling-cpu_percent")).toHaveText("not looked at");
  // The bands are named from their bounds, which are thirds of that millisecond.
  await expect(page.getByTestId("load-bands").locator("thead th.load-band")).toHaveText([
    "Under 0.3 ms",
    "0.3 to 0.7 ms",
    "0.7 to 1 ms",
    "Over 1 ms",
  ]);

  // The slowest requests of the ten minutes, the slowest first, each by its route as a
  // pattern with who asked, and nothing of what was asked for. They are of the whole
  // server, so after other files have run they need not be this account's.
  const slowest = page.getByTestId("load-slowest");
  await expect(slowest.locator("thead th")).toHaveText([
    "When",
    "Who",
    "Request",
    "Time",
    "Status",
    "Request ID",
  ]);
  const slow = slowest.locator("tbody tr");
  await expect(slow.first()).toBeVisible();
  await expect(slow.first().getByTestId("load-slow-id")).toHaveText(/\S{8,}/);
  const routes = await slowest.getByTestId("load-slow-request").allTextContents();
  expect(routes.length).toBeGreaterThan(0);
  expect(routes.length).toBeLessThanOrEqual(10);
  for (const route of routes) {
    expect(route).toMatch(/^[A-Z]+ (\/api\/v1\/[a-z0-9/{}_-]*|a path that no route answers)$/);
    expect(route).not.toContain(suffix);
  }
  const times = (await slow.locator("td:nth-child(4)").allTextContents()).map((text) =>
    Number(text.replace(/[^\d.]/g, "")),
  );
  expect(
    [...times].sort((one, other) => other - one),
    "the slowest first",
  ).toEqual(times);
  // Who is active: whoever asked each of the slowest is among them, and so is this
  // account, with what it met; an Admin opens an account from its name.
  const people = page.getByTestId("load-people");
  const names = (await people.getByTestId("load-person-name").allTextContents()).map((name) =>
    name.trim(),
  );
  for (const who of await slowest.getByTestId("load-slow-who").allTextContents()) {
    expect(who.trim()).not.toBe("");
    expect(names, "who asked a slow request is among the people").toContain(who.trim());
  }
  const me = people.locator(`tbody tr[data-person="${account.username}"]`);
  await expect(me).toHaveCount(1);
  await expect(me).toHaveAttribute("data-kind", "person");
  await expect(me.locator("td").first()).toHaveText(/^[1-9][\d,]*$/);
  await expect(me.getByRole("link", { name: account.username, exact: true })).toHaveAttribute(
    "href",
    new RegExp(`/admin/users/${account.hid}$`),
  );
  await expect(people.locator("thead th.load-band")).toHaveCount(4);
  await expect(page.getByTestId("fault")).toHaveCount(0);

  // A list still loads: slow is not busy, and nothing says that it is.
  await page.goto(list);
  await expect(page.getByTestId("grid-total")).toHaveText("1 item", { timeout: 20_000 });
  await expect(page.locator("main .alert-error")).toHaveCount(0);
  await expect(healthMark).toHaveAttribute("data-refusing", "nothing");

  // ---- load: the reads are refused -------------------------------------------------------
  // The measure now reaches back two minutes, and reads come ten a second.
  await setCeiling(request, headers, LOAD_SECONDS);
  const stop = drive(request, headers);
  try {
    await expect
      .poll(() => refusing(request, headers), { timeout: 30_000, intervals: [500] })
      .toBe("reads");

    // A list says that the server is busy, in the page's words, and offers to try again.
    await page.goto(list);
    await saysBusy(page, "the list of items");
    const again = listAgain(page);
    await expect(again).toBeVisible();
    await expect(page.locator("main .alert-error").first()).toHaveAttribute("data-status", "503");
    // And the mark says busy, with what is not answered.
    await expect(healthMark).toHaveAttribute("data-health", "busy");
    await expect(healthMark).toHaveAttribute("data-refusing", "reads");
    await expect(healthMark).toHaveAccessibleName(`Server health: ${BUSY_READS}`);
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

    // About still answers: what is refused, and the ceiling in force.
    await page.goto("./about");
    await expect(page.getByTestId("about-software")).toContainText("hirdir");
    await expect(health).toHaveAttribute("data-health", "busy");
    await expect(health).toHaveAttribute("data-refusing", "reads");
    await expect(page.getByTestId("load-health-words")).toHaveText(BUSY_READS);
    await expect(health).toContainText(SLOWER);
    await expect(health).toContainText("Sign-ins are taken and every change is stored.");
    await expect(health).not.toContainText("No ceiling is set");
    await expect(page.getByTestId("load-few")).toHaveCount(0);
    const measures = page.getByTestId("load-measures");
    await expect(measures.locator("thead")).toContainText(`over the last ${LOAD_SECONDS} seconds`);
    await expect(measures.locator('tr[data-measure="response_ms"]')).toHaveAttribute(
      "data-past",
      "true",
    );
    await expect(page.getByTestId("load-measured")).toHaveText(
      /of [2-9]\d+ requests|of [\d,]{3,} requests/,
    );
    await expect(page.getByTestId("load-ceiling-response_ms")).toHaveText("1 ms");
    // The answers of busy are counted, and the steps they were given in are marked.
    await expect(page.getByTestId("load-count-busy")).toHaveText(/^[1-9][\d,]*$/);
    await expect(page.getByTestId("load-busy-mark").first()).toBeAttached();
    const steps = page.getByTestId("load-busy-steps");
    await expect(steps).toContainText(/An answer of busy was given in [1-9]\d* of the graph's/);
    await expect(steps).toContainText(/the last at \d\d:\d\d:\d\d \S+\./);
    await expect(
      page.getByRole("img", { name: /The server's last 10 minutes/ }),
    ).toHaveAccessibleDescription(/An answer of busy was given in [1-9]/);
    // Whoever met them is told of: this account was answered as busy.
    await expect(me.locator("td").nth(6)).toHaveText(/^[1-9][\d,]*$/);
    // And it goes on answering: the numbers are read again, and are not stale.
    const since = page.getByTestId("load-since");
    const at = await since.getAttribute("data-at");
    await expect(since).not.toHaveAttribute("data-at", at ?? "", { timeout: 8_000 });
    await expect(since).toHaveAttribute("data-stale", "false");
    await expect(page.getByTestId("fault")).toHaveCount(0);

    // A save still goes through: the Admin changes a setting of the ceiling, on the
    // Settings page, which a busy server still shows.
    await page.goto("./admin/settings");
    const row = page.getByTestId("settings").locator('tr[data-setting="busy_over_seconds"]');
    await expect(page.getByTestId("value-busy_over_seconds")).toHaveText(String(LOAD_SECONDS));
    expect(await refusing(request, headers), "refused when the save is sent").toBe("reads");
    await row.getByRole("button", { name: "Change busy_over_seconds" }).click();
    const form = page.getByTestId("setting-form");
    await form.getByLabel("New value").fill(String(LOAD_SECONDS + 1));
    await form.getByRole("button", { name: "Set", exact: true }).click();
    await expect(page.getByText(`busy_over_seconds was set to ${LOAD_SECONDS + 1}.`)).toBeVisible();
    await expect(page.getByTestId("value-busy_over_seconds")).toHaveText(String(LOAD_SECONDS + 1));
    // Nothing was refused but what a busy server does not answer: the kept reports,
    // which the page lists beneath the settings.
    await expect(page.locator("main .alert-error:not([data-busy])")).toHaveCount(0);
    await expect(page.getByTestId("fault")).toHaveCount(0);

    // Still past the ceiling, the list still says busy.
    await expect
      .poll(() => refusing(request, headers), { timeout: 15_000, intervals: [500] })
      .toBe("reads");
    await page.goto(list);
    await saysBusy(page, "the list of items, before the ceiling is put back");

    // The ceiling put back: Try again loads the list, and nothing says busy.
    await putBack(request, headers);
    await expect
      .poll(() => refusing(request, headers), { timeout: 60_000, intervals: [500] })
      .not.toBe("reads");
    const anyAgain = page.locator("main").getByRole("button", { name: "Try again", exact: true });
    await expect(page.locator("main .alert-error > p:first-child").first()).toHaveText(BUSY);
    // One press asks again for the rows and for whatever else of the page was refused.
    await listAgain(page).click();
    await expect(page.getByTestId("grid-total")).toHaveText("1 item", { timeout: 20_000 });
    await expect(page.locator("main .alert-error")).toHaveCount(0);
    await expect(anyAgain).toHaveCount(0);
    await expect(healthMark).not.toHaveAttribute("data-refusing", "reads");

    // A report is asked again from under its refusal. Past the ceiling once more, the
    // scoreboard says busy; with the ceiling put back, one press fills every table.
    await setCeiling(request, headers, LOAD_SECONDS);
    await expect
      .poll(() => refusing(request, headers), { timeout: 30_000, intervals: [500] })
      .toBe("reads");
    await page.goto("./reports/scoreboard");
    await saysBusy(page, "the scoreboard, once more");
    await expect(readAgain(page).first()).toBeVisible();
    await putBack(request, headers);
    // What is long comes back a while after the reads do.
    await expect
      .poll(() => refusing(request, headers), { timeout: 150_000, intervals: [1000] })
      .toBe("nothing");
    await readAgain(page).first().click();
    await expect(page.locator("main .alert-error")).toHaveCount(0, { timeout: 20_000 });
    await expect(anyAgain).toHaveCount(0);
    await expect(page.getByTestId("fault")).toHaveCount(0);
  } finally {
    await stop();
    await putBack(request, headers);
  }

  // About refuses nothing, and its graph still marks when it did.
  await page.goto("./about");
  await expect(health).toHaveAttribute("data-refusing", "nothing");
  await expect(page.getByTestId("load-no-ceiling")).toContainText("No ceiling is set");
  await expect(page.getByTestId("load-busy-mark").first()).toBeAttached();
  await expect(page.getByTestId("load-count-busy")).toHaveText(/^[1-9][\d,]*$/);
  await expect(healthMark).toHaveAttribute("data-refusing", "nothing");

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
