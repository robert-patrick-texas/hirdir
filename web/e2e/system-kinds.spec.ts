// The browser scenario of the kinds of external system in release 0.9.3:
//
//   P-170  The kinds of external system are the editable list `system_kind`, named
//          External system kind on Admin › Choices, loaded with the eight kinds that were
//          fixed. A kind added there is offered by the form of a system, by its label;
//          the list of systems and a system's page show the label, a label changed there
//          shows at once, and a kind made inactive is offered no more while the system
//          that holds it keeps it and shows its label. A system made with no kind is
//          given Other while the list offers other, and is refused, on the field, where it
//          does not.
//
// It keeps to the rules of support.ts: an account of its own, and a kind and systems of
// its own with the file's mark in their names. Rule 5: it changes a list of choices that
// other files read, in two ways. Its own kind, which it adds, renames and makes inactive,
// is read by no other file. And it makes `other` inactive for a moment, and active again
// however the scenario ends: while it is inactive a system made with no kind is refused,
// and no other file makes one so (systems.spec.ts chooses Monitoring and SDN controller).
// So it runs beside the others.

import { type APIRequestContext, expect, type Locator, type Page } from "@playwright/test";
import { type Headers, session } from "./referenceSteps";
import { region } from "./structure";
import { expectClean, mark, signIn, test, watch } from "./support";

const suffix = mark("system-kinds");
const value = `ipam-${suffix}`;
const label = `Address management ${suffix}`;
const renamed = `IP address management ${suffix}`;
const system = `IPAM ${suffix}`;
const kindless = `Kindless ${suffix}`;

/** The eight kinds that were fixed, by their values and the labels they are loaded with. */
const LOADED: ReadonlyArray<readonly [string, string]> = [
  ["monitoring", "Monitoring"],
  ["config_backup", "Configuration backup"],
  ["access_control", "Access control"],
  ["sdn_controller", "SDN controller"],
  ["cloud_service", "Cloud service"],
  ["dns", "DNS"],
  ["discovery", "Discovery"],
  ["other", "Other"],
];

/** Admin › Choices, on the list of the kinds of external system. */
async function openKinds(page: Page) {
  await page.goto("./admin/choices");
  await expect(page.getByRole("heading", { level: 1, name: "Choices" })).toBeVisible();
  await page.getByLabel("List", { exact: true }).selectOption({ label: "External system kind" });
  await expect(page).toHaveURL(/list=system_kind/);
  await expect(page.getByRole("rowheader", { name: "other", exact: true })).toBeVisible();
}

/** The row of a value of the list on show. */
function choiceRow(page: Page, one: string): Locator {
  return page.locator("tr", { has: page.getByRole("rowheader", { name: one, exact: true }) });
}

/** Offer a value of the list on show, or offer it no more, and save that. */
async function offer(page: Page, one: string, offered: boolean) {
  const row = choiceRow(page, one);
  await row.getByLabel(`Offer ${one}`).setChecked(offered);
  await row.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText(`${one} was saved.`)).toBeVisible();
}

/** The form of a new system, opened on the list of systems. */
async function newSystemForm(page: Page): Promise<Locator> {
  await page.goto("./systems");
  await expect(page.getByRole("heading", { level: 1, name: "External systems" })).toBeVisible();
  await page.getByRole("button", { name: "New system" }).click();
  return region(page, "New external system");
}

/** Make `other` active again through the API, whatever the page did. */
async function offerOther(request: APIRequestContext, headers: Headers) {
  const listed = await request.get("./api/v1/choices?list=system_kind", { headers });
  const all = (await listed.json()) as Array<{
    hid: string;
    value: string;
    active: boolean;
    row_version: number;
  }>;
  const other = all.find((one) => one.value === "other");
  if (!other || other.active) return;
  const answer = await request.patch(`./api/v1/choices/${other.hid}`, {
    headers,
    data: { row_version: other.row_version, active: true },
  });
  expect(answer.status(), "other is offered again").toBe(200);
}

