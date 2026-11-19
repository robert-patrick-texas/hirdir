// The browser scenarios of the server's own measures on About, of 0.9.10 (P-266):
//
//   About shows, under what is running, whether the server is busy and the ceiling in
//   force, the two measures the ceiling reads, the lowest, the average and the highest
//   of the last ten minutes, how the requests were answered, what is in flight, the
//   process and its host, whether the background work is being done, and one graph,
//   named for a reader of the page aloud, with its legend. A value the host does not say
//   is "not known". The page is no wider than the window with the graph on it.
//   The page asks for the measures when it opens and every five seconds after, one
//   request at a time, and for nothing else by the clock; not while its tab is hidden;
//   once at once on coming back; and no more when another page is opened.
//   A request that fails leaves the numbers on show, and the page says that it failed
//   and since when the numbers are; the next that is answered takes the words away.
//
// How this file keeps to the rules of support.ts: an account of its own, and it changes
// nothing. The measures are of the whole server, which every file drives, so no number
// of them is compared with another: each is read as a number with its unit, and what the
// host says or does not say is compared with one answer of the API, which does not
// change while the server runs. The run has no ceiling (support.ts), and the scenarios
// of a server past its ceiling are in busy.spec.ts, which runs by itself.

import { type APIRequestContext, expect, type Page, type Request } from "@playwright/test";
import { type Account, expectClean, signIn, test, watch } from "./support";

const isLoad = (url: string) => new URL(url).pathname.endsWith("/api/v1/about/load");
const isApi = (url: string) => new URL(url).pathname.includes("/api/v1/");

interface Host {
  memory_total_bytes: number | null;
  memory_used_bytes: number | null;
  memory_free_bytes: number | null;
  disk_total_bytes: number | null;
  disk_free_bytes: number | null;
  processors: number | null;
  load_1m: number | null;
}

interface Load {
  state: string;
  worker: "running" | "not_running" | "in_process";
  process: { memory_bytes: number | null };
  host: Host;
}

