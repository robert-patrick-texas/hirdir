// The browser scenarios of lane B of the second review of the web UI: a place's contacts
// first and one click to call or write (P-194), Home sooner and counts that open
// (P-195), plain words find a record (P-187), find a place (P-188) and the Scoreboard at
// size (P-196). 0.9.6: the sentence of a contact named elsewhere (P-197) is gone, and its
// scenario with it: the page lists every record that names a contact, which
// review-3b.spec.ts holds (P-205).
//
// The file keeps the rules of support.ts. It signs in as an Admin of its own, and its
// mark is in every name it gives a record: the region, the sites and their codes, the
// locations, the contacts and the items, all made through the API as that Admin. It
// changes no setting, no list of choices and no account, and counts only its own
// records: a total of the whole inventory is never compared with a number. The scenarios
// run in order and share the places the first one makes.

import type { APIRequestContext, Page, Response } from "@playwright/test";
import { expect } from "@playwright/test";
import { answer, listed, queried } from "./answers";
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

// P-309: each read of the server is waited for before what the page shows of it is
// expected, with answer, listed and queried of answers.ts.

/** The page's answer to a search of the items whose body holds each of `parts`. */
function itemsFound(page: Page, ...parts: string[]): Promise<Response> {
  return queried(page, "/items/query", ...parts);
}

/** The answers to a search of Find a place: the sites and the locations that match. */
function placesFound(page: Page, ...parts: string[]): Promise<Response[]> {
  return Promise.all([listed(page, "/sites", ...parts), listed(page, "/locations", ...parts)]);
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
  // What is in force at the site, its contacts among it, is read for the page.
  const inForce = answer(page, "GET", `/sites/${made.site}/effective`);
  await page.goto(`./geography/site/${made.site}`);
  await inForce;
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
  // Beside them, two the total does not count, of the same health: one in a state outside
  // count_states, and one of a kind outside count_kinds. A link of health alone would
  // open them too (B6 of the review of 0.9.5).
  await make(request, headers, "/items", { hostname: `hl-4-${id}`, lifecycle_state: "Delivered" });
  const vendor = (await make(request, headers, "/vendors", { name: label("Hollow Soft") })).hid;
  const software = (
    await make(request, headers, "/catalog-entries", {
      vendor_hid: vendor,
      pid: `HS-${id}`,
      kind: "software",
    })
  ).hid;
  await make(request, headers, "/items", { hostname: `hl-5-${id}`, catalog_entry_hid: software });
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
  // The totals, the summary of the whole inventory asked with nothing beside it.
  const totals = answer(
    page,
    "GET",
    "/reports/summary",
    (request) => new URL(request.url()).search === "",
  );
  await page.goto("./");
  await totals;
  await expect(page.getByTestId("total-components")).toBeVisible();
  await expect(page.getByTestId("unassigned")).toHaveCount(0);
  // A total of health is a link, where it counts any.
  const health = page.getByTestId("totals-by-health");
  await expect(health.getByRole("link").first()).toBeVisible();
  const byOperator = listed(page, "/reports/summary", "by=operator");
  release();
  await byOperator;
  await expect(page.getByTestId("unassigned")).toBeVisible();
  await page.unroute("**/api/v1/reports/summary?by=operator*");

  // On the summary, within its filter: the link opens the list of what it counted.
  const summary = listed(page, "/reports/summary", id);
  await page.goto(`./reports?filter=${encodeURIComponent(`hostname:contains:${id}`)}`);
  await summary;
  const cell = page.getByTestId("total-health-unknown");
  await expect(cell).toHaveText("3");
  const counted = itemsFound(page, id);
  await cell.getByRole("link").click();
  await expect(page).toHaveURL(/\/items\?/);
  await counted;
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
  const first = answer(page, "POST", "/items/query");
  await page.goto("./items");
  await first;
  const box = page.getByLabel("Filter", { exact: true });
  await expect(box).toBeVisible();
  /** Words in the filter box, and the list they find once the server has answered. */
  const search = async (words: string) => {
    await box.fill(words);
    const found = itemsFound(page, ...words.split(" "));
    await box.press("Enter");
    await found;
  };

  // Two words, each held by one of the fields an item is known by: no condition typed.
  await search(`core ${id}`);
  await expect(page.getByTestId("grid-total")).toHaveText("2 items");
  await expect(box).not.toHaveAttribute("aria-invalid", "true");
  // A serial number, in any case.
  await search(`sn${id}q`);
  await expect(page.getByTestId("grid-total")).toHaveText("1 item");

  // Words, then Export CSV: the file holds the rows shown, and no other.
  await search(`core ${id}`);
  await expect(page.getByTestId("grid-total")).toHaveText("2 items");
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export CSV" }).click();
  const file = await download;
  const path = testInfo.outputPath(file.suggestedFilename());
  await file.saveAs(path);
  const { readFile } = await import("node:fs/promises");
  const lines = (await readFile(path, "utf8")).replace(/\n$/, "").split("\n");
  expect(lines, "a header row and the two rows shown").toHaveLength(3);
  expect(
    lines
      .slice(1)
      .map((line) => line.split(",")[0])
      .sort(),
  ).toEqual([...words.core].sort());

  // Text that is neither words nor conditions is answered with the list's own example.
  const contactsListed = listed(page, "/contacts");
  await page.goto("./contacts");
  await contactsListed;
  const contacts = page.getByLabel("Filter", { exact: true });
  await contacts.fill(`rowan tags:has:${id}`);
  await contacts.press("Enter");
  await expect(contacts).toHaveAttribute("aria-invalid", "true");
  await expect(page.getByText(/as in organization:contains:Operations/).first()).toBeVisible();
  await expect(page.getByText(/lifecycle_state:in:Test,Prod/)).toHaveCount(0);
  // And words find a contact by its name or its email.
  await contacts.fill(`rowan.${id}@example`);
  const contactFound = listed(page, "/contacts", `rowan.${id}@example`);
  await contacts.press("Enter");
  await contactFound;
  await expect(page.getByTestId("grid-total")).toHaveText("1 contact");

  // Owners has the box the other lists have.
  const ownersListed = listed(page, "/owners");
  await page.goto("./owners");
  await ownersListed;
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
  const found = itemsFound(page, "core", id);
  await box.press("Enter");
  await found;
  await expect(page.getByTestId("grid-total")).toHaveText("2 items");
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
  const edge = itemsFound(page, "edge", id);
  await find.getByRole("searchbox", { name: "Find an item" }).press("Enter");
  await expect(page).toHaveURL(/\/items\?filter=edge%20.*&minor=1$/);
  await edge;
  await expect(page.getByTestId("grid-total")).toHaveText("1 item");
  await expect(page.getByLabel("Filter", { exact: true })).toHaveValue(`edge ${id}`);
  // The page begins at its top, with the keyboard in its content (P-167).
  expect(await page.evaluate(() => window.scrollY)).toBe(0);
  await expect(page.locator("main")).toBeFocused();

  // The same words again, after the list's own filter was changed: the list is made anew
  // with them (B5 of the review of 0.9.5).
  const grid = page.getByLabel("Filter", { exact: true });
  await grid.fill(`core ${id}`);
  const core = itemsFound(page, "core", id);
  await grid.press("Enter");
  await core;
  await expect(page.getByTestId("grid-total")).toHaveText("2 items");
  const findBox = find.getByRole("searchbox", { name: "Find an item" });
  await findBox.fill(`edge ${id}`);
  const edgeAgain = itemsFound(page, "edge", id);
  await findBox.press("Enter");
  await expect(grid).toHaveValue(`edge ${id}`);
  await edgeAgain;
  await expect(page.getByTestId("grid-total")).toHaveText("1 item");
  await expectClean(page, seen);
});

