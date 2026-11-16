// The browser scenario of what circuits cost in release 0.8.0 (P-150, P-152, scenario S48
// as far as a page of a circuit and of a group show it; the report by year is a tab of
// Reports, tested with it):
//
//   Two circuits of one carrier, loaded from a file of circuits. The first is given three
//   monthly cost lines: its monthly cost is their sum and its annual cost twelve times
//   that. A line given an end in the past is no longer billed, and leaves the sum. The
//   second is given a line of its own; both are put into one group, several at once, and
//   the group shows what they cost as one sum, each circuit once. One taken out of the
//   group leaves its cost.
//
// It keeps to the rules of support.ts: an account and names of its own, and nothing
// changed that another file reads.

import { expect, type Page } from "@playwright/test";
import { importFile, region } from "./structure";
import { expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const random = mark("x").slice(2);
const suffix = mark("circuit-costs", random);
const upper = random.toUpperCase();

const carrier = `Example Telecom ${suffix}`;
const regionName = `Cost Region ${suffix}`;
const siteName = `Cost Site ${suffix}`;
const site = `${regionName} > ${siteName}`;
const building = `Cost Building ${suffix}`;
const buildingPath = `${site} > ${building}`;
const first = `Cost internet ${suffix}`;
const firstId = `EC-${upper}-C1`;
const second = `Cost backup ${suffix}`;
const secondId = `EC-${upper}-C2`;
const ordered = `Cost ordered ${suffix}`;
const orderedId = `EC-${upper}-C3`;
const group = `Internet access ${suffix}`;

async function openCircuit(page: Page, enterpriseId: string, name: string, more = "") {
  await page.goto(
    `./circuits?filter=${encodeURIComponent(`enterprise_circuit_id:eq:${enterpriseId}`)}${more ? `&${more}` : ""}`,
  );
  await page.getByTestId("grid-circuits").getByRole("link", { name, exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: new RegExp(`^${name}`) })).toBeVisible();
}

/** Add a cost line on the page of the circuit on show. */
async function addLine(page: Page, description: string, cost: string) {
  const form = region(page, "Add a cost line");
  await form.getByLabel("Line (required)").fill(description);
  await form.getByLabel("Monthly cost (required)").fill(cost);
  await form.getByRole("button", { name: "Add the line" }).click();
  await expect(page.getByText(new RegExp(`^The line ${description} was added to`))).toBeVisible();
}

