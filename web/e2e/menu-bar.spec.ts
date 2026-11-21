// The browser scenario of the menu bar of 0.9.2 (P-167):
//
//   A page opened from the menu bar begins at its top, with the menu bar in view, and
//   focus is on its content, which is not scrolled up to the top of the window: Groups,
//   Addresses, Vendors, Owners, Contracts and Home, each taller than the window.
//   A page opened from a link far down another page begins at its top in the same way.
//
// And of 0.9.15 (P-301): every entry of the menu bar, read from the bar itself so that a
// new one is held too, opens its page at the top with the menu bar in view, the first
// time and again after the person has scrolled each page down and opened a row of each
// list from there. Until 0.9.14 a list put the window back where it had been when a row
// was opened from it (P-203), so that its entry in the menu bar opened it scrolled down,
// past the menu bar: the owner saw it on Contacts and Operators, which this file gives a
// row of its own each.
//
// Until 0.9.1 focus moved to the content of a page by scrolling it to the top of the
// window, past the menu bar and the renewal alert above it, on every page taller than
// the window. The window here is shorter than each of those pages.
//
// How this file keeps to the rules of support.ts: it signs in as an Admin of its own,
// makes one contact and one operator, under its mark, and changes nothing else, and
// reads only where the window is and what has focus, never what is in a list.

import { type APIRequestContext, expect, type Page } from "@playwright/test";
import { main as menuBar } from "./structure";
import { type Account, expectClean, mark, signIn, test, watch } from "./support";

test.use({ viewport: { width: 1280, height: 700 } });

const HOME = /^Welcome, /;

/** Where the window is scrolled to, in pixels from the top of the page. */
function scrolled(page: Page): Promise<number> {
  return page.evaluate(() => window.scrollY);
}

/**
 * The page that has just opened is at its top, with the whole menu bar in view and
 * focus on its content. It is taller than the window, or there would be nothing to see.
 */
async function opensAtItsTop(page: Page, heading: string | RegExp, moved = true) {
  const named = typeof heading === "string" ? heading : "Home";
  await expect(page.getByRole("heading", { level: 1, name: heading, exact: true })).toBeVisible();
  // A grid has read its rows, and the first page its summary: each is as tall as it will be.
  if (heading === HOME) await expect(page.getByTestId("totals")).toBeVisible();
  else await expect(page.getByTestId("grid-total")).not.toBeEmpty();
  // Focus moves to the content of a page that is moved to, not of the first one shown.
  if (moved) await expect(page.locator("main")).toBeFocused();
  const taller = await page.evaluate(
    () => document.documentElement.scrollHeight > window.innerHeight + 100,
  );
  expect(taller, `${named} is taller than the window`).toBe(true);
  expect(await scrolled(page), `${named} opens at its top`).toBe(0);
  await expect(menuBar(page)).toBeInViewport({ ratio: 1 });
  await expect(page.locator(".brand")).toBeInViewport({ ratio: 1 });
}

