// The browser scenarios of what an operator is on and of the leaderboard, in release
// 0.9.4 (P-177, P-178, P-180, P-181):
//
//   One scenario of this file's own, made through the API: the operator OPA given a site,
//   whose Room 1 has it from there while Room 2 has OPB of its own; switches in each room,
//   one with OPB of its own, and an optic in the first; a custom group G given OPA, with a
//   member that has OPB of its own and a group G2 nested in it; a switch given OPA as its
//   own, with an optic. Three switches are of the model P1 of a vendor of the file, and one
//   of the model P2.
//
//   The operator's page draws what OPA is on as a tree of boxes: OPA at the top with the 6
//   items it is in force for; the site, from which 2 items have it, with Room 1 beneath it
//   and 2 items beneath it marked as another operator's; the group G, from which 2 items
//   have it, with G2 nested in it and 1 member marked; and the item given it, with the
//   optic that has it from that item. Every count is a link to exactly those items.
//
//   The scoreboard's operators say how the items of each have it, own, from the item, from
//   a group and from a place, and the groups and places given it; its new table of groups
//   ranks G above G2, with the items under no group in a row with no rank, and a group's
//   count of items leads to the items under it at any depth. The summary is offered by
//   group and by model and opens with the most items first, the blank row last; a row by
//   model is named by its vendor and PID and leads to its catalog entry, which has a
//   column of how many items are of it, a link to them.

import {
  type APIRequestContext,
  expect,
  type Locator,
  type Page,
  type Response,
} from "@playwright/test";
import { answer, listed, queried } from "./answers";
import { type Account, expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });
test.use({ viewport: { width: 1280, height: 900 } });

// P-309: each scenario opens page after page, each counted by the server, which on a busy
// host answers a count in several seconds: a scenario is given two minutes, as those of
// the other files are, and waits for each answer before it reads what the page shows.
const BUDGET = 120_000;

const suffix = mark("leaderboard");
const name = (one: string) => `${one} ${suffix}`;
const mine = `hostname:contains:${suffix}`;

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

/** The page does not scroll sideways. */
async function noSidewaysScroll(page: Page) {
  const [scroll, client] = await page.evaluate(() => [
    document.documentElement.scrollWidth,
    document.documentElement.clientWidth,
  ]);
  expect(scroll, "the page is no wider than the window").toBeLessThanOrEqual(client);
}

/**
 * The page's answers to the counts of the scoreboard, by operator, by site and by group,
 * for the items of this file: the three tables of the page.
 */
function scoreboardCounted(page: Page): Promise<Response[]> {
  return Promise.all(
    ["operator", "site", "group"].map((by) => listed(page, "/reports/summary", `by=${by}`, suffix)),
  );
}

/**
 * The page's answers to what an operator's page reads of what it is on: the tree, and the
 * count of its items beside it, which is a search of the items as the grid's is.
 */
function treeDrawn(page: Page, operator: string): Promise<Response[]> {
  return Promise.all([
    answer(page, "GET", `/operators/${operator}/assignments`),
    queried(page, "/items/query", '"limit":1,'),
  ]);
}

/**
 * The grid of items a link led to holds as many as the count said, once the server has
 * answered the grid's search. The page the link is on has no search of the items of its
 * own left unanswered: the first that is answered is the grid's.
 */
async function leadsTo(page: Page, link: Locator, items: number) {
  const listedItems = answer(page, "POST", "/items/query");
  await link.click();
  await listedItems;
  await expect(page.getByRole("heading", { level: 1, name: "Items" })).toBeVisible();
  await expect(page.getByTestId("grid-total")).toHaveText(
    `${items} ${items === 1 ? "item" : "items"}`,
  );
}

/** The browser's Back, to a page that `read` says is read again, once it is. */
async function backTo(page: Page, read: () => Promise<unknown>) {
  const again = read();
  await page.goBack();
  await again;
}

const ids: Record<string, string> = {};

