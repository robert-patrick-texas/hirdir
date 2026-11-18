// 0.9.7: a page that cannot be drawn says so and offers to load again, and the page holds
// words before its script runs (P-230); a page older than the server says that a new
// version is installed, and never loads again by itself (P-231).
//
// The faults are made as the probe of 2026-11-18 made them: an answer of another shape
// than the page expects on coming back to the tab, the page's own script not arriving,
// and a file of a page that cannot be fetched. This file signs in as an Admin of its own
// and changes nothing: what it reads is the frame and the words of its own faults.

import { expect, type Page, type Route } from "@playwright/test";
import { signIn, test } from "./support";

const back = (page: Page) =>
  page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));

/** What the page holds: how many elements in #root, and how many letters it shows. */
function shown(page: Page) {
  return page.evaluate(() => {
    const root = document.getElementById("root");
    return { kids: root?.childElementCount ?? 0, text: (root?.textContent ?? "").trim().length };
  });
}

/** The addresses of the menu bar, as the page writes them, under its prefix. */
async function menuLinks(page: Page): Promise<string[]> {
  return page
    .getByRole("navigation", { name: "Main" })
    .locator("a")
    .evaluateAll((links) => links.map((link) => (link as HTMLAnchorElement).href));
}

const fault = (page: Page) => page.getByTestId("fault");

test("a script that does not arrive leaves words, and to load again after a while", async ({
  page,
}) => {
  await page.route("**/assets/index-*.js", (route) => route.abort());
  await page.goto("./");
  const boot = page.locator("#root .boot");
  await expect(boot).toContainText("hirdir");
  await expect(boot).toContainText("Loading…");
  // The words to load again come after a few seconds, by the stylesheet.
  await expect(boot.getByText("load the page again")).toBeHidden();
  await expect(boot.getByText("load the page again")).toBeVisible({ timeout: 15_000 });

  // With no stylesheet either, they are there at once.
  await page.route("**/assets/index-*.css", (route) => route.abort());
  await page.goto("./");
  await expect(page.locator("#root .boot").getByText("load the page again")).toBeVisible({
    timeout: 1_000,
  });
});

test("the words before the script are replaced when the page draws", async ({ page, account }) => {
  await signIn(page, account);
  await expect(page.locator("#root .boot")).toHaveCount(0);
});

const SHAPES: Record<string, string> = { null: "null", "{}": "{}", "[]": "[]" };

test("an answer of another shape on coming back leaves words and a way on, on every page of the menu", async ({
  page,
  account,
}) => {
  test.setTimeout(300_000);
  await signIn(page, account);
  const links = await menuLinks(page);
  expect(links.length).toBeGreaterThan(15);
  // The first record of the lists whose pages emptied in the probe.
  for (const list of ["items", "groups", "circuits"]) {
    await page.goto(`./${list}`);
    const first = page.locator(`main a[href*="/${list}/"]`).first();
    await expect(first).toBeVisible({ timeout: 20_000 });
    links.push(await first.evaluate((link) => (link as HTMLAnchorElement).href));
  }

  const faulted: string[] = [];
  for (const [name, body] of Object.entries(SHAPES)) {
    for (const link of links) {
      await page.unroute("**/api/v1/**");
      await page.goto(link);
      await page.waitForLoadState("networkidle");
      await page.route("**/api/v1/**", (route: Route) =>
        route.fulfill({ status: 200, contentType: "application/json", body }),
      );
      await back(page);
      await page.waitForTimeout(500);
      const now = await shown(page);
      expect(now.kids, `${name} on ${link}`).toBeGreaterThan(0);
      expect(now.text, `${name} on ${link}`).toBeGreaterThan(0);
      // The menu bar stays, whatever the page beneath it did.
      await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
      if (await fault(page).isVisible()) {
        faulted.push(`${name} ${new URL(link).pathname}`);
        await expect(fault(page).getByRole("button", { name: "Load again" })).toBeVisible();
        await expect(fault(page).getByRole("link", { name: "The first page" })).toBeVisible();
        await expect(page.getByTestId("fault-text")).not.toHaveValue("");
      }
    }
  }
  await page.unroute("**/api/v1/**");
  // The probe emptied pages with each of the three answers: the same answers now fault
  // some of them, and each of those says so.
  console.log(`faulted, said so: ${faulted.length}\n  ${faulted.join("\n  ")}`);
  expect(faulted.length).toBeGreaterThan(0);
});

