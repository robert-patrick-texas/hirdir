// The browser scenarios of the third review of the web UI, lane A, P-200 to P-204: what
// is typed after a save is kept, a list keeps its place, a record is chosen by searching
// for it, a model not in the catalog is added from New item, and small words.
//
// The file keeps the rules of support.ts. It signs in as an Admin of its own, and its
// mark is in every name it gives a record: the region, the site, the location, the
// vendors, the catalog entries and the items, made through the API as that Admin or
// through the forms the scenarios walk. It changes no setting, no list of choices, no
// lifecycle rule and no account, and reads only its own records, the lists filtered down
// to them. The scenarios need nothing of each other but what the first makes, and run in
// order.

import type { APIRequestContext, Locator, Page } from "@playwright/test";
import { expect } from "@playwright/test";
import { type Account, expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const id = mark("review-3a");
const label = (name: string) => `${name} ${id}`;
/** A host name of this file, which begins with its mark. */
const host = (name: string) => `${id}-${name}`;

type Headers = { Authorization: string };

async function session(request: APIRequestContext, account: Account): Promise<Headers> {
  const answer = await request.post("./api/v1/auth/sign-in", {
    data: { username: account.username, access_code: account.accessCode },
  });
  expect(answer.status(), "the account of the file signs in through the API").toBe(200);
  const { token } = (await answer.json()) as { token: string };
  return { Authorization: `Bearer ${token}` };
}

async function make(
  request: APIRequestContext,
  headers: Headers,
  path: string,
  data: unknown,
): Promise<{ hid: string }> {
  const answer = await request.post(`./api/v1${path}`, { headers, data });
  expect(answer.status(), `post ${path}: ${await answer.text()}`).toBe(201);
  return (await answer.json()) as { hid: string };
}

async function read(
  request: APIRequestContext,
  headers: Headers,
  path: string,
): Promise<Record<string, unknown>> {
  const answer = await request.get(`./api/v1${path}`, { headers });
  expect(answer.status(), `get ${path}`).toBe(200);
  return (await answer.json()) as Record<string, unknown>;
}

// What the first scenario makes, which the others use.
const made: {
  location?: string;
  vendor?: string;
  pid?: string;
  entry?: string;
  second?: string;
  item?: string;
} = {};

async function records(request: APIRequestContext, account: Account): Promise<Headers> {
  const headers = await session(request, account);
  if (made.item === undefined) {
    const region = (await make(request, headers, "/regions", { name: label("Westfold") })).hid;
    const site = (
      await make(request, headers, "/sites", {
        name: label("Mill Row"),
        code: `MR-${id}`,
        region_hid: region,
      })
    ).hid;
    made.location = (
      await make(request, headers, "/locations", { name: label("Room 2"), site_hid: site })
    ).hid;
    made.vendor = (
      await make(request, headers, "/vendors", { name: label("Sample Networks") })
    ).hid;
    made.pid = `SN-48P-${id}`;
    made.entry = (
      await make(request, headers, "/catalog-entries", {
        vendor_hid: made.vendor,
        pid: made.pid,
        model_name: label("Edge Switch"),
      })
    ).hid;
    made.item = (
      await make(request, headers, "/items", {
        hostname: host("mill-sw-01"),
        location_hid: made.location,
      })
    ).hid;
  }
  return headers;
}

function details(page: Page): Locator {
  return page.getByRole("region", { name: "Details" });
}

/** A request held back until it is let go, as a busy server answers late. */
async function holdBack(page: Page, url: string, method: string) {
  let release = () => {};
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  let asked = 0;
  await page.route(url, async (route) => {
    if (route.request().method() === method) {
      asked += 1;
      await held;
    }
    // A request the page has given up meanwhile, as a read replaced by a newer one, is gone.
    await route.continue().catch(() => {});
  });
  return {
    release,
    asked: () => asked,
    done: () => page.unroute(url),
  };
}

test("what is typed into an item's details after Save, while the page reads it again, is kept and saved (P-202)", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(120_000);
  const headers = await records(request, account);
  const seen = await watch(page.context());
  await signIn(page, account);
  await page.goto(`./items/${made.item}`);
  await expect(page.getByRole("heading", { level: 1, name: host("mill-sw-01") })).toBeVisible();
  const form = details(page);
  const serial = form.getByLabel("Serial number");
  const tag = form.getByLabel("Asset tag");
  const save = form.getByRole("button", { name: "Save", exact: true });
  const saved = page.getByRole("status").filter({ hasText: "The item was saved." });

  // The page's reading of the item after the save is held back, as a busy server's.
  const reread = await holdBack(page, `**/api/v1/items/${made.item}`, "GET");
  await serial.fill(`SER-${id}`);
  await save.click();
  await expect(saved).toBeVisible();
  await expect.poll(reread.asked, "the page reads the item again").toBeGreaterThan(0);
  // Typed in the moment after Save, before the item has been read again.
  await tag.fill(`TAG-${id}`);
  const answered = page.waitForResponse(
    (answer) =>
      answer.url().endsWith(`/api/v1/items/${made.item}`) && answer.request().method() === "GET",
  );
  reread.release();
  await answered;
  await reread.done();
  // The item read again shows its serial number, and what was typed meanwhile stays.
  await expect(form.getByLabel("Serial number")).toHaveValue(`SER-${id}`);
  await expect(form.getByLabel("Asset tag")).toHaveValue(`TAG-${id}`);
  await expect(save).toBeEnabled();
  await save.click();
  await expect(saved).toBeVisible();
  await expect(page.getByText("changed by someone else", { exact: false })).toHaveCount(0);
  await expect
    .poll(async () => (await read(request, headers, `/items/${made.item}`)).asset_tag)
    .toBe(`TAG-${id}`);

  // Saved again before the page has read the item: the second save goes with the version
  // the first was answered with, and is not refused as stale.
  const late = await holdBack(page, `**/api/v1/items/${made.item}`, "GET");
  await form.getByLabel("FQDN").fill(`${host("mill-sw-01")}.example.net`);
  await save.click();
  await expect.poll(late.asked, "the page reads the item again").toBeGreaterThan(0);
  await form.getByLabel("MAC address").fill("00:00:5e:00:53:01");
  await save.click();
  await expect
    .poll(async () => (await read(request, headers, `/items/${made.item}`)).mac_address)
    .toBeTruthy();
  late.release();
  await late.done();
  await expect(saved).toBeVisible();
  const item = await read(request, headers, `/items/${made.item}`);
  expect(item.fqdn).toBe(`${host("mill-sw-01")}.example.net`);

  await expectClean(page, seen);
});

