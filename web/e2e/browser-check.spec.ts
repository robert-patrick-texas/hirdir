// The short browser check of the package through nginx (P-305, P-309): what only the
// installed package can get wrong, which the passes of packaging/package-test.sh that
// talk to the API with curl cannot see, in four scenarios that build on one another:
//
//   1. Signing in under the prefix: the page says the prefix as its base, and every file
//      it fetches, the scripts, the stylesheet, the icon and the API, is fetched from
//      under it; no response sets a cookie.
//   2. A list: the items of this file, made through the API, in the grid filtered down
//      to them, read through nginx.
//   3. A download: that list exported as CSV, fetched under the prefix and saved under
//      the name the server gives it.
//   4. A page reached by its address: an item's page, opened from the grid and reloaded,
//      and opened afresh by its address in a browser that has no session, which signs in
//      on that page and stays there; every part of the page is fetched from under the
//      prefix, from however deep an address.
//
// The package test runs this file alone, as the pass --browser-check, against a fresh
// install behind nginx under /hirdir/; --e2e and the browser scenarios on the host run
// it beside the others, at the root of a development server too, where the prefix is /.
//
// How this file keeps to the rules of support.ts: it signs in as an Admin of its own,
// makes one vendor, one catalog entry and two items, under its mark, changes nothing
// else, and reads its own items alone, the grid filtered down to them.

import { readFile } from "node:fs/promises";
import { type APIRequestContext, expect, type Page } from "@playwright/test";
import { main } from "./structure";
import { type Account, expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const id = mark("browser-check");
const vendor = `Example Networks ${id}`;
const pid = `EN-2200-24P-${id}`;
const hosts = [`${id}-sw-01`, `${id}-sw-02`];
const serials = hosts.map((_, place) => `BCK${id.slice(-6).toUpperCase()}0${place + 1}`);
const filter = `hostname:prefix:${id}-sw-`;

/** What the scenarios made, for the ones after. */
const made: { items: string[] } = { items: [] };

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
): Promise<string> {
  const answer = await request.post(`./api/v1${path}`, { headers, data });
  expect(answer.status(), `POST ${path}: ${await answer.text()}`).toBe(201);
  return ((await answer.json()) as { hid: string }).hid;
}

/**
 * Every address a page asks the server for, from now on, beside where it was asked
 * from: the requests of the browser itself, as for a file saved from memory, are not.
 */
function fetched(page: Page): string[] {
  const asked: string[] = [];
  page.on("request", (request) => {
    const url = request.url();
    if (url.startsWith("http:") || url.startsWith("https:")) asked.push(url);
  });
  return asked;
}

/** The addresses asked for that are not under the base address of the app. */
function outside(asked: readonly string[], base: URL): string[] {
  return asked.filter((url) => {
    const at = new URL(url);
    return at.origin !== base.origin || !at.pathname.startsWith(base.pathname);
  });
}

/** The paths asked for, under the base address, without it: `assets/index-….js`. */
function under(asked: readonly string[], base: URL): string[] {
  return asked
    .map((url) => new URL(url).pathname)
    .filter((path) => path.startsWith(base.pathname))
    .map((path) => path.slice(base.pathname.length));
}

/** The base address of the app, from the configuration, ending in a slash. */
function baseOf(baseURL: string | undefined): URL {
  expect(baseURL, "the base address of the app").toBeTruthy();
  return new URL(baseURL ?? "");
}

/** Rows of cells of CSV text with no quoted line breaks, which these rows have none of. */
function rowsOf(text: string): string[][] {
  return text
    .split(/\r?\n/)
    .filter((line) => line !== "")
    .map((line) => line.split(",").map((cell) => cell.replace(/^"(.*)"$/, "$1")));
}

test("signing in under the prefix: the page, its files and the API are all under it, and no cookie is set", async ({
  page,
  baseURL,
  account,
}) => {
  test.setTimeout(60_000);
  const base = baseOf(baseURL);
  const seen = await watch(page.context());
  const asked = fetched(page);
  await signIn(page, account);

  // The page names the prefix as its base, which the server writes into it.
  expect(new URL(await page.evaluate(() => document.baseURI)).pathname).toBe(base.pathname);
  expect(new URL(page.url()).pathname).toBe(base.pathname);
  // Its script, its stylesheet and its icon, and the sign-in and the account, all from
  // under the prefix, and nothing from anywhere else.
  expect(outside(asked, base), "addresses asked for outside the prefix").toEqual([]);
  const paths = under(asked, base);
  expect(paths.filter((path) => /^assets\/[^/]+\.js$/.test(path)).length).toBeGreaterThan(0);
  expect(paths.filter((path) => /^assets\/[^/]+\.css$/.test(path)).length).toBeGreaterThan(0);
  expect(paths).toContain("api/v1/auth/sign-in");
  expect(paths).toContain("api/v1/auth/me");
  await expectClean(page, seen);
});