test("a page that cannot be drawn says so; another page clears it; Load again loads it again", async ({
  page,
  account,
}) => {
  await signIn(page, account);
  await page.goto("./items");
  await expect(page.getByRole("heading", { level: 1, name: "Items" })).toBeVisible();
  await page.route("**/api/v1/**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "{}" }),
  );
  await back(page);
  await expect(fault(page)).toBeVisible();
  await expect(
    page.getByRole("heading", { level: 1, name: "This page could not be drawn" }),
  ).toBeVisible();
  await expect(page.getByTestId("fault-text")).toHaveValue(/^TypeError: /);
  await expect(page.getByTestId("fault-text")).toHaveValue(/Web page version: \d+\.\d+\.\d+/);

  // The text is copied for whoever is asked about it.
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
  await fault(page).getByRole("button", { name: "Copy the text" }).click();
  await expect(fault(page).getByText("Copied.")).toBeVisible();
  const copied = await page.evaluate(() => navigator.clipboard.readText());
  expect(copied).toBe(await page.getByTestId("fault-text").inputValue());

  // Going to another page clears it.
  await page.unroute("**/api/v1/**");
  await page
    .getByRole("navigation", { name: "Main" })
    .getByRole("link", { name: "Vendors" })
    .click();
  await expect(page.getByRole("heading", { level: 1, name: "Vendors" })).toBeVisible();
  await expect(fault(page)).toHaveCount(0);

  // Load again loads the page at its present address.
  await page.goto("./items");
  await expect(page.getByRole("heading", { level: 1, name: "Items" })).toBeVisible();
  await page.route("**/api/v1/**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "{}" }),
  );
  await back(page);
  await expect(fault(page)).toBeVisible();
  await page.unroute("**/api/v1/**");
  await page.evaluate(() => {
    (window as unknown as { notLoadedAgain: boolean }).notLoadedAgain = true;
  });
  await fault(page).getByRole("button", { name: "Load again" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Items" })).toBeVisible();
  expect(new URL(page.url()).pathname.endsWith("/items")).toBe(true);
  expect(await page.evaluate(() => "notLoadedAgain" in window)).toBe(false);

  // The first page is at the prefix the page is served under.
  const first = await page.evaluate(() => document.baseURI);
  await page.route("**/api/v1/**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "{}" }),
  );
  await back(page);
  await expect(fault(page).getByRole("link", { name: "The first page" })).toHaveAttribute(
    "href",
    first,
  );
});

test("a part of the page that cannot be fetched says so beneath the menu bar", async ({
  page,
  account,
}) => {
  // The file of the page of vendors is gone, as after a release installed meanwhile.
  await page.route("**/assets/Vendors-*.js", (route) => route.abort());
  await signIn(page, account);
  await page
    .getByRole("navigation", { name: "Main" })
    .getByRole("link", { name: "Vendors" })
    .click();
  await expect(fault(page)).toBeVisible({ timeout: 20_000 });
  await expect(fault(page)).toContainText("A part of the page could not be fetched");
  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
  // Another page is drawn as ever.
  await page
    .getByRole("navigation", { name: "Main" })
    .getByRole("link", { name: "Owners" })
    .click();
  await expect(page.getByRole("heading", { level: 1, name: "Owners" })).toBeVisible();
});

test("a fault in the frame itself says so over the whole page", async ({ page, account }) => {
  await signIn(page, account);
  await page.goto("./vendors");
  await expect(page.getByRole("heading", { level: 1, name: "Vendors" })).toBeVisible();
  // Who is signed in, of a shape the menu bar cannot draw.
  await page.route("**/api/v1/auth/me", async (route) => {
    const answer = await route.fetch();
    await route.fulfill({ response: answer, json: { ...(await answer.json()), username: {} } });
  });
  await page.goto("./owners");
  await expect(fault(page)).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Main" })).toHaveCount(0);
  await expect(fault(page).getByRole("button", { name: "Load again" })).toBeVisible();
  await expect(page.getByTestId("fault-text")).toHaveValue(/^Error: .*React/);
  // Load again, with the frame put right, draws it.
  await page.unroute("**/api/v1/auth/me");
  await fault(page).getByRole("button", { name: "Load again" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Owners" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
});

/** Answer `GET /about` as the server would, with another version. */
async function aboutSays(page: Page, version: string): Promise<void> {
  await page.route("**/api/v1/about", async (route) => {
    const answer = await route.fetch();
    const body = await answer.json();
    await route.fulfill({ response: answer, json: { ...body, version } });
  });
}

test("a page older than the server says a new version is installed, and stays as it is", async ({
  page,
  account,
}) => {
  await signIn(page, account);
  await page.goto("./vendors");
  await expect(page.getByRole("heading", { level: 1, name: "Vendors" })).toBeVisible();
  const notice = page.getByTestId("new-version");

  // A request for /about that fails says nothing; nor does the same version.
  await page.route("**/api/v1/about", (route) => route.abort());
  await back(page);
  await page.waitForTimeout(500);
  await expect(notice).toHaveCount(0);
  await page.unroute("**/api/v1/about");
  await back(page);
  await page.waitForTimeout(500);
  await expect(notice).toHaveCount(0);

  // Another version, on coming back to the tab.
  const filter = page.getByRole("searchbox", { name: "Find an item" });
  await filter.fill("typed and not saved");
  await filter.focus();
  await page.evaluate(() => {
    (window as unknown as { notLoadedAgain: boolean }).notLoadedAgain = true;
  });
  await aboutSays(page, "99.0.0");
  await back(page);
  await expect(notice).toBeVisible();
  await expect(notice).toContainText("A new version of hirdir has been installed: 99.0.0");
  await expect(notice.getByRole("button", { name: "Load again" })).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  // It takes no focus, and what was typed is where it was.
  await expect(filter).toBeFocused();
  await expect(filter).toHaveValue("typed and not saved");

  // It stands on every page, and the page never loads again by itself.
  await page
    .getByRole("navigation", { name: "Main" })
    .getByRole("link", { name: "Owners" })
    .click();
  await expect(page.getByRole("heading", { level: 1, name: "Owners" })).toBeVisible();
  await expect(notice).toBeVisible();
  await page.waitForTimeout(1_000);
  expect(await page.evaluate(() => "notLoadedAgain" in window)).toBe(true);

  // Load again loads the page, which is then of the version the server runs.
  await page.unroute("**/api/v1/about");
  await notice.getByRole("button", { name: "Load again" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Owners" })).toBeVisible();
  expect(await page.evaluate(() => "notLoadedAgain" in window)).toBe(false);
  await back(page);
  await page.waitForTimeout(500);
  await expect(notice).toHaveCount(0);
});

test("a page that cannot be drawn asks what version runs", async ({ page, account }) => {
  await signIn(page, account);
  await page.goto("./vendors");
  await expect(page.getByRole("heading", { level: 1, name: "Vendors" })).toBeVisible();
  // Every answer is of another shape but /about, which names another version. The page
  // is opened from the menu bar a moment after it was loaded, which does not ask by
  // itself: the fault alone asks.
  await page.route("**/api/v1/**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "{}" }),
  );
  await aboutSays(page, "99.0.0");
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Items" }).click();
  await expect(fault(page)).toBeVisible();
  await expect(page.getByTestId("new-version")).toBeVisible();
});
