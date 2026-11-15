// The browser scenarios of capacity in release 0.6.0, and of capacity over time in 0.7.0:
//
//   S39  The lines of the worked example of the data model page are entered: two pieces
//        of other work, six positions at three levels, an escalation partner, smart
//        hands and tooling. Demand rises by 2.0 and supply by 9.0, of which 6.0 is the
//        team's own positions, by category as the example has it.
//   S40  A draft services line is supply only in the balance with drafts; a line given
//        an end date in the past drops out of the supply in both.
//   S44  The balance is recorded, a line that multiplies two of the staff lines is added,
//        and the balance is recorded again: the week's point of the trend follows, the
//        supply of the two staff lines is multiplied and no other is, and the week's
//        figures are corrected, marked as corrected, and the record removed and made
//        again. A browser cannot make the next week come, so the two weeks of S44 are
//        the server's acceptance test; here both records fall in the week of today.
//   S45  Items in two regions of this file's own: the report stays one balance for the
//        whole, and beside it the demand of each region, whose regions at the top and
//        what is nowhere add up to the whole support weight, with no supply divided.
//
// How this file keeps to rule 4 and rule 5 of support.ts. The capacity report is of the
// whole installation: its infrastructure demand is the support weight of every item,
// which the other files change while this one runs, and an installation that was loaded
// with the examples has lines of its own. So no number of the report is compared with a
// number here. The report is read before and after each step, and what is compared is
// the difference in the parts that only capacity lines move: the supply, in total and by
// category, the team's own share of it, and the other work. Those change only when a
// capacity line does, and no other file writes one, reads the report or changes the
// `weight_per_resource_unit` setting: a file that comes to do so cannot run beside this
// one. The acceptance tests of the server hold the exact figures of S39 and S40, against
// an inventory of their own. The records of the balance are of the whole installation
// too, one to a week, and this file is the one that records, corrects and removes them:
// it looks at the week it records in, and compares the supply of that week's record
// with the supply of the report, which only capacity lines move. The demand of a region
// of its own is the weight of its own items alone.
//
// Every line this file makes carries its mark in its name: a name is unique on its side.

