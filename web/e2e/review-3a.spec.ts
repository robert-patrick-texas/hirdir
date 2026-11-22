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

import { readFile } from "node:fs/promises";
import type { APIRequestContext, Locator, Page, Response } from "@playwright/test";
import { expect } from "@playwright/test";
import { answer, listed, queried } from "./answers";
import { type Account, expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const id = mark("review-3a");
const label = (name: string) => `${name} ${id}`;
/** A host name of this file, which begins with its mark. */
const host = (name: string) => `${id}-${name}`;

/**
 * What the file's own requests to the API are sent with: the session, and a connection
 * of their own. P-309: the request client keeps a connection open between requests, and
 * the server closes one that has been idle for 5 seconds; on a busy host a request sent
 * on it as it closes was answered `read ECONNRESET`. A connection that ends with its
 * answer is never sent on idle.
 */
type Headers = { Authorization: string; Connection: "close" };

async function session(request: APIRequestContext, account: Account): Promise<Headers> {
  const answer = await request.post("./api/v1/auth/sign-in", {
    headers: { Connection: "close" },
    data: { username: account.username, access_code: account.accessCode },
  });
  expect(answer.status(), "the account of the file signs in through the API").toBe(200);
  const { token } = (await answer.json()) as { token: string };
  return { Authorization: `Bearer ${token}`, Connection: "close" };
}

// P-309: each read and each save of the server is waited for before what the page shows
// of it is expected, with answer, listed and queried of answers.ts.

/** The page's answer to a search of the catalog whose address, decoded, holds `parts`. */
function catalogSearched(page: Page, ...parts: string[]): Promise<Response> {
  return listed(page, "/catalog-entries", ...parts);
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

/** An item's page, once the server has answered with the item. */
async function openItem(page: Page, hid: string) {
  const opened = answer(page, "GET", `/items/${hid}`);
  await page.goto(`./items/${hid}`);
  await opened;
}

/**
 * Press Save in an item's details, and wait for the server's answer, which must be that
 * it was saved. Until then the status "saved" on show may be the save's before it.
 */
async function saveItem(page: Page, save: Locator, hid: string) {
  const answered = answer(page, "PATCH", `/items/${hid}`);
  await save.click();
  expect((await answered).status(), "the save is answered as saved").toBe(200);
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
  const item = made.item ?? "";
  await openItem(page, item);
  await expect(page.getByRole("heading", { level: 1, name: host("mill-sw-01") })).toBeVisible();
  const form = details(page);
  const serial = form.getByLabel("Serial number");
  const tag = form.getByLabel("Asset tag");
  const save = form.getByRole("button", { name: "Save", exact: true });
  const saved = page.getByRole("status").filter({ hasText: "The item was saved." });

  // The page's reading of the item after the save is held back, as a busy server's.
  const reread = await holdBack(page, `**/api/v1/items/${item}`, "GET");
  await serial.fill(`SER-${id}`);
  await saveItem(page, save, item);
  await expect(saved).toBeVisible();
  await expect.poll(reread.asked, "the page reads the item again").toBeGreaterThan(0);
  // Typed in the moment after Save, before the item has been read again.
  await tag.fill(`TAG-${id}`);
  const answered = answer(page, "GET", `/items/${item}`);
  reread.release();
  await answered;
  await reread.done();
  // The item read again shows its serial number, and what was typed meanwhile stays.
  await expect(form.getByLabel("Serial number")).toHaveValue(`SER-${id}`);
  await expect(form.getByLabel("Asset tag")).toHaveValue(`TAG-${id}`);
  await expect(save).toBeEnabled();
  // The second save is answered, and the item read again after it, before the scenario
  // goes on: the status "saved" on show until then is the first save's.
  const readAgain = answer(page, "GET", `/items/${item}`);
  await saveItem(page, save, item);
  await readAgain;
  await expect(saved).toBeVisible();
  await expect(page.getByText("changed by someone else", { exact: false })).toHaveCount(0);
  expect((await read(request, headers, `/items/${item}`)).asset_tag).toBe(`TAG-${id}`);

  // Saved again before the page has read the item: the second save goes with the version
  // the first was answered with, and is not refused as stale.
  const late = await holdBack(page, `**/api/v1/items/${item}`, "GET");
  await form.getByLabel("FQDN").fill(`${host("mill-sw-01")}.example.net`);
  await saveItem(page, save, item);
  await expect.poll(late.asked, "the page reads the item again").toBeGreaterThan(0);
  await form.getByLabel("MAC address").fill("00:00:5e:00:53:01");
  await saveItem(page, save, item);
  expect((await read(request, headers, `/items/${item}`)).mac_address).toBeTruthy();
  late.release();
  await late.done();
  await expect(saved).toBeVisible();
  const now = await read(request, headers, `/items/${item}`);
  expect(now.fqdn).toBe(`${host("mill-sw-01")}.example.net`);

  await expectClean(page, seen);
});

test("a kept field that someone else changed meanwhile says so under it, and a field not touched takes the new value (P-202)", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(120_000);
  const headers = await records(request, account);
  const item = (
    await make(request, headers, "/items", {
      hostname: host("mill-sw-02"),
      location_hid: made.location,
    })
  ).hid;
  const seen = await watch(page.context());
  await signIn(page, account);
  await openItem(page, item);
  await expect(page.getByRole("heading", { level: 1, name: host("mill-sw-02") })).toBeVisible();
  const form = details(page);
  const tag = form.getByLabel("Asset tag");
  const save = form.getByRole("button", { name: "Save", exact: true });
  const saved = page.getByRole("status").filter({ hasText: "The item was saved." });

  const reread = await holdBack(page, `**/api/v1/items/${item}`, "GET");
  await form.getByLabel("Serial number").fill(`SER2-${id}`);
  await saveItem(page, save, item);
  await expect(saved).toBeVisible();
  await expect.poll(reread.asked, "the page reads the item again").toBeGreaterThan(0);
  await tag.fill(`MINE-${id}`);
  // Another person saves the asset tag and the FQDN before the page has read the item.
  const now = await read(request, headers, `/items/${item}`);
  const other = await request.patch(`./api/v1/items/${item}`, {
    headers,
    data: {
      row_version: now.row_version,
      asset_tag: `THEIRS-${id}`,
      fqdn: `${host("mill-sw-02")}.example.net`,
    },
  });
  expect(other.status(), await other.text()).toBe(200);
  const answered = answer(page, "GET", `/items/${item}`);
  reread.release();
  await answered;
  await reread.done();

  // What was typed stays, and the person is told what saving it replaces.
  const note = `Changed meanwhile to “THEIRS-${id}”; saving replaces it.`;
  await expect(form.getByLabel("FQDN")).toHaveValue(`${host("mill-sw-02")}.example.net`);
  await expect(tag).toHaveValue(`MINE-${id}`);
  await expect(form.getByText(note, { exact: true })).toBeVisible();
  await expect(tag).toHaveAccessibleDescription(new RegExp(`THEIRS-${id}.*saving replaces it`));
  await expect(form.getByRole("status").filter({ hasText: `Asset tag: ${note}` })).toHaveCount(1);
  // The field the person did not touch takes the new value, and nothing is said of it.
  await expect(form.getByLabel("FQDN")).not.toHaveAccessibleDescription(/meanwhile/);

  // Saving replaces it, as the person was told, and the note goes.
  await saveItem(page, save, item);
  await expect(saved).toBeVisible();
  expect((await read(request, headers, `/items/${item}`)).asset_tag).toBe(`MINE-${id}`);
  await expect(form.getByText("Changed meanwhile", { exact: false })).toHaveCount(0);

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
  // Each reading of the list is of this file's rows: it is waited for before the grid is.
  const listed = () => queried(page, "/items/query", host("row-"));
  await page.getByLabel("Filter", { exact: true }).fill(`hostname:prefix:${host("row-")}`);
  const filtered = listed();
  await page.getByRole("button", { name: "Apply", exact: true }).click();
  await filtered;
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
  // The item's page, once the server has answered with the item.
  const shown = () => answer(page, "GET", `/items/${rowId}`);
  const first = shown();
  await row.locator('[col-id="name"] a').click();
  await first;
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();

  // The browser's Back: the same rows, scrolled as they were, the row opened marked.
  const back = listed();
  await page.goBack();
  await back;
  await expect(opened).toHaveClass(/row-opened/);
  await expect(opened).toBeInViewport();
  expect(await scrolled(grid)).toBeGreaterThan(900);
  await expect(page.getByTestId("grid-cell-note")).toHaveText(
    "Back where the list was left. The row opened last is marked.",
  );

  // A link back to the list, while the server answers late: the same rows once they
  // come, scrolled inside the grid as they were, with the row opened marked. 0.9.15: the
  // page itself is at its top, with the menu bar in view, as every page opened from the
  // menu bar is; only Back and Forward put the window back (P-301).
  const again = shown();
  await opened.locator('[col-id="name"] a').click();
  await again;
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
  await page.route("**/api/v1/items/query", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 1500));
    await route.continue().catch(() => {});
  });
  const menuBar = page.getByRole("navigation", { name: "Main" });
  const late = listed();
  await menuBar.getByRole("link", { name: "Items", exact: true }).click();
  await late;
  await expect(opened).toHaveClass(/row-opened/);
  expect(await scrolled(grid)).toBeGreaterThan(900);
  expect(await page.evaluate(() => window.scrollY)).toBe(0);
  await expect(menuBar).toBeInViewport({ ratio: 1 });
  await page.unroute("**/api/v1/items/query");

  // A new sort begins at the top, with no row marked.
  const sorted = listed();
  await grid.locator('[role="columnheader"][col-id="name"]').click();
  await sorted;
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
  const listed = () => queried(page, "/items/query", host("row-"));
  const first = listed();
  await page.goto(`./items?filter=${encodeURIComponent(`hostname:prefix:${host("row-")}`)}`);
  await first;
  const grid = page.getByTestId("grid-items");
  await expect(page.getByText("60 items", { exact: true })).toBeVisible();
  const row = grid.locator(".ag-row[row-index='2']");
  const name = (await row.locator('[col-id="name"] a').textContent()) ?? "";
  const shown = answer(page, "GET", `/items/${await row.getAttribute("row-id")}`);
  await row.locator('[col-id="name"] a').click();
  await shown;
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
  const back = listed();
  await page.goBack();
  await back;
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
  const searched = catalogSearched(page, id, "access");
  await entry.fill(`${id} access`);
  await expect(form.getByText("Searching…")).toBeVisible();
  const offered = entriesFound(form).getByRole("button");
  await searched;
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

  // Create and add another like it keeps the model, and a scanner's Enter makes the next:
  // each item made once the server has answered that it is.
  const create = async (send: () => Promise<void>) => {
    const created = answer(page, "POST", "/items");
    await send();
    expect((await created).status(), "the item is made").toBe(201);
  };
  await serial.fill(`SER-${id}-N1`);
  await hostname.fill(host("new-01"));
  await create(() => form.getByRole("button", { name: "Create and add another like it" }).click());
  await expect(serial).toBeFocused();
  await expect(form.getByTestId("chosen-catalog_entry_hid")).toContainText(`SN-24T-${id}`);
  await hostname.fill(host("new-02"));
  await serial.fill(`SER-${id}-N2`);
  await create(() => serial.press("Enter"));
  await expect(serial).toHaveValue("");
  await expect(serial).toBeFocused();
  // Both are made: the list of them is read once, after the second was answered.
  const both = await request.post("./api/v1/items/query", {
    headers,
    data: { filter: { field: "hostname", op: "prefix", value: host("new-") }, limit: 10 },
  });
  expect(both.status(), "the items made are looked for").toBe(200);
  const { items } = (await both.json()) as { items: Array<{ catalog_entry_hid: string }> };
  expect(items.map((item) => item.catalog_entry_hid)).toEqual([second, second]);

  // An item's details: the entry it has is named, and another is found by searching.
  const item = made.item ?? "";
  await openItem(page, item);
  const details = page.getByRole("region", { name: "Details" });
  await details.getByLabel("Catalog entry").fill(`48P ${id}`);
  await entriesFound(details)
    .getByRole("button", { name: new RegExp(`^SN-48P-${id} ·`) })
    .click();
  await saveItem(page, details.getByRole("button", { name: "Save", exact: true }), item);
  await expect(page.getByRole("status").filter({ hasText: "The item was saved." })).toBeVisible();
  expect((await read(request, headers, `/items/${item}`)).catalog_entry_hid).toBe(made.entry);
  await expect(details.getByTestId("chosen-catalog_entry_hid")).toContainText(`SN-48P-${id}`);

  // The successor of a catalog entry, named by the entry by HID alone, is named in its form.
  await page.goto(`./catalog/${second}`);
  const entryForm = page.getByRole("region", { name: "Details" });
  await entryForm.getByLabel("Successor").fill(`${id} edge`);
  await entriesFound(entryForm)
    .getByRole("button", { name: new RegExp(`^SN-48P-${id} ·`) })
    .click();
  const entrySaved = answer(page, "PATCH", `/catalog-entries/${second}`);
  await entryForm.getByRole("button", { name: "Save", exact: true }).click();
  expect((await entrySaved).status(), "the catalog entry is saved").toBe(200);
  expect((await read(request, headers, `/catalog-entries/${second}`)).successor_hid).toBe(
    made.entry,
  );
  // Read again, the page has the entry, and the successor it names by HID alone, which
  // it reads to name it.
  const entryRead = answer(page, "GET", `/catalog-entries/${second}`);
  const successorRead = answer(page, "GET", `/catalog-entries/${made.entry}`);
  await page.reload();
  await Promise.all([entryRead, successorRead]);
  await expect(entryForm.getByTestId("chosen-successor_hid")).toHaveText(
    `SN-48P-${id} · ${label("Sample Networks")} · ${label("Edge Switch")}`,
  );

  await expectClean(page, seen);
});