test("a scenario of its own is made through the API", async ({ account, request }) => {
  const headers = await session(request, account);
  const opa = await make(request, headers, "/operators", { label: name("OPA") });
  const opb = await make(request, headers, "/operators", { label: name("OPB") });
  const region = await make(request, headers, "/regions", { name: name("Region") });
  const site = await make(request, headers, "/sites", {
    name: name("Site"),
    region_hid: region.hid,
    operator_hid: opa.hid,
  });
  const room1 = await make(request, headers, "/locations", { name: "Room 1", site_hid: site.hid });
  const room2 = await make(request, headers, "/locations", {
    name: "Room 2",
    site_hid: site.hid,
    operator_hid: opb.hid,
  });
  const vendor = await make(request, headers, "/vendors", { name: name("Example Networks") });
  const p1 = await make(request, headers, "/catalog-entries", {
    vendor_hid: vendor.hid,
    pid: name("P1"),
  });
  const p2 = await make(request, headers, "/catalog-entries", {
    vendor_hid: vendor.hid,
    pid: name("P2"),
  });
  const item = (hostname: string, more: Record<string, unknown> = {}) =>
    make(request, headers, "/items", { hostname: `${hostname}-${suffix}`, ...more });
  const sw1 = await item("sw1", { location_hid: room1.hid, catalog_entry_hid: p1.hid });
  await item("sfp1", { parent_item_hid: sw1.hid });
  await item("sw2", { location_hid: room1.hid, operator_hid: opb.hid, catalog_entry_hid: p1.hid });
  await item("sw3", { location_hid: room2.hid, catalog_entry_hid: p1.hid });
  const sw4 = await item("sw4", { catalog_entry_hid: p2.hid });
  const sw5 = await item("sw5");
  const sw6 = await item("sw6", { operator_hid: opb.hid });
  const g = await make(request, headers, "/device-groups", {
    type: "custom",
    name: name("G"),
    operator_hid: opa.hid,
    members: [{ item_hid: sw4.hid }, { item_hid: sw6.hid }],
  });
  const g2 = await make(request, headers, "/device-groups", {
    type: "custom",
    name: name("G2"),
    parent_group_hid: g.hid,
    members: [{ item_hid: sw5.hid }],
  });
  const sw7 = await item("sw7", { operator_hid: opa.hid });
  await item("sfp7", { parent_item_hid: sw7.hid });
  Object.assign(ids, { opa: opa.hid, site: site.hid, g: g.hid, g2: g2.hid, p1: p1.hid });
});

test("what an operator is on, as a tree of boxes, every count a link", async ({
  page,
  account,
}) => {
  test.setTimeout(BUDGET);
  const seen = await watch(page.context());
  await signIn(page, account);
  const opa = ids.opa ?? "";
  const drawn = treeDrawn(page, opa);
  await page.goto(`./operators/${opa}`);
  await drawn;
  const tree = page.getByTestId("operator-tree");
  await expect(tree.getByRole("figure", { name: `What ${name("OPA")} is on` })).toBeVisible();
  // At the top, the operator and every item it is in force for.
  const root = tree.getByTestId("tree-root");
  await expect(root).toContainText(name("OPA"));
  await expect(root.getByRole("link", { name: "6 items in force" })).toBeVisible();

  // The columns: its places, its groups and its own items, each under a heading.
  const column = (key: string) => tree.locator(`[data-testid="tree-column"][data-column="${key}"]`);
  await expect(tree.getByTestId("tree-column")).toHaveCount(3);
  await expect(column("places").getByRole("heading", { level: 3 })).toHaveText("Places given it");

  // The site: two items have it from there, Room 1 beneath has it, and two items beneath
  // have another operator, marked.
  const siteBox = column("places").locator(`[data-testid="tree-box"][data-key="${ids.site}"]`);
  await expect(siteBox).toContainText(name("Site"));
  await expect(siteBox.getByRole("link", { name: "2 items have it from here" })).toBeVisible();
  await expect(siteBox).toContainText("1 place beneath has it");
  const marked = siteBox.getByTestId("tree-exceptions");
  await expect(marked).toHaveAttribute("data-value", "2");
  await expect(marked.locator(".tree-mark")).toHaveAttribute("aria-hidden", "true");
  await expect(
    column("places").locator(".tree-beneath").getByRole("link", { name: "Room 1", exact: true }),
  ).toBeVisible();
  await expect(siteBox).toHaveClass(/tree-has-exceptions/);

  // The group: two items have it from it, G2 nested in it has it, one member is another's.
  const groupBox = column("groups").locator(`[data-testid="tree-box"][data-key="${ids.g}"]`);
  await expect(groupBox.getByRole("link", { name: "2 items have it from it" })).toBeVisible();
  await expect(groupBox).toContainText("1 nested group has it");
  await expect(groupBox.getByTestId("tree-exceptions")).toHaveAttribute("data-value", "1");
  await expect(
    column("groups")
      .locator(".tree-beneath")
      .getByRole("link", { name: name("G2"), exact: true }),
  ).toHaveAttribute("href", new RegExp(`/groups/${ids.g2}$`));

  // Its own item, and the optic that has it from that item.
  await expect(column("own").getByTestId("tree-box")).toHaveCount(2);
  await expect(column("own").getByRole("link", { name: "1 item" })).toHaveCount(2);
  await noSidewaysScroll(page);

  // Every count leads to exactly its items, the minor ones among them; the keyboard
  // reaches a count as it does any link.
  const fromSite = siteBox.getByRole("link", { name: "2 items have it from here" });
  await fromSite.focus();
  await expect(fromSite).toBeFocused();
  const fromSiteListed = answer(page, "POST", "/items/query");
  await page.keyboard.press("Enter");
  await fromSiteListed;
  await expect(page.getByTestId("grid-total")).toHaveText("2 items");
  await expect(page.getByTestId("grid-items")).toContainText(`sfp1-${suffix}`);
  await backTo(page, () => treeDrawn(page, opa));
  await leadsTo(
    page,
    page.getByTestId("tree-root").getByRole("link", { name: "6 items in force" }),
    6,
  );
  await backTo(page, () => treeDrawn(page, opa));
  await leadsTo(
    page,
    page
      .getByTestId("operator-tree")
      .locator(`[data-key="${ids.g}"]`)
      .getByTestId("tree-exceptions")
      .getByRole("link"),
    1,
  );
  await expect(page.getByTestId("grid-items")).toContainText(`sw6-${suffix}`);

  await expectClean(page, seen);
});

