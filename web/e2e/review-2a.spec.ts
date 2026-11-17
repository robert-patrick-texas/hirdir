// The browser scenarios of the second review of the web UI, lane A, P-189 to P-193: the
// list of items says where each is, the form of standing offers what the state allows,
// an item's page leads to what is near it and to its state, the buttons of a form stay
// in reach and a new form takes the keyboard, and a new item is made again like the last.
//
// The file keeps the rules of support.ts. It signs in as an Admin of its own, and its
// mark is in every name it gives a record: the region, the site, the locations, the
// vendor, the catalog entry and the items, all made through the API as that Admin, but
// for the items the last scenario makes through the form. It changes no setting, no list
// of choices, no lifecycle rule and no account, and reads only its own records. The
// scenarios need nothing of each other but the places the first one makes, and run in
// order.

import type { APIRequestContext, Locator, Page } from "@playwright/test";
import { expect } from "@playwright/test";
import { type Account, createAccount, expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const id = mark("review-2a");
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

// What the first scenario makes, which the others use.
const made: {
  site?: string;
  location?: string;
  other?: string;
  pid?: string;
  item?: string;
} = {};

async function places(request: APIRequestContext, account: Account): Promise<Headers> {
  const headers = await session(request, account);
  if (made.item === undefined) {
    const region = (await make(request, headers, "/regions", { name: label("Eastmarch") })).hid;
    made.site = (
      await make(request, headers, "/sites", {
        name: label("Kiln Lane"),
        code: `KL-${id}`,
        region_hid: region,
      })
    ).hid;
    made.location = (
      await make(request, headers, "/locations", { name: label("Room 4"), site_hid: made.site })
    ).hid;
    made.other = (
      await make(request, headers, "/locations", { name: label("Room 5"), site_hid: made.site })
    ).hid;
    const vendor = (await make(request, headers, "/vendors", { name: label("Example Gear") })).hid;
    made.pid = `EG-24T-${id}`;
    await make(request, headers, "/catalog-entries", { vendor_hid: vendor, pid: made.pid });
    made.item = (
      await make(request, headers, "/items", {
        hostname: host("kiln-sw-01"),
        location_hid: made.location,
      })
    ).hid;
    await make(request, headers, "/items", {
      hostname: host("kiln-sw-02"),
      location_hid: made.other,
    });
  }
  return headers;
}

function region(page: Page, name: string): Locator {
  return page.getByRole("region", { name, exact: true });
}

async function openItem(page: Page, hid: string, name: string) {
  await page.goto(`./items/${hid}`);
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
}

test("the list of items says where each is, and keeps a layout a person has changed (P-193)", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(120_000);
  await places(request, account);
  const seen = await watch(page.context());
  await signIn(page, account);
  await page.goto(`./items?filter=${encodeURIComponent(`hostname:prefix:${host("kiln-sw-")}`)}`);
  const grid = page.getByTestId("grid-items");
  const header = (column: string) => grid.locator(`[role="columnheader"][col-id="${column}"]`);
  const row = (name: string) => grid.locator("[row-id]", { hasText: host(name) });
  await expect(row("kiln-sw-01")).toBeVisible();
  // Both are drawn from the start, past the operator, and Expected online is not.
  await expect(header("location.name")).toHaveCount(1);
  await expect(header("expected_online")).toHaveCount(0);
  await page.getByText("Columns", { exact: true }).click();
  const shown = page.getByRole("group", { name: "Columns to show" });
  const choice = (column: string) => shown.getByLabel(column, { exact: true });
  await expect(choice("Location")).toBeChecked();
  await expect(choice("Site")).toBeChecked();
  // Expected online is in the column chooser, as any other is.
  await expect(choice("Expected online")).not.toBeChecked();
  // The grid draws only the columns in view: room is made for the two by hiding four.
  for (const column of ["Vendor", "PID", "Serial number", "State"]) await choice(column).uncheck();
  await page.getByText("Columns", { exact: true }).click();
  await expect(header("location.name")).toBeInViewport();
  await expect(header("site")).toBeInViewport();
  await expect(row("kiln-sw-01").locator('[col-id="location.name"]')).toHaveText(label("Room 4"));
  await expect(row("kiln-sw-02").locator('[col-id="location.name"]')).toHaveText(label("Room 5"));
  await expect(row("kiln-sw-01").locator('[col-id="site"]')).toHaveText(label("Kiln Lane"));

  // A layout a person has changed is kept as it was left: the site hidden again stays so.
  await page.getByText("Columns", { exact: true }).click();
  await choice("Site").uncheck();
  await page.getByText("Columns", { exact: true }).click();
  await expect(header("site")).toHaveCount(0);
  await page.reload();
  await expect(row("kiln-sw-01")).toBeVisible();
  await expect(header("location.name")).toBeInViewport();
  await expect(header("site")).toHaveCount(0);
  await page.getByText("Columns", { exact: true }).click();
  await expect(choice("Site")).not.toBeChecked();
  await expect(choice("Vendor")).not.toBeChecked();
  await expect(choice("Location")).toBeChecked();

  await expectClean(page, seen);
});