test("a model that is not in the catalog is added from New item, and what was typed stays (P-201)", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(150_000);
  const headers = await records(request, account);
  const seen = await watch(page.context());
  await signIn(page, account);
  await page.goto("./items");
  await page.getByRole("button", { name: "New item" }).click();
  const form = page.getByRole("region", { name: "New item", exact: true });
  // What is typed into the item first, which must not be lost on the way.
  await form.getByLabel("Hostname").fill(host("new-model-01"));
  await form.getByLabel("Asset tag").fill(`AT-${id}-M1`);

  // A model the catalog does not have: the search finds nothing, and offers to add it.
  const pid = `SN-8X-${id}`;
  const nothing = catalogSearched(page, pid);
  await form.getByLabel("Catalog entry").fill(pid);
  await nothing;
  await expect(form.getByText("No catalog entry matches.")).toBeVisible();
  await form.getByRole("button", { name: "Add this model to the catalog" }).click();
  const add = form.getByRole("group", { name: "Add a model to the catalog" });
  await expect(add.getByLabel("PID")).toHaveValue(pid);
  /** Send the model to the catalog, and wait for the server's answer, of `status`. */
  const addModel = async (send: () => Promise<void>, status: number) => {
    const answered = answer(page, "POST", "/catalog-entries");
    await send();
    expect((await answered).status(), "the catalog's answer to the model").toBe(status);
  };

  // Refused by the server: its answer is shown, and everything typed stays.
  await add.getByLabel("Model name").fill(label("Uplink Module"));
  await add.getByLabel("Kind").selectOption("hardware");
  await add.getByRole("button", { name: "Add to the catalog" }).click();
  await expect(add.getByText("Choose the vendor.")).toBeVisible();
  await add.getByLabel("Vendor").selectOption({ label: label("Sample Networks") });
  await add.getByLabel("PID").fill(made.pid ?? "");
  await addModel(() => add.getByRole("button", { name: "Add to the catalog" }).click(), 409);
  await expect(add.locator(".field-error, .alert-error").first()).toBeVisible();
  await expect(add.getByLabel("Model name")).toHaveValue(label("Uplink Module"));
  await expect(form.getByLabel("Hostname")).toHaveValue(host("new-model-01"));

  // Added: the entry is chosen for the item and the keyboard goes on to its next field.
  await add.getByLabel("PID").fill(pid);
  await addModel(() => add.getByLabel("PID").press("Enter"), 201);
  await expect(form.getByTestId("chosen-catalog_entry_hid")).toHaveText(
    `${pid} · ${label("Sample Networks")} · ${label("Uplink Module")}`,
  );
  await expect(add).toHaveCount(0);
  await expect(form.getByLabel("Serial number")).toBeFocused();
  await expect(form.getByLabel("Hostname")).toHaveValue(host("new-model-01"));
  await expect(form.getByLabel("Asset tag")).toHaveValue(`AT-${id}-M1`);
  await form.getByLabel("Serial number").fill(`SER-${id}-M1`);
  // Made, and its page opened, once the server has answered with it.
  const created = answer(page, "POST", "/items");
  const opened = answer(page, "GET", /\/api\/v1\/items\/[^/]+$/);
  await form.getByRole("button", { name: "Create item" }).click();
  expect((await created).status(), "the item is made").toBe(201);
  await opened;
  await expect(page.getByRole("heading", { level: 1, name: host("new-model-01") })).toBeVisible();
  const hid = page.url().split("/").pop() ?? "";
  const item = await read(request, headers, `/items/${hid}`);
  expect(item.serial_number).toBe(`SER-${id}-M1`);
  const entry = await read(request, headers, `/catalog-entries/${String(item.catalog_entry_hid)}`);
  expect(entry.pid).toBe(pid);

  // Where the search finds models, adding another is offered as a small link.
  await page.goto("./items");
  await page.getByRole("button", { name: "New item" }).click();
  const some = catalogSearched(page, id);
  await form.getByLabel("Catalog entry").fill(id);
  await some;
  await expect(entriesFound(form).getByRole("button").first()).toBeVisible();
  await expect(form.getByRole("button", { name: "Add a model to the catalog" })).toBeVisible();

  await expectClean(page, seen, ["409 POST"]);
});