test("a list: the grid of this file's items, read through nginx under the prefix", async ({
  page,
  baseURL,
  account,
  request,
}) => {
  test.setTimeout(60_000);
  const base = baseOf(baseURL);
  const headers = await session(request, account);
  const vendorHid = await make(request, headers, "/vendors", { name: vendor });
  const entry = await make(request, headers, "/catalog-entries", { vendor_hid: vendorHid, pid });
  for (const [place, hostname] of hosts.entries()) {
    made.items.push(
      await make(request, headers, "/items", {
        catalog_entry_hid: entry,
        hostname,
        serial_number: serials[place],
      }),
    );
  }

  const seen = await watch(page.context());
  const asked = fetched(page);
  await signIn(page, account);
  await main(page).getByRole("link", { name: "Items" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Items" })).toBeVisible();
  await page.goto(`./items?filter=${encodeURIComponent(filter)}`);
  const grid = page.getByTestId("grid-items");
  await expect(page.getByTestId("grid-total")).toHaveText("2 items");
  for (const hostname of hosts) {
    await expect(grid.getByRole("link", { name: hostname, exact: true })).toBeVisible();
  }
  expect(new URL(page.url()).pathname).toBe(`${base.pathname}items`);
  expect(outside(asked, base), "addresses asked for outside the prefix").toEqual([]);
  const items = under(asked, base).filter((path) => path.startsWith("api/v1/items"));
  expect(items.length, "the grid's rows asked of the API under the prefix").toBeGreaterThan(0);
  await expectClean(page, seen);
});

test("a download: the list exported as CSV under the prefix, saved under the server's name", async ({
  page,
  baseURL,
  account,
}, testInfo) => {
  test.setTimeout(60_000);
  const base = baseOf(baseURL);
  const seen = await watch(page.context());
  const asked = fetched(page);
  await signIn(page, account);
  await page.goto(`./items?filter=${encodeURIComponent(filter)}`);
  await expect(page.getByTestId("grid-total")).toHaveText("2 items");

  const exported = page.waitForRequest(
    (sent) =>
      sent.method() === "POST" && new URL(sent.url()).pathname === `${base.pathname}api/v1/exports`,
  );
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export CSV" }).click();
  await exported;
  const file = await download;
  expect(file.suggestedFilename()).toMatch(/^hirdir-items-[^/]+\.csv$/);
  const path = testInfo.outputPath(file.suggestedFilename());
  await file.saveAs(path);
  const rows = rowsOf(await readFile(path, "utf8"));
  // A header row and the two items, each by its HID, whatever columns are on show.
  expect(rows[0]?.[0]).toBe("hid");
  expect(rows.slice(1).map((row) => row[0])).toEqual(expect.arrayContaining(made.items));
  expect(rows).toHaveLength(3);
  await expect(page.getByText(`Exported to ${file.suggestedFilename()}.`)).toBeVisible();
  expect(outside(asked, base), "addresses asked for outside the prefix").toEqual([]);
  await expectClean(page, seen);
});

test("a page reached by its address: an item's page under the prefix, reloaded, and opened afresh", async ({
  page,
  baseURL,
  account,
  browser,
}) => {
  test.setTimeout(90_000);
  const base = baseOf(baseURL);
  const [hostname] = hosts;
  const [hid] = made.items;
  expect(hid, "the item the list made").toBeTruthy();
  const address = `${base.pathname}items/${hid}`;
  const seen = await watch(page.context());
  await signIn(page, account);
  await page.goto(`./items?filter=${encodeURIComponent(filter)}`);
  await page.getByTestId("grid-items").getByRole("link", { name: hostname, exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: hostname })).toBeVisible();
  expect(new URL(page.url()).pathname).toBe(address);

  // Reloaded, the address is asked of the server, through nginx: the same page comes
  // back, still signed in, with its parts fetched from under the prefix, not from under
  // items/, which a page two levels deep would ask for if its base were wrong.
  const asked = fetched(page);
  await page.reload();
  await expect(page.getByRole("heading", { level: 1, name: hostname })).toBeVisible();
  await expect(page.locator(".who-name")).toHaveText(account.username);
  expect(new URL(page.url()).pathname).toBe(address);
  expect(new URL(await page.evaluate(() => document.baseURI)).pathname).toBe(base.pathname);
  expect(outside(asked, base), "addresses asked for outside the prefix").toEqual([]);
  const paths = under(asked, base);
  expect(paths).toContain(`items/${hid}`);
  expect(paths.filter((path) => path.startsWith("items/") && path !== `items/${hid}`)).toEqual([]);
  expect(paths.filter((path) => /^assets\/[^/]+\.js$/.test(path)).length).toBeGreaterThan(1);
  await expectClean(page, seen);

  // Opened by its address in a browser with no session, as a link that somebody sends:
  // the sign-in page is shown there, and signing in shows the item, at that address.
  const context = await browser.newContext();
  try {
    const fresh = await context.newPage();
    const freshSeen = await watch(context);
    const freshAsked = fetched(fresh);
    await fresh.goto(`./items/${hid}`);
    await expect(
      fresh.getByRole("heading", { level: 1, name: "Sign in to hirdir", exact: true }),
    ).toBeVisible();
    await fresh.getByLabel("Username").fill(account.username);
    await fresh.getByLabel("Access code").fill(account.accessCode);
    await fresh.getByRole("button", { name: "Sign in" }).click();
    await expect(fresh.getByRole("heading", { level: 1, name: hostname })).toBeVisible({
      timeout: 20_000,
    });
    expect(new URL(fresh.url()).pathname).toBe(address);
    expect(outside(freshAsked, base), "addresses asked for outside the prefix").toEqual([]);
    await expectClean(fresh, freshSeen);
  } finally {
    await context.close();
  }
});
