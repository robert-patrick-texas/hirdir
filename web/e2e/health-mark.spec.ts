// The browser scenarios of the mark of health in the menu bar, of 0.9.10 (P-270, P-272):
//
//   Nobody signed in sees no mark. Signed in, the mark is in the menu bar of every page:
//   one of four shapes, with its words as its name and as what pointing at it shows, the
//   words being of speed, since this run refuses nothing. It is a link to About. It is
//   what the newest answer of the server said, in the header every answer carries, and
//   it asks the server nothing: a page that stands open sends no request by the clock,
//   and answers that say another word change the mark, where answers that carry no
//   such header, or one that does not read, leave no mark and no fault. The menu bar is
//   no wider than the window with the mark in it.
//
// How this file keeps to the rules of support.ts: an account of its own, and it changes
// nothing. The health is of the whole server, which every file drives, so no word of it
// is compared with a word: the mark is read as one of the four, and what a header makes
// of it is shown by giving the answers to this file's own page another header on their
// way, the answers being the server's own otherwise. busy.spec.ts, which runs by itself, holds the mark of a server
// past its ceiling.

import { expect, type Page } from "@playwright/test";
import { main as menuBar } from "./structure";
import { expectClean, signIn, test, watch } from "./support";

const SPEED =
  /^Server health: Answers are (quick|slow|very slow|slower than the server's ceiling)\.$/;
const SHAPES: Readonly<Record<string, string>> = {
  good: "circle",
  slow: "polygon",
  very_slow: "polygon",
  busy: "rect",
};
const isApi = (url: string) => new URL(url).pathname.includes("/api/v1/");

const healthMark = (page: Page) => page.getByTestId("health-mark");

/** The mark as it should be while nothing is refused: one of four, said in words of speed. */
async function expectMark(page: Page, where: string): Promise<void> {
  const shown = healthMark(page);
  await expect(shown, where).toBeVisible();
  await expect(shown, where).toHaveAttribute("data-health", /^(good|slow|very_slow|busy)$/);
  await expect(shown, where).toHaveAttribute("data-refusing", "nothing");
  await expect(shown, where).toHaveAccessibleName(SPEED);
  await expect(shown, where).toHaveAttribute("title", /^Answers are .*About shows/);
  const health = (await shown.getAttribute("data-health")) ?? "";
  await expect(shown.locator(`svg[data-shape="${health}"] ${SHAPES[health]}`), where).toHaveCount(
    1,
  );
  // It is in the menu bar, and one mark is all there is.
  await expect(page.locator("header.top").getByTestId("health-mark"), where).toHaveCount(1);
}

/**
 * Answer every request of the page to the API as the server does, with another header of
 * health, or with none: the mark shows what the newest answer said, whichever it was.
 */
async function answersSay(page: Page, header: string | null): Promise<void> {
  await page.unrouteAll({ behavior: "ignoreErrors" });
  await page.route("**/api/v1/**", async (route) => {
    const answer = await route.fetch();
    const headers = { ...answer.headers() };
    delete headers["x-hirdir-health"];
    if (header !== null) headers["x-hirdir-health"] = header;
    await route.fulfill({ response: answer, headers });
  });
}

test("the mark of health is in the menu bar of every page, says the health in words, leads to About, and asks nothing", async ({
  page,
  account,
}) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 1280, height: 700 });
  const seen = await watch(page.context());

  // Nobody signed in: no mark.
  await page.goto("./");
  await expect(page.getByRole("heading", { level: 1, name: "Sign in to hirdir" })).toBeVisible();
  await expect(healthMark(page)).toHaveCount(0);

  await signIn(page, account);
  await expectMark(page, "the first page");
  for (const [name, path] of [
    ["Items", /\/items$/],
    ["Reports", /\/reports/],
    ["Vendors", /\/vendors$/],
    ["Admin", /\/admin$/],
  ] as const) {
    await menuBar(page).getByRole("link", { name, exact: true }).click();
    await expect(page).toHaveURL(path);
    await expectMark(page, name);
  }

  // The menu bar is no wider than the window with the mark in it, and the mark is on the
  // row of who is signed in, before the name.
  const wider = () =>
    page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
  expect(await wider(), "wider than a window of 1280").toBeLessThanOrEqual(0);
  const box = await healthMark(page).boundingBox();
  const who = await page.locator(".who-name").boundingBox();
  expect(box && who && box.x + box.width <= who.x, "the mark stands before the name").toBe(true);
  expect(box && who && Math.abs(box.y + box.height / 2 - (who.y + who.height / 2)) < 12).toBe(true);
  await page.setViewportSize({ width: 480, height: 800 });
  await expect(healthMark(page)).toBeVisible();
  expect(await wider(), "wider than a window of 480").toBeLessThanOrEqual(0);
  await page.setViewportSize({ width: 1280, height: 700 });

  // A page that stands open asks nothing: no request is sent by the clock for the mark,
  // on a page that is not About.
  await menuBar(page).getByRole("link", { name: "Vendors", exact: true }).click();
  await expect(page).toHaveURL(/\/vendors$/);
  await page.waitForLoadState("networkidle");
  const asked: string[] = [];
  const count = (request: { url: () => string }) => {
    if (isApi(request.url())) asked.push(new URL(request.url()).pathname);
  };
  page.on("request", count);
  await page.waitForTimeout(12_000);
  page.off("request", count);
  expect(asked, "requests of a page that stood open for twelve seconds").toEqual([]);
  await expectMark(page, "after standing open");

  // It is a link to About, where the measures are.
  await healthMark(page).click();
  await expect(page).toHaveURL(/\/about$/);
  await expect(page.getByRole("heading", { level: 1, name: "About" })).toBeVisible();
  await expect(page.getByTestId("load-health")).toBeVisible();
  await expectMark(page, "About");
  await expectClean(page, seen);
});