test("the scoreboard: how an operator's items have it, and the groups ranked", async ({
  page,
  account,
}) => {
  test.setTimeout(BUDGET);
  const seen = await watch(page.context());
  await signIn(page, account);
  // Three tables are counted at once: on a busy host longer than the 5 seconds of a wait,
  // so each count is waited for, and then what the page shows of it.
  const counted = scoreboardCounted(page);
  await page.goto(`./reports/scoreboard?${new URLSearchParams({ filter: mine }).toString()}`);
  await counted;
  await expect(page.getByRole("heading", { level: 1, name: "Scoreboard" })).toBeVisible();

  // The leaderboard: OPA with its six items, and none of the split, which is a table of its
  // own beneath it.
  const operators = page.getByTestId("score-operators");
  const measure = (row: Locator, which: string) => row.locator(`[data-measure="${which}"]`);
  const leader = operators.locator(`tbody tr[data-operator="${ids.opa}"]`);
  await expect(measure(leader, "items")).toHaveText("6");
  await expect(measure(leader, "own")).toHaveCount(0);
  await expect(operators.getByRole("columnheader", { name: "Own", exact: true })).toHaveCount(0);
  // Its health is one column: a bar in four parts that nobody hears, the numbers beside it
  // for the eye, and the four counts once in words for a screen reader.
  await expect(operators.getByRole("columnheader", { name: "Good", exact: true })).toHaveCount(0);
  const health = measure(leader, "health");
  await expect(health.locator(".health-bar")).toHaveAttribute("aria-hidden", "true");
  await expect(health.locator(".health-figures")).toHaveAttribute("aria-hidden", "true");
  await expect(health.locator(".health-figure")).toHaveCount(4);
  await expect(health.locator(".visually-hidden")).toHaveText(
    /^\d+ good, \d+ degraded, \d+ failed, \d+ unknown$/,
  );
  // It sorts the worst first at the first press of its header.
  await operators.getByRole("button", { name: "Health", exact: true }).click();
  await expect(
    operators.getByRole("columnheader", { name: "Health", exact: true }),
  ).toHaveAttribute("aria-sort", "descending");
  await expect(operators.getByRole("columnheader", { name: "Rank" })).toHaveAttribute(
    "data-rank-by",
    "health",
  );

  // How each operator has its items: OPA its own item, the optic from that item, two from
  // its group and two from its site, which add up to its six; one group and one place given
  // it. It opens with the most given it first: OPB with two, then OPA with one.
  const split = page.getByTestId("score-split");
  await expect(
    page.getByRole("heading", { level: 3, name: "How each operator has its items" }),
  ).toBeVisible();
  const opa = split.locator(`tbody tr[data-operator="${ids.opa}"]`);
  await expect(measure(opa, "own")).toHaveText("1");
  await expect(measure(opa, "from_item")).toHaveText("1");
  await expect(measure(opa, "from_group")).toHaveText("2");
  await expect(measure(opa, "from_place")).toHaveText("2");
  await expect(measure(opa, "groups_given")).toHaveText("1");
  await expect(measure(opa, "places_given")).toHaveText("1");
  await expect(measure(opa, "own").locator(".bar")).toHaveAttribute("aria-hidden", "true");
  await expect(split.getByRole("columnheader", { name: "Own", exact: true })).toHaveAttribute(
    "aria-sort",
    "descending",
  );
  await expect(split.getByRole("columnheader", { name: "Rank" })).toHaveAttribute(
    "data-rank-by",
    "own",
  );
  await expect(measure(opa, "rank")).toHaveText("2");
  await expect(split.locator("tbody tr").nth(1)).toHaveAttribute("data-operator", ids.opa ?? "");
  // Sorted by what is had from a group, OPA with two is ranked first.
  await split.getByRole("button", { name: "From group", exact: true }).click();
  await expect(split.getByRole("columnheader", { name: "Rank" })).toHaveAttribute(
    "data-rank-by",
    "from_group",
  );
  await expect(measure(opa, "rank")).toHaveText("1");
  // It is saved as a file of its own, one line for each operator.
  const saved = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export CSV of how each operator has its items" }).click();
  expect((await saved).suggestedFilename()).toBe("hirdir-scoreboard-operators-split.csv");

  // The groups: G, with its two members, G2 nested in it and three items under it; G2 with
  // one; and the items under no group, a row with no rank.
  const groups = page.getByTestId("score-groups");
  await expect(groups.getByRole("caption")).toContainText("The device groups of the items in view");
  await groups.getByRole("button", { name: "Items", exact: true }).click();
  const g = groups.locator(`tbody tr[data-group="${ids.g}"]`);
  const g2 = groups.locator(`tbody tr[data-group="${ids.g2}"]`);
  const none = groups.getByTestId("score-no-group");
  await expect(measure(g, "members")).toHaveText("2");
  await expect(measure(g, "nested")).toHaveText("1");
  await expect(measure(g, "items")).toHaveText("3");
  await expect(measure(g2, "items")).toHaveText("1");
  // The groups' health is one column too.
  await expect(groups.getByRole("columnheader", { name: "Health", exact: true })).toBeVisible();
  await expect(measure(g, "health").locator(".health-figure")).toHaveCount(4);
  await expect(measure(g, "rank")).toHaveText("1");
  await expect(measure(g2, "rank")).toHaveText("2");
  await expect(measure(none, "rank")).toHaveText("");
  await expect(g.getByRole("rowheader")).toContainText("Custom");
  // The bars: G's three items the longest of the groups', the blank row's six the longest of all.
  await expect(measure(none, "items").locator(".bar-fill")).toHaveAttribute(
    "style",
    /inline-size: 100%/,
  );
  await expect(measure(g, "items").locator(".bar-fill")).toHaveAttribute(
    "style",
    /inline-size: 50%/,
  );
  await noSidewaysScroll(page);
  // A group's count of items leads to the items under it at any depth, the member of G2
  // among them; its members to its own members.
  await leadsTo(page, measure(g, "items").getByRole("link"), 3);
  await expect(page.getByTestId("grid-items")).toContainText(`sw5-${suffix}`);
  // Back, the scoreboard counts its tables again.
  const back = () => backTo(page, () => scoreboardCounted(page));
  await back();
  await leadsTo(
    page,
    page
      .getByTestId("score-groups")
      .locator(`tbody tr[data-group="${ids.g}"] [data-measure="members"]`)
      .getByRole("link"),
    2,
  );

  // How OPA's items have it leads to exactly those items: the two from its group, the
  // member of the nested group among them; and the groups given it to the list of groups.
  await back();
  const opaAgain = page.getByTestId("score-split").locator(`tbody tr[data-operator="${ids.opa}"]`);
  await leadsTo(page, measure(opaAgain, "from_group").getByRole("link"), 2);
  await expect(page.getByTestId("grid-items")).toContainText(`sw5-${suffix}`);
  await back();
  await leadsTo(page, measure(opaAgain, "from_place").getByRole("link"), 2);
  await expect(page.getByTestId("grid-items")).toContainText(`sfp1-${suffix}`);
  await back();
  const groupsListed = answer(page, "POST", "/device-groups/query");
  await measure(opaAgain, "groups_given").getByRole("link").click();
  await groupsListed;
  await expect(page.getByTestId("grid-device-groups")).toContainText(name("G"));
  await expect(page.getByTestId("grid-total")).toHaveText("1 group");
  // The places given it are no one list, and lead nowhere.
  await back();
  await expect(measure(opaAgain, "places_given")).toHaveText("1");
  await expect(measure(opaAgain, "places_given").getByRole("link")).toHaveCount(0);

  await expectClean(page, seen);
});