/** The part of a grid whose rows scroll, and how far it is scrolled. */
function scrolled(grid: Locator): Promise<number> {
  return grid.locator(".ag-grid-viewport").evaluate((rows) => Math.round(rows.scrollTop));
}

/** Sixty items of the file's own, for a list longer than its window. */
async function rows(request: APIRequestContext, headers: Headers): Promise<void> {
  const answer = await request.post("./api/v1/items/query", {
    headers,
    data: {
      filter: { field: "hostname", op: "prefix", value: host("row-") },
      limit: 1,
    },
  });
  expect(answer.status(), "the items of the file are looked for").toBe(200);
  const { total } = (await answer.json()) as { total: number };
  for (let at = total; at < 60; at += 1) {
    await make(request, headers, "/items", {
      hostname: host(`row-${String(at).padStart(2, "0")}`),
      location_hid: made.location,
    });
  }
}

test("a list keeps its place: Back and a link back show the rows it was on, with the row opened marked; a new sort begins at the top (P-203)", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(180_000);
  const headers = await records(request, account);
  await rows(request, headers);
  const seen = await watch(page.context());
  await signIn(page, account);
  await page.goto("./items");
  const grid = page.getByTestId("grid-items");
  await page.getByLabel("Filter", { exact: true }).fill(`hostname:prefix:${host("row-")}`);
  await page.getByRole("button", { name: "Apply", exact: true }).click();
  await expect(page.getByText("60 items", { exact: true })).toBeVisible();
  await expect(grid.locator(".ag-row[row-index='0']")).toBeVisible();

  // Down the list, and a row opened by its link.
  await grid.locator(".ag-grid-viewport").evaluate((rows) => {
    rows.scrollTop = 1000;
  });
  await expect(grid.locator(".ag-row[row-index='40']")).toBeVisible();
  // The place is kept once the scrolling has ended.
  await page.waitForTimeout(500);
  const row = grid.locator(".ag-row[row-index='40']");
  const rowId = await row.getAttribute("row-id");
  expect(rowId).toBeTruthy();
  const opened = grid.locator(`.ag-row[row-id="${rowId}"]`);
  const name = (await row.locator('[col-id="name"] a').textContent()) ?? "";
  await row.locator('[col-id="name"] a').click();
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();

  // The browser's Back: the same rows, scrolled as they were, the row opened marked.
  await page.goBack();
  await expect(opened).toHaveClass(/row-opened/);
  await expect(opened).toBeInViewport();
  expect(await scrolled(grid)).toBeGreaterThan(900);
  await expect(page.getByTestId("grid-cell-note")).toHaveText(
    "Back where the list was left. The row opened last is marked.",
  );

  // A link back to the list, while the server answers late: the same once the rows come.
  await opened.locator('[col-id="name"] a').click();
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
  await page.route("**/api/v1/items/query", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 1500));
    await route.continue().catch(() => {});
  });
  await page
    .getByRole("navigation", { name: "Main" })
    .getByRole("link", { name: "Items", exact: true })
    .click();
  await expect(opened).toHaveClass(/row-opened/, { timeout: 15_000 });
  await expect(opened).toBeInViewport();
  await page.unroute("**/api/v1/items/query");

  // A new sort begins at the top, with no row marked.
  await grid.locator('[role="columnheader"][col-id="name"]').click();
  await expect(grid.locator(".ag-row[row-index='0']")).toBeInViewport();
  await expect.poll(() => scrolled(grid)).toBe(0);
  await expect(grid.locator(".row-opened")).toHaveCount(0);

  await expectClean(page, seen);
});