test("P-187: text that cannot be read never shows every item, from Find an item or in a link", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(120_000);
  await wordItems(request, account);
  const seen = await watch(page.context());
  await signIn(page, account);
  let reads = 0;
  page.on("request", (sent) => {
    if (sent.url().includes("/api/v1/items/query")) reads += 1;
  });

  // Find an item reads the text first: it stays on the page and says what is wrong.
  await page.goto("./about");
  const find = page.getByRole("search", { name: "Find an item" });
  const box = find.getByRole("searchbox", { name: "Find an item" });
  await box.fill("core:sw:01");
  await box.press("Enter");
  await expect(find.getByRole("alert")).toContainText("The short form is field:op:value");
  await expect(box).toHaveAttribute("aria-invalid", "true");
  await expect(box).toHaveValue("core:sw:01");
  await expect(page).toHaveURL(/\/about$/);

  // A list opened with that text says why at once, and asks for no row: nothing to count,
  // to select, to export or to edit in bulk.
  reads = 0;
  // The page asks for no row, but it is there, its grid with it, once it has read the
  // choices it offers: a busy server sends its scripts and that answer late (P-309).
  const ready = answer(page, "GET", "/choices");
  await page.goto(`./items?filter=${encodeURIComponent("core:sw:01")}&minor=1`);
  await ready;
  const filter = page.getByLabel("Filter", { exact: true });
  await expect(filter).toHaveAttribute("aria-invalid", "true");
  await expect(page.getByText(/^Words alone find a record by its/)).toBeVisible();
  await expect(page.getByTestId("grid-total")).toHaveText(
    "No items are shown: the filter in force cannot be read",
  );
  for (const name of ["Select all that match", "Export CSV", "Export JSON"]) {
    await expect(page.getByRole("button", { name, exact: true })).toBeDisabled();
  }
  await expect(page.getByTestId("grid-items").locator(".ag-row")).toHaveCount(0);
  expect(reads, "no row was asked for").toBe(0);

  // Text that reads takes its place, and the rows come.
  await filter.fill(`edge ${id}`);
  const edge = itemsFound(page, "edge", id);
  await filter.press("Enter");
  await edge;
  await expect(page.getByTestId("grid-total")).toHaveText("1 item");
  await expect(filter).not.toHaveAttribute("aria-invalid", "true");
  await expectClean(page, seen);
});

