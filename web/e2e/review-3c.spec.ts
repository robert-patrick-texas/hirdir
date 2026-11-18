// The browser scenarios of lane C1 of the third review of the web UI: receiving opens
// ready to type, where the line is going (P-209), a request's page (P-208), the lists of
// purchases (P-210) and a vendor's page at size (P-211).
//
// The file keeps the rules of support.ts. It signs in as an Admin of its own, and its
// mark is in every name it gives a record: the region, the sites and their codes, the
// locations, the vendors, the models, the request and the serial numbers, all made
// through the API as that Admin. It changes no setting, no list of choices and no
// account, and counts only its own records: a list is filtered down to them first. The
// scenarios run in order and share what the first one makes.

import type { APIRequestContext, Locator, Page } from "@playwright/test";
import { expect } from "@playwright/test";
import { type Account, expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const id = mark("review-3c");
const label = (name: string) => `${name} ${id}`;
const upper = id.slice(-6).toUpperCase();
const reference = `RITM-${id}`;

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
interface Made {
  harbor: string;
  annex: string;
  mill: string;
  vendor: string;
  model: string;
  request: string;
}
let made: Made | undefined;

/**
 * The places, a model and a request of two lines: one going to a site of two locations,
 * one to a draft site of one location. A third site, of one location, is where a person
 * chooses instead.
 */
async function setUp(request: APIRequestContext, account: Account): Promise<Made> {
  if (made) return made;
  const headers = await session(request, account);
  const region = (await make(request, headers, "/regions", { name: label("Saltmarsh") })).hid;
  const site = async (name: string, code: string, draft = false) =>
    (
      await make(request, headers, "/sites", {
        name: label(name),
        code: `${code}-${upper}`,
        region_hid: region,
        ...(draft ? { record_status: "draft" } : {}),
      })
    ).hid;
  const harbor = await site("Harbor Yard", "HY");
  const annex = await site("Ridge Annex", "RA", true);
  const mill = await site("Mill Point", "MP");
  const location = (name: string, site_hid: string) =>
    make(request, headers, "/locations", { name: label(name), site_hid });
  await location("Bay 1", harbor);
  await location("Bay 2", harbor);
  await location("Annex Room", annex);
  await location("Mill Store", mill);
  const vendor = (await make(request, headers, "/vendors", { name: label("Tidewater Systems") }))
    .hid;
  const model = (
    await make(request, headers, "/catalog-entries", {
      vendor_hid: vendor,
      pid: `TW-2400-${upper}`,
      model_name: "Tidewater 2400",
    })
  ).hid;
  const purchase = (
    await make(request, headers, "/purchase-requests", {
      reference,
      status: "ordered",
      lines: [
        {
          catalog_entry_hid: model,
          quantity: 3,
          destination_site_hid: harbor,
          expected_on: "2031-03-14",
        },
        {
          catalog_entry_hid: model,
          quantity: 2,
          destination_site_hid: annex,
          expected_on: "2031-03-21",
        },
      ],
    })
  ).hid;
  made = { harbor, annex, mill, vendor, model, request: purchase };
  return made;
}

function lineRow(page: Page, name: string): Locator {
  return page.getByTestId("purchase-lines").locator(`tr[data-line="${name}"]`);
}

async function openRequest(page: Page, hid: string) {
  await page.goto(`./purchases/${encodeURIComponent(hid)}`);
  await expect(page.getByRole("heading", { level: 1, name: reference })).toBeVisible();
  await expect(lineRow(page, `${reference}/1`)).toBeVisible();
}

test("P-209: Receive opens in the window, ready to type, with the locations of the line's site", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(180_000);
  const { request: purchase } = await setUp(request, account);
  const seen = await watch(page.context());
  await signIn(page, account);
  await openRequest(page, purchase);

  await page.getByRole("button", { name: `Receive on ${reference}/1` }).click();
  const form = page.getByTestId("receive-line");
  await expect(form.getByRole("heading", { name: `Receive on ${reference}/1` })).toBeInViewport();
  // The keyboard is in the box of what arrived: the serial numbers are typed at once.
  await expect(form.getByRole("textbox", { name: "Serial numbers" })).toBeFocused();
  await page.keyboard.type(`TW${upper}01\nTW${upper}02`);

  // The site's two locations are offered before anything is typed, and nothing elsewhere.
  const offered = form.getByRole("list", { name: "Locations that match" });
  await expect(offered.getByRole("button", { name: new RegExp(label("Bay 1")) })).toBeVisible();
  await expect(offered.getByRole("button", { name: new RegExp(label("Bay 2")) })).toBeVisible();
  await expect(offered.getByRole("button")).toHaveCount(2);
  await expect(form.getByTestId("chosen-location_hid")).toHaveText("Not said");

  // Cleared, Only at searches every site: the person chooses another.
  await form.getByLabel(`Only at ${label("Harbor Yard")}`).uncheck();
  await form.getByLabel("Location they were put in").fill(label("Mill Store"));
  await offered.getByRole("button", { name: new RegExp(label("Mill Store")) }).click();
  await expect(form.getByTestId("chosen-location_hid")).toContainText(label("Mill Store"));
  await form.getByRole("button", { name: "Receive 2 items" }).click();
  const arrived = page.getByTestId("arrived");
  await expect(arrived.locator("tr", { hasText: `TW${upper}01` })).toContainText(
    label("Mill Store"),
  );
  await expectClean(page, seen);
});

test("P-209: a site of one location is chosen at once, and a choice made while it is read stays", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(180_000);
  const { request: purchase } = await setUp(request, account);
  const seen = await watch(page.context());
  await signIn(page, account);
  await openRequest(page, purchase);

  await page.getByRole("button", { name: `Receive on ${reference}/2` }).click();
  const form = page.getByTestId("receive-line");
  await expect(form.getByTestId("chosen-location_hid")).toContainText(label("Annex Room"));
  await form.getByRole("button", { name: "Cancel" }).click();

  // A busy server: the site's one location comes late, after the person chose another.
  let held = 0;
  await page.route("**/api/v1/locations/query", async (route) => {
    const body = route.request().postDataJSON() as { limit?: number };
    if (body.limit === 2) {
      held += 1;
      await new Promise((resolve) => setTimeout(resolve, 4_000));
    }
    await route.continue();
  });
  const late = page.waitForResponse(
    (answer) =>
      answer.url().endsWith("/api/v1/locations/query") &&
      (answer.request().postDataJSON() as { limit?: number }).limit === 2,
  );
  await page.getByRole("button", { name: `Receive on ${reference}/2` }).click();
  await expect(form.getByTestId("chosen-location_hid")).toHaveText("Not said");
  await form.getByLabel(`Only at ${label("Ridge Annex")}`).uncheck();
  await form.getByLabel("Location they were put in").fill(label("Mill Store"));
  await form
    .getByRole("list", { name: "Locations that match" })
    .getByRole("button", { name: new RegExp(label("Mill Store")) })
    .click();
  await late;
  expect(held, "the site's one location was asked for, and held back").toBe(1);
  await expect(form.getByTestId("chosen-location_hid")).toContainText(label("Mill Store"));
  await page.unrouteAll({ behavior: "wait" });
  await expectClean(page, seen);
});
