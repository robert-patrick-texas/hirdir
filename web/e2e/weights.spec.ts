// The browser scenarios of the support weight of 0.8.0 (P-139, P-141, P-155 to P-157):
//
//   The six settings of a default and a minimum are blank unless an Admin sets one, are
//   set on the Settings page and returned to their default there.
//   A region, a site and a location show and change their own weight; a site with none
//   counts at the default of a site, shown as inherited with its setting, and a site whose
//   own weight is below the minimum is raised to it, with what it was; an item whose
//   model's weight is below the minimum of a major item says it was raised.
//   The capacity page shows the support weight in its parts, the items, the places and
//   the circuits, with how many counted at a default and were raised, and the demand of a
//   region holds the weights of its places.
//   Try: another default, another weight one engineer carries, a staff line changed, one
//   left out and one added give a balance beside the one in force, and nothing is saved:
//   the page read again shows the balance as before. An Admin then saves a setting tried.
//   The Settings page checks the kept reports, and none differed.
//
// How this file keeps to rule 5 of support.ts: it sets the defaults and minimums of
// support weight, which every count of a weight reads, writes staff lines and reads the
// capacity report, which capacity.spec.ts alone may beside the others, and checks the
// kept reports, which a change of any other file sets aside. So it runs in the project
// "the weights alone" of playwright.config.ts, by itself, when every other project has
// ended. It notes each setting it may change as it found it, and puts it back when it
// ends, and retires the lines and the places it made, so that none of them counts after
// it. What it compares of the report of the whole installation is either one answer of
// Try with itself, the balance tried beside the balance in force, or one reading of the
// page with another, never a reading with a number; the demand of its own region is the
// weight of its own places alone.

