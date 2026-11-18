// The browser scenarios of lane C2 of the third review of the web UI: the items a
// contract covers found by plain words, and an end on the contract's last day that is
// not announced as kept (P-213); the renewal form that starts from what follows
// (P-214); the lists of contracts, renewals and agreements (P-212); what an agreement's
// contracts cost a year (P-215); and what a minor item is and where (P-216).
//
// The file keeps the rules of support.ts. It signs in as an Admin of its own, and its
// mark is in every name it gives a record: the vendor, the models, the items, the
// contracts, the agreement and the site, all made through the API as that Admin. It
// changes no setting, no list of choices and no account, and counts only its own
// records: a grid is filtered down to them before its rows are counted.

import type { APIRequestContext, Page } from "@playwright/test";
import { expect } from "@playwright/test";
import { gridRow } from "./contractSteps";
import { type Account, expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const id = mark("review-3d");
const upper = id.slice(-6).toUpperCase();
const label = (name: string) => `${name} ${id}`;
const year = new Date().getFullYear();

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

/** The vendor and the model the scenarios share, made once. */
const made: { vendor?: string; model?: string } = {};

async function vendorAndModel(request: APIRequestContext, headers: Headers) {
  if (made.vendor === undefined) {
    made.vendor = (await make(request, headers, "/vendors", { name: label("Example Fabric") })).hid;
    made.model = (
      await make(request, headers, "/catalog-entries", {
        vendor_hid: made.vendor,
        pid: `EF-SW-${upper}`,
        model_name: "Example fabric switch",
        type: "switch",
      })
    ).hid;
  }
  return { vendor: made.vendor, model: made.model ?? "" };
}

/** A contract over new items of the shared model, for the period given. */
async function contractOver(
  request: APIRequestContext,
  headers: Headers,
  number: string,
  hostnames: readonly string[],
  period: { starts: string; ends: string; agreement?: string; cost?: string },
) {
  const { vendor, model } = await vendorAndModel(request, headers);
  const contract = await make(request, headers, "/contracts", {
    number,
    vendor_hid: vendor,
    starts_on: period.starts,
    ends_on: period.ends,
    ...(period.agreement ? { agreement_hid: period.agreement } : {}),
    ...(period.cost ? { annual_cost: period.cost } : {}),
  });
  const items: string[] = [];
  for (const [at, hostname] of hostnames.entries()) {
    const item = await make(request, headers, "/items", {
      catalog_entry_hid: model,
      hostname,
      serial_number: `EFS${upper}${number.slice(-2)}${at}`,
      asset_tag: `AT-${upper}-${number.slice(-2)}${at}`,
      lifecycle_state: "Prod",
    });
    items.push(item.hid);
  }
  if (items.length > 0) {
    const answer = await request.post(`./api/v1/contracts/${contract.hid}/coverage`, {
      headers,
      data: { items: items.map((item_hid) => ({ item_hid })) },
    });
    expect(answer.ok(), `cover: ${await answer.text()}`).toBe(true);
  }
  return { hid: contract.hid, items };
}

async function openContractPage(page: Page, hid: string, number: string) {
  await page.goto(`./contracts/${hid}`);
  await expect(page.getByRole("heading", { level: 1, name: number })).toBeVisible();
}

test("P-213: the items a contract covers are found by plain words, and an end on its last day is not announced as kept", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(180_000);
  const seen = await watch(page.context());
  const headers = await session(request, account);
  const number = `EFC-${upper}-13`;
  const hosts = ["north", "south", "east", "west"].map((side) => `sw-${side}-${id}`);
  const ends = `${year + 1}-12-31`;
  const contract = await contractOver(request, headers, number, hosts, {
    starts: `${year - 1}-01-01`,
    ends,
  });
  await signIn(page, account);
  await openContractPage(page, contract.hid, number);
  const grid = "grid-contract-coverage";
  const section = page.getByRole("region", { name: "Items it covers" });
  await expect(section.getByTestId("grid-total")).toHaveText("4 coverages");

  // Plain words look in the item's serial number, its asset tag and its name.
  const box = section.getByLabel("Filter", { exact: true });
  await box.fill(`EFS${upper}131`);
  await section.getByRole("button", { name: "Apply", exact: true }).click();
  await expect(section.getByTestId("grid-total")).toHaveText("1 coverage");
  await expect(gridRow(page, grid, hosts[1] ?? "")).toBeVisible();
  await box.fill(`AT-${upper}-132`);
  await section.getByRole("button", { name: "Apply", exact: true }).click();
  await expect(section.getByTestId("grid-total")).toHaveText("1 coverage");
  await expect(gridRow(page, grid, hosts[2] ?? "")).toBeVisible();
  await box.fill(`west ${id}`);
  await section.getByRole("button", { name: "Apply", exact: true }).click();
  await expect(section.getByTestId("grid-total")).toHaveText("1 coverage");
  await expect(gridRow(page, grid, hosts[3] ?? "")).toBeVisible();

  // An end on the contract's own last day is said, before it is sent, to change nothing.
  await gridRow(page, grid, hosts[3] ?? "")
    .locator('[col-id="item.pid"]')
    .click();
  await section.getByRole("button", { name: "End coverage" }).click();
  const ending = page.getByTestId("end-coverage");
  await expect(ending.getByTestId("end-follows")).toHaveCount(0);
  await ending.getByLabel("Last day (required)").fill(ends);
  await expect(ending.getByTestId("end-follows")).toContainText(
    `${ends} is the contract's own last day: ending on it changes nothing.`,
  );
  await expect(ending.getByTestId("end-follows")).toContainText("mark it not to be renewed");
  await ending.getByRole("button", { name: "End coverage" }).click();
  // The server kept the contract's period: the page does not say it was ended.
  const notice = page.getByText(/The coverage was not ended: /);
  await expect(notice).toBeVisible();
  await expect(notice).toContainText(`${ends} is the contract's own last day`);
  await expect(page.getByText(/coverages? (was|were) ended on/)).toHaveCount(0);
  await expect(
    gridRow(page, grid, hosts[3] ?? "").locator('[col-id="effective.ends_on"]'),
  ).toHaveClass(/cell-inherited/);

  // An earlier day is kept, and is said to be.
  const earlier = `${year + 1}-06-30`;
  await gridRow(page, grid, hosts[3] ?? "")
    .locator('[col-id="item.pid"]')
    .click();
  await section.getByRole("button", { name: "End coverage" }).click();
  await ending.getByLabel("Last day (required)").fill(earlier);
  await expect(ending.getByTestId("end-follows")).toHaveCount(0);
  await ending.getByRole("button", { name: "End coverage" }).click();
  await expect(
    page.getByText(`1 coverage was ended on ${earlier}. Nothing was removed.`),
  ).toBeVisible();
  await expect(
    gridRow(page, grid, hosts[3] ?? "").locator('[col-id="effective.ends_on"]'),
  ).toHaveText(earlier);
  await expectClean(page, seen);
});