test("P-188: Find a place lists the sites and the locations, a location narrowed by its site, each a link, with how many more", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(180_000);
  const headers = await places(request, account);
  await make(request, headers, "/locations", {
    name: label("Draft bay"),
    site_hid: made.site,
    record_status: "draft",
  });
  const gone = await make(request, headers, "/locations", {
    name: label("Old bay"),
    site_hid: made.site,
  });
  const retired = await request.post(`./api/v1/locations/${gone.hid}/retire`, {
    headers,
    data: { row_version: 1 },
  });
  expect(retired.status(), await retired.text()).toBe(200);
  for (let n = 1; n <= 11; n++) {
    await make(request, headers, "/locations", { name: `Shelf ${n} ${id}`, site_hid: made.site });
  }
  const seen = await watch(page.context());
  await signIn(page, account);
  await page.goto("./geography");
  const find = page.getByRole("search", { name: "Find a place" });
  const box = find.getByRole("searchbox", { name: "Find a place" });
  const sites = find.getByRole("list", { name: "Sites that match" });
  const locations = find.getByRole("list", { name: "Locations that match" });

  /**
   * Words in Find a place, and what it finds once the server has answered both of its
   * searches: `sent` is a word of what is typed that the one before did not hold.
   */
  const search = async (typed: string, sent: string) => {
    const found = placesFound(page, sent, id);
    await box.fill(typed);
    await found;
  };

  // By its code: the location, by its path; no site has that code.
  await search(`C4-${id}`, "C4-");
  await expect(locations.getByRole("link")).toHaveText([
    `${label("Eastmarch")} > ${label("Quarry Point")} > ${label("Cage 4")}`,
  ]);
  await expect(sites).toContainText("No site matches.");

  // By its name: the site, a draft marked as one, and no retired place.
  await search(`bay ${id}`, "bay");
  await expect(locations.getByRole("listitem")).toHaveCount(1);
  await expect(locations.getByRole("listitem")).toContainText(label("Draft bay"));
  await expect(locations.getByRole("listitem")).toContainText("Draft");
  await expect(locations).not.toContainText(label("Old bay"));

  // The site named with the room narrows it, by the site's code or as a path is pasted
  // (B3 of the review of 0.9.5).
  const cage = `${label("Eastmarch")} > ${label("Quarry Point")} > ${label("Cage 4")}`;
  await search(`QP-${id} cage`, "QP-");
  await expect(locations.getByRole("link")).toHaveText([cage]);
  await search(`${label("Quarry Point")} > Cage`, "Point");
  await expect(locations.getByRole("link")).toHaveText([cage]);

  // Ten of each, and how many more match.
  await search(`Shelf ${id}`, "Shelf");
  await expect(locations.getByRole("link")).toHaveCount(10);
  await expect(locations).toContainText("1 more location matches.");

  // A site by its name, Enter as well as a pause, and the link opens its page.
  await box.fill(`Quarry ${id}`);
  await box.press("Enter");
  await sites.getByRole("link", { name: new RegExp(label("Quarry Point")) }).click();
  await expect(page).toHaveURL(new RegExp(`/geography/site/${made.site}`));
  // The tree beneath is as it was.
  await expect(page.getByRole("heading", { name: "Regions, sites and locations" })).toBeVisible();

  // With Retired places on in the view, a retired place is found, and marked (B8).
  await page.goto("./geography?archived=1");
  await search(`bay ${id}`, "bay");
  await expect(locations.getByRole("listitem")).toHaveCount(2);
  await expect(locations.getByRole("listitem").filter({ hasText: label("Old bay") })).toContainText(
    "Retired",
  );
  await expectClean(page, seen);
});