import { type APIRequestContext, expect, type Page } from "@playwright/test";
import { openItem, region } from "./structure";
import { type Account, expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const suffix = mark("weights");
const regionName = `Weights Region ${suffix}`;
const weighed = `Weights Site Own ${suffix}`;
const plain = `Weights Site Plain ${suffix}`;
const building = `Building ${suffix}`;
const vendor = `Example Networks ${suffix}`;
const pid = `EN-W-24-${suffix}`;
const hostname = `site9-sw-${suffix}`;
const engineer = `Network engineer ${suffix}`;
const junior = `Junior network engineer ${suffix}`;
const added = `Network engineer, tried ${suffix}`;

// The settings this file may change, which it puts back as it found them.
const SETTINGS = [
  "default_item_weight",
  "minimum_item_weight",
  "default_site_weight",
  "minimum_site_weight",
  "default_circuit_weight",
  "minimum_circuit_weight",
  "weight_per_resource_unit",
  "stack_discount_pct",
] as const;

type Headers = { Authorization: string };

/** Sign in through the API as the account of the file, for what is done there. */
async function session(request: APIRequestContext, account: Account): Promise<Headers> {
  const answer = await request.post("./api/v1/auth/sign-in", {
    data: { username: account.username, access_code: account.accessCode },
  });
  expect(answer.status(), "the account of the file signs in through the API").toBe(200);
  const { token } = (await answer.json()) as { token: string };
  return { Authorization: `Bearer ${token}` };
}

interface Made {
  hid: string;
  row_version: number;
}

async function send<T = Made>(
  request: APIRequestContext,
  headers: Headers,
  method: "post" | "put" | "patch",
  path: string,
  data: unknown,
  status = method === "post" ? 201 : 200,
): Promise<T> {
  const answer = await request[method](`./api/v1${path}`, { headers, data });
  expect(answer.status(), `${method} ${path}: ${await answer.text()}`).toBe(status);
  return (await answer.json()) as T;
}

async function read<T>(request: APIRequestContext, headers: Headers, path: string): Promise<T> {
  const answer = await request.get(`./api/v1${path}`, { headers });
  expect(answer.status(), `get ${path}`).toBe(200);
  return (await answer.json()) as T;
}

interface Setting {
  key: string;
  value: unknown;
  is_default: boolean;
  row_version: number;
}

async function setting(request: APIRequestContext, headers: Headers, key: string) {
  const all = await read<Setting[]>(request, headers, "/settings");
  const found = all.find((one) => one.key === key);
  if (!found) throw new Error(`there is no setting ${key}`);
  return found;
}

/** Give a setting a value, or its default for null. */
async function put(request: APIRequestContext, headers: Headers, key: string, value: unknown) {
  const { row_version } = await setting(request, headers, key);
  await send(request, headers, "put", `/settings/${key}`, { row_version, value });
}

// What this file made, and the settings as it found them.
const made: { places: Array<[level: string, made: Made]>; lines: Made[]; item?: Made } = {
  places: [],
  lines: [],
};
const ids: Record<string, string> = {};
const found = new Map<string, unknown>();

test.beforeAll(async ({ request, accounts }) => {
  const headers = await session(request, await accounts.of("weights"));
  for (const key of SETTINGS) {
    const now = await setting(request, headers, key);
    found.set(key, now.is_default ? null : now.value);
  }
  const top = await send(request, headers, "post", "/regions", { name: regionName });
  const own = await send(request, headers, "post", "/sites", {
    name: weighed,
    region_hid: top.hid,
    support_weight: "0.5",
  });
  const none = await send(request, headers, "post", "/sites", { name: plain, region_hid: top.hid });
  const inside = await send(request, headers, "post", "/locations", {
    name: building,
    site_hid: own.hid,
  });
  made.places = [
    ["locations", inside],
    ["sites", own],
    ["sites", none],
    ["regions", top],
  ];
  Object.assign(ids, { region: top.hid, weighed: own.hid, plain: none.hid, building: inside.hid });
  const maker = await send(request, headers, "post", "/vendors", { name: vendor });
  const model = await send(request, headers, "post", "/catalog-entries", {
    vendor_hid: maker.hid,
    pid,
    support_weight: "0.5",
  });
  made.item = await send(request, headers, "post", "/items", {
    catalog_entry_hid: model.hid,
    hostname,
  });
  for (const [name, quantity, each] of [
    [engineer, "2", "1"],
    [junior, "1", "0.5"],
  ] as const) {
    made.lines.push(
      await send(request, headers, "post", "/capacity-lines", {
        side: "supply",
        category: "staff",
        effect: "add",
        name,
        quantity,
        units_each: each,
        record_status: "active",
      }),
    );
  }
});

test.afterAll(async ({ request, accounts }) => {
  const headers = await session(request, await accounts.of("weights"));
  for (const key of SETTINGS) {
    const now = await setting(request, headers, key);
    const was = found.get(key) ?? null;
    if ((now.is_default ? null : now.value) !== was) await put(request, headers, key, was);
  }
  // What it made counts for nothing once it is retired: the lines, the places, inside first.
  for (const line of made.lines) {
    const now = await read<Made>(request, headers, `/capacity-lines/${line.hid}`);
    await send(
      request,
      headers,
      "post",
      `/capacity-lines/${line.hid}/retire`,
      { row_version: now.row_version },
      200,
    );
  }
  for (const [level, place] of made.places) {
    const now = await read<Made>(request, headers, `/${level}/${place.hid}`);
    await send(
      request,
      headers,
      "post",
      `/${level}/${place.hid}/retire`,
      { row_version: now.row_version },
      200,
    );
  }
});

function placePage(level: string, hid: string): string {
  return `./geography/${level}/${encodeURIComponent(hid)}`;
}

/** The weight a figure of the page holds, in hundredths. */
async function hundredths(page: Page, testId: string, within = page.locator("body")) {
  const value = await within.getByTestId(testId).first().getAttribute("data-value");
  expect(value, `a number in ${testId}`).toMatch(/^-?\d+(\.\d+)?$/);
  return Math.round(Number(value) * 100);
}

/** The balance in force as the Capacity page shows it, each figure in hundredths. */
async function balance(page: Page) {
  const report = page.getByTestId("capacity-report");
  await expect(report).toBeVisible();
  const figures: Record<string, number> = {};
  for (const view of ["active", "with_drafts"]) {
    for (const key of ["support_weight", "places_weight", "demand", "supply", "balance"]) {
      figures[`${view}-${key}`] = await hundredths(page, `${view}-${key}`, report);
    }
  }
  return figures;
}

test("the defaults and minimums of support weight are blank, set and returned to their default", async ({
  page,
  account,
}) => {
  test.setTimeout(120_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  await page.goto("./admin/settings");
  await expect(page.getByRole("heading", { level: 1, name: "Settings" })).toBeVisible();
  const table = page.getByTestId("settings");
  for (const key of SETTINGS.slice(0, 6)) {
    await expect(table.getByTestId(`default-${key}`)).toHaveText("Blank");
  }
  await expect(table.getByTestId("default-circuit_cost_side")).toHaveText("A side");

  // Set from its form, then returned to its default by the button of its row.
  await table.getByRole("button", { name: "Change default_circuit_weight" }).click();
  const form = page.getByTestId("setting-form");
  await expect(form).toContainText("The default is blank.");
  await form.getByLabel("New value").fill("2.5");
  await form.getByRole("button", { name: "Set" }).click();
  await expect(page.getByText("default_circuit_weight was set to 2.5.")).toBeVisible();
  await expect(table.getByTestId("value-default_circuit_weight")).toHaveText("2.5");
  await expect(table.getByTestId("standing-default_circuit_weight")).toHaveText("Set here");
  await table.getByRole("button", { name: "Return default_circuit_weight to its default" }).click();
  await expect(
    page.getByText("default_circuit_weight is at its default again: blank."),
  ).toBeVisible();
  await expect(table.getByTestId("value-default_circuit_weight")).toHaveText("Blank");

  // A value the setting does not take is refused under its input, with what it takes.
  await table.getByRole("button", { name: "Change minimum_site_weight" }).click();
  await form.getByLabel("New value").fill("0.125");
  await form.getByRole("button", { name: "Set" }).click();
  await expect(form).toContainText("at most two decimal places");
  await expectClean(page, seen, ["422 PUT"]);
});

test("a place shows its own weight, and a site the default where it has none, raised to the minimum", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(150_000);
  const headers = await session(request, account);
  await put(request, headers, "default_site_weight", "3");
  await put(request, headers, "minimum_site_weight", "1");
  await put(request, headers, "minimum_item_weight", "1");
  const seen = await watch(page.context());
  await signIn(page, account);

  // A region's own weight, set in its form: it has nothing of a default.
  await page.goto(placePage("region", ids.region ?? ""));
  await expect(page.getByTestId("place-path")).toHaveText(regionName);
  await expect(page.getByTestId("place-weight")).toContainText("None of its own");
  const regionDetails = region(page, "Details");
  await regionDetails.getByLabel("Support weight").fill("2");
  await regionDetails.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("The region was saved.")).toBeVisible();
  await expect(page.getByTestId("place-weight")).toHaveAttribute("data-value", "2");
  await expect(page.getByTestId("place-weight-in-force")).toHaveCount(0);

  // A site whose own weight is below the minimum counts at the minimum, and says so.
  await page.goto(placePage("site", ids.weighed ?? ""));
  await expect(page.getByTestId("place-path")).toHaveText(`${regionName} > ${weighed}`);
  await expect(page.getByTestId("place-weight")).toHaveAttribute("data-value", "0.5");
  const raised = page.getByTestId("place-weight-in-force").getByTestId("weight-in-force");
  await expect(raised).toHaveAttribute("data-value", "1");
  await expect(raised).toHaveAttribute("data-source", "own");
  await expect(raised.getByTestId("weight-source")).toHaveText("Set here");
  await expect(raised.getByTestId("weight-raised")).toHaveAttribute("data-raised-from", "0.5");
  await expect(raised).toContainText("Raised to the minimum, minimum_site_weight, from 0.5");

  // A site with none counts at the default of a site: inherited, from its setting.
  await page.goto(placePage("site", ids.plain ?? ""));
  await expect(page.getByTestId("place-path")).toHaveText(`${regionName} > ${plain}`);
  await expect(page.getByTestId("place-weight")).toContainText("None of its own");
  const fromDefault = page.getByTestId("place-weight-in-force").getByTestId("weight-in-force");
  await expect(fromDefault).toHaveAttribute("data-value", "3");
  await expect(fromDefault).toHaveAttribute("data-source", "setting");
  await expect(fromDefault).toHaveClass(/inherited/);
  await expect(fromDefault).toContainText("Inherited");
  await expect(fromDefault.getByTestId("weight-source")).toHaveText(
    "The default of a site, default_site_weight",
  );
  await expect(fromDefault.getByTestId("weight-raised")).toHaveCount(0);
  const siteDetails = region(page, "Details");
  await expect(siteDetails).toContainText("Blank counts at default_site_weight, 3.");
  // Its own, set and taken away again: the default is in force once more.
  await siteDetails.getByLabel("Support weight").fill("4");
  await siteDetails.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("The site was saved.")).toBeVisible();
  await expect(fromDefault).toHaveAttribute("data-source", "own");
  await expect(fromDefault).toHaveAttribute("data-value", "4");
  await region(page, "Details").getByLabel("Support weight").fill("");
  await region(page, "Details").getByRole("button", { name: "Save" }).click();
  await expect(fromDefault).toHaveAttribute("data-source", "setting");
  await expect(fromDefault).toHaveAttribute("data-value", "3");

  // A location counts its own alone.
  await page.goto(placePage("location", ids.building ?? ""));
  await expect(page.getByTestId("place-path")).toHaveText(
    `${regionName} > ${weighed} > ${building}`,
  );
  const locationDetails = region(page, "Details");
  await locationDetails.getByLabel("Support weight").fill("1.5");
  await locationDetails.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("The location was saved.")).toBeVisible();
  await expect(page.getByTestId("place-weight")).toHaveAttribute("data-value", "1.5");
  await expect(page.getByTestId("place-weight-in-force")).toHaveCount(0);

  // An item whose model weighs less than the minimum of a major item says it was raised.
  await openItem(page, hostname);
  const weight = page.locator('tr[data-field="support_weight"]');
  await expect(weight).toHaveAttribute("data-source", "catalog");
  await expect(weight.locator("td").nth(0)).toContainText("1");
  await expect(weight.getByTestId("weight-raised")).toHaveAttribute("data-raised-from", "0.5");
  await expect(weight).toContainText("Raised to the minimum, minimum_item_weight, from 0.5");
  await expect(weight.locator("td").nth(1)).toContainText("From the catalog entry");
  await expectClean(page, seen);
});

