// The browser scenario of why a record has each value, in release 0.9.4 (P-175, P-176):
//
//   An optic in a switch, made through the API with names of this file's own. The optic is
//   in two custom groups of its own, aaa-pool with no operator and optics-pool with RA;
//   the switch has LM of its own and is in the group sw-group, which has PR. On the
//   optic's page, under Values in force, the walk of its operator is a row of boxes: its
//   own, holding nothing and dashed; aaa-pool, ranked 1st, holding nothing; optics-pool,
//   ranked 2nd, which decides, in the accent; the switch, passed over with LM struck
//   through; and sw-group, passed over too. A minor item's own groups come before the item
//   it is in (P-175), so it is optics-pool that decides and not the switch. The same walk
//   is a table beneath, for a screen reader and to copy. On the switch's page its own LM
//   decides and overrides PR, from sw-group. A group nested in another with an operator
//   has the walk of its own: its own, holding nothing, then the group it is nested in,
//   which decides. Each record of a box is a link, reached from the keyboard, and the page
//   does not scroll sideways in a window 1280 pixels wide.

import { type APIRequestContext, expect, type Locator, type Page } from "@playwright/test";
import { type Account, expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });
test.use({ viewport: { width: 1280, height: 900 } });

const suffix = mark("walks");
const label = (name: string) => `${name} ${suffix}`;

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

/** The walk of one value on the page on show. */
function walkOf(page: Page, field: string): Locator {
  return page.getByTestId("walk-field").and(page.locator(`[data-field="${field}"]`));
}

/** The boxes of a walk, in its order. */
function boxes(walk: Locator): Locator {
  return walk.getByTestId("walk-step");
}

/** The page does not scroll sideways. */
async function noSidewaysScroll(page: Page) {
  const [scroll, client] = await page.evaluate(() => [
    document.documentElement.scrollWidth,
    document.documentElement.clientWidth,
  ]);
  expect(scroll, "the page is no wider than the window").toBeLessThanOrEqual(client);
}

const ids: Record<string, string> = {};

