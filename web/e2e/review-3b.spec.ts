// The browser scenarios of lane B of the third review of the web UI: a refusal says where
// to go (P-207), counts that open their rows (P-206) and where a contact is named
// (P-205).
//
// The file keeps the rules of support.ts. It signs in as an Admin of its own, and its
// mark is in every name it gives a record: the vendors, the models, the items, the
// contacts and the records that name them, all made through the API as that Admin. It
// changes no setting, no list of choices and no account, and counts only its own
// records: a report is filtered down to them before a number of it is read.

import type { APIRequestContext, Locator, Page } from "@playwright/test";
import { expect } from "@playwright/test";
import { type Account, expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const id = mark("review-3b");

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

function region(page: Page, name: string): Locator {
  return page.getByRole("region", { name, exact: true });
}

test("P-207: a duplicate asset tag names the item that has it, as a link to it", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(120_000);
  const headers = await session(request, account);
  const tag = `AT-${id}`;
  const first = `ex-sw-${id}-01.example.net`;
  await make(request, headers, "/items", { hostname: first, asset_tag: tag });
  const seen = await watch(page.context());
  await signIn(page, account);

  await page.goto("./items");
  await page.getByRole("button", { name: "New item" }).click();
  const form = region(page, "New item");
  await form.getByLabel("Asset tag").fill(tag.toLowerCase());
  await form.getByLabel("Hostname").fill(`ex-sw-${id}-02.example.net`);
  await form.getByRole("button", { name: "Create item" }).click();

  const refusal = page.locator(".alert-error");
  await expect(refusal).toContainText("There is already an item with the asset tag");
  await expect(refusal).toContainText("The item that has it:");
  await refusal.getByRole("link", { name: first }).click();
  await expect(page.getByRole("heading", { level: 1, name: first })).toBeVisible();
  await expectClean(page, seen, ["409 POST"]);
});

test("P-207: a filter of a field the item list has not names the nearest it has", async ({
  page,
  account,
}) => {
  test.setTimeout(120_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  await page.goto("./items");
  const box = page.getByLabel("Filter", { exact: true });
  await box.fill("type:eq:switch");
  await page.getByRole("button", { name: "Apply", exact: true }).click();
  await expect(
    page.getByText(
      "type is not a field this list can be filtered by; the nearest fields it has are catalog.type and group.type",
    ),
  ).toBeVisible();
  await expectClean(page, seen, ["422 POST"]);
});

// What a scenario of P-206 counts: a vendor of its own, a model of it, three major items
// of the model, one of them failed, and a minor item in one of them. `part` tells the
// records of one scenario from those of the other.
interface Counted {
  vendor: string;
  model: string;
  prefix: string;
}

async function counted(
  request: APIRequestContext,
  headers: Headers,
  part: string,
): Promise<Counted> {
  const prefix = `ex-count-${id}-${part}`;
  const name = `Example Counts ${id} ${part}`;
  const vendor = await make(request, headers, "/vendors", { name });
  const model = await make(request, headers, "/catalog-entries", {
    vendor_hid: vendor.hid,
    pid: `EXC-48-${id}-${part}`,
  });
  const first = await make(request, headers, "/items", {
    catalog_entry_hid: model.hid,
    hostname: `${prefix}-01.example.net`,
    condition: "failed",
  });
  for (const place of ["02", "03"]) {
    await make(request, headers, "/items", {
      catalog_entry_hid: model.hid,
      hostname: `${prefix}-${place}.example.net`,
    });
  }
  await make(request, headers, "/items", { parent_item_hid: first.hid, name: `${prefix}-psu` });
  return { vendor: name, model: model.hid, prefix };
}

test("P-206: each count of the summary opens the items it counts", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(180_000);
  const headers = await session(request, account);
  const made = await counted(request, headers, "s");
  const seen = await watch(page.context());
  await signIn(page, account);

  // The summary is held back, as on a busy server: no count leads anywhere until it has
  // come, and then each does.
  let release: () => void = () => {};
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/v1/reports/summary?*", async (route) => {
    await held;
    await route.continue();
  });
  const byVendor = encodeURIComponent(`catalog.vendor:eq:${made.vendor}`);
  await page.goto(`./reports?filter=${byVendor}&by=model`);
  await expect(page.getByText("Counting…")).toBeVisible();
  release();
  const row = page.getByTestId("summary-rows").locator(`tr[data-key="${made.model}"]`);
  await expect(row.locator('[data-measure="items"]')).toHaveText("3");
  await expect(row.locator('[data-measure="components"]')).toHaveText("3");
  await page.unroute("**/api/v1/reports/summary?*");

  // The components of the row: its three major items, and not the one in an item.
  await row.locator('[data-measure="components"]').getByRole("link").click();
  await expect(page.getByTestId("grid-total")).toHaveText("3 items");
  await page.goBack();
  // Its failed components: the one that failed.
  await row.locator('[data-health="failed"]').getByRole("link").click();
  await expect(page.getByTestId("grid-total")).toHaveText("1 item");
  await page.goBack();
  // A managed node is no item, and a count of none leads nowhere.
  await expect(row.locator('[data-measure="components"]').getByRole("link")).toBeVisible();
  await expect(row.locator('[data-measure="nodes"]').getByRole("link")).toHaveCount(0);
  await expect(row.locator('[data-health="degraded"]').getByRole("link")).toHaveCount(0);

  // The totals of the view, with the minor item among its items.
  await page.goto(`./reports?filter=${encodeURIComponent(`name:contains:${made.prefix}`)}`);
  await expect(page.getByTestId("total-items")).toHaveText("4");
  await page.getByTestId("total-items").getByRole("link").click();
  await expect(page.getByTestId("grid-total")).toHaveText("4 items");
  await expectClean(page, seen);
});

