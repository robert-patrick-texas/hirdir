// The browser scenarios of lane B of the second review of the web UI: a place's contacts
// first and one click to call or write (P-194), Home sooner and counts that open
// (P-195), plain words find a record (P-187), find a place (P-188), the Scoreboard at
// size (P-196) and a contact named elsewhere (P-197).
//
// The file keeps the rules of support.ts. It signs in as an Admin of its own, and its
// mark is in every name it gives a record: the region, the sites and their codes, the
// locations, the contacts and the items, all made through the API as that Admin. It
// changes no setting, no list of choices and no account, and counts only its own
// records: a total of the whole inventory is never compared with a number. The scenarios
// run in order and share the places the first one makes.

import type { APIRequestContext, Page } from "@playwright/test";
import { expect } from "@playwright/test";
import { type Account, expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const id = mark("review-2b");
const label = (name: string) => `${name} ${id}`;

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

// What the first scenario makes, which the others use.
const made: { region?: string; site?: string; location?: string; contact?: string } = {};

async function places(request: APIRequestContext, account: Account): Promise<Headers> {
  const headers = await session(request, account);
  if (made.region === undefined) {
    made.region = (await make(request, headers, "/regions", { name: label("Eastmarch") })).hid;
    made.site = (
      await make(request, headers, "/sites", {
        name: label("Quarry Point"),
        code: `QP-${id}`,
        region_hid: made.region,
      })
    ).hid;
    made.location = (
      await make(request, headers, "/locations", {
        name: label("Cage 4"),
        code: `C4-${id}`,
        site_hid: made.site,
      })
    ).hid;
    made.contact = (
      await make(request, headers, "/contacts", {
        name: label("Rowan Vale"),
        email: `rowan.${id}@example.org`,
        phone: "+1 555 0142 ext. 7",
      })
    ).hid;
    await make(request, headers, "/contact-assignments", {
      contact_hid: made.contact,
      site_hid: made.site,
      role: "technical",
    });
  }
  return headers;
}

async function top(page: Page, name: string): Promise<number> {
  const box = await page.getByRole("heading", { name, exact: true }).boundingBox();
  expect(box, `the heading ${name} is on the page`).not.toBeNull();
  return box?.y ?? 0;
}

test("P-194: a site's contacts stand above its files, and its email and number are links", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(120_000);
  await places(request, account);
  const seen = await watch(page.context());
  await signIn(page, account);
  await page.goto(`./geography/site/${made.site}`);
  const contacts = page.getByTestId("in-force-contacts");
  const row = contacts.locator('tr[data-role="technical"]');
  await expect(row.getByRole("link", { name: label("Rowan Vale") })).toBeVisible();

  expect(await top(page, "In force"), "what is in force comes before the files").toBeLessThan(
    await top(page, "Files and links"),
  );
  await expect(row.getByRole("link", { name: `rowan.${id}@example.org` })).toHaveAttribute(
    "href",
    `mailto:rowan.${id}@example.org`,
  );
  // The extension is not dialled.
  await expect(row.getByRole("link", { name: "+1 555 0142 ext. 7" })).toHaveAttribute(
    "href",
    "tel:+15550142",
  );
  await expectClean(page, seen);
});

test("P-195: Home shows its totals before the summary by operator, and a total of health opens what it counts", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(180_000);
  const headers = await places(request, account);
  for (const n of [1, 2, 3]) {
    await make(request, headers, "/items", { hostname: `hl-${n}-${id}` });
  }
  const seen = await watch(page.context());
  await signIn(page, account);

  // The summary by operator is held back, as on a busy server: the totals do not wait.
  let release: () => void = () => {};
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/v1/reports/summary?by=operator*", async (route) => {
    await held;
    await route.continue();
  });
  await page.goto("./");
  await expect(page.getByTestId("total-components")).toBeVisible();
  await expect(page.getByTestId("unassigned")).toHaveCount(0);
  // A total of health is a link, where it counts any.
  const health = page.getByTestId("totals-by-health");
  await expect(health.getByRole("link").first()).toBeVisible();
  release();
  await expect(page.getByTestId("unassigned")).toBeVisible();
  await page.unroute("**/api/v1/reports/summary?by=operator*");

  // On the summary, within its filter: the link opens the list of what it counted.
  await page.goto(`./reports?filter=${encodeURIComponent(`hostname:contains:${id}`)}`);
  const cell = page.getByTestId("total-health-unknown");
  await expect(cell).toHaveText("3");
  await cell.getByRole("link").click();
  await expect(page).toHaveURL(/\/items\?/);
  await expect(page.getByTestId("grid-total")).toHaveText("3 items");
  await expectClean(page, seen);
});

// The items the scenarios of words find, by host name and by serial number.
const words = { made: false, core: [] as string[] };

