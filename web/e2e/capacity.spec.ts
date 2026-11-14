// The browser scenarios of capacity in release 0.6.0:
//
//   S39  The lines of the worked example of the data model page are entered: two pieces
//        of other work, six positions at three levels, an escalation partner, smart
//        hands and tooling. Demand rises by 2.0 and supply by 9.0, of which 6.0 is the
//        team's own positions, by category as the example has it.
//   S40  A draft services line is supply only in the balance with drafts; a line given
//        an end date in the past drops out of the supply in both.
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
// an inventory of their own.
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
const mine = `name:contains:${suffix}`;

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