test("P-196: the Scoreboard links to its tables, shows twenty rows of a long one, and keeps the rest for Show all", async ({
  page,
  account,
  request,
}, testInfo) => {
  test.setTimeout(240_000);
  const headers = await places(request, account);
  // Twenty-two groups of the file's own items: the first with three, the others with one.
  const groupNames: string[] = [];
  for (let n = 1; n <= 22; n++) {
    const members = [];
    for (let m = 1; m <= (n === 1 ? 3 : 1); m++) {
      const host = `grp-${n}-${m}-${id}`;
      const item = await make(request, headers, "/items", { hostname: host });
      members.push({ item_hid: item.hid });
    }
    const name = label(`Ring ${String(n).padStart(2, "0")}`);
    await make(request, headers, "/device-groups", { type: "custom", name, members });
    groupNames.push(name);
  }
  const seen = await watch(page.context());
  await signIn(page, account);
  // Words as the view: the items of the file's groups. The three tables are counted at
  // once, by operator, by site and by group, which a busy server answers late: each count
  // is waited for, and then what the page shows of it.
  const counted = () =>
    Promise.all(
      ["operator", "site", "group"].map((by) =>
        listed(page, "/reports/summary", `by=${by}`, "grp", id),
      ),
    );
  const first = counted();
  await page.goto(`./reports/scoreboard?${new URLSearchParams({ filter: `grp ${id}` })}`);
  await first;

  const tables = page.getByRole("navigation", { name: "The tables of the scoreboard" });
  await expect(tables.getByRole("link")).toHaveText([
    "Operators",
    "How each operator has its items",
    "Groups",
    "Sites",
  ]);
  const groups = page.getByTestId("score-groups");
  const rows = groups.locator("tbody tr");
  await expect(rows).toHaveCount(20);
  // The link brings the table into the window, and the keyboard to it. The address is
  // the router's, so that a path prefix is kept (B1 of the review of 0.9.5).
  const before = new URL(page.url());
  const keyOf = () => page.evaluate(() => (window.history.state as { key?: string } | null)?.key);
  const keyBefore = await keyOf();
  await tables.getByRole("link", { name: "Groups" }).click();
  await expect(page.getByRole("heading", { name: "Groups", exact: true })).toBeFocused();
  await expect(page.getByRole("heading", { name: "Groups", exact: true })).toBeInViewport();
  const after = new URL(page.url());
  expect(after.pathname).toBe(before.pathname);
  expect(after.search).toBe(before.search);
  expect(after.hash).toBe("#score-groups");
  // A move the router made has a key of its own; an address written past it keeps the old.
  expect(await keyOf(), "the router made the move").not.toBe(keyBefore);

  // The first, with the most weight, is first; the rank is of all the rows.
  await expect(rows.first()).toHaveAttribute("data-label", label("Ring 01"));
  await expect(rows.first().locator('[data-measure="rank"]')).toHaveText("1");
  // The operators involved are a number, with the list behind it.
  await expect(rows.first().getByTestId("involved-count")).toHaveText("Nobody is assigned");
  await expect(rows.first().getByTestId("involved")).toBeHidden();
  await rows.first().getByTestId("involved-count").click();
  await expect(rows.first().getByTestId("involved")).toBeVisible();

  // A sort is of all the rows: the fewest items first puts Ring 01 last, out of the twenty.
  const itemsHeader = groups.getByRole("columnheader", { name: "Items", exact: true });
  await groups.getByRole("button", { name: "Items", exact: true }).click();
  if ((await itemsHeader.getAttribute("aria-sort")) !== "ascending") {
    await groups.getByRole("button", { name: "Items", exact: true }).click();
  }
  await expect(itemsHeader).toHaveAttribute("aria-sort", "ascending");
  await expect(rows).toHaveCount(20);
  await expect(groups.locator(`tbody tr[data-label="${label("Ring 01")}"]`)).toHaveCount(0);

  // A file saved holds all the rows.
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export CSV of the groups" }).click();
  const file = await download;
  const path = testInfo.outputPath(file.suggestedFilename());
  await file.saveAs(path);
  const { readFile } = await import("node:fs/promises");
  const text = await readFile(path, "utf8");
  for (const name of groupNames) expect(text).toContain(name);

  // Show all: the twenty-two, Ring 01 last.
  await page.getByRole("button", { name: "Show all 22 groups" }).click();
  await expect(rows).toHaveCount(22);
  await expect(rows.last()).toHaveAttribute("data-label", label("Ring 01"));

  // Opened at an address that names a table, the page stands at that table.
  await page.goto("./about");
  const again = counted();
  await page.goto(
    `./reports/scoreboard?${new URLSearchParams({ filter: `grp ${id}` })}#score-sites`,
  );
  await again;
  const sitesHeading = page.getByRole("heading", { name: "Sites", exact: true });
  await expect(sitesHeading).toBeFocused();
  await expect(sitesHeading).toBeInViewport();
  expect(await page.evaluate(() => window.scrollY)).toBeGreaterThan(0);
  await expectClean(page, seen);
});