/** The options a select offers, by their words. */
async function offered(select: Locator): Promise<string[]> {
  return select.locator("option").allTextContents();
}

test("the form of standing offers only what the state of the item allows (P-191)", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(120_000);
  const headers = await places(request, account);
  const prod = await make(request, headers, "/items", {
    hostname: host("kiln-sw-prod"),
    lifecycle_state: "Prod",
    location_hid: made.location,
  });
  const seen = await watch(page.context());
  await signIn(page, account);
  // The rules come late, as on a busy server: the form offers all until they are read.
  let release = () => {};
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/v1/lifecycle-rules*", async (route) => {
    await held;
    await route.continue();
  });
  await openItem(page, prod.hid, host("kiln-sw-prod"));
  const standing = region(page, "Change the disposition or the intent");
  const disposition = standing.getByLabel("Disposition");
  const online = standing.getByLabel("Expected online");
  await expect(disposition).toHaveValue("Production");
  await expect
    .poll(() => offered(disposition))
    .toEqual(["None", "Staging", "Production", "Spare", "Excess"]);
  release();
  // The rule of Prod: Production or Spare, and a Production item is expected online.
  await expect.poll(() => offered(disposition)).toEqual(["Production", "Spare"]);
  expect(await offered(online)).toEqual(["Yes"]);
  await page.unroute("**/api/v1/lifecycle-rules*");

  // A spare may be either.
  await disposition.selectOption("Spare");
  await expect.poll(() => offered(online)).toEqual(["Yes", "No"]);
  await online.selectOption({ label: "No" });
  await standing.getByRole("button", { name: "Save standing" }).click();
  await expect(page.getByTestId("disposition")).toHaveText("Spare");
  await expect(page.getByTestId("intent")).toHaveText("Expected offline");

  // Back to Production: the intent the item has is still shown, and gives way to Yes.
  await expect(online).toHaveValue("false");
  await disposition.selectOption("Production");
  await expect(online).toHaveValue("true");
  await standing.getByRole("button", { name: "Save standing" }).click();
  await expect(page.getByTestId("disposition")).toHaveText("Production");
  await expect(page.getByTestId("intent")).toHaveText("Expected online");
  expect(await offered(online)).toEqual(["Yes"]);

  await expectClean(page, seen);
});

