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