test("a page opened from the menu bar begins at its top, with the menu bar in view", async ({
  page,
  account,
}) => {
  test.setTimeout(90_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  await opensAtItsTop(page, HOME, false);

  for (const [link, heading] of [
    ["Groups", "Groups"],
    ["Addresses", "Addresses"],
    ["Vendors", "Vendors"],
    ["Owners", "Owners"],
    ["Contracts", "Contracts"],
    ["Home", HOME],
  ] as const) {
    await menuBar(page).getByRole("link", { name: link, exact: true }).click();
    await opensAtItsTop(page, heading);
  }
  await expectClean(page, seen);
});

test("a page opened from a link far down another page begins at its top", async ({
  page,
  account,
}) => {
  test.setTimeout(90_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  const inventory = page.getByRole("region", { name: "Inventory", exact: true });

  for (const link of ["Vendors", "Contracts"]) {
    await page.goto("./");
    await expect(page.getByRole("heading", { level: 1, name: HOME })).toBeVisible();
    await expect(page.getByTestId("totals")).toBeVisible();
    // The link is far down the first page: the window is scrolled to it, past the menu bar.
    await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
    const far = inventory.getByRole("link", { name: link, exact: true });
    await expect(far).toBeInViewport();
    expect(await scrolled(page), "the first page is scrolled down to the link").toBeGreaterThan(0);
    await expect(menuBar(page)).not.toBeInViewport();
    await far.click();
    await opensAtItsTop(page, link);
  }
  await expectClean(page, seen);
});

/** A contact and an operator behind it, so that Contacts and Operators have a row each. */
async function people(request: APIRequestContext, account: Account): Promise<void> {
  const signedIn = await request.post("./api/v1/auth/sign-in", {
    data: { username: account.username, access_code: account.accessCode },
  });
  expect(signedIn.status(), "the account of the file signs in through the API").toBe(200);
  const { token } = (await signedIn.json()) as { token: string };
  const headers = { Authorization: `Bearer ${token}` };
  const id = mark("menu-bar");
  const contact = await request.post("./api/v1/contacts", {
    headers,
    data: { name: `Menu Person ${id}`, email: `${id}@example.com` },
  });
  expect(contact.status(), await contact.text()).toBe(201);
  const { hid } = (await contact.json()) as { hid: string };
  const operator = await request.post("./api/v1/operators", {
    headers,
    data: { label: id, contact_hid: hid },
  });
  expect(operator.status(), await operator.text()).toBe(201);
}

/**
 * The page pressed has settled: its heading is shown, its list has read its first rows,
 * nothing more is being read, and the frames after the rows came are drawn, when a list
 * that went back to where it was left would have moved the window.
 */
async function settled(page: Page): Promise<void> {
  await expect(page.locator("main h1").first()).toBeVisible();
  if ((await page.locator("main .ag-root-wrapper").count()) > 0) {
    await expect(page.getByTestId("grid-total").first()).not.toBeEmpty();
  }
  await page.waitForLoadState("networkidle");
  await page.evaluate(
    () =>
      new Promise<void>((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
      ),
  );
}

test("every entry of the menu bar opens its page at the top, again after each list was left from far down", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(300_000);
  await people(request, account);
  const seen = await watch(page.context());
  await signIn(page, account);
  await settled(page);

  // Every entry of the menu bar, and the two pages beside it reached from the bar: the
  // product name, Home, and the name of the person signed in, their Profile.
  const entries = await menuBar(page).getByRole("link").allTextContents();
  expect(entries.length, "the menu bar has its entries").toBeGreaterThan(10);
  const pressed = (entry: string) =>
    entry === "(product name)"
      ? page.getByTestId("brand")
      : entry === "(profile)"
        ? page.locator(".who-name")
        : menuBar(page).getByRole("link", { name: entry, exact: true });
  const every = [...entries, "(product name)", "(profile)"];

  for (const round of ["first", "after each list was left from far down"]) {
    for (const entry of every) {
      // The person presses the entry from the top of the page they are on: it is there
      // that the menu bar is.
      await page.evaluate(() => window.scrollTo(0, 0));
      await pressed(entry).click();
      await settled(page);
      const where = `${entry}, ${round}`;
      expect(await scrolled(page), `${where}: the page opens at its top`).toBe(0);
      await expect(menuBar(page), `${where}: the menu bar is in view`).toBeInViewport({
        ratio: 1,
      });

      // The person's own: down to the foot of the page, and a row of its list opened
      // from there, which the list keeps its place for (P-203).
      if (round !== "first") continue;
      await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
      const link = page
        .locator(
          "main .ag-row[row-index='0'] a[href]" +
            ':not([href^="mailto:"]):not([href^="tel:"]):not([href^="http"])',
        )
        .first();
      if ((await link.count()) === 0 || (await scrolled(page)) === 0) continue;
      const before = page.url();
      await link.click();
      await expect(page).not.toHaveURL(before);
      await expect(page.locator("main h1").first()).toBeVisible();
    }
  }
  await expectClean(page, seen);
});