import { expect, type Page } from "@playwright/test";
import { importFile, main, region } from "./structure";
import { expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const suffix = mark("capacity");
const project = `Site consolidation project ${suffix}`;
const transition = `Organization transition ${suffix}`;
const junior = `Junior network engineer ${suffix}`;
const engineer = `Network engineer ${suffix}`;
const senior = `Senior network engineer ${suffix}`;
const partner = `Escalation partner ${suffix}`;
const hands = `Colocation smart hands ${suffix}`;
const tooling = `Automation and tooling ${suffix}`;
const assistant = `AI assistant ${suffix}`;
const multiplier = `Automation assistant ${suffix}`;
const mine = `name:contains:${suffix}`;
// S45: two regions of this file's own, each with a site, a room and items in it.
const vendor = `Example Networks ${suffix}`;
const pid = `EN-CAP-24-${suffix}`;
const north = `Capacity North ${suffix}`;
const south = `Capacity South ${suffix}`;

const CATEGORIES = ["staff", "professional_services", "smart_hands", "tools", "services"] as const;
type View = "active" | "with_drafts";

/** What the report says at one moment, in hundredths of a resource unit. */
interface Reading {
  asOf: string;
  supply: Record<View, number>;
  own: Record<View, number>;
  outside: Record<View, number>;
  other: Record<View, number>;
  demand: Record<View, number>;
  balance: Record<View, number>;
  category: Record<View, Record<string, number>>;
}

function hundredths(value: string | null): number {
  expect(value, "a number of the report").toMatch(/^-?\d+(\.\d+)?$/);
  return Math.round(Number(value) * 100);
}

/** Read the capacity report as the page shows it: every number is the server's. */
async function reading(page: Page): Promise<Reading> {
  await page.goto("./capacity");
  await expect(page.getByRole("heading", { level: 1, name: "Capacity" })).toBeVisible();
  const report = page.getByTestId("capacity-report");
  await expect(report).toBeVisible();
  const measure = async (view: View, key: string) =>
    hundredths(await report.getByTestId(`${view}-${key}`).getAttribute("data-value"));
  const both = async (key: string) => ({
    active: await measure("active", key),
    with_drafts: await measure("with_drafts", key),
  });
  const category: Reading["category"] = { active: {}, with_drafts: {} };
  for (const name of CATEGORIES) {
    const row = report.getByTestId("capacity-sides").locator(`tr[data-row="${name}"]`);
    category.active[name] = hundredths(
      await row.getByTestId("units-active").getAttribute("data-value"),
    );
    category.with_drafts[name] = hundredths(
      await row.getByTestId("units-with-drafts").getAttribute("data-value"),
    );
  }
  return {
    asOf: (await report.getAttribute("data-as-of")) ?? "",
    supply: await both("supply"),
    own: await both("own_units"),
    outside: await both("outside_units"),
    other: await both("other_demand"),
    demand: await both("demand"),
    balance: await both("balance"),
    category,
  };
}

/** What is said of one view holds together: the balance is the supply less the demand. */
function expectConsistent(now: Reading) {
  for (const view of ["active", "with_drafts"] as const) {
    // Each number is rounded to two places once, so the three may differ by a hundredth or two.
    expect(Math.abs(now.balance[view] - (now.supply[view] - now.demand[view]))).toBeLessThanOrEqual(
      2,
    );
    expect(Math.abs(now.own[view] + now.outside[view] - now.supply[view])).toBeLessThanOrEqual(2);
    const byCategory = CATEGORIES.reduce((sum, name) => sum + (now.category[view][name] ?? 0), 0);
    expect(Math.abs(byCategory - now.supply[view])).toBeLessThanOrEqual(2);
  }
}

/** Make a line with the form of the page, and see its own page. */
async function newLine(
  page: Page,
  line: {
    side: string;
    category?: string;
    name: string;
    quantity: string;
    each: string;
    status?: string;
  },
) {
  await page.goto("./capacity");
  await page.getByRole("button", { name: "New line" }).click();
  const form = region(page, "New capacity line");
  await form.getByLabel("Side (required)").selectOption({ label: line.side });
  if (line.category) {
    await form.getByLabel("Category").selectOption({ label: line.category });
  } else {
    // A demand line is other work: it has no category to choose.
    await expect(form.getByLabel("Category")).toHaveCount(0);
  }
  await form.getByLabel("Name (required)").fill(line.name);
  await form.getByLabel("Quantity").fill(line.quantity);
  await form.getByLabel("Units each (required)").fill(line.each);
  if (line.status) await form.getByLabel("Record status").selectOption({ label: line.status });
  await form.getByRole("button", { name: "Create line" }).click();
  await expect(page.getByRole("heading", { level: 1, name: line.name })).toBeVisible();
}

/** Open a line of this file from the grid of lines. */
async function openLine(page: Page, name: string) {
  await page.goto(`./capacity?filter=${encodeURIComponent(`name:eq:${name}`)}`);
  await page.getByTestId("grid-capacity-lines").getByRole("link", { name, exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
}

test("S39, S40: the lines of the worked example, a draft line, and a line that has ended", async ({
  page,
  account,
}) => {
  test.setTimeout(300_000);
  const seen = await watch(page.context());
  await signIn(page, account);

  await main(page).getByRole("link", { name: "Capacity" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Capacity" })).toBeVisible();
  const before = await reading(page);
  expectConsistent(before);

  // S39. Two of the lines are entered with the form: a piece of other work, which is
  // demand, and the three mid-level positions, which are supply.
  await newLine(page, { side: "Demand", name: project, quantity: "1", each: "1.5" });
  await expect(page.getByTestId("line-units")).toContainText("1.5");
  await expect(page.getByTestId("capacity-line-facts")).toContainText("Other work");
  await expect(page.getByTestId("line-counts")).toHaveText("Yes");
  await newLine(page, {
    side: "Supply",
    category: "Staff",
    name: engineer,
    quantity: "3",
    each: "1.0",
  });
  // The units of a line are its quantity times the units of one.
  await expect(page.getByTestId("line-units")).toContainText("3");
  // The rest come from a file, as a team that keeps them in a sheet would load them.
  await importFile(
    page,
    "capacity_lines",
    `capacity-lines-${suffix}.csv`,
    ["side", "category", "name", "quantity", "units_each", "record_status"],
    [
      ["demand", "", transition, "1", "0.5", "active"],
      ["supply", "staff", junior, "2", "0.6", "active"],
      ["supply", "staff", senior, "1", "1.8", "active"],
      ["supply", "professional_services", partner, "1", "1.0", "active"],
      ["supply", "smart_hands", hands, "1", "0.5", "active"],
      ["supply", "tools", tooling, "1", "1.5", "active"],
    ],
  );

  // Demand rose by the 2.0 of other work, and supply by 9.0: 6.0 of staff, 1.0 of
  // professional services, 0.5 of smart hands and 1.5 of tools. None of it is a draft,
  // so both views rose alike.
  const entered = await reading(page);
  expectConsistent(entered);
  for (const view of ["active", "with_drafts"] as const) {
    expect(entered.other[view] - before.other[view], `other work, ${view}`).toBe(200);
    expect(entered.supply[view] - before.supply[view], `supply, ${view}`).toBe(900);
    expect(entered.own[view] - before.own[view], `the team's own, ${view}`).toBe(600);
    expect(entered.outside[view] - before.outside[view], `everything else, ${view}`).toBe(300);
    for (const [name, units] of [
      ["staff", 600],
      ["professional_services", 100],
      ["smart_hands", 50],
      ["tools", 150],
      ["services", 0],
    ] as const) {
      expect(
        (entered.category[view][name] ?? 0) - (before.category[view][name] ?? 0),
        `${name}, ${view}`,
      ).toBe(units);
    }
  }

  // The lines are a grid like any other: these eight, found by their mark.
  await page.goto(`./capacity?filter=${encodeURIComponent(mine)}`);
  await expect(page.getByTestId("grid-total")).toHaveText("8 lines");
  const row = page.getByTestId("grid-capacity-lines").locator("[row-id]", { hasText: junior });
  await expect(row.locator('[col-id="units"]')).toHaveText("1.2");
  await expect(row.locator('[col-id="category"]')).toHaveText("Staff");

  // S40. A draft services line is a what-if: it is supply only in the view with drafts.
  await newLine(page, {
    side: "Supply",
    category: "Services",
    name: assistant,
    quantity: "1",
    each: "1.0",
    status: "Draft",
  });
  await expect(page.getByTestId("line-counts")).toHaveText("Only with the drafts: it is a what-if");
  const withDraft = await reading(page);
  expectConsistent(withDraft);
  expect(withDraft.supply.active - entered.supply.active).toBe(0);
  expect(withDraft.supply.with_drafts - entered.supply.with_drafts).toBe(100);
  expect((withDraft.category.active.services ?? 0) - (entered.category.active.services ?? 0)).toBe(
    0,
  );
  expect(
    (withDraft.category.with_drafts.services ?? 0) - (entered.category.with_drafts.services ?? 0),
  ).toBe(100);
  // The grid leaves the draft out until drafts are asked for.
  await page.goto(`./capacity?filter=${encodeURIComponent(mine)}`);
  await expect(page.getByTestId("grid-total")).toHaveText("8 lines");
  await page.getByLabel("Include drafts").check();
  await expect(page.getByTestId("grid-total")).toHaveText("9 lines");
  await page.getByLabel("Include drafts").uncheck();

  // The professional services line is given an end date in the past: it is in date no
  // longer, and drops out of the supply in both views.
  const yesterday = new Date(`${withDraft.asOf}T12:00:00Z`);
  yesterday.setUTCDate(yesterday.getUTCDate() - 1);
  await openLine(page, partner);
  const details = region(page, "Details");
  await details.getByLabel("Ends on").fill(yesterday.toISOString().slice(0, 10));
  await details.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("The line was saved.")).toBeVisible();
  await expect(page.getByTestId("line-counts")).toHaveText("No: today is outside its dates");
  const ended = await reading(page);
  expectConsistent(ended);
  for (const view of ["active", "with_drafts"] as const) {
    expect(ended.supply[view] - withDraft.supply[view], `supply, ${view}`).toBe(-100);
    expect(
      (ended.category[view].professional_services ?? 0) -
        (withDraft.category[view].professional_services ?? 0),
      `professional services, ${view}`,
    ).toBe(-100);
    // The team's own positions are as they were.
    expect(ended.own[view] - withDraft.own[view]).toBe(0);
  }

  await expectClean(page, seen);
});

/** Record the balance now, with the button of the page, and say which week it is of. */
async function recordNow(page: Page, note: string): Promise<string> {
  await page.goto("./capacity");
  const trend = page.getByTestId("capacity-trend");
  await trend.getByLabel("Note", { exact: true }).fill(note);
  await trend.getByRole("button", { name: "Record the balance now" }).click();
  const said = trend.getByText(/^The balance was recorded for the week of \d{4}-\d{2}-\d{2}\.$/);
  await expect(said).toBeVisible();
  const week = /\d{4}-\d{2}-\d{2}/.exec((await said.textContent()) ?? "")?.[0] ?? "";
  expect(week, "the week the balance was recorded for").not.toBe("");
  return week;
}

/** The point of one week in the graph of the trend. */
function point(page: Page, week: string) {
  return page.locator(`[data-testid="trend-point"][data-week="${week}"]`);
}

/** The row of one week in the table of the records. */
function recordRow(page: Page, week: string) {
  return page.getByTestId("capacity-records").locator(`tr[data-week="${week}"]`);
}

test("S44, S45: the balance over time, a line that multiplies, and the demand of each region", async ({
  page,
  account,
}) => {
  test.setTimeout(300_000);
  const seen = await watch(page.context());
  await signIn(page, account);

  // S45. Three items in two regions of this file's own: two in the north, one in the south.
  await importFile(page, "vendors", `vendors-${suffix}.csv`, ["name"], [[vendor]]);
  await importFile(
    page,
    "catalog_entries",
    `catalog-entries-${suffix}.csv`,
    ["vendor", "pid", "type", "support_weight"],
    [[vendor, pid, "switch", "1.50"]],
  );
  await importFile(page, "regions", `regions-${suffix}.csv`, ["name"], [[north], [south]]);
  await importFile(
    page,
    "sites",
    `sites-${suffix}.csv`,
    ["name", "region"],
    [
      ["Site N", north],
      ["Site S", south],
    ],
  );
  await importFile(
    page,
    "locations",
    `locations-${suffix}.csv`,
    ["name", "site", "kind"],
    [
      ["Room 1", `${north} > Site N`, "room"],
      ["Room 1", `${south} > Site S`, "room"],
    ],
  );
  const serial = suffix.toUpperCase().replace(/[^A-Z0-9]/g, "");
  await importFile(
    page,
    "items",
    `items-${suffix}.csv`,
    ["vendor", "pid", "serial_number", "hostname", "lifecycle_state", "location"],
    [
      [vendor, pid, `CAP${serial}1`, `cap-n1-${suffix}`, "Prod", `${north} > Site N > Room 1`],
      [vendor, pid, `CAP${serial}2`, `cap-n2-${suffix}`, "Prod", `${north} > Site N > Room 1`],
      [vendor, pid, `CAP${serial}3`, `cap-s1-${suffix}`, "Prod", `${south} > Site S > Room 1`],
    ],
  );
  const before = await reading(page);
  const report = page.getByTestId("capacity-report");
  const regions = report.getByTestId("demand-by-region");
  const weightOf = (path: string) =>
    regions.locator(`tr[data-region="${path}"]`).getByTestId("region-active-weight");
  // Each region holds the weight of the items at or beneath it, by where they are.
  await expect(weightOf(north)).toHaveAttribute("data-value", /^3(\.0+)?$/);
  await expect(weightOf(south)).toHaveAttribute("data-value", /^1\.50?$/);
  // The regions at the top and what is nowhere add up to the whole support weight, of
  // the same answer; each is rounded to two places once, so they may differ by a
  // hundredth for each row.
  const whole = hundredths(
    await report.getByTestId("active-support_weight").getAttribute("data-value"),
  );
  const tops = await regions
    .locator('tr[data-depth="0"]')
    .getByTestId("region-active-weight")
    .all();
  let sum = 0;
  for (const cell of tops) {
    const value = await cell.getAttribute("data-value");
    if (value) sum += hundredths(value);
  }
  expect(Math.abs(sum - whole), "the regions at the top and what is nowhere").toBeLessThanOrEqual(
    tops.length,
  );
  await expect(regions.locator('tr[data-region=""]')).toContainText("Nowhere");
  // One balance for the whole team: no supply is divided among the regions.
  await expect(regions.locator("thead")).not.toContainText("Supply");

  // S44. The balance is recorded: this week's point has the supply the report has.
  const week = await recordNow(page, `Before the assistant ${suffix}`);
  await expect(point(page, week)).toHaveCount(1);
  expect(hundredths(await point(page, week).getAttribute("data-supply"))).toBe(
    before.supply.active,
  );
  await expect(point(page, week)).toHaveAttribute("data-adjusted", "false");
  await expect(recordRow(page, week).getByTestId("record-note")).toHaveText(
    `Before the assistant ${suffix}`,
  );

  // A line that multiplies the two higher levels of staff, and no other line.
  await page.goto("./capacity");
  await page.getByRole("button", { name: "New line" }).click();
  const form = region(page, "New capacity line");
  await form.getByLabel("Side (required)").selectOption({ label: "Supply" });
  await form.getByLabel("Category").selectOption({ label: "Services" });
  await form.getByLabel("Effect").selectOption({ label: "Multiplies staff lines" });
  // A line that multiplies has no quantity of its own: it works on that of others.
  await expect(form.getByLabel("Quantity")).toHaveCount(0);
  await expect(form.getByLabel("Units each (required)")).toHaveCount(0);
  await form.getByLabel("Name (required)").fill(multiplier);
  await form.getByLabel("Factor (required)").fill("1.25");
  await form.getByLabel("Share").fill("0.5");
  const targets = form.getByRole("group", { name: "Applies to" });
  // The staff lines that add are offered, and nothing else.
  await expect(targets.getByLabel(engineer, { exact: true })).toBeVisible();
  await expect(targets.getByLabel(partner, { exact: true })).toHaveCount(0);
  await expect(targets.getByLabel(tooling, { exact: true })).toHaveCount(0);
  await targets.getByLabel(engineer, { exact: true }).check();
  await targets.getByLabel(senior, { exact: true }).check();
  await form.getByRole("button", { name: "Create line" }).click();
  await expect(page.getByRole("heading", { level: 1, name: multiplier })).toBeVisible();
  await expect(page.getByTestId("line-effect")).toHaveText("Multiplies staff lines");
  await expect(page.getByTestId("line-factor")).toHaveText("1.25");
  await expect(page.getByTestId("line-share")).toHaveText(/^0\.50?$/);
  const appliesTo = page.getByTestId("line-applies-to");
  await expect(appliesTo.getByRole("link")).toHaveCount(2);
  await expect(appliesTo.getByRole("link", { name: engineer, exact: true })).toBeVisible();
  await expect(appliesTo.getByRole("link", { name: senior, exact: true })).toBeVisible();

  // Its gain is (1.25 − 1) × 0.5 × the 4.8 units of the two lines: 0.6, in its own
  // category, in both views, and the team's own positions are as they were.
  const multiplied = await reading(page);
  expectConsistent(multiplied);
  for (const view of ["active", "with_drafts"] as const) {
    expect(multiplied.supply[view] - before.supply[view], `supply, ${view}`).toBe(60);
    expect(
      (multiplied.category[view].services ?? 0) - (before.category[view].services ?? 0),
      `services, ${view}`,
    ).toBe(60);
    expect((multiplied.category[view].staff ?? 0) - (before.category[view].staff ?? 0)).toBe(0);
    expect(multiplied.own[view] - before.own[view], `the team's own, ${view}`).toBe(0);
  }
  for (const which of ["active", "with_drafts"]) {
    const row = page.getByTestId(`multiplying-${which}`).locator(`tr[data-line="${multiplier}"]`);
    expect(hundredths(await row.getByTestId("multiplying-gain").getAttribute("data-value"))).toBe(
      60,
    );
    expect(hundredths(await row.getByTestId("multiplying-base").getAttribute("data-value"))).toBe(
      480,
    );
    // The two lines it works on count, and are the only ones.
    await expect(row.locator("li[data-target]")).toHaveCount(2);
    await expect(row.locator(`li[data-target="${engineer}"]`)).toHaveAttribute(
      "data-counted",
      "true",
    );
    await expect(row.locator(`li[data-target="${senior}"]`)).toHaveAttribute(
      "data-counted",
      "true",
    );
  }

  // Recorded again in the same week, the record of the week is replaced: its point has
  // the supply with the gain.
  expect(await recordNow(page, `With the assistant ${suffix}`)).toBe(week);
  await expect(point(page, week)).toHaveCount(1);
  expect(hundredths(await point(page, week).getAttribute("data-supply"))).toBe(
    multiplied.supply.active,
  );
  await expect(recordRow(page, week)).toHaveCount(1);
  await expect(recordRow(page, week).getByTestId("record-note")).toHaveText(
    `With the assistant ${suffix}`,
  );

  // The week's supply is corrected. A correction says why: without a note it is refused.
  const corrected = ((multiplied.supply.active + 100) / 100).toFixed(2);
  await recordRow(page, week).getByRole("button", { name: "Correct" }).click();
  const correction = page.getByTestId("correct-record");
  await correction.getByLabel("Supply", { exact: true }).fill(corrected);
  await correction.getByRole("button", { name: "Correct the figures" }).click();
  await expect(correction.getByLabel("Why the figures are corrected (required)")).toHaveAttribute(
    "aria-invalid",
    "true",
  );
  await correction
    .getByLabel("Why the figures are corrected (required)")
    .fill(`A contractor left on Friday ${suffix}`);
  await correction.getByRole("button", { name: "Correct the figures" }).click();
  await expect(page.getByText(`The figures of the week of ${week} were corrected.`)).toBeVisible();
  await expect(recordRow(page, week).getByTestId("record-adjusted")).toHaveText("Corrected");
  await expect(recordRow(page, week).getByTestId("record-note")).toHaveText(
    `A contractor left on Friday ${suffix}`,
  );
  // The trend marks the week, and its lines go through the corrected total.
  await expect(point(page, week)).toHaveAttribute("data-adjusted", "true");
  expect(hundredths(await point(page, week).getAttribute("data-supply"))).toBe(
    multiplied.supply.active + 100,
  );
  await expect(point(page, week).locator(".trend-adjusted-label")).toHaveText("corrected");
  // Broken into its parts, the supply is stacked by category as it was recorded, and
  // the corrected total is still what the line of supply goes through.
  const graph = page.getByTestId("capacity-trend-graph");
  await graph.getByLabel(/^Show the parts/).check();
  await expect(graph).toHaveAttribute("data-parts", "true");
  await expect(graph.locator('path.trend-layer[data-category="staff"]')).toHaveCount(1);
  await expect(graph.locator('path.trend-layer[data-category="services"]')).toHaveCount(1);
  await expect(graph.locator("path.trend-infrastructure")).toHaveCount(1);
  expect(hundredths(await point(page, week).getAttribute("data-supply"))).toBe(
    multiplied.supply.active + 100,
  );

  // A record that was a mistake is removed outright, and the week recorded afresh.
  await recordRow(page, week).getByRole("button", { name: "Remove" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Remove the record" }).click();
  await expect(page.getByText(`The record of the week of ${week} was removed.`)).toBeVisible();
  await expect(recordRow(page, week)).toHaveCount(0);
  await expect(point(page, week)).toHaveCount(0);
  expect(await recordNow(page, `Recorded afresh ${suffix}`)).toBe(week);
  await expect(point(page, week)).toHaveAttribute("data-adjusted", "false");
  expect(hundredths(await point(page, week).getAttribute("data-supply"))).toBe(
    multiplied.supply.active,
  );

  await expectClean(page, seen, ["422 PATCH"]);
});
