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