test("a model the catalog has already is offered to be used, and the part that adds one closes once an entry is chosen (P-201)", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(120_000);
  await records(request, account);
  const seen = await watch(page.context());
  await signIn(page, account);
  await page.goto("./items");
  await page.getByRole("button", { name: "New item" }).click();
  const form = page.getByRole("region", { name: "New item", exact: true });
  await form.getByLabel("Hostname").fill(host("new-model-02"));
  const chosen = form.getByTestId("chosen-catalog_entry_hid");
  const entryName = `${made.pid} · ${label("Sample Networks")} · ${label("Edge Switch")}`;

  // The part that adds a model is open; an entry chosen from the search closes it.
  await form.getByLabel("Catalog entry").fill(id);
  await form.getByRole("button", { name: "Add a model to the catalog" }).click();
  const add = form.getByRole("group", { name: "Add a model to the catalog" });
  await expect(add).toBeVisible();
  await entriesFound(form).getByRole("button", { name: entryName }).click();
  await expect(chosen).toHaveText(entryName);
  await expect(add).toHaveCount(0);
  await form.getByRole("button", { name: "Clear the catalog entry" }).click();

  // The PID the catalog has already: the refusal offers that entry, to use or to open
  // in a new tab, and Use it chooses it with what was typed kept.
  const nothing = catalogSearched(page, `${id}-none`);
  await form.getByLabel("Catalog entry").fill(`${id}-none`);
  await nothing;
  await expect(form.getByText("No catalog entry matches.")).toBeVisible();
  await form.getByRole("button", { name: "Add this model to the catalog" }).click();
  await add.getByLabel("Vendor").selectOption({ label: label("Sample Networks") });
  await add.getByLabel("PID").fill(made.pid ?? "");
  const refused = answer(page, "POST", "/catalog-entries");
  await add.getByRole("button", { name: "Add to the catalog" }).click();
  expect((await refused).status(), "the PID the catalog has already is refused").toBe(409);
  await expect(add.getByText("The catalog entry that has it:")).toBeVisible();
  const existing = add.getByRole("link", { name: /opens in a new tab/ });
  await expect(existing).toHaveAttribute("target", "_blank");
  await expect(existing).toHaveAttribute("href", new RegExp(`/catalog/${made.entry}$`));
  await add.getByRole("button", { name: "Use it" }).click();
  await expect(chosen).toHaveText(entryName);
  await expect(add).toHaveCount(0);
  await expect(form.getByLabel("Hostname")).toHaveValue(host("new-model-02"));

  await expectClean(page, seen, ["409 POST"]);
});

