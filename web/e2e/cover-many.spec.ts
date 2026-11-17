// The browser scenario of covering more than a thousand items at once, in release 0.6.1,
// for what only unit tests held before:
//
//   D-137  The server takes a thousand items to a request, `MAX_AT_ONCE` in
//          src/hirdir/domain/contracts.py, and covers all of them or none. A thousand
//          rows chosen in the item grid go in one request. More go a thousand to a
//          request, one after another; should one be refused, the page says how many
//          were covered before it, and those stay covered.
//
// It has a file of its own: loading a thousand switches is the longest part of it, and no
// other scenario needs them. It keeps to the rules of support.ts: an account and names of
// its own, and every grid filtered down to this file's records before anything is counted.

import { expect, type Page, type Request } from "@playwright/test";
import { newContract, openContract, pickContract } from "./contractSteps";
import { importFile, openItem } from "./structure";
import { expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const random = mark("x").slice(2);
const suffix = mark("cover-many", random);
const upper = random.toUpperCase();
const year = new Date().getFullYear();

/** As many as one request takes: `MAX_AT_ONCE` of the server. */
const AT_ONCE = 1000;
// A count in a sentence, with the separator of thousands (P-195).
const n = (count: number) => count.toLocaleString("en-US");

const vendor = `Example Networks ${suffix}`;
const pid = `EN-9200-48P-${suffix}`;
const prefix = `site5-sw-${suffix}`;
const many = Array.from(
  { length: AT_ONCE },
  (_, at) => `${prefix}-a-${String(at + 1).padStart(4, "0")}`,
);
// One more, loaded after the others: its HID comes after theirs, so it is in the last request.
const oneMore = `${prefix}-b-0001`;
const thousand = `hostname:prefix:${prefix}-a-`;
const all = `hostname:prefix:${prefix}-`;
const whole = `CON-${suffix}-W`;
const partly = `CON-${suffix}-P`;

/** The requests that put items under a contract, as the page sends them. */
function coverRequests(page: Page): Request[] {
  const sent: Request[] = [];
  page.on("request", (request) => {
    if (
      request.method() === "POST" &&
      /\/api\/v1\/contracts\/[^/]+\/coverage$/.test(request.url())
    ) {
      sent.push(request);
    }
  });
  return sent;
}

/** How many items each request named. */
function sizes(sent: Request[]): number[] {
  return sent.map((request) => (request.postDataJSON() as { items: unknown[] }).items.length);
}

/** Select every row of the item grid that a filter keeps, and open the form to cover them. */
async function coverAll(page: Page, filter: string, count: number) {
  await page.goto(`./items?filter=${encodeURIComponent(filter)}`);
  await expect(page.getByTestId("grid-total")).toHaveText(`${n(count)} items`);
  await page.getByRole("button", { name: "Select all that match" }).click();
  await page.getByRole("button", { name: "Cover with a contract" }).click();
  const cover = page.getByTestId("cover-items");
  await expect(
    cover.getByRole("heading", { name: `Cover ${n(count)} items with a contract` }),
  ).toBeVisible();
  await expect(cover).toContainText(`All ${n(count)} items that match the filter.`);
  return cover;
}

test("a thousand switches and one more are loaded, and two contracts made", async ({
  page,
  account,
}) => {
  test.setTimeout(300_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  await importFile(page, "vendors", `vendors-${suffix}.csv`, ["name"], [[vendor]]);
  await importFile(
    page,
    "catalog_entries",
    `catalog-entries-${suffix}.csv`,
    ["vendor", "pid", "model_name", "type"],
    [[vendor, pid, "Example 9200 48-port", "switch"]],
  );
  const header = ["vendor", "pid", "serial_number", "hostname", "lifecycle_state"];
  await importFile(
    page,
    "items",
    `items-${suffix}.csv`,
    header,
    many.map((name, at) => [
      vendor,
      pid,
      `ENM${upper}A${String(at + 1).padStart(4, "0")}`,
      name,
      "Prod",
    ]),
    { timeout: 120_000 },
  );
  await importFile(page, "items", `items-${suffix}-b.csv`, header, [
    [vendor, pid, `ENM${upper}B0001`, oneMore, "Prod"],
  ]);
  for (const number of [whole, partly]) {
    await newContract(page, {
      number,
      vendor,
      starts: `${year - 1}-01-01`,
      ends: `${year + 2}-12-31`,
    });
  }
  await expectClean(page, seen);
});

test("D-137: a thousand go in one request, and more a thousand to a request", async ({
  page,
  account,
}) => {
  test.setTimeout(300_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  const sent = coverRequests(page);

  // At the limit: a thousand are one request, all of them or none.
  const atLimit = await coverAll(page, thousand, AT_ONCE);
  await expect(atLimit).toContainText("In one request: all of them, or none.");
  await atLimit.getByRole("button", { name: "Cancel" }).click();

  // Past it: a thousand to a request, one after another.
  const pastLimit = await coverAll(page, all, AT_ONCE + 1);
  await expect(pastLimit).toContainText(
    `They go ${n(AT_ONCE)} to a request, one request after another: each request covers all of its items, or none.`,
  );
  await pickContract(pastLimit, whole);
  await pastLimit.getByRole("button", { name: `Cover ${n(AT_ONCE + 1)} items` }).click();
  await expect(
    page.getByText(
      `${n(AT_ONCE + 1)} items are now under ${whole}. Nothing was written to any of them.`,
    ),
  ).toBeVisible({ timeout: 120_000 });
  expect(sizes(sent)).toEqual([AT_ONCE, 1]);

  await openContract(page, whole);
  await expect(page.getByTestId("covered-items")).toHaveText(`${n(AT_ONCE + 1)} items`);
  await expect(page.getByTestId("grid-total")).toHaveText(`${n(AT_ONCE + 1)} coverages`);
  await expectClean(page, seen);
});

test("D-137: a request refused after the first was taken leaves the first covered, and says so", async ({
  page,
  account,
}) => {
  test.setTimeout(300_000);
  const seen = await watch(page.context());
  await signIn(page, account);

  // The one more is under the second contract already, by itself.
  await openItem(page, oneMore);
  await page.getByRole("button", { name: "Cover with a contract" }).click();
  const single = page.getByTestId("cover-items");
  await pickContract(single, partly);
  await single.getByRole("button", { name: `Cover ${oneMore}` }).click();
  await expect(page.getByTestId("item-contract-count")).toHaveAttribute("data-count", "2");

  // All of them again: the first request covers the thousand, the second is refused,
  // since the contract covers the one more in those days already.
  const sent = coverRequests(page);
  const cover = await coverAll(page, all, AT_ONCE + 1);
  await pickContract(cover, partly);
  await cover.getByRole("button", { name: `Cover ${n(AT_ONCE + 1)} items` }).click();
  await expect(cover.locator('.alert-error[data-status="409"]')).toBeVisible({ timeout: 120_000 });
  await expect(cover.locator(".warning")).toHaveText(
    `${n(AT_ONCE)} items were put under the contract before this was refused, and are covered.`,
  );
  expect(sizes(sent)).toEqual([AT_ONCE, 1]);

  await openContract(page, partly);
  await expect(page.getByTestId("covered-items")).toHaveText(`${n(AT_ONCE + 1)} items`);
  await openItem(page, many[0] ?? "");
  await expect(page.getByTestId("item-contract-count")).toHaveAttribute("data-count", "2");
  await expectClean(page, seen, ["409 POST"]);
});