test("the capacity page shows the support weight in its parts, and a region holds its places", async ({
  page,
  account,
}) => {
  test.setTimeout(120_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  await page.goto("./capacity");
  const report = page.getByTestId("capacity-report");
  await expect(report).toBeVisible();
  const parts = report.getByTestId("weight-parts");
  const places = parts.locator('tr[data-part="places"]');
  // The site of this file with no weight counts at the default, and its weighed site was
  // raised: the counts hold at least those.
  expect(await hundredths(page, "part-defaulted", places)).toBeGreaterThanOrEqual(100);
  expect(await hundredths(page, "part-raised", places)).toBeGreaterThanOrEqual(100);
  for (const view of ["active", "with_drafts"] as const) {
    const whole = await hundredths(page, `${view}-support_weight`, report);
    const items = await hundredths(page, `${view}-items_weight`, report);
    const placesWeight = await hundredths(page, `${view}-places_weight`, report);
    const circuits = await hundredths(page, `${view}-circuits_weight`, report);
    // Each is rounded to two places once, so the parts may miss the whole by a hundredth or two.
    expect(Math.abs(whole - (items + placesWeight + circuits))).toBeLessThanOrEqual(3);
  }
  expect(await hundredths(page, "part-weight", places)).toBe(
    await hundredths(page, "active-places_weight", report),
  );
  // The region of this file holds its own weight, its sites' in force and its building's:
  // 2, 1 raised from 0.5, 3 by the default and 1.5. Nothing else is in it.
  const mine = report.getByTestId("demand-by-region").locator(`tr[data-region="${regionName}"]`);
  await expect(mine.getByTestId("region-active-weight")).toHaveAttribute("data-value", "7.5");
  await expectClean(page, seen);
});

test("Try gives a balance beside the one in force, saves nothing, and an Admin saves a setting tried", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(180_000);
  const headers = await session(request, account);
  const perEngineer = String((await setting(request, headers, "weight_per_resource_unit")).value);
  const seen = await watch(page.context());
  await signIn(page, account);
  await page.goto("./capacity");
  const before = await balance(page);
  const panel = page.getByRole("region", { name: "Try", exact: true });
  const siteDefault = panel.getByLabel("Default weight of a site", { exact: true });
  const perUnit = panel.getByLabel("Support weight one engineer carries", { exact: true });
  // Each figure starts as it is in force.
  await expect(siteDefault).toHaveValue("3");
  await expect(perUnit).toHaveValue(perEngineer);
  await siteDefault.fill("5");
  await perUnit.fill("150");
  const staff = panel.getByTestId("try-staff");
  await expect(staff.getByLabel(`Quantity of ${engineer}`)).toHaveValue("2");
  await staff.getByLabel(`Quantity of ${engineer}`).fill("3");
  await staff.getByLabel(`Leave out ${junior}`).check();
  await panel.getByRole("button", { name: "Add a staff line to try" }).click();
  await panel.getByLabel("Name of added line 1").fill(added);
  await panel.getByLabel("Quantity of added line 1").fill("2");
  await panel.getByLabel("Units each of added line 1").fill("1");
  await panel.getByRole("button", { name: "Try", exact: true }).click();

  const compare = panel.getByTestId("try-compare");
  await expect(compare).toBeVisible({ timeout: 20_000 });
  const figure = (key: string) => compare.locator(`tr[data-figure="${key}"]`);
  const both = (key: string, cell: string) => hundredths(page, cell, figure(key));
  await expect(figure("weight_per_resource_unit").getByTestId("tried-active")).toHaveAttribute(
    "data-value",
    "150",
  );
  // One more engineer, two added, and a junior of half a unit left out: 2.5 more units.
  for (const [inForce, tried] of [
    ["in-force-active", "tried-active"],
    ["in-force-drafts", "tried-drafts"],
  ] as const) {
    expect((await both("supply", tried)) - (await both("supply", inForce))).toBe(250);
    expect((await both("category.staff", tried)) - (await both("category.staff", inForce))).toBe(
      250,
    );
  }
  // Each site at the default weighs 2 more, and as many are at the default as before.
  const defaulted = await both("defaulted.sites", "in-force-active");
  expect(await both("defaulted.sites", "tried-active")).toBe(defaulted);
  expect(
    (await both("places_weight", "tried-active")) -
      (await both("places_weight", "in-force-active")),
  ).toBe(2 * defaulted);
  await expect(figure("places_weight")).toHaveAttribute("data-differs", "true");
  // The balance in force beside it is the page's.
  expect(await both("balance", "in-force-active")).toBe(before["active-balance"]);
  await expect(panel.getByTestId("try-changed")).toContainText("default_site_weight at 5");
  await expect(panel.getByTestId("try-changed")).toContainText("weight_per_resource_unit at 150");
  const tried = panel.getByTestId("tried-staff");
  await expect(tried).toContainText(`Added: ${added}, 2 × 1 = 2 units`);
  await expect(tried).toContainText(`Changed: ${engineer}, 3 × 1 = 3 units`);
  await expect(tried).toContainText(`Left out: ${junior}`);
  await expect(panel.getByText("A staff line tried is not saved")).toBeVisible();

  // Nothing was saved: the page read again shows the balance as before, the settings are
  // as they were, and so are the staff lines.
  await page.reload();
  expect(await balance(page)).toEqual(before);
  expect((await setting(request, headers, "default_site_weight")).value).toBe(3);
  expect(String((await setting(request, headers, "weight_per_resource_unit")).value)).toBe(
    perEngineer,
  );
  const lines = await read<{ items: Array<{ name: string; quantity: string }> }>(
    request,
    headers,
    `/capacity-lines?filter=${encodeURIComponent(`name:contains:${suffix}`)}&include_drafts=true`,
  );
  expect(lines.items.map((line) => [line.name, line.quantity]).sort()).toEqual(
    [
      [engineer, "2"],
      [junior, "1"],
    ].sort(),
  );

  // An Admin agrees an estimate and saves the setting tried, one audited change.
  const again = page.getByRole("region", { name: "Try", exact: true });
  await again.getByLabel("Default weight of a site", { exact: true }).fill("4");
  await again.getByRole("button", { name: "Try", exact: true }).click();
  await expect(again.getByTestId("try-changed")).toHaveText("default_site_weight at 4");
  await again.getByRole("button", { name: "Save these settings" }).click();
  await expect(page.getByText("Saved: default_site_weight at 4.")).toBeVisible();
  expect((await setting(request, headers, "default_site_weight")).value).toBe(4);
  // The balance in force is read again: each site at the default weighs 1 more.
  await expect
    .poll(async () => (await balance(page))["active-places_weight"], { timeout: 20_000 })
    .toBe((before["active-places_weight"] ?? 0) + defaulted);
  // The form starts again from what is in force.
  await expect(
    page.getByRole("region", { name: "Try", exact: true }).getByLabel("Default weight of a site", {
      exact: true,
    }),
  ).toHaveValue("4");
  await expectClean(page, seen);
});

