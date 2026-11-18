// The browser scenarios of lane W2 of release 0.9.8:
//
//   P-240  The tables not yet looked at one by one are. The record of an audit event
//          opens its page, and one that an event on show deleted is text, said to be
//          deleted; one deleted in an event not on show leads to a page that says so.
//          The user who did it opens the user's page, for an Admin. A row of the
//          summary by owner opens the owner's page.
//   P-239  The username in the list of contacts is a link to the user's page for an
//          Admin, and text for every other role.
//   0.9.7  A file chosen before the kinds of file are read is given its first kind when
//          they are: a picture, a photograph.
//
// The file keeps the rules of support.ts: it signs in as an Admin of its own, makes a
// View-only account of its own, which it disables when it ends, and its mark is in every
// name it gives a record. The records are made through the API. The audit trail is
// filtered to device groups and its rows found by the HIDs of the file's own.

import { randomBytes } from "node:crypto";
import { type APIRequestContext, type Browser, expect, type Page } from "@playwright/test";
import {
  choose,
  chosen,
  filesOf,
  type Headers,
  make,
  openPlace,
  pdf,
  png,
  session,
} from "./referenceSteps";
import { type Account, createAccount, expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const random = randomBytes(3).toString("hex");
const suffix = mark("table-links", random);
const owner = `Network Engineering ${suffix}`;
const host = `site9-sw-tables-${suffix}-01`;
const kept = `site9-cluster-kept-${suffix}`;
const removed = `site9-cluster-mistake-${suffix}`;
const reason = `Made by mistake ${suffix}`;
const person = { name: `Vera Viewer ${suffix}`, email: `vera.${suffix}@example.com` };

const made: { owner?: string; kept?: string; removed?: string } = {};

/** Sign in, in a browser of its own, as another account. */
async function signInElsewhere(browser: Browser, account: Account) {
  const context = await browser.newContext();
  const page = await context.newPage();
  const seen = await watch(context);
  await signIn(page, account);
  return { context, page, seen };
}

/** Disable an account the file made, which ends its sessions. */
async function disable(request: APIRequestContext, headers: Headers, account: Account) {
  const path = `./api/v1/users/${encodeURIComponent(account.hid)}`;
  const found = (await (await request.get(path, { headers })).json()) as { row_version: number };
  const answer = await request.patch(path, {
    headers,
    data: { disabled: true, row_version: found.row_version },
  });
  expect(answer.status(), "the View-only account is disabled").toBe(200);
}

/** The list of contacts, filtered down to the user the file made. */
async function contactsOfFile(page: Page) {
  const filter = `is_user:eq:true name:contains:${suffix}`;
  await page.goto(`./contacts?filter=${encodeURIComponent(filter)}`);
  const grid = page.getByTestId("grid-contacts");
  await expect(grid.locator("[row-id]")).toHaveCount(1, { timeout: 20_000 });
  return grid.locator('[row-id] [col-id="is_user"]');
}

test("the records of the file are made, and a group of them deleted", async ({
  account,
  request,
}) => {
  const headers = await session(request, account);
  const vendor = await make(request, headers, "/vendors", { name: `Example Networks ${suffix}` });
  const entry = await make(request, headers, "/catalog-entries", {
    vendor_hid: vendor.hid,
    pid: `EN-4800-${suffix}`,
  });
  const theOwner = await make(request, headers, "/owners", { label: owner });
  await make(request, headers, "/items", {
    catalog_entry_hid: entry.hid,
    serial_number: `ENT${suffix.toUpperCase()}01`,
    hostname: host,
    owner_hid: theOwner.hid,
  });
  const one = await make(request, headers, "/device-groups", { type: "cluster", name: kept });
  const other = await make(request, headers, "/device-groups", { type: "cluster", name: removed });
  const answer = await request.post("./api/v1/device-groups/delete", {
    headers,
    data: { hids: [other.hid], reason },
  });
  expect(answer.status(), `the group is deleted: ${await answer.text()}`).toBe(200);
  Object.assign(made, { owner: theOwner.hid, kept: one.hid, removed: other.hid });
});

test("P-240: an audit event's record opens its page, and a deleted one is text that says so", async ({
  page,
  account,
}) => {
  const seen = await watch(page.context());
  await signIn(page, account);
  await page.goto("./audit?record_type=device_group");
  const trail = page.locator("table.audit");
  const ofKept = trail.locator("tbody tr", { hasText: made.kept ?? "" });
  await expect(ofKept).toHaveCount(1, { timeout: 20_000 });
  const record = ofKept.getByRole("link", { name: made.kept, exact: true });
  await expect(record).toHaveAttribute("href", new RegExp(`/groups/${made.kept}$`));
  // Who did it is the account of the file, whose page an Admin opens.
  const who = ofKept.getByRole("link", { name: account.username, exact: true });
  await expect(who).toHaveAttribute("href", new RegExp(`/admin/users/${account.hid}$`));
  await expect(who).toHaveClass(/value-link/);

  // The group deleted: its creation and its deletion are both on show, and name it as
  // text, said to be deleted.
  const ofRemoved = trail.locator("tbody tr", { hasText: made.removed ?? "" });
  await expect(ofRemoved).toHaveCount(2);
  await expect(ofRemoved.getByRole("link", { name: made.removed })).toHaveCount(0);
  for (const row of await ofRemoved.all()) await expect(row).toContainText("deleted");

  await record.click();
  await expect(page.getByRole("heading", { level: 1, name: kept })).toBeVisible();

  // With the creations alone on show, the list cannot know: the link leads to a page
  // that says the group was deleted, and why.
  await page.goto("./audit?action=create&record_type=device_group");
  const created = trail.locator("tbody tr", { hasText: made.removed ?? "" });
  await expect(created).toHaveCount(1, { timeout: 20_000 });
  await created.getByRole("link", { name: made.removed, exact: true }).click();
  await expect(page.getByTestId("deleted-reason")).toHaveText(`The reason given: ${reason}`);
  await expectClean(page, seen, ["404 GET"]);
});

test("P-240: a row of the summary by owner opens the owner's page", async ({ page, account }) => {
  const seen = await watch(page.context());
  await signIn(page, account);
  await page.goto(`./reports?by=owner&filter=${encodeURIComponent(`hostname:eq:${host}`)}`);
  const name = page.getByRole("rowheader").getByRole("link", { name: owner, exact: true });
  await expect(name).toHaveAttribute("href", new RegExp(`/owners/${made.owner}$`));
  await name.click();
  await expect(page.getByRole("heading", { level: 1, name: owner })).toBeVisible();
  await expectClean(page, seen);
});

test("P-239: the username of a contact is a link for an Admin, and text for View-only", async ({
  page,
  account,
  browser,
  request,
}) => {
  test.setTimeout(120_000);
  const viewer = await createAccount(request, `e2e-${suffix}-vera`, "viewer", person);
  try {
    const seen = await watch(page.context());
    await signIn(page, account);
    const cell = await contactsOfFile(page);
    const link = cell.getByRole("link", { name: viewer.username, exact: true });
    await expect(link).toHaveAttribute("href", new RegExp(`/admin/users/${viewer.hid}$`));
    await expect(link).toHaveClass(/value-link/);
    await link.click();
    await expect(page.getByRole("heading", { level: 1, name: viewer.username })).toBeVisible();
    await expectClean(page, seen);

    const elsewhere = await signInElsewhere(browser, viewer);
    const theirs = await contactsOfFile(elsewhere.page);
    await expect(theirs).toHaveText(viewer.username);
    await expect(theirs.getByRole("link")).toHaveCount(0);
    await expectClean(elsewhere.page, elsewhere.seen);
    await elsewhere.context.close();
  } finally {
    await disable(request, await session(request, account), viewer);
  }
});

test("a file chosen before the kinds of file are read is given its first kind when they are", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(120_000);
  const headers = await session(request, account);
  const region = await make(request, headers, "/regions", { name: `Tables Region ${suffix}` });
  const site = await make(request, headers, "/sites", {
    name: `Tables Site ${suffix}`,
    region_hid: region.hid,
  });
  const location = await make(request, headers, "/locations", {
    name: "Building 1",
    site_hid: site.hid,
  });
  const seen = await watch(page.context());
  await signIn(page, account);
  // The kinds of file are held back until the files are chosen.
  let release = () => {};
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/v1/choices**", async (route) => {
    await held;
    await route.continue();
  });
  await openPlace(
    page,
    "location",
    location.hid,
    `Tables Region ${suffix} > Tables Site ${suffix} > Building 1`,
  );
  const section = filesOf(page);
  const PHOTO = png(`rack-front-${suffix}.png`, 41);
  const PLAN = pdf(`rack-plan-${suffix}.pdf`, "Rack plan");
  await choose(section, [PHOTO, PLAN]);
  const photo = chosen(section, PHOTO.name);
  const plan = chosen(section, PLAN.name);
  await expect(photo.getByLabel("Kind")).toHaveValue("");
  release();
  await expect(photo.getByLabel("Kind")).toHaveValue("photograph", { timeout: 20_000 });
  await expect(plan.getByLabel("Kind")).toHaveValue("");
  await expect(photo.getByLabel("Title")).toHaveValue(`rack-front-${suffix}`);
  await expectClean(page, seen);
});