test("P-206: a count of the management report opens its items, and money leads nowhere", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(180_000);
  const headers = await session(request, account);
  const made = await counted(request, headers, "m");
  const seen = await watch(page.context());
  await signIn(page, account);
  const byVendor = encodeURIComponent(`catalog.vendor:eq:${made.vendor}`);
  await page.goto(`./reports/management?filter=${byVendor}&by=vendor`);
  const rows = page.getByTestId("management-rows").locator("tbody tr");
  await expect(rows).toHaveCount(1);
  await expect(rows.locator('[data-measure="items"]')).toHaveText("3");
  await expect(rows.locator('[data-measure="items"]').getByRole("link")).toBeVisible();
  await expect(rows.locator('[data-measure="value"]').getByRole("link")).toHaveCount(0);
  await expect(rows.locator('[data-measure="cost"]').getByRole("link")).toHaveCount(0);
  await rows.locator('[data-measure="items"]').getByRole("link").click();
  await expect(page.getByTestId("grid-total")).toHaveText("3 items");
  await expectClean(page, seen);
});

test("P-205: a contact's page lists every record that names it, each a link with the role", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(180_000);
  const headers = await session(request, account);
  const name = `Example Named ${id}`;
  const person = await make(request, headers, "/contacts", {
    name,
    email: `named.${id}@example.net`,
  });
  const region = await make(request, headers, "/regions", { name: `Example North ${id}` });
  await make(request, headers, "/contact-assignments", {
    contact_hid: person.hid,
    region_hid: region.hid,
    role: "technical",
  });
  const vendor = await make(request, headers, "/vendors", { name: `Example Support ${id}` });
  const agreement = await make(request, headers, "/agreements", {
    name: `Example Cover ${id}`,
    vendor_hid: vendor.hid,
  });
  await make(request, headers, `/agreements/${agreement.hid}/contacts`, {
    contact_hid: person.hid,
    role: "account_manager",
  });
  await make(request, headers, `/vendors/${vendor.hid}/contacts`, {
    contact_hid: person.hid,
    role: "support_contact",
  });
  await make(request, headers, "/operators", {
    label: `ex-ops-${id}`.slice(0, 40),
    contact_hid: person.hid,
  });
  const idle = await make(request, headers, "/contacts", { name: `Example Idle ${id}` });
  const seen = await watch(page.context());
  await signIn(page, account);

  // The list of where it is named is held back, as on a busy server.
  let release: () => void = () => {};
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route(`**/api/v1/contacts/${person.hid}/uses`, async (route) => {
    await held;
    await route.continue();
  });
  await page.goto(`./contacts/${person.hid}`);
  const named = page.getByRole("region", { name: "Where it is named" });
  await expect(named.getByText("Loading…")).toBeVisible();
  release();
  await expect(named.getByRole("heading", { level: 3 })).toHaveText([
    "Places it is a contact of",
    "Operators it stands behind",
    "Agreements that name it",
    "Vendors that name it",
  ]);
  await page.unroute(`**/api/v1/contacts/${person.hid}/uses`);
  // No sentence of what the page does not list is left: it lists everything (P-197).
  await expect(page.getByTestId("contact-elsewhere")).toHaveCount(0);
  const places = page.getByTestId("contact-places");
  await expect(places).toContainText("Region");
  await expect(places).toContainText("Technical");
  await expect(page.getByTestId("contact-operators")).toContainText("Behind 1 operator");
  const agreements = page.getByTestId("contact-agreements");
  await expect(agreements).toContainText("Account manager");
  await expect(page.getByTestId("contact-vendors")).toContainText("Support contact");
  await agreements.getByRole("link", { name: `Example Cover ${id}` }).click();
  await expect(page.getByRole("heading", { level: 1, name: `Example Cover ${id}` })).toBeVisible();

  await page.goto(`./contacts/${idle.hid}`);
  await expect(named.getByText("This contact is assigned nowhere.")).toBeVisible();
  await expect(named.getByRole("heading", { level: 3 })).toHaveCount(0);
  await expectClean(page, seen);
});