test("the summary by group and by model, the most first, and a model's items on the catalog", async ({
  page,
  account,
}) => {
  test.setTimeout(BUDGET);
  const seen = await watch(page.context());
  await signIn(page, account);
  // By model: P1 with three items, P2 with one, and the five with no model last, unranked.
  const byModel = listed(page, "/reports/summary", "by=model", suffix);
  await page.goto(`./reports?${new URLSearchParams({ filter: mine, by: "model" }).toString()}`);
  await byModel;
  await expect(page.getByRole("heading", { level: 1, name: "Summary" })).toBeVisible();
  const rows = page.getByTestId("summary-rows").locator("tbody tr");
  await expect(rows).toHaveCount(3);
  await expect(
    page.getByTestId("summary-rows").getByRole("columnheader", { name: "Items" }),
  ).toHaveAttribute("aria-sort", "descending");
  await expect(rows.nth(0)).toHaveAttribute("data-key", ids.p1 ?? "");
  await expect(rows.nth(0).locator('[data-measure="rank"]')).toHaveText("1");
  await expect(rows.nth(0).locator('[data-measure="items"]')).toHaveText("3");
  await expect(rows.nth(1).locator('[data-measure="rank"]')).toHaveText("2");
  await expect(rows.nth(2)).toHaveAttribute("data-key", "");
  await expect(rows.nth(2)).toContainText("No model");
  await expect(rows.nth(2).locator('[data-measure="items"]')).toHaveText("5");
  await expect(rows.nth(2).locator('[data-measure="rank"]')).toHaveText("");
  // A model is named by its vendor and its PID, and leads to its catalog entry.
  const model = rows
    .nth(0)
    .getByRole("link", { name: `${name("Example Networks")} ${name("P1")}` });
  await expect(model).toHaveAttribute("href", new RegExp(`/catalog/${ids.p1}$`));

  // By group: offered among the choices, each row a group with its type and members.
  const byGroup = listed(page, "/reports/summary", "by=group", suffix);
  await page.getByLabel("By", { exact: true }).selectOption("group");
  await byGroup;
  await expect(page.getByRole("heading", { level: 2, name: "By group" })).toBeVisible();
  const g = page.getByTestId("summary-rows").locator(`tbody tr[data-key="${ids.g}"]`);
  await expect(g.getByTestId("row-detail")).toHaveText("Custom · 2 members · 1 nested group");
  await expect(g.locator('[data-measure="items"]')).toHaveText("3");
  await expect(page.getByTestId("summary-rows").locator("tbody tr").last()).toContainText(
    "In no group",
  );
  await noSidewaysScroll(page);

  // The management report is by model too.
  const management = listed(page, "/reports/management", "by=model", suffix);
  await page.goto(
    `./reports/management?${new URLSearchParams({ filter: mine, by: "model" }).toString()}`,
  );
  await management;
  await expect(
    page
      .getByTestId("management-rows")
      .locator(`tbody tr[data-key="${ids.p1}"] [data-measure="items"]`),
  ).toHaveText("3");

  // The catalog: how many items are of each model, a link to them, sorted by the server.
  const entries = queried(page, "/catalog-entries/query", suffix);
  await page.goto(`./catalog?filter=${encodeURIComponent(`pid:eq:${name("P1")}`)}`);
  await entries;
  const catalog = page.getByTestId("grid-catalog");
  await expect(catalog.getByRole("columnheader", { name: "Items" })).toBeVisible();
  await leadsTo(page, catalog.getByRole("link", { name: "3", exact: true }), 3);

  await expectClean(page, seen);
});
