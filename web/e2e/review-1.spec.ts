// The browser scenarios of the first review of the web UI, P-182 to P-186: what a page
// answers stays in the window, a picker asks again, a site with no location is named
// where a location is searched for, Change beside an item's facts, and a wide table that
// does not widen the page.
//
// The file keeps the rules of support.ts. It signs in as an Admin of its own, and its
// mark is in every name it gives a record: the region, the sites and their codes, the
// locations and the items, all made through the API as that Admin. It changes no
// setting, no list of choices and no account, and reads only its own records, but for
// the width of the Capacity page, which holds no number. The scenarios need nothing of
// each other but the places the first one makes, and run in order.

import type { APIRequestContext, Locator, Page } from "@playwright/test";
import { expect } from "@playwright/test";
import { type Account, expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const id = mark("review-1");
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
const made: { region?: string; site?: string; item?: string } = {};

async function places(request: APIRequestContext, account: Account): Promise<Headers> {
  const headers = await session(request, account);
  if (made.region === undefined) {
    made.region = (await make(request, headers, "/regions", { name: label("Northfold") })).hid;
    made.site = (
      await make(request, headers, "/sites", {
        name: label("Harbour Yard"),
        code: `HY-${id}`,
        region_hid: made.region,
      })
    ).hid;
    await make(request, headers, "/locations", { name: label("Bay 1"), site_hid: made.site });
    made.item = (await make(request, headers, "/items", { hostname: label("edge-sw") })).hid;
  }
  return headers;
}

/** The form of details of the item on show. */
function details(page: Page): Locator {
  return page.getByRole("region", { name: "Details" });
}

async function openTheItem(page: Page) {
  await page.goto(`./items/${made.item}`);
  await expect(page.getByRole("heading", { level: 1, name: label("edge-sw") })).toBeVisible();
}

test("Enter in a location field asks again for the same text, and finds a location made meanwhile", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(120_000);
  const headers = await places(request, account);
  const seen = await watch(page.context());
  await signIn(page, account);
  await openTheItem(page);

  let asked = 0;
  page.on("request", (sent) => {
    if (sent.method() === "POST" && sent.url().includes("/api/v1/locations/query")) asked += 1;
  });
  const field = details(page).getByLabel("Location", { exact: true });
  const offered = details(page).getByRole("list", { name: "Locations that match" });
  const rack = label("Rack 7");
  await field.fill(rack);
  await expect(details(page).getByText("No location matches.")).toBeVisible();
  const before = asked;
  expect(before, "the text typed was searched for").toBeGreaterThan(0);

  // Made in another tab, as it were: through the API.
  await make(request, headers, "/locations", { name: rack, site_hid: made.site });

  // Enter with the text unchanged asks the server again, and finds it.
  await field.press("Enter");
  await expect(offered.getByRole("button", { name: new RegExp(rack) })).toBeVisible();
  expect(asked, "Enter sent one more request for the same text").toBe(before + 1);
  await expect(field).toHaveValue(rack);

  await expectClean(page, seen);
});

test("after Save at the foot of an item's page, what the page answers is in the window", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(120_000);
  await places(request, account);
  const seen = await watch(page.context());
  await signIn(page, account);
  await openTheItem(page);

  const form = details(page);
  const saved = page.getByRole("status").filter({ hasText: "The item was saved." });
  await form.getByLabel("FQDN").fill(`${label("edge-sw").replace(/ /g, "-")}.example.net`);
  await form.getByRole("button", { name: "Save", exact: true }).click();
  await expect(saved).toBeVisible();
  // The page was scrolled to the form, far below the message's place; the message is
  // in the window all the same, at its top.
  expect(await page.evaluate(() => window.scrollY), "the window is down the page").toBeGreaterThan(
    800,
  );
  await expect(saved).toBeInViewport();

  // The next change sent takes the message away, and once it is done the same words are
  // shown again. The answer is held back a moment, to see the page while it is sent.
  let release = () => {};
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route(`**/api/v1/items/${made.item}`, async (route) => {
    if (route.request().method() === "PATCH") await held;
    await route.continue();
  });
  await form.getByLabel("FQDN").fill(`${label("edge-sw-2").replace(/ /g, "-")}.example.net`);
  await form.getByRole("button", { name: "Save", exact: true }).click();
  await expect(saved).toHaveCount(0);
  release();
  await expect(saved).toBeInViewport();
  await page.unroute(`**/api/v1/items/${made.item}`);

  await expectClean(page, seen);
});

test("the Capacity page is no wider than the window", async ({ page, account }) => {
  const seen = await watch(page.context());
  await signIn(page, account);
  await page.goto("./capacity");
  await expect(page.getByRole("heading", { level: 1, name: "Capacity" })).toBeVisible();
  await page.waitForLoadState("networkidle");
  const [scroll, client] = await page.evaluate(() => [
    document.documentElement.scrollWidth,
    document.documentElement.clientWidth,
  ]);
  expect(scroll, "the page does not scroll sideways").toBeLessThanOrEqual(client);
  await expectClean(page, seen);
});