test("from an item to the items near it, to its state, to its comments and to its sections (P-189)", async ({
  page,
  browser,
  account,
  request,
}) => {
  test.setTimeout(120_000);
  const headers = await places(request, account);
  const edge = await make(request, headers, "/items", {
    hostname: host("kiln-sw-edge"),
    lifecycle_state: "Prod",
    location_hid: made.location,
  });
  const seen = await watch(page.context());
  await signIn(page, account);
  await openItem(page, edge.hid, host("kiln-sw-edge"));
  const identity = region(page, "Identity");

  // Its standing among the first facts, with Change, which moves to the form of a move.
  await expect(identity.getByTestId("standing-fact")).toHaveText(
    "Prod · Production · Expected online",
  );
  await identity.getByRole("button", { name: "Change the lifecycle state" }).click();
  const to = region(page, "Move to another state").getByLabel("Move to");
  await expect(to).toBeFocused();
  await expect(to).toBeInViewport();
  // And Change beside its comments, to their field of the form of details.
  await page.evaluate(() => window.scrollTo(0, 0));
  await identity.getByRole("button", { name: "Change the comments" }).click();
  const comments = region(page, "Details").getByLabel("Comments", { exact: true });
  await expect(comments).toBeFocused();
  await expect(comments).toBeInViewport();

  // Links to the sections of the page, under its name: each moves to its section.
  await page.evaluate(() => window.scrollTo(0, 0));
  const sections = page.getByRole("navigation", { name: "Sections of the page" });
  await expect(sections).toBeInViewport();
  const names = await sections.getByRole("link").allTextContents();
  for (const name of ["Identity", "Lifecycle", "Details", "History"]) expect(names).toContain(name);
  expect(names.length, "one link for each section of the page").toBe(
    (await page.locator("main section > h2[id]").count()) -
      (await page.locator("main section section > h2[id]").count()),
  );
  await sections.getByRole("link", { name: "History", exact: true }).click();
  await expect(page.getByRole("heading", { level: 2, name: "History" })).toBeInViewport();
  await expect(page.getByRole("heading", { level: 1, name: host("kiln-sw-edge") })).toBeAttached();
  expect(new URL(page.url()).hash).toBe("#history");

  // From its location and its site, the items there, each link named by its place: the
  // location by its path.
  await page.evaluate(() => window.scrollTo(0, 0));
  await identity
    .getByRole("link", {
      name: `items here at ${label("Eastmarch")} > ${label("Kiln Lane")} > ${label("Room 4")}`,
    })
    .click();
  const grid = page.getByTestId("grid-items");
  const row = (name: string) => grid.locator("[row-id]", { hasText: host(name) });
  await expect(row("kiln-sw-edge")).toBeVisible();
  await expect(row("kiln-sw-01")).toBeVisible();
  await expect(row("kiln-sw-02")).toHaveCount(0);
  await page.goBack();
  await identity.getByRole("link", { name: `items here at ${label("Kiln Lane")}` }).click();
  await expect(row("kiln-sw-02")).toBeVisible();
  await expect(row("kiln-sw-edge")).toBeVisible();

  // A person who may not change the item is offered no form to go to.
  await expectClean(page, seen);
  const viewer = await createAccount(request, `e2e-${id}-viewer`, "viewer");
  const context = await browser.newContext();
  const looking = await context.newPage();
  const seenToo = await watch(context);
  await signIn(looking, viewer);
  await openItem(looking, edge.hid, host("kiln-sw-edge"));
  const links = looking.getByRole("navigation", { name: "Sections of the page" });
  const facts = region(looking, "Identity");
  await expect(links.getByRole("link", { name: "History", exact: true })).toBeVisible();
  await expect(links.getByRole("link", { name: "Lifecycle", exact: true })).toBeVisible();
  await expect(links.getByRole("link", { name: "Details", exact: true })).toHaveCount(0);
  await expect(facts.getByRole("button", { name: /^Change/ })).toHaveCount(0);
  await expect(facts.getByRole("link", { name: /^items here at/ })).toHaveCount(2);
  await expectClean(looking, seenToo);
  await context.close();
  const found = await request.get(`./api/v1/users/${viewer.hid}`, { headers });
  const { row_version } = (await found.json()) as { row_version: number };
  const disabled = await request.patch(`./api/v1/users/${viewer.hid}`, {
    headers,
    data: { disabled: true, row_version },
  });
  expect(disabled.status(), "the file's own viewer is disabled at the end").toBe(200);
});