test("the Settings page checks the kept reports, and none differed", async ({ page, account }) => {
  test.setTimeout(120_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  // The capacity balance is kept once it has been asked for.
  await page.goto("./capacity");
  await expect(page.getByTestId("capacity-report")).toBeVisible();
  await page.goto("./admin/settings");
  const kept = page.getByRole("region", { name: "Kept reports" });
  await expect(kept.getByTestId("kept-list").locator('tr[data-report="capacity"]')).toBeVisible();
  // 0.9.11: each row says where it is kept (P-275): in the database, where the second
  // process worked it out ahead, or in the server's memory, where this page asked first.
  await expect(
    kept.getByTestId("kept-list").locator('tr[data-report="capacity"] td[data-ahead]'),
  ).toHaveText(/^(In the database, worked out ahead|In the server's memory)$/);
  await expect(kept.getByTestId("kept-list").locator('button[data-sort="ahead"]')).toHaveText(
    "Kept",
  );
  await kept.getByRole("button", { name: "Check kept reports" }).click();
  const check = kept.getByTestId("kept-check");
  await expect(check).toHaveAttribute("data-differed", "0", { timeout: 30_000 });
  expect(Number(await check.getAttribute("data-checked"))).toBeGreaterThanOrEqual(1);
  await expect(check).toContainText("None differed.");
  await expect(kept.getByTestId("kept-differed")).toHaveCount(0);
  await expectClean(page, seen);
});
