// The browser scenario of the menu bar of 0.9.2 (P-167):
//
//   A page opened from the menu bar begins at its top, with the menu bar in view, and
//   focus is on its content, which is not scrolled up to the top of the window: Groups,
//   Addresses, Vendors, Owners, Contracts and Home, each taller than the window.
//   A page opened from a link far down another page begins at its top in the same way.
//
// Until 0.9.1 focus moved to the content of a page by scrolling it to the top of the
// window, past the menu bar and the renewal alert above it, on every page taller than
// the window. The window here is shorter than each of those pages.
//
// How this file keeps to the rules of support.ts: it signs in as an Admin of its own,
// makes nothing and changes nothing, and reads only where the window is and what has
// focus, never what is in a list.

import { expect, type Page } from "@playwright/test";
import { main as menuBar } from "./structure";
import { expectClean, signIn, test, watch } from "./support";

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