test("small words: a create says so with a link, a bulk edit's preview speaks of the items, and the first export holds the host name (P-204)", async ({
  page,
  account,
  request,
}, testInfo) => {
  test.setTimeout(180_000);
  const headers = await records(request, account);
  await rows(request, headers);
  const seen = await watch(page.context());
  await signIn(page, account);

  // Geography: a new region is said to be created, its name a link to it.
  await page.goto("./geography");
  await page.getByRole("button", { name: "New region", exact: true }).click();
  const newRegion = page.getByRole("region", { name: "New region", exact: true });
  await newRegion.getByLabel("Name (required)").fill(label("Northreach"));
  const regionMade = answer(page, "POST", "/regions");
  await newRegion.getByRole("button", { name: "Create region" }).click();
  expect((await regionMade).status(), "the region is made").toBe(201);
  const said = page.getByRole("status").filter({ hasText: "was created." });
  await expect(said).toHaveText(`Region ${label("Northreach")} was created.`);
  await expect(said).toBeInViewport();
  const link = said.getByRole("link", { name: label("Northreach") });
  await expect(link).toHaveAttribute("href", /\/geography\/region\//);

  // The catalog: a new entry's page says it was created.
  await page.goto("./catalog");
  await page.getByRole("button", { name: "New catalog entry" }).click();
  const newEntry = page.getByRole("region", { name: "New catalog entry", exact: true });
  await newEntry.getByLabel("Vendor").selectOption({ label: label("Sample Networks") });
  await newEntry.getByLabel("PID").fill(`SN-4X-${id}`);
  // Made, and its page opened, once the server has answered with it.
  const entryMade = answer(page, "POST", "/catalog-entries");
  const entryOpened = answer(page, "GET", /\/api\/v1\/catalog-entries\/[^/]+$/);
  await newEntry.getByRole("button", { name: "Create catalog entry" }).click();
  expect((await entryMade).status(), "the catalog entry is made").toBe(201);
  await entryOpened;
  await expect(said).toHaveText(
    `Catalog entry ${label("Sample Networks")} SN-4X-${id} was created.`,
  );

  // A bulk edit's preview: nothing to create, and the rows in the order of the items.
  const tenListed = () => queried(page, "/items/query", host("row-0"));
  const ten = tenListed();
  await page.goto(`./items?filter=${encodeURIComponent(`hostname:prefix:${host("row-0")}`)}`);
  await ten;
  const grid = page.getByTestId("grid-items");
  await expect(page.getByText("10 items", { exact: true })).toBeVisible();
  await grid.locator(".ag-row[row-index='0'] [col-id='serial_number']").click();
  await page.getByRole("button", { name: "Bulk edit" }).click();
  const bulk = page.getByTestId("bulk-edit");
  await bulk.getByLabel("Field to change").selectOption({ label: "Comments" });
  await bulk.getByRole("button", { name: "Add", exact: true }).click();
  await bulk.getByLabel("Set to").fill(label("Checked"));
  const previewed = answer(page, "POST", "/items/bulk-update");
  await bulk.getByRole("button", { name: "Preview the change" }).click();
  await previewed;
  const counts = page.getByTestId("preview-counts");
  await expect(counts.locator('[data-count="updated"] dd')).toHaveText("1");
  await expect(counts.locator('[data-count="created"]')).toHaveCount(0);
  await expect(page.getByTestId("preview-rows").locator("caption")).toHaveText(
    "What each row would do, in the order of the items until a header is clicked",
  );
  await bulk.getByRole("button", { name: "Cancel" }).click();

  // The export of the list as it first stands holds the host name of each item.
  await page.getByText("Columns", { exact: true }).click();
  await page.getByRole("button", { name: "Reset layout and filters" }).click();
  await page.getByText("Columns", { exact: true }).click();
  await page.getByLabel("Filter", { exact: true }).fill(`hostname:prefix:${host("row-0")}`);
  const tenAgain = tenListed();
  await page.getByRole("button", { name: "Apply", exact: true }).click();
  await tenAgain;
  await expect(page.getByText("10 items", { exact: true })).toBeVisible();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export CSV" }).click();
  const file = await download;
  const path = testInfo.outputPath(file.suggestedFilename());
  await file.saveAs(path);
  const lines = (await readFile(path, "utf8")).replace(/\n$/, "").split("\n");
  expect(lines[0]?.split(",")).toContain("hostname");
  expect(lines.some((line) => line.includes(host("row-00")))).toBe(true);

  await expectClean(page, seen);
});