test("a list shows its rows where the browser refuses session storage (P-203)", async ({
  browser,
  baseURL,
  account,
  request,
}) => {
  test.setTimeout(120_000);
  const headers = await records(request, account);
  await rows(request, headers);
  const context = await browser.newContext(baseURL ? { baseURL } : {});
  await context.addInitScript(() => {
    Object.defineProperty(window, "sessionStorage", {
      get() {
        throw new DOMException("refused", "SecurityError");
      },
    });
  });
  const page = await context.newPage();
  const seen = await watch(context);
  await signIn(page, account);
  await page.goto(`./items?filter=${encodeURIComponent(`hostname:prefix:${host("row-")}`)}`);
  const grid = page.getByTestId("grid-items");
  await expect(page.getByText("60 items", { exact: true })).toBeVisible();
  const row = grid.locator(".ag-row[row-index='2']");
  const name = (await row.locator('[col-id="name"] a').textContent()) ?? "";
  await row.locator('[col-id="name"] a').click();
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
  await page.goBack();
  await expect(page.getByText("60 items", { exact: true })).toBeVisible();
  await expect(grid.locator(".ag-row[row-index='0']")).toBeVisible();
  await expectClean(page, seen);
  await context.close();
});

/** The list a search for a catalog entry offers in a form. */
function entriesFound(form: Locator): Locator {
  return form.getByRole("list", { name: "Catalog entries that match" });
}

/** A second model of the file's vendor, made once. */
async function secondEntry(request: APIRequestContext, headers: Headers): Promise<string> {
  if (made.second === undefined) {
    made.second = (
      await make(request, headers, "/catalog-entries", {
        vendor_hid: made.vendor,
        pid: `SN-24T-${id}`,
        model_name: label("Access Switch"),
      })
    ).hid;
  }
  return made.second;
}

