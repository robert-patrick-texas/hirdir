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

/** 0.9.6: the model of a line is chosen by searching for it, here by its PID (P-200). */
async function chooseModel(form: Locator, pid: string) {
  await form.getByLabel("Model", { exact: true }).fill(pid);
  await form
    .getByRole("list", { name: "Catalog entries that match" })
    .getByRole("button", { name: new RegExp(`^${pid} ·`) })
    .click();
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

test("P-208: the next line like the last, a draft site, the lines in the window and every item it brought", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(180_000);
  const { request: purchase } = await setUp(request, account);
  const seen = await watch(page.context());
  await signIn(page, account);
  await openRequest(page, purchase);

  // Something arrives on the second line too, at the draft site's one location.
  await page.getByRole("button", { name: `Receive on ${reference}/2` }).click();
  const receive = page.getByTestId("receive-line");
  await expect(receive.getByTestId("chosen-location_hid")).toContainText(label("Annex Room"));
  await receive.getByLabel("Serial numbers", { exact: true }).fill(`TW${upper}03`);
  await receive.getByRole("button", { name: "Receive 1 item" }).click();
  await expect(
    page.getByTestId("arrived").locator("tr", { hasText: `TW${upper}03` }),
  ).toBeVisible();

  // Two lines more, the second like the first: to the draft site, on the same day.
  const modelPid = `TW-2400-${upper}`;
  const draftSite = `${label("Saltmarsh")} > ${label("Ridge Annex")} (draft)`;
  await page.getByRole("button", { name: "Add a line" }).click();
  const form = page.getByRole("region", { name: `New line of ${reference}` });
  await chooseModel(form, modelPid);
  await form.getByLabel("Quantity (required)").fill("5");
  await form.getByLabel("Destination site").selectOption({ label: draftSite });
  await form.getByLabel("Expected on").fill("2031-04-02");
  await form.getByRole("button", { name: "Add and add another like it" }).click();
  await expect(lineRow(page, `${reference}/3`)).toBeVisible();
  // The form stays, with the site and the day kept and the keyboard on the model.
  await expect(form.getByLabel("Model", { exact: true })).toBeFocused();
  await expect(form.getByLabel("Destination site")).toHaveValue(made?.annex ?? "");
  await expect(form.getByLabel("Expected on")).toHaveValue("2031-04-02");
  await chooseModel(form, modelPid);
  await form.getByLabel("Quantity (required)").fill("6");
  await form.getByRole("button", { name: "Add line" }).click();
  const fourth = lineRow(page, `${reference}/4`);
  await expect(fourth).toContainText(label("Ridge Annex"));
  await expect(fourth).toContainText("2031-04-02");

  // The table of lines is within the window, its buttons whole.
  const lines = page.getByTestId("purchase-lines");
  const fits = await lines.evaluate((table) => {
    const box = table.parentElement as HTMLElement;
    const right = box.getBoundingClientRect().right;
    const buttons = [...table.querySelectorAll("tbody button")];
    return {
      over: box.scrollWidth - box.clientWidth,
      cut: buttons.filter((button) => button.getBoundingClientRect().right > right + 0.5).length,
      buttons: buttons.length,
    };
  });
  expect(fits.buttons, "the rows have their buttons").toBeGreaterThan(0);
  expect(fits.over, "the lines scroll sideways by").toBeLessThanOrEqual(0);
  expect(fits.cut, "buttons cut off at the right").toBe(0);

  // One link opens every item the request brought, of both lines.
  await page.getByRole("link", { name: "Every item it brought" }).click();
  await expect(page).toHaveURL(/\/items\?filter=purchase_line_hid/);
  await expect(page.getByTestId("grid-total")).toHaveText("3 items", { timeout: 20_000 });
  await expectClean(page, seen);
});

/** Where a column's header ends, and whether its words are cut short. */
async function header(page: Page, grid: string, column: string) {
  const cell = page.getByTestId(grid).locator(`.ag-header-cell[col-id="${column}"]`);
  await expect(cell).toBeVisible();
  return cell.evaluate((element) => {
    const text = element.querySelector(".ag-header-cell-text") as HTMLElement;
    return {
      right: element.getBoundingClientRect().right,
      cut: text.scrollWidth > text.clientWidth,
    };
  });
}