async function wordItems(request: APIRequestContext, account: Account) {
  const headers = await places(request, account);
  if (!words.made) {
    for (const host of [`core-${id}-1`, `core-${id}-2`, `edge-${id}-1`]) {
      const { hid } = await make(request, headers, "/items", { hostname: host });
      if (host.startsWith("core")) words.core.push(hid);
    }
    await make(request, headers, "/items", { name: label("Spare"), serial_number: `SN${id}Q` });
    words.made = true;
  }
}

test("P-187: plain words in the filter box find items, and Export CSV holds the rows shown", async ({
  page,
  account,
  request,
}, testInfo) => {
  test.setTimeout(180_000);
  await wordItems(request, account);
  const seen = await watch(page.context());
  await signIn(page, account);
  await page.goto("./items");
  const box = page.getByLabel("Filter", { exact: true });
  await expect(box).toBeVisible();

  // Two words, each held by one of the fields an item is known by: no condition typed.
  await box.fill(`core ${id}`);
  await box.press("Enter");
  await expect(page.getByTestId("grid-total")).toHaveText("2 items");
  await expect(box).not.toHaveAttribute("aria-invalid", "true");
  // A serial number, in any case.
  await box.fill(`sn${id}q`);
  await box.press("Enter");
  await expect(page.getByTestId("grid-total")).toHaveText("1 item");

  // Words, then Export CSV: the file holds the rows shown, and no other.
  await box.fill(`core ${id}`);
  await box.press("Enter");
  await expect(page.getByTestId("grid-total")).toHaveText("2 items");
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export CSV" }).click();
  const file = await download;
  const path = testInfo.outputPath(file.suggestedFilename());
  await file.saveAs(path);
  const { readFile } = await import("node:fs/promises");
  const lines = (await readFile(path, "utf8")).replace(/\n$/, "").split("\n");
  expect(lines, "a header row and the two rows shown").toHaveLength(3);
  expect(lines.slice(1).map((line) => line.split(",")[0]).sort()).toEqual([...words.core].sort());

  // Text that is neither words nor conditions is answered with the list's own example.
  await page.goto("./contacts");
  const contacts = page.getByLabel("Filter", { exact: true });
  await contacts.fill(`rowan tags:has:${id}`);
  await contacts.press("Enter");
  await expect(contacts).toHaveAttribute("aria-invalid", "true");
  await expect(page.getByText(/as in organization:contains:Operations/).first()).toBeVisible();
  await expect(page.getByText(/lifecycle_state:in:Test,Prod/)).toHaveCount(0);
  // And words find a contact by its name or its email.
  await contacts.fill(`rowan.${id}@example`);
  await contacts.press("Enter");
  await expect(page.getByTestId("grid-total")).toHaveText("1 contact");

  // Owners has the box the other lists have.
  await page.goto("./owners");
  await expect(page.getByLabel("Filter", { exact: true })).toBeVisible();
  await expectClean(page, seen);
});

test("P-187: words typed while the list is still being read on a busy server still find the items", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(180_000);
  await wordItems(request, account);
  const seen = await watch(page.context());
  await signIn(page, account);
  // Every read of the item list answers late.
  await page.route("**/api/v1/items/query", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 1500));
    await route.continue().catch(() => {});
  });
  await page.goto("./items");
  const box = page.getByLabel("Filter", { exact: true });
  // Before the whole list has come, twice: each read that is let go is ended.
  await box.fill(`edge ${id}`);
  await box.press("Enter");
  await page.getByRole("button", { name: "Clear" }).click();
  await box.fill(`core ${id}`);
  await box.press("Enter");
  await expect(page.getByTestId("grid-total")).toHaveText("2 items", { timeout: 20_000 });
  await page.unroute("**/api/v1/items/query");
  await expectClean(page, seen);
});

test("P-187: Find an item, in the menu bar of every page, opens the items with those words", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(120_000);
  await wordItems(request, account);
  const seen = await watch(page.context());
  await page.setViewportSize({ width: 1280, height: 800 });
  await signIn(page, account);
  await page.goto("./about");
  const find = page.getByRole("search", { name: "Find an item" });
  // On the row of who is signed in: the menu bar is no taller for it.
  const signOut = await page.getByRole("button", { name: "Sign out" }).boundingBox();
  const box = await find.boundingBox();
  expect(box && signOut && Math.abs(box.y - signOut.y) < 4, "on the row of Sign out").toBe(true);

  await page.evaluate(() => window.scrollTo(0, 200));
  await find.getByRole("searchbox", { name: "Find an item" }).fill(`edge ${id}`);
  await find.getByRole("searchbox", { name: "Find an item" }).press("Enter");
  await expect(page).toHaveURL(/\/items\?filter=edge%20.*&minor=1$/);
  await expect(page.getByTestId("grid-total")).toHaveText("1 item");
  await expect(page.getByLabel("Filter", { exact: true })).toHaveValue(`edge ${id}`);
  // The page begins at its top, with the keyboard in its content (P-167).
  expect(await page.evaluate(() => window.scrollY)).toBe(0);
  await expect(page.locator("main")).toBeFocused();
  await expectClean(page, seen);
});