test("P-170: the kinds of external system are a list of Admin › Choices", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(180_000);
  const headers = await session(request, account);
  const seen = await watch(page.context());
  await signIn(page, account);

  // The list, named for people, with the eight kinds that were fixed and their labels.
  await openKinds(page);
  for (const [one, named] of LOADED) {
    await expect(choiceRow(page, one).getByLabel(`Label of ${one}`)).toHaveValue(named);
  }

  // A kind of the site's own.
  const add = region(page, "New value");
  await add.getByLabel("Value (required)").fill(value);
  await add.getByLabel("Label").fill(label);
  await add.getByRole("button", { name: "Add value" }).click();
  await expect(page.getByText(`${value} was added.`)).toBeVisible();

  // The form of a system offers it by its label; the system shows the label.
  let form = await newSystemForm(page);
  await expect(form.getByLabel("Kind")).toHaveValue("other");
  await form.getByLabel("Name (required)").fill(system);
  await form.getByLabel("Kind").selectOption({ label });
  await form.getByRole("button", { name: "Create system" }).click();
  await expect(page.getByRole("heading", { level: 1, name: system })).toBeVisible();
  await expect(page.getByTestId("system-kind")).toHaveText(label);
  await expect(page.getByTestId("system-kind-fact")).toHaveText(label);
  const systemPage = new URL(page.url()).pathname;
  const listed = `./systems?filter=${encodeURIComponent(`name:eq:${system}`)}`;
  await page.goto(listed);
  const grid = page.getByTestId("grid-external-systems");
  await expect(grid.locator('[row-id] [col-id="kind"]')).toHaveText(label);

  // Its label is changed on Admin › Choices: the list and the page say the new one.
  await openKinds(page);
  await choiceRow(page, value).getByLabel(`Label of ${value}`).fill(renamed);
  await choiceRow(page, value).getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText(`${value} was saved.`)).toBeVisible();
  await page.goto(listed);
  await expect(grid.locator('[row-id] [col-id="kind"]')).toHaveText(renamed);

  // Made inactive: no longer offered, and the system keeps it through another change.
  await openKinds(page);
  await offer(page, value, false);
  form = await newSystemForm(page);
  await expect(form.getByLabel("Kind").locator("option", { hasText: renamed })).toHaveCount(0);
  await form.getByRole("button", { name: "Cancel" }).click();
  await page.goto(systemPage);
  await expect(page.getByTestId("system-kind-fact")).toHaveText(renamed);
  const details = region(page, "Details");
  await expect(details.getByLabel("Kind")).toHaveValue(value);
  await expect(details.getByLabel("Kind").locator("option:checked")).toHaveText(
    `${renamed} (inactive)`,
  );
  await details.getByLabel("Notes").fill(`Kept its kind ${suffix}`);
  await details.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("The system was saved.")).toBeVisible();
  await expect(page.getByTestId("system-kind-fact")).toHaveText(renamed);

  try {
    // Other offered no more: a system with no kind is refused, on the field.
    await openKinds(page);
    await offer(page, "other", false);
    form = await newSystemForm(page);
    await expect(form.getByLabel("Kind")).toHaveValue("");
    await expect(form).toContainText("A kind is needed");
    await form.getByLabel("Name (required)").fill(kindless);
    await form.getByRole("button", { name: "Create system" }).click();
    await expect(form.getByLabel("Kind")).toHaveAttribute("aria-invalid", "true");
    await expect(page.getByRole("heading", { level: 1, name: kindless })).toHaveCount(0);
  } finally {
    await offerOther(request, headers);
  }

  // Offered again: a system made with no kind is given Other.
  form = await newSystemForm(page);
  await expect(form).toContainText("Left out, it is Other.");
  await form.getByLabel("Name (required)").fill(kindless);
  await form.getByLabel("Kind").selectOption({ label: "None given" });
  await form.getByRole("button", { name: "Create system" }).click();
  await expect(page.getByRole("heading", { level: 1, name: kindless })).toBeVisible();
  await expect(page.getByTestId("system-kind-fact")).toHaveText("Other");
  await expectClean(page, seen, ["422 POST"]);
});