test("the walk of each value of an item and of a group, as a row of boxes", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(150_000);
  const headers = await session(request, account);
  const lm = await make(request, headers, "/operators", { label: label("LM") });
  const ra = await make(request, headers, "/operators", { label: label("RA") });
  const pr = await make(request, headers, "/operators", { label: label("PR") });
  const vendor = await make(request, headers, "/vendors", { name: label("Example Networks") });
  const entry = await make(request, headers, "/catalog-entries", {
    vendor_hid: vendor.hid,
    pid: label("WX-24"),
  });
  const sw = await make(request, headers, "/items", {
    hostname: label("sw"),
    catalog_entry_hid: entry.hid,
    operator_hid: lm.hid,
  });
  const optic = await make(request, headers, "/items", {
    hostname: label("sfp"),
    parent_item_hid: sw.hid,
  });
  await make(request, headers, "/device-groups", {
    type: "custom",
    name: label("aaa-pool"),
    members: [{ item_hid: optic.hid }],
  });
  const pool = await make(request, headers, "/device-groups", {
    type: "custom",
    name: label("optics-pool"),
    operator_hid: ra.hid,
    members: [{ item_hid: optic.hid }],
  });
  const swGroup = await make(request, headers, "/device-groups", {
    type: "custom",
    name: label("sw-group"),
    operator_hid: pr.hid,
    members: [{ item_hid: sw.hid }],
  });
  const outer = await make(request, headers, "/device-groups", {
    type: "custom",
    name: label("outer"),
    operator_hid: pr.hid,
  });
  const inner = await make(request, headers, "/device-groups", {
    type: "custom",
    name: label("inner"),
    parent_group_hid: outer.hid,
  });
  Object.assign(ids, { pool: pool.hid, swGroup: swGroup.hid, outer: outer.hid });

  const seen = await watch(page.context());
  await signIn(page, account);

  // The optic: its own groups before the switch it is in.
  await page.goto(`./items/${optic.hid}`);
  await expect(page.getByRole("heading", { level: 1, name: label("sfp") })).toBeVisible();
  const values = page.getByRole("region", { name: "Values in force" });
  const operator = walkOf(page, "operator_hid");
  await expect(operator).toHaveAttribute("data-source", "device_group");
  await expect(operator.getByRole("heading", { level: 3 })).toHaveText(`Operator: ${label("RA")}`);
  const steps = boxes(operator);
  await expect(steps).toHaveCount(5);
  await expect(steps.nth(0)).toHaveAttribute("data-state", "nothing");
  await expect(steps.nth(0).locator(".walk-box")).toHaveCSS("border-top-style", "dashed");
  await expect(steps.nth(1)).toContainText(label("aaa-pool"));
  await expect(steps.nth(1)).toContainText("ranked 1st");
  await expect(steps.nth(1)).toHaveAttribute("data-state", "nothing");
  // The one that decides is optics-pool, the optic's own group, and no other box is.
  const decides = operator.locator('[data-testid="walk-step"][data-state="decides"]');
  await expect(decides).toHaveCount(1);
  await expect(decides).toHaveAttribute("data-step", "3");
  await expect(decides).toContainText(label("optics-pool"));
  await expect(decides).toContainText("ranked 2nd");
  await expect(decides.getByTestId("walk-value")).toHaveText(label("RA"));
  // The switch it is in, and the switch's group, are passed over, their values struck.
  await expect(steps.nth(3)).toHaveAttribute("data-state", "passed_over");
  await expect(steps.nth(3)).toContainText("Item it is in");
  await expect(steps.nth(3).locator("s")).toHaveText(label("LM"));
  await expect(steps.nth(4)).toHaveAttribute("data-state", "passed_over");
  await expect(steps.nth(4).locator("s")).toHaveText(label("PR"));
  // The box that decides is drawn in the accent of the theme, and the others are not.
  const accent = await page.evaluate(() =>
    getComputedStyle(document.documentElement).getPropertyValue("--accent").trim(),
  );
  expect(accent).not.toBe("");
  const colourOf = (box: Locator) =>
    box.locator(".walk-box").evaluate((one) => getComputedStyle(one).borderTopColor);
  const deciding = await colourOf(decides);
  expect(await colourOf(steps.nth(3))).not.toBe(deciding);
  // The arrows join the boxes, for the eye alone.
  await expect(operator.locator(".walk-arrow")).toHaveCount(4);
  await expect(operator.locator(".walk-arrow").first()).toHaveAttribute("aria-hidden", "true");
  // The same walk as a table, opened to read and to copy.
  await operator.locator("summary", { hasText: "As a table" }).click();
  const rows = operator.locator("table tbody tr");
  await expect(rows).toHaveCount(5);
  await expect(rows.nth(2)).toHaveAttribute("data-state", "decides");
  await expect(rows.nth(2).locator("td").last()).toHaveText("decides");
  await expect(rows.nth(3).locator("td").last()).toHaveText("passed over");
  await expect(rows.nth(0).locator("td").last()).toHaveText("holds nothing");
  // The values of a model have their walk too: the optic has no model, so its own alone.
  await expect(boxes(walkOf(page, "est_value"))).toHaveCount(1);
  await expect(values.getByTestId("walk-field")).toHaveCount(12);
  await noSidewaysScroll(page);

  // A record of a box is a link, and the keyboard reaches it.
  const toPool = decides.getByRole("link", { name: label("optics-pool"), exact: true });
  await toPool.focus();
  await expect(toPool).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { level: 1, name: label("optics-pool") })).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`/groups/${ids.pool}$`));

  // The switch: its own operator decides, and overrides the one of its group.
  await page.goto(`./items/${sw.hid}`);
  await expect(page.getByRole("heading", { level: 1, name: label("sw") })).toBeVisible();
  const own = walkOf(page, "operator_hid");
  await expect(own).toHaveAttribute("data-source", "own");
  await expect(boxes(own).nth(0)).toHaveAttribute("data-state", "decides");
  await expect(boxes(own).nth(0)).toContainText("Its own");
  await expect(boxes(own).nth(1)).toHaveAttribute("data-state", "passed_over");
  const overrides = own.getByTestId("walk-overrides");
  await expect(overrides).toHaveText(`Overrides ${label("PR")}, from ${label("sw-group")}`);
  await expect(overrides.getByRole("link", { name: label("sw-group") })).toHaveAttribute(
    "href",
    new RegExp(`/groups/${ids.swGroup}$`),
  );
  // The switch's model: its own, which holds nothing, then its catalog entry.
  const value = boxes(walkOf(page, "est_value"));
  await expect(value).toHaveCount(2);
  await expect(value.nth(1)).toContainText("Catalog entry");

  // A group nested in another: its own holds nothing, the group it is in decides.
  await page.goto(`./groups/${inner.hid}`);
  await expect(page.getByRole("heading", { level: 1, name: label("inner") })).toBeVisible();
  const nested = walkOf(page, "operator_hid");
  await expect(nested.getByRole("heading", { level: 3 })).toHaveText(`Operator: ${label("PR")}`);
  await expect(boxes(nested)).toHaveCount(2);
  await expect(boxes(nested).nth(0)).toHaveAttribute("data-state", "nothing");
  await expect(boxes(nested).nth(1)).toHaveAttribute("data-state", "decides");
  await expect(boxes(nested).nth(1)).toContainText("Group it is in");
  await expect(
    boxes(nested)
      .nth(1)
      .getByRole("link", { name: label("outer") }),
  ).toHaveAttribute("href", new RegExp(`/groups/${ids.outer}$`));
  await expect(page.getByTestId("walk-field")).toHaveCount(4);
  await noSidewaysScroll(page);

  await expectClean(page, seen);
});