test("the mark shows what the newest answer said, each health by its shape and its words, and none for an answer that says nothing that reads", async ({
  page,
  account,
}) => {
  test.setTimeout(120_000);
  await signIn(page, account);
  // Another page is opened, and asks what it asks: every answer to it says the same.
  const open = async (name: "Vendors" | "Owners") => {
    await menuBar(page).getByRole("link", { name, exact: true }).click();
    await expect(page.getByRole("heading", { level: 1, name, exact: true })).toBeVisible();
    await page.waitForLoadState("networkidle");
  };

  const cases: Array<
    [header: string, health: string, refusing: string, name: string, shape: string]
  > = [
    ["good; refusing=nothing", "good", "nothing", "Server health: Answers are quick.", "circle"],
    ["slow; refusing=nothing", "slow", "nothing", "Server health: Answers are slow.", "polygon"],
    [
      "very_slow; refusing=nothing",
      "very_slow",
      "nothing",
      "Server health: Answers are very slow.",
      "polygon",
    ],
    [
      "very_slow; refusing=long",
      "very_slow",
      "long",
      "Server health: The server is busy: reports, exports and previews are not answered for now.",
      "polygon",
    ],
    [
      "busy; refusing=nothing",
      "busy",
      "nothing",
      "Server health: Answers are slower than the server's ceiling.",
      "rect",
    ],
    [
      "busy; refusing=reads",
      "busy",
      "reads",
      "Server health: The server is busy: lists and everything else that only reads are not answered for now.",
      "rect",
    ],
  ];
  let next: "Vendors" | "Owners" = "Vendors";
  for (const [header, health, refusing, name, shape] of cases) {
    await answersSay(page, header);
    await open(next);
    next = next === "Vendors" ? "Owners" : "Vendors";
    const shown = healthMark(page);
    await expect(shown, header).toHaveAttribute("data-health", health);
    await expect(shown, header).toHaveAttribute("data-refusing", refusing);
    await expect(shown, header).toHaveAccessibleName(name);
    await expect(shown.locator(`svg[data-shape="${health}"] ${shape}`), header).toHaveCount(1);
    // The four are four shapes: the two polygons are a triangle and a diamond.
    if (shape === "polygon") {
      const corners = (await shown.locator("polygon").getAttribute("points"))?.split(" ").length;
      expect(corners, header).toBe(health === "slow" ? 3 : 4);
    }
  }

  // An answer with no such header, or with one that does not read: no mark, and no fault.
  for (const header of [null, "purple; refusing=nothing", "busy", ""]) {
    await answersSay(page, "good; refusing=nothing");
    await open(next);
    next = next === "Vendors" ? "Owners" : "Vendors";
    await expect(healthMark(page)).toHaveAttribute("data-health", "good");
    await answersSay(page, header);
    await open(next);
    next = next === "Vendors" ? "Owners" : "Vendors";
    await expect(healthMark(page), String(header)).toHaveCount(0);
    await expect(page.getByTestId("fault"), String(header)).toHaveCount(0);
    await expect(menuBar(page)).toBeVisible();
  }
  await page.unrouteAll({ behavior: "ignoreErrors" });
});