test("a catalog entry is chosen by searching for it, in New item, in an item's details and as a successor (P-200)", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(180_000);
  const headers = await records(request, account);
  const second = await secondEntry(request, headers);
  const seen = await watch(page.context());
  await signIn(page, account);
  await page.goto("./items");
  await page.getByRole("button", { name: "New item" }).click();
  const form = page.getByRole("region", { name: "New item", exact: true });
  const entry = form.getByLabel("Catalog entry");
  const serial = form.getByLabel("Serial number");
  const hostname = form.getByLabel("Hostname");

  // The search answers late, as a busy server does: it is said, and the answer comes.
  await page.route("**/api/v1/catalog-entries?*", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 1500));
    await route.continue().catch(() => {});
  });
  // Each word is looked for in the PID, the model name and the vendor's name.
  await entry.fill(`${id} access`);
  await expect(form.getByText("Searching…")).toBeVisible();
  const offered = entriesFound(form).getByRole("button");
  await expect(offered).toHaveCount(1);
  await expect(offered).toHaveText(
    `SN-24T-${id} · ${label("Sample Networks")} · ${label("Access Switch")}`,
  );
  await page.unroute("**/api/v1/catalog-entries?*");
  // Enter in the search box searches, and makes no item.
  await entry.press("Enter");
  await expect(form).toBeVisible();
  await expect(page).toHaveURL(/\/items$/);
  await offered.click();
  await expect(form.getByTestId("chosen-catalog_entry_hid")).toHaveText(
    `SN-24T-${id} · ${label("Sample Networks")} · ${label("Access Switch")}`,
  );

  // Create and add another like it keeps the model, and a scanner's Enter makes the next.
  await serial.fill(`SER-${id}-N1`);
  await hostname.fill(host("new-01"));
  await form.getByRole("button", { name: "Create and add another like it" }).click();
  await expect(serial).toBeFocused();
  await expect(form.getByTestId("chosen-catalog_entry_hid")).toContainText(`SN-24T-${id}`);
  await hostname.fill(host("new-02"));
  await serial.fill(`SER-${id}-N2`);
  await serial.press("Enter");
  await expect(serial).toHaveValue("");
  await expect(serial).toBeFocused();
  await expect
    .poll(async () => {
      const answer = await request.post("./api/v1/items/query", {
        headers,
        data: { filter: { field: "hostname", op: "prefix", value: host("new-") }, limit: 10 },
      });
      const { items } = (await answer.json()) as { items: Array<{ catalog_entry_hid: string }> };
      return items.map((item) => item.catalog_entry_hid);
    })
    .toEqual([second, second]);

  // An item's details: the entry it has is named, and another is found by searching.
  await page.goto(`./items/${made.item}`);
  const details = page.getByRole("region", { name: "Details" });
  await details.getByLabel("Catalog entry").fill(`48P ${id}`);
  await entriesFound(details)
    .getByRole("button", { name: new RegExp(`^SN-48P-${id} ·`) })
    .click();
  await details.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "The item was saved." })).toBeVisible();
  await expect
    .poll(async () => (await read(request, headers, `/items/${made.item}`)).catalog_entry_hid)
    .toBe(made.entry);
  await expect(details.getByTestId("chosen-catalog_entry_hid")).toContainText(`SN-48P-${id}`);

  // The successor of a catalog entry, named by the entry by HID alone, is named in its form.
  await page.goto(`./catalog/${second}`);
  const entryForm = page.getByRole("region", { name: "Details" });
  await entryForm.getByLabel("Successor").fill(`${id} edge`);
  await entriesFound(entryForm)
    .getByRole("button", { name: new RegExp(`^SN-48P-${id} ·`) })
    .click();
  await entryForm.getByRole("button", { name: "Save", exact: true }).click();
  await expect
    .poll(async () => (await read(request, headers, `/catalog-entries/${second}`)).successor_hid)
    .toBe(made.entry);
  await page.reload();
  await expect(entryForm.getByTestId("chosen-successor_hid")).toHaveText(
    `SN-48P-${id} · ${label("Sample Networks")} · ${label("Edge Switch")}`,
  );

  await expectClean(page, seen);
});