/** The version of a record as the API reads it now. */
async function versionOf(request: APIRequestContext, headers: Headers, path: string) {
  const answer = await request.get(`./api/v1${path}`, { headers });
  expect(answer.ok(), `get ${path}`).toBe(true);
  return ((await answer.json()) as { row_version: number }).row_version;
}

async function patch(request: APIRequestContext, headers: Headers, path: string, data: object) {
  const answer = await request.patch(`./api/v1${path}`, {
    headers,
    data: { row_version: await versionOf(request, headers, path), ...data },
  });
  expect(answer.ok(), `patch ${path}: ${await answer.text()}`).toBe(true);
}

test("P-214: the renewal form starts from what follows, and says what follows, stays behind and begins with it", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(180_000);
  const seen = await watch(page.context());
  const headers = await session(request, account);
  const number = `EFC-${upper}-14`;
  const ends = `${year + 1}-12-31`;
  const hosts = ["one", "two", "flagged", "ending"].map((side) => `sw-${side}-${id}`);
  const contract = await contractOver(request, headers, number, hosts, {
    starts: `${year}-01-01`,
    ends,
  });
  await patch(request, headers, `/contracts/${contract.hid}`, {
    purchase_reference: `REQ-${upper}-OLD`,
  });
  // One item is marked not to be renewed; one coverage ends on a day of its own.
  const [, , flagged, ending] = contract.items;
  await patch(request, headers, `/items/${flagged}`, { do_not_renew: true });
  const rows = await request.get(`./api/v1/contracts/${contract.hid}/coverage`, {
    headers,
    params: { filter: `item_hid:eq:${ending}` },
  });
  const [row] = ((await rows.json()) as { items: { hid: string; row_version: number }[] }).items;
  const ended = await request.patch(`./api/v1/contracts/${contract.hid}/coverage/${row?.hid}`, {
    headers,
    data: { row_version: row?.row_version, ends_on: `${year + 1}-06-30` },
  });
  expect(ended.ok(), await ended.text()).toBe(true);
  // And one item is put under it from the day the next term begins.
  const { model } = await vendorAndModel(request, headers);
  const later = await make(request, headers, "/items", {
    catalog_entry_hid: model,
    hostname: `sw-later-${id}`,
    serial_number: `EFS${upper}149`,
    lifecycle_state: "Prod",
  });
  const added = await request.post(`./api/v1/contracts/${contract.hid}/coverage`, {
    headers,
    data: { items: [{ item_hid: later.hid, starts_on: `${year + 2}-01-01` }] },
  });
  expect(added.ok(), await added.text()).toBe(true);

  await signIn(page, account);
  await openContractPage(page, contract.hid, number);
  const renew = page.getByRole("region", { name: "Renew" });
  await renew.getByRole("button", { name: "Renew", exact: true }).click();
  const form = page.getByTestId("renew-form");
  // The period that follows the present term, a year from the day after it ends.
  await expect(form.getByLabel("New period: starts on")).toHaveValue(`${year + 2}-01-01`);
  await expect(form.getByLabel("New period: ends on")).toHaveValue(`${year + 2}-12-31`);
  await expect(form.getByLabel("Purchase reference")).toHaveValue("");
  // Under the button: what follows, what stays behind, what begins with the new term.
  const follows = form.getByTestId("renew-follows");
  await expect(follows.getByTestId("renew-follow")).toHaveAttribute("data-count", "3");
  await expect(follows.getByTestId("renew-follow")).toContainText(
    "3 coverages have the contract's period and follow into the new term, but for those of the items marked not to be renewed.",
  );
  await expect(follows.getByTestId("renew-flagged")).toHaveAttribute("data-count", "1");
  await expect(follows.getByTestId("renew-flagged")).toContainText(
    "1 item it covers today is marked not to be renewed, and stays behind",
  );
  await expect(follows.getByTestId("renew-begin")).toContainText(
    `1 coverage begins after ${ends}, with the new term.`,
  );
  await expect(follows.getByTestId("renew-own-end")).toContainText(
    `1 coverage ends on a day of its own by ${ends}, and does not follow.`,
  );
  // The count of what stays behind leads to those items.
  await expect(follows.getByRole("link", { name: "1 item it covers today" })).toHaveAttribute(
    "href",
    /effective\.do_not_renew/,
  );
  // Nothing more is typed than the new reference: the renewal is kept as the next term.
  await form.getByLabel("Purchase reference").fill(`REQ-${upper}-NEW`);
  await form.getByRole("button", { name: /^Renew for \d+ items?$/ }).click();
  await expect(page.getByText(/^The renewal is kept as the next term\./)).toBeVisible();
  await expect(page.getByTestId("next-term")).toHaveAttribute("data-starts", `${year + 2}-01-01`);
  await expect(page.getByTestId("next-term")).toContainText(`REQ-${upper}-NEW`);
  await expectClean(page, seen);
});
