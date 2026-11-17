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
import { type Account, expectClean, mark, signIn, test, watch } from "./support";

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
