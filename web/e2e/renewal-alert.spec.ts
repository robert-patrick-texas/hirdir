// The browser scenario of the renewal alert in release 0.7.0 (P-117, P-128, as the owner
// answered it: once a day):
//
//   After signing in, a person with the Inventory or the Admin role is shown a banner
//   under the header of every page while the server says to show it: how many contracts
//   have lapsed, have a renewal pending and end within the warning period, each leading
//   to its list on the Renewals page. Dismissed, it is not shown again that day, in this
//   browser or another, also when another contract comes onto a list. A View-only person
//   is never shown it, and the page does not ask for it.
//
// The alert is of the whole inventory: what it counts depends on every contract there
// is, which every other file makes and changes. So this file runs in the project "the
// alert alone", by itself, once every other project has ended (rule 4 of support.ts). It
// keeps to the other rules: an account and names of its own, and nothing changed that
// another file reads.

import { expect, type Page } from "@playwright/test";
import { dayAfter } from "./contractSteps";
import { importFile, region } from "./structure";
import { createAccount, expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const random = mark("x").slice(2);
const suffix = mark("renewal-alert", random);
const upper = random.toUpperCase();
const year = new Date().getFullYear();
const today = new Date().toISOString().slice(0, 10);

const vendor = `Example Alerts ${suffix}`;
const first = `CON-${upper}-A1`;
const second = `CON-${upper}-A2`;

/** The banner of the alert, on the page on show. */
function banner(page: Page) {
  return page.getByTestId("renewal-alert");
}

/** Wait for the page to have read the alert, after it was made to. */
function alertRead(page: Page) {
  return page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname.endsWith("/api/v1/renewals/alert") &&
      response.request().method() === "GET",
  );
}

/** Make a contract of this file's vendor that ends within the warning period. */
async function endingSoon(page: Page, number: string) {
  await page.goto("./contracts");
  await page.getByRole("button", { name: "New contract" }).click();
  const form = region(page, "New contract");
  await form.getByLabel("Number (required)").fill(number);
  await form.getByLabel("Vendor", { exact: true }).selectOption({ label: vendor });
  await form.getByLabel("Starts on").fill(`${year - 1}-01-01`);
  await form.getByLabel("Ends on").fill(dayAfter(today, 30));
  await form.getByRole("button", { name: "Create contract" }).click();
  await expect(page.getByRole("heading", { level: 1, name: number })).toBeVisible();
}

test("P-128: the alert is shown once a day, in every browser, and never to View-only", async ({
  page,
  account,
  browser,
  playwright,
}) => {
  test.setTimeout(240_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  await importFile(page, "vendors", `vendors-${suffix}.csv`, ["name"], [[vendor]]);
  await endingSoon(page, first);

  // A contract ends within the warning period, and this account has dismissed nothing.
  const read = alertRead(page);
  await page.goto("./");
  await read;
  const ending = banner(page).locator('li[data-section="ending"]');
  await expect(ending).toBeVisible();
  expect(Number(await ending.getAttribute("data-count"))).toBeGreaterThanOrEqual(1);

  // A count leads to its list on the Renewals page, and the banner is there too.
  await ending.getByRole("link").first().click();
  await expect(page.getByRole("heading", { level: 1, name: "Renewals" })).toBeVisible();
  await expect(page.getByTestId("renewal-open")).toHaveAttribute("data-section", "ending");
  await expect(banner(page)).toBeVisible();

  // Dismissed, it is gone, and stays gone when the page is read again.
  await banner(page).getByRole("button", { name: "Dismiss" }).click();
  await expect(banner(page)).toHaveCount(0);
  const again = alertRead(page);
  await page.reload();
  await again;
  await expect(page.getByRole("heading", { level: 1, name: "Renewals" })).toBeVisible();
  await expect(banner(page)).toHaveCount(0);

  // What was dismissed is kept on the server: another browser does not show it today.
  const otherContext = await browser.newContext();
  const otherPage = await otherContext.newPage();
  const otherRead = alertRead(otherPage);
  await signIn(otherPage, account);
  await otherRead;
  await expect(banner(otherPage)).toHaveCount(0);
  await otherContext.close();

  // Another contract onto a list does not bring it back the same day.
  await endingSoon(page, second);
  const later = alertRead(page);
  await page.goto("./");
  await later;
  await expect(banner(page)).toHaveCount(0);

  await expectClean(page, seen);

  // A View-only person is never shown it, and the page does not ask for it.
  const api = await playwright.request.newContext({
    baseURL: test.info().project.use.baseURL,
    ignoreHTTPSErrors: true,
  });
  const viewer = await createAccount(api, `e2e-${mark("renewal-alert")}-viewer`, "viewer");
  await api.dispose();
  const viewerContext = await browser.newContext();
  const viewerPage = await viewerContext.newPage();
  const asked: string[] = [];
  viewerPage.on("request", (request) => {
    if (new URL(request.url()).pathname.endsWith("/api/v1/renewals/alert")) {
      asked.push(request.url());
    }
  });
  await signIn(viewerPage, viewer);
  await viewerPage.goto("./contracts/renewals");
  await expect(viewerPage.getByRole("heading", { level: 1, name: "Renewals" })).toBeVisible();
  await expect(banner(viewerPage)).toHaveCount(0);
  expect(asked, "the alert asked for by a View-only person").toEqual([]);
  await viewerContext.close();
});
