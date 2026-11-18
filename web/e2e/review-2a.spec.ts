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
  // Both stand within the window from the start, with nothing hidden to make room.
  await page.getByText("Columns", { exact: true }).click();
  await expect(header("location.name")).toBeInViewport({ ratio: 1 });
  await expect(header("site")).toBeInViewport({ ratio: 1 });
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
  // On a busy server the parts of the page above the form come late and push it down
  // after Change has moved to it: the field is still in the window when they have come.
  await page.route("**/api/v1/items/*/resolution*", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 1500));
    await route.continue();
  });
  await openItem(page, edge.hid, host("kiln-sw-edge"));
  const identity = region(page, "Identity");

  // Its standing among the first facts, with Change, which moves to the form of a move.
  await expect(identity.getByTestId("standing-fact")).toHaveText(
    "Prod · Production · Expected online",
  );
  await identity.getByRole("button", { name: "Change the lifecycle state" }).click();
  const to = region(page, "Move to another state").getByLabel("Move to");
  await expect(to).toBeFocused();
  await expect(region(page, "Values in force").getByTestId("walks")).toBeVisible();
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

/** How far below the foot of the window an element ends, in pixels: 0 or less is in it. */
async function belowTheWindow(target: Locator): Promise<number> {
  return target.evaluate((element) =>
    Math.round(element.getBoundingClientRect().bottom - window.innerHeight),
  );
}

test("Save stays in reach, the field with the keyboard is not under it, and New takes the keyboard (P-190)", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(150_000);
  await places(request, account);
  const seen = await watch(page.context());
  await signIn(page, account);
  await openItem(page, made.item ?? "", host("kiln-sw-01"));

  // From Change beside the location to its field: Save is at the foot of the window.
  await region(page, "Identity").getByRole("button", { name: "Change the location" }).click();
  const details = region(page, "Details");
  const location = details.getByLabel("Location", { exact: true });
  await expect(location).toBeFocused();
  const save = details.getByRole("button", { name: "Save", exact: true });
  await expect(save).toBeInViewport({ ratio: 1 });
  expect(await belowTheWindow(save), "Save is within the window").toBeLessThanOrEqual(0);

  // Tab through the form from its first field: what has the keyboard is never beneath the
  // buttons, which stay at the foot of the window.
  const foot = details.locator(".form-foot");
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  await details.locator("input, select, textarea").first().focus();
  let steps = 0;
  for (; steps < 80; steps += 1) {
    const where = await page.evaluate(() => {
      const focused = document.activeElement as HTMLElement | null;
      const footer = document.querySelector('section[aria-labelledby="details"] .form-foot');
      if (!focused || !footer || footer.contains(focused)) return null;
      if (!focused.closest('section[aria-labelledby="details"]')) return null;
      const box = focused.getBoundingClientRect();
      const above = Math.min(footer.getBoundingClientRect().top, window.innerHeight);
      return { top: box.top, bottom: box.bottom, above };
    });
    if (where === null) break;
    expect(where.top, `field ${steps} is in the window`).toBeGreaterThanOrEqual(0);
    expect(where.bottom, `field ${steps} is above the buttons`).toBeLessThanOrEqual(
      where.above + 1,
    );
    await page.keyboard.press("Tab");
  }
  expect(steps, "the form has many fields to pass through").toBeGreaterThan(10);
  await expect(foot).toBeInViewport();

  // New contract, far down the page of contracts: the form comes into the window with the
  // keyboard in its first field.
  await page.goto("./contracts");
  await expect(page.getByRole("heading", { level: 1, name: "Contracts" })).toBeVisible();
  const newContract = page.getByRole("button", { name: "New contract" });
  await newContract.scrollIntoViewIfNeeded();
  await newContract.click();
  const contractForm = region(page, "New contract");
  await expect(contractForm.getByRole("heading", { name: "New contract" })).toBeInViewport();
  await expect(contractForm.locator("input, select, textarea").first()).toBeFocused();
  await contractForm.getByRole("button", { name: "Cancel" }).click();

  // New item, while the lists it offers come late, as on a busy server.
  await page.route("**/api/v1/catalog-entries*", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 1500));
    await route.continue();
  });
  await page.goto("./items");
  await expect(page.getByRole("heading", { level: 1, name: "Items" })).toBeVisible();
  await page.getByRole("button", { name: "New item" }).click();
  const itemForm = region(page, "New item");
  await expect(itemForm.getByLabel("Catalog entry")).toBeFocused();
  await expect(itemForm.getByLabel("Catalog entry")).toBeInViewport();
  await page.unroute("**/api/v1/catalog-entries*");
  await itemForm.getByRole("button", { name: "Cancel" }).click();

  // A page opened from a link begins at its top all the same, with no form taking the
  // keyboard (P-167).
  await page
    .getByRole("navigation", { name: "Main" })
    .getByRole("link", { name: "Contracts" })
    .click();
  await expect(page.getByRole("heading", { level: 1, name: "Contracts" })).toBeVisible();
  expect(await page.evaluate(() => window.scrollY)).toBe(0);
  await expect(page.locator("main")).toBeFocused();

  await expectClean(page, seen);
});