/** The server's measures as the API answers them to the account of the file. */
async function loadOf(request: APIRequestContext, account: Account): Promise<Load> {
  const session = await request.post("./api/v1/auth/sign-in", {
    data: { username: account.username, access_code: account.accessCode },
  });
  expect(session.status(), "the account of the file signs in through the API").toBe(200);
  const { token } = (await session.json()) as { token: string };
  const answer = await request.get("./api/v1/about/load", {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(answer.status(), "GET /about/load").toBe(200);
  return (await answer.json()) as Load;
}

/** Make the tab hidden, or in front again, as the browser tells a page of it. */
async function show(page: Page, visible: boolean): Promise<void> {
  await page.evaluate(
    (state) => {
      Object.defineProperty(document, "visibilityState", { configurable: true, get: () => state });
      document.dispatchEvent(new Event("visibilitychange"));
    },
    visible ? "visible" : "hidden",
  );
}

/** The requests for the measures that a page sends: when each was sent, and how many are out. */
function countLoads(page: Page) {
  const counted = { sent: [] as number[], out: 0, mostOut: 0, others: [] as string[] };
  const ended = (request: Request) => {
    if (isLoad(request.url())) counted.out -= 1;
  };
  page.on("request", (request) => {
    if (isLoad(request.url())) {
      counted.sent.push(Date.now());
      counted.out += 1;
      counted.mostOut = Math.max(counted.mostOut, counted.out);
    } else if (isApi(request.url())) {
      counted.others.push(new URL(request.url()).pathname);
    }
  });
  page.on("requestfinished", ended);
  page.on("requestfailed", ended);
  return counted;
}

const WORKER_WORDS = {
  running: "Running, as a process of its own.",
  in_process: "Done by the server itself.",
  not_running: "Not running.",
} as const;

test("About shows the server's own measures and one graph, and is no wider than the window", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(90_000);
  const seen = await watch(page.context());
  await page.setViewportSize({ width: 1280, height: 800 });
  await signIn(page, account);
  await page.goto("./about");

  // What About showed before is there, with the measures under it.
  await expect(page.getByTestId("about-software")).toContainText("hirdir");
  const load = page.getByRole("region", { name: "The server's own measures" });
  await expect(load).toBeVisible();

  // Whether it is busy, and the ceiling in force: this run has none.
  const state = page.getByTestId("load-state");
  await expect(state).toHaveAttribute("data-state", "ok");
  await expect(state).toContainText("Not busy.");
  await expect(state).toContainText("No ceiling is set");
  await expect(page.getByTestId("load-since")).toContainText(
    /Read at \d\d:\d\d:\d\d \S+, and again every 5 seconds while this page is in front\./,
  );
  const measures = page.getByTestId("load-measures");
  await expect(measures.locator("thead")).toContainText(/over the last \d+ seconds/);
  await expect(page.getByTestId("load-now-response_ms")).toHaveText(
    /^([\d,.]+ ms|too few requests to say)$/,
  );
  await expect(page.getByTestId("load-now-cpu_percent")).toHaveText(/^[\d,.]+%$/);
  await expect(page.getByTestId("load-ceiling-response_ms")).toHaveText("not looked at");
  await expect(page.getByTestId("load-ceiling-cpu_percent")).toHaveText("not looked at");
  await expect(measures.locator('tr[data-past="true"]')).toHaveCount(0);

  // The last ten minutes: the lowest, the average and the highest of each.
  const spread = page.getByTestId("load-spread");
  await expect(spread.locator("thead th")).toHaveText([
    "Over the last ten minutes",
    "Lowest",
    "Average",
    "Highest",
  ]);
  await expect(spread.locator('tr[data-measure="response_ms"] td')).toHaveText([
    /^[\d,.]+ ms$/,
    /^[\d,.]+ ms$/,
    /^[\d,.]+ ms$/,
  ]);
  await expect(spread.locator('tr[data-measure="cpu_percent"] td')).toHaveText([
    /^([\d,.]+%|not known yet)$/,
    /^([\d,.]+%|not known yet)$/,
    /^([\d,.]+%|not known yet)$/,
  ]);

  // How the requests were answered, and what is in flight.
  const requests = page.getByTestId("load-requests");
  await expect(requests.locator("dt")).toHaveText([
    "Requests answered",
    "Answered well",
    "Not taken as asked",
    "Failed",
    "Answered as busy",
    "In flight now",
    "The oldest has waited",
  ]);
  for (const count of ["requests", "ok", "not-accepted", "failed", "busy"]) {
    await expect(page.getByTestId(`load-count-${count}`)).toHaveText(/^[\d,]+$/);
  }
  await expect(page.getByTestId("load-count-requests")).not.toHaveText("0");
  await expect(page.getByTestId("load-in-flight")).toHaveText(/^[\d,]+$/);
  await expect(page.getByTestId("load-oldest")).toHaveText(
    /^([\d,.]+ (ms|seconds?)|none is in flight)$/,
  );

  // The process and its host: each as the server says it, and what the host does not
  // say is not known, never 0.
  const said = await loadOf(request, account);
  const size = /^[\d,.]+ (bytes?|KB|MB|GB|TB)( of [\d,.]+ (bytes?|KB|MB|GB|TB))?$/;
  for (const [id, value, shape] of [
    ["load-process-memory", said.process.memory_bytes, size],
    ["load-memory-used", said.host.memory_used_bytes, size],
    ["load-memory-free", said.host.memory_free_bytes, size],
    ["load-disk-free", said.host.disk_free_bytes, size],
    ["load-processors", said.host.processors, /^[\d,]+$/],
    ["load-average", said.host.load_1m, /^[\d,]+\.\d\d$/],
  ] as const) {
    await expect(page.getByTestId(id), id).toHaveText(value === null ? "not known" : shape);
  }
  await expect(page.getByTestId("load-host")).toContainText("Server started");
  const worker = page.getByTestId("load-worker");
  await expect(worker).toHaveAttribute("data-worker", said.worker);
  await expect(worker).toContainText(WORKER_WORDS[said.worker]);
  // Background work that is not running is said so that it is noticed.
  await expect(page.getByTestId("load-worker-stopped")).toHaveCount(
    said.worker === "not_running" ? 1 : 0,
  );

  // One graph, drawn by the page: named by what it shows, with a legend of how each
  // line is drawn, and the words of what it marks beneath it.
  const graph = page.getByRole("img", {
    name: /The server's last 10 minutes in steps of 5 seconds: the time of an answer in milliseconds, and beneath it the share of one processor in percent, with a mark at each step in which an answer of busy was given/,
  });
  await expect(graph).toBeVisible();
  await expect(graph).toHaveAccessibleDescription(
    /From \d\d:\d\d:\d\d \S+ to \d\d:\d\d:\d\d \S+\./,
  );
  await expect(graph.locator("text.load-plot-name")).toHaveText([
    "Time of an answer, in milliseconds",
    "Share of one processor, in percent",
  ]);
  await expect(graph.locator("path.load-time-line")).toHaveCount(1);
  await expect(graph.locator("path.load-cpu")).toHaveCount(1);
  const legend = page.getByRole("list", { name: "What the graph shows" });
  await expect(legend.getByRole("listitem")).toHaveText([
    "Time of an answer: the average of each 5 seconds",
    "Time of an answer: the longest of each 5 seconds",
    "Share of one processor",
    "A step in which an answer of busy was given",
  ]);
  const steps = page.getByTestId("load-busy-steps");
  await expect(steps).toContainText(/answer of busy was given in/i);
  // As many marks on the graph as the words say steps.
  const marked = Number(await steps.getAttribute("data-steps"));
  await expect(page.getByTestId("load-busy-mark")).toHaveCount(marked);

  // The page is no wider than the window with the graph on it, at a desk and on a
  // narrow window, where the graph is drawn smaller to fit.
  const wider = () =>
    page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
  expect(await wider(), "wider than a window of 1280").toBeLessThanOrEqual(0);
  const box = await graph.boundingBox();
  expect(box && box.x >= 0 && box.x + box.width <= 1280, "the graph is within the window").toBe(
    true,
  );
  await page.setViewportSize({ width: 480, height: 800 });
  await expect(graph).toBeVisible();
  const narrow = await graph.boundingBox();
  expect(
    narrow && narrow.x >= 0 && narrow.x + narrow.width <= 480,
    "the graph is within a window of 480",
  ).toBe(true);
  expect(await wider(), "wider than a window of 480").toBeLessThanOrEqual(0);
  await expectClean(page, seen);
});

test("About asks for the measures every five seconds while in front, not while hidden, and once on coming back", async ({
  page,
  account,
}) => {
  test.setTimeout(120_000);
  await signIn(page, account);
  const counted = countLoads(page);
  await page.goto("./about");
  await expect(page.getByTestId("load-state")).toBeVisible();
  // What the page reads as it opens has been read: from here only the clock asks.
  await page.waitForLoadState("networkidle");
  counted.others.length = 0;

  // Three requests: as the page opened, and five and ten seconds after.
  await expect.poll(() => counted.sent.length, { timeout: 14_000 }).toBe(3);
  const [first = 0, second = 0, third = 0] = counted.sent;
  for (const gap of [second - first, third - second]) {
    expect(gap, "from one request to the next, in milliseconds").toBeGreaterThan(4_000);
    expect(gap, "from one request to the next, in milliseconds").toBeLessThan(6_500);
  }
  // Nothing else of About was read again by the clock.
  expect(counted.others, "other requests of the API while the page stood").toEqual([]);
  // The numbers are those of the last answer, and the page says since when.
  const since = page.getByTestId("load-since");
  await expect(since).toHaveAttribute("data-stale", "false");
  const at = await since.getAttribute("data-at");

  // Hidden: nothing is asked, for longer than two requests are apart.
  await show(page, false);
  await page.waitForTimeout(1_000);
  const whenHidden = counted.sent.length;
  await page.waitForTimeout(11_000);
  expect(counted.sent.length, "requests while the tab was hidden").toBe(whenHidden);

  // In front again: one request at once, and then every five seconds from it.
  const back = Date.now();
  await show(page, true);
  await expect.poll(() => counted.sent.length, { timeout: 2_000 }).toBe(whenHidden + 1);
  expect((counted.sent.at(-1) ?? 0) - back).toBeLessThan(1_500);
  await expect(since).not.toHaveAttribute("data-at", at ?? "");
  await expect.poll(() => counted.sent.length, { timeout: 7_000 }).toBe(whenHidden + 2);
  expect((counted.sent.at(-1) ?? 0) - (counted.sent.at(-2) ?? 0)).toBeGreaterThan(4_000);
  expect(counted.mostOut, "requests for the measures out at one time").toBe(1);

  // Another page: the measures are asked for no more.
  await page
    .getByRole("navigation", { name: "Main" })
    .getByRole("link", { name: "Home", exact: true })
    .click();
  await expect(page.getByTestId("load-state")).toHaveCount(0);
  await page.waitForTimeout(500);
  const whenLeft = counted.sent.length;
  await page.waitForTimeout(6_500);
  expect(counted.sent.length, "requests after About was left").toBe(whenLeft);
});

test("a request for the measures that fails or is slow leaves the numbers, says since when they are, and is not followed by a pile of others", async ({
  page,
  account,
}) => {
  test.setTimeout(120_000);
  await signIn(page, account);
  const counted = countLoads(page);
  await page.goto("./about");
  const since = page.getByTestId("load-since");
  await expect(since).toHaveAttribute("data-stale", "false");
  const read = (await since.textContent())?.match(/Read at (\d\d:\d\d:\d\d \S+),/)?.[1] ?? "";
  expect(read).not.toBe("");
  await page.waitForLoadState("networkidle");

  // The server cannot be reached: the numbers stay, and the page says of when they are.
  await page.route("**/api/v1/about/load", (route) => route.abort());
  await expect(since).toHaveAttribute("data-stale", "true", { timeout: 8_000 });
  await expect(since).toContainText("The server's measures could not be read at");
  await expect(since).toContainText("The server could not be reached.");
  await expect(since).toContainText(/These are the numbers of \d\d:\d\d:\d\d \S+\./);
  await expect(page.getByTestId("load-state")).toBeVisible();
  await expect(page.getByTestId("load-count-requests")).toHaveText(/^[\d,]+$/);
  await expect(page.getByRole("img", { name: /The server's last 10 minutes/ })).toBeVisible();
  // While it fails it is asked no more often than before.
  const failing = counted.sent.length;
  await page.waitForTimeout(11_000);
  expect(counted.sent.length - failing, "requests in eleven seconds of failing").toBeLessThan(4);
  await expect(page.getByTestId("fault")).toHaveCount(0);

  // A server that answers again is read again, and the words go.
  await page.unroute("**/api/v1/about/load");
  await expect(since).toHaveAttribute("data-stale", "false", { timeout: 8_000 });

  // A slow answer, of twelve seconds: no second request is sent while it is out.
  await page.route("**/api/v1/about/load", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 12_000));
    await route.continue().catch(() => undefined);
  });
  const slow = counted.sent.length;
  await expect.poll(() => counted.sent.length, { timeout: 8_000 }).toBe(slow + 1);
  await page.waitForTimeout(9_000);
  expect(counted.sent.length, "requests while a slow one was out").toBe(slow + 1);
  expect(counted.mostOut, "requests for the measures out at one time").toBe(1);
  await page.unrouteAll({ behavior: "ignoreErrors" });
});