test("P-210: a site's name finds the lines going to it, Destination site and Expected in view, Still to come whole", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(120_000);
  await setUp(request, account);
  const seen = await watch(page.context());
  await signIn(page, account);
  const width = page.viewportSize()?.width ?? 0;
  expect(width, "the window is 1280 pixels wide").toBe(1280);

  await page.goto("./purchases/lines");
  await expect(page.getByRole("heading", { level: 1, name: "Purchase lines" })).toBeVisible();
  await expect(page.getByText(/Words find lines by their .* or site\./)).toBeVisible();
  const box = page.getByLabel("Filter", { exact: true });
  await box.fill(label("Harbor Yard"));
  await box.press("Enter");
  await expect(page.getByTestId("grid-total")).toHaveText("1 line");
  const row = page.getByTestId("grid-purchase-lines").locator("[row-id]");
  await expect(row.locator('[col-id="site"]')).toHaveText(label("Harbor Yard"));
  await expect(row.locator('[col-id="request.reference"]')).toHaveText(reference);

  // Destination site and Expected stand within the window, their headings whole; Part
  // number and Tracked wait in the column chooser.
  for (const column of ["site", "expected_on", "pending_quantity", "quantity"]) {
    const at = await header(page, "grid-purchase-lines", column);
    expect(at.right, `${column} ends within the window`).toBeLessThanOrEqual(width);
    expect(at.cut, `the heading of ${column} is cut short`).toBe(false);
  }
  const grid = page.getByTestId("grid-purchase-lines");
  await expect(grid.locator('.ag-header-cell[col-id="part_number"]')).toHaveCount(0);
  await expect(grid.locator('.ag-header-cell[col-id="tracked"]')).toHaveCount(0);
  await page.getByText("Columns", { exact: true }).click();
  const shown = page.getByRole("group", { name: "Columns to show" });
  await expect(shown.getByLabel("Part number", { exact: true })).not.toBeChecked();
  await expect(shown.getByLabel("Tracked", { exact: true })).not.toBeChecked();
  await page.getByText("Columns", { exact: true }).click();

  // The list of requests: Still to come is whole.
  await page.goto(`./purchases?filter=${encodeURIComponent(`reference:eq:${reference}`)}`);
  await expect(page.getByTestId("grid-total")).toHaveText("1 request");
  const still = await header(page, "grid-purchase-requests", "pending_quantity");
  expect(still.cut, "Still to come is cut short").toBe(false);
  await expectClean(page, seen);
});

test("P-211: a vendor's page shows twenty models, its items before its agreements, and narrows them by the filter box", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(240_000);
  await setUp(request, account);
  const headers = await session(request, account);
  // A vendor of 22 models, an item of each: one model loses support soon, one has no date.
  const vendor = (await make(request, headers, "/vendors", { name: label("Fernbrook Optics") }))
    .hid;
  for (let n = 1; n <= 22; n += 1) {
    const ldos =
      n === 3 ? "2027-02-01" : n === 7 ? null : `2031-${String(n % 12 || 12).padStart(2, "0")}-01`;
    const model = (
      await make(request, headers, "/catalog-entries", {
        vendor_hid: vendor,
        pid: `FB-${String(n).padStart(2, "0")}-${upper}`,
        ...(ldos ? { ldos } : {}),
      })
    ).hid;
    await make(request, headers, "/items", {
      hostname: `fb-edge-${n}-${id}`,
      catalog_entry_hid: model,
    });
  }
  // An item of another vendor, which a search on this vendor's page does not find.
  await make(request, headers, "/items", {
    hostname: `fb-edge-99-${id}`,
    catalog_entry_hid: made?.model,
  });
  const seen = await watch(page.context());
  await signIn(page, account);
  await page.goto(`./vendors/${encodeURIComponent(vendor)}`);
  const models = page.getByTestId("portfolio-models");
  await expect(models.locator("tbody tr")).toHaveCount(20);

  // Sorted by LDoS, the model with none comes last, whichever way.
  await models.getByRole("button", { name: "LDoS" }).click();
  await expect(models.locator("tbody tr").first()).toHaveAttribute("data-pid", `FB-03-${upper}`);
  await page.getByRole("button", { name: "Show all 22 models" }).click();
  await expect(models.locator("tbody tr")).toHaveCount(22);
  await expect(models.locator("tbody tr").last()).toHaveAttribute("data-pid", `FB-07-${upper}`);
  await models.getByRole("button", { name: "LDoS" }).click();
  await expect(models.locator("tbody tr").first()).not.toHaveAttribute(
    "data-pid",
    `FB-07-${upper}`,
  );
  await expect(models.locator("tbody tr").last()).toHaveAttribute("data-pid", `FB-07-${upper}`);

  // Its items stand above its agreements and contracts.
  const items = page.getByRole("heading", { name: "Its items", exact: true });
  const agreements = page.getByRole("heading", { name: "Support agreements", exact: true });
  const contracts = page.getByRole("heading", { name: "Contracts", exact: true });
  const itemsAt = (await items.boundingBox())?.y ?? Number.POSITIVE_INFINITY;
  expect(itemsAt).toBeLessThan((await agreements.boundingBox())?.y ?? 0);
  expect(itemsAt).toBeLessThan((await contracts.boundingBox())?.y ?? 0);

  // The filter box narrows within the vendor's items: by a condition, and by plain words.
  const section = page.getByRole("region", { name: "Its items" });
  const total = section.getByTestId("grid-total");
  await expect(total).toHaveText("22 items");
  const box = section.getByLabel("Filter", { exact: true });
  await box.fill("effective.ldos:lt:2028-01-01");
  await box.press("Enter");
  await expect(total).toHaveText("1 item");
  await expect(section.getByRole("link", { name: `fb-edge-3-${id}`, exact: true })).toBeVisible();
  await box.fill(`fb-edge-99-${id}`);
  await box.press("Enter");
  await expect(total).toHaveText("No items");
  await box.fill(`fb-edge-12-${id}`);
  await box.press("Enter");
  await expect(total).toHaveText("1 item");
  await expectClean(page, seen);
});