test("Create and add another like it makes the item and keeps what the next one shares (P-192)", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(150_000);
  const headers = await places(request, account);
  const owner = label("Plant team");
  await make(request, headers, "/owners", { label: owner });
  const seen = await watch(page.context());
  await signIn(page, account);
  await page.goto("./items");
  await page.getByRole("button", { name: "New item" }).click();
  const form = region(page, "New item");
  const serial = form.getByLabel("Serial number");
  const hostname = form.getByLabel("Hostname");
  const another = form.getByRole("button", { name: "Create and add another like it" });

  // The first of a batch, as the form is filled for it.
  await form.getByLabel("Catalog entry").selectOption({ label: made.pid ?? "" });
  await form.getByLabel("Owner").selectOption({ label: owner });
  await form.getByLabel("Location", { exact: true }).fill(label("Room 5"));
  await form
    .getByRole("list", { name: "Locations that match" })
    .getByRole("button", { name: new RegExp(label("Room 5")) })
    .click();
  await form.getByLabel("Lifecycle state").selectOption("Assigned");
  await serial.fill(`SN-${id}-A`);
  await form.getByLabel("Asset tag").fill(`AT-${id}-A`);
  await form.getByLabel("Name", { exact: true }).fill(label("Batch A"));
  await hostname.fill(host("batch-a"));
  await form.getByLabel("MAC address").fill("00-00-5E-00-53-0A");

  const notice = page.getByRole("status").filter({ hasText: "Created" });
  const made2: string[] = [];
  for (const [step, next] of [
    ["A", "B"],
    ["B", "C"],
  ] as const) {
    await another.click();
    // The page says so, with a link to it, in the window.
    const link = notice.getByRole("link", { name: label(`Batch ${step}`) });
    await expect(link).toBeVisible();
    await expect(notice).toBeInViewport();
    made2.push(((await link.getAttribute("href")) ?? "").split("/").pop() ?? "");
    // The form stays open: what is each one's own is blank, the keyboard in the serial.
    await expect(serial).toBeFocused();
    for (const own of ["Serial number", "Asset tag", "Name", "Hostname", "MAC address"]) {
      await expect(form.getByLabel(own, { exact: true })).toHaveValue("");
    }
    await expect(form.getByLabel("Catalog entry")).not.toHaveValue("");
    await expect(form.getByLabel("Owner")).not.toHaveValue("");
    await expect(form.getByTestId("chosen-location_hid")).toContainText(label("Room 5"));
    await expect(form.getByLabel("Lifecycle state")).toHaveValue("Assigned");
    await serial.fill(`SN-${id}-${next}`);
    await form.getByLabel("Name", { exact: true }).fill(label(`Batch ${next}`));
    await hostname.fill(host(`batch-${next.toLowerCase()}`));
  }

  // A serial number that is there already is refused, and what was typed is kept.
  await serial.fill(`SN-${id}-A`);
  await another.click();
  await expect(form.getByText(/There is already an item of this vendor and PID/)).toBeVisible();
  await expect(serial).toHaveAttribute("aria-invalid", "true");
  await expect(serial).toHaveValue(`SN-${id}-A`);
  await expect(hostname).toHaveValue(host("batch-c"));

  // Once one was made by the second button, Enter in a box makes the next as it does, as
  // a scanner's Enter after the serial number would: the run goes on (A3 of the review).
  await serial.fill(`SN-${id}-C`);
  await expect(form.getByTestId("enter-as-another")).toBeVisible();
  await serial.press("Enter");
  await expect(notice.getByRole("link", { name: label("Batch C") })).toBeVisible();
  await expect(page).toHaveURL(/\/items$/);
  await expect(serial).toBeFocused();
  await expect(serial).toHaveValue("");
  await expect(form.getByTestId("chosen-location_hid")).toContainText(label("Room 5"));

  // Create alone opens the new item, as it did.
  await serial.fill(`SN-${id}-D`);
  await form.getByLabel("Name", { exact: true }).fill(label("Batch D"));
  await hostname.fill(host("batch-d"));
  await form.getByRole("button", { name: "Create item" }).click();
  await expect(page.getByRole("heading", { level: 1, name: label("Batch D") })).toBeVisible();

  // The two made by the second button: the second has what the first shared.
  const read = async (hid: string) =>
    (await (await request.get(`./api/v1/items/${hid}`, { headers })).json()) as Record<
      string,
      unknown
    >;
  const [first, second] = [await read(made2[0] ?? ""), await read(made2[1] ?? "")];
  for (const field of ["catalog_entry_hid", "owner_hid", "location_hid", "lifecycle_state"]) {
    expect(second[field], field).toBe(first[field]);
    expect(second[field], field).toBeTruthy();
  }
  expect(first.serial_number).toBe(`SN-${id}-A`);
  expect(second.serial_number).toBe(`SN-${id}-B`);
  expect(second.asset_tag ?? null).toBeNull();
  expect(second.mac_address ?? null).toBeNull();

  await expectClean(page, seen, ["409 POST"]);
});