test("S48: the monthly cost of a circuit is the sum of its lines, and the annual twelve times that", async ({
  page,
  account,
}) => {
  test.setTimeout(300_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  await importFile(page, "vendors", `vendors-${suffix}.csv`, ["name"], [[carrier]]);
  await importFile(page, "regions", `regions-${suffix}.csv`, ["name"], [[regionName]]);
  await importFile(
    page,
    "sites",
    `sites-${suffix}.csv`,
    ["name", "region"],
    [[siteName, regionName]],
  );
  await importFile(
    page,
    "locations",
    `locations-${suffix}.csv`,
    ["name", "site", "kind"],
    [[building, site, "building"]],
  );
  // The circuits come from a file of their own, which the Import page knows by its name.
  await importFile(
    page,
    "circuits",
    `circuits-${suffix}.csv`,
    [
      "name",
      "enterprise_circuit_id",
      "circuit_type",
      "port_mbps",
      "a_location",
      "z_note",
      "carrier",
      "record_status",
    ],
    [
      [first, firstId, "internet", "1000", buildingPath, "carrier network", carrier, "active"],
      [second, secondId, "internet", "100", buildingPath, "carrier network", carrier, "active"],
      [ordered, orderedId, "internet", "100", buildingPath, "carrier network", carrier, "draft"],
    ],
  );

  await openCircuit(page, firstId, first);
  await expect(page.getByTestId("monthly-cost")).toHaveText("0.00");
  await addLine(page, "Port", "850.00");
  await addLine(page, "Local loop", "120");
  await addLine(page, "Access", "30.00");
  await expect(page.getByTestId("costs").locator("tbody tr")).toHaveCount(3);
  await expect(page.getByTestId("monthly-cost")).toHaveText("1,000.00");
  await expect(page.getByTestId("annual-cost")).toHaveText("12,000.00");

  // A credit is a line below zero; an amount that is no amount is refused before it is sent.
  const form = region(page, "Add a cost line");
  await form.getByLabel("Line (required)").fill("Promotional credit");
  await form.getByLabel("Monthly cost (required)").fill("ten");
  await expect(form.getByRole("button", { name: "Add the line" })).toBeDisabled();
  await expect(form.getByText("below zero for a credit.", { exact: false }).first()).toBeVisible();
  await addLine(page, "Promotional credit", "-20");
  await expect(page.getByTestId("monthly-cost")).toHaveText("980.00");

  // A line that was billed for a time is given an end: ended in the past, it is billed no more.
  const credit = page.getByTestId("costs").locator('tr[data-line="Promotional credit"]');
  await expect(credit.getByTestId("line-cost")).toHaveText("-20.00");
  await credit.getByRole("button", { name: "End" }).click();
  const ending = region(page, "End the line Promotional credit");
  await ending.getByLabel("Last day billed (required)").fill("2020-01-31");
  await ending.getByRole("button", { name: "End the line" }).click();
  await expect(
    page.getByText("The line Promotional credit is billed until 2020-01-31."),
  ).toBeVisible();
  await expect(credit.getByTestId("line-billed")).toHaveText("No");
  await expect(credit.getByTestId("line-ends")).toHaveText("2020-01-31");
  await expect(page.getByTestId("monthly-cost")).toHaveText("1,000.00");
  await expect(page.getByTestId("annual-cost")).toHaveText("12,000.00");

  // A description that the circuit has already is refused under its field, by the server.
  await region(page, "Add a cost line").getByLabel("Line (required)").fill("port");
  await region(page, "Add a cost line").getByLabel("Monthly cost (required)").fill("5");
  await region(page, "Add a cost line").getByRole("button", { name: "Add the line" }).click();
  await expect(region(page, "Add a cost line").getByLabel("Line (required)")).toHaveAttribute(
    "aria-invalid",
    "true",
  );

  // The second circuit, of the same carrier.
  await openCircuit(page, secondId, second);
  await addLine(page, "Port", "500");
  await expect(page.getByTestId("monthly-cost")).toHaveText("500.00");
  await expect(page.getByTestId("annual-cost")).toHaveText("6,000.00");

  // The grid shows what each costs. The draft, ordered and not in service, is left out.
  await page.goto(`./circuits?filter=${encodeURIComponent(`carrier.name:eq:${carrier}`)}`);
  await expect(page.getByTestId("grid-total")).toHaveText("2 circuits");
  const grid = page.getByTestId("grid-circuits");
  const rowOf = (name: string) => grid.locator("[row-id]", { hasText: name });
  await expect(rowOf(first).locator('[col-id="monthly_cost"]')).toHaveText("1,000.00");
  await expect(rowOf(second).locator('[col-id="monthly_cost"]')).toHaveText("500.00");
  // The annual cost, which the grid holds beyond the right edge of a narrow window, is
  // filtered by the server.
  await page.goto(
    `./circuits?filter=${encodeURIComponent(`carrier.name:eq:${carrier} annual_cost:gte:12000`)}`,
  );
  await expect(page.getByTestId("grid-total")).toHaveText("1 circuit");
  await expect(grid.getByRole("link", { name: first, exact: true })).toBeVisible();

  // An ordered circuit, a draft, keeps the amounts of its lines and costs nothing yet; a
  // link that asks for drafts by the list's own name for it finds it.
  await openCircuit(page, orderedId, ordered, "include_drafts=true");
  await expect(page.getByTestId("circuit-status")).toHaveText("Draft");
  await addLine(page, "Port", "75");
  await expect(
    page.getByTestId("costs").locator('tr[data-line="Port"] [data-testid="line-cost"]'),
  ).toHaveText("75.00");
  await expect(page.getByTestId("monthly-cost")).toHaveText("0.00");
  await expect(page.getByTestId("annual-cost")).toHaveText("0.00");
  await expect(page.getByTestId("not-in-service")).toContainText("It is a draft");

  await expectClean(page, seen, ["409 POST"]);
});

test("S48: both circuits in one group, whose cost is one sum", async ({ page, account }) => {
  test.setTimeout(240_000);
  const seen = await watch(page.context());
  await signIn(page, account);

  await page.goto("./circuit-groups");
  await expect(page.getByRole("heading", { level: 1, name: "Circuit groups" })).toBeVisible();
  await page.getByRole("button", { name: "New circuit group" }).click();
  const made = region(page, "New circuit group");
  await made.getByLabel("Name (required)").fill(group);
  await made.getByRole("button", { name: "Create group" }).click();
  await expect(page.getByRole("heading", { level: 1, name: group })).toBeVisible();
  await expect(page.getByTestId("group-circuits")).toHaveText("0");

  // Both circuits chosen, and put in together.
  const adding = region(page, "Add circuits");
  for (const [id, name] of [
    [firstId, first],
    [secondId, second],
  ] as const) {
    await adding.getByLabel("Add a circuit").fill(id);
    await adding
      .getByRole("list", { name: "Circuits that match" })
      .getByRole("button", { name: `${name} (${id})` })
      .click();
  }
  await expect(adding.getByTestId("circuits-to-add").locator("tbody tr")).toHaveCount(2);
  await adding.getByRole("button", { name: "Put 2 circuits in" }).click();
  await expect(page.getByText(`2 circuits were put into ${group}.`)).toBeVisible();
  await expect(page.getByTestId("group-circuits")).toHaveText("2");
  await expect(page.getByTestId("group-in-service")).toHaveText("2");
  await expect(page.getByTestId("group-monthly-cost")).toHaveText("1,500.00");
  await expect(page.getByTestId("group-annual-cost")).toHaveText("18,000.00");
  const members = page.getByTestId("grid-circuit-group-circuits");
  await expect(members.getByRole("link", { name: first, exact: true })).toBeVisible();
  await expect(members.getByRole("link", { name: second, exact: true })).toBeVisible();

  // The list of groups says the same, and the circuit lists its group.
  await page.goto(`./circuit-groups?filter=${encodeURIComponent(`name:eq:${group}`)}`);
  const row = page.getByTestId("grid-circuit-groups").locator("[row-id]").first();
  await expect(row.locator('[col-id="circuits"]')).toHaveText("2");
  await expect(row.locator('[col-id="monthly_cost"]')).toHaveText("1,500.00");
  await expect(row.locator('[col-id="annual_cost"]')).toHaveText("18,000.00");
  await openCircuit(page, secondId, second);
  await expect(
    page.getByTestId("groups-of-circuit").getByRole("link", { name: group, exact: true }),
  ).toBeVisible();

  // The grid of circuits finds them by their group.
  await page.goto(`./circuits?filter=${encodeURIComponent(`groups.name:eq:${group}`)}`);
  await expect(page.getByTestId("grid-total")).toHaveText("2 circuits");

  // The second taken out of the group: the group's cost is the first's alone.
  await page.goto(`./circuit-groups?filter=${encodeURIComponent(`name:eq:${group}`)}`);
  await page
    .getByTestId("grid-circuit-groups")
    .getByRole("link", { name: group, exact: true })
    .click();
  await expect(page.getByRole("heading", { level: 1, name: group })).toBeVisible();
  const secondRow = page
    .getByTestId("grid-circuit-group-circuits")
    .locator("[row-id]", { hasText: second });
  await secondRow.locator('[col-id="enterprise_circuit_id"]').click();
  await page.getByRole("button", { name: "Take out of the group" }).click();
  await expect(page.getByText(`1 circuit was taken out of ${group}.`)).toBeVisible();
  await expect(page.getByTestId("group-circuits")).toHaveText("1");
  await expect(page.getByTestId("group-monthly-cost")).toHaveText("1,000.00");
  await expect(page.getByTestId("group-annual-cost")).toHaveText("12,000.00");

  await expectClean(page, seen);
});
