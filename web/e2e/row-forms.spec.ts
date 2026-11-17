// The browser scenarios of a form opened beneath the row it changes, in release 0.9.3:
//
//   P-171  As Change does on Admin › Settings (settings.spec.ts), Edit on Admin › Tags and
//          on Admin › Lifecycle rules, Change on Admin › Files, and Change in the Files
//          and links of a record's page each open their form directly beneath the row
//          they change, in a row of its own whose one cell spans every column. The focus
//          moves into the form as it opens, and back to the button that opened it when it
//          closes. One form is open at a time: opening another closes the first, and
//          lets go of what was typed in it.
//
// They keep to the rules of support.ts: an account of their own, and records of their own
// with the file's mark in their names: a region with two links, which are erased when
// the scenario ends, and two tags, which are removed. A lifecycle rule, which other files read, is opened and
// closed and never saved. The window is 1280 x 800, so that a form opened below a whole
// table would be out of view.

import { type APIRequestContext, expect, type Locator, type Page } from "@playwright/test";
import { filesOf, type Headers, make, openPlace, session } from "./referenceSteps";
import { expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const suffix = mark("row-forms");
const regionName = `Region ${suffix}`;
const titles = [`Survey one ${suffix}`, `Survey two ${suffix}`] as const;
const tagLabels = [`first-${suffix}`, `second-${suffix}`] as const;

const ids: { region?: string; links: string[]; tags: string[] } = { links: [], tags: [] };

/**
 * The form of a row, opened by its button: directly beneath the row, in a row of its own
 * whose one cell spans every column of the table, with the focus in it and its first
 * field in view, and no other such form on the page.
 */
async function opensBeneath(
  page: Page,
  table: Locator,
  rowOf: string,
  key: string,
  button: Locator,
): Promise<Locator> {
  await button.click();
  const formRow = table.locator(`${rowOf} + tr[data-form-of="${key}"]`);
  await expect(formRow).toHaveCount(1);
  await expect(page.locator("tr[data-form-of]")).toHaveCount(1);
  const columns = await table.locator("thead th").count();
  await expect(formRow.locator("> td")).toHaveAttribute("colspan", String(columns));
  const form = formRow.locator("> td");
  await expect(form.locator(":focus")).toHaveCount(1);
  await expect(button).toHaveAttribute("aria-expanded", "true");
  await expect(button).toBeInViewport();
  await expect(form.locator("input, select, textarea").first()).toBeInViewport();
  return form;
}

/** The form is closed, and the focus is back on the button that opened it. */
async function closedTo(page: Page, button: Locator) {
  await expect(page.locator("tr[data-form-of]")).toHaveCount(0);
  await expect(button).toBeFocused();
  await expect(button).toHaveAttribute("aria-expanded", "false");
}

/** Take away what the file made: an erased reference, a removed tag. */
async function remove(request: APIRequestContext, headers: Headers, path: string) {
  const answer = await request.delete(`./api/v1${path}`, { headers });
  expect(answer.status(), `delete ${path}: ${await answer.text()}`).toBe(204);
}

test("P-171: Edit on Admin › Tags opens the tag's form beneath its row", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 1280, height: 800 });
  const headers = await session(request, account);
  for (const label of tagLabels) {
    ids.tags.push((await make(request, headers, "/tags", { label })).hid);
  }
  const seen = await watch(page.context());
  await signIn(page, account);
  await page.goto("./admin/tags");
  await expect(page.getByRole("heading", { level: 1, name: "Tags" })).toBeVisible();
  const table = page.locator("table", { has: page.locator(`tr[data-tag="${tagLabels[0]}"]`) });
  const edit = (label: string) =>
    table.getByRole("button", { name: `Edit the tag ${label}`, exact: true });
  const [first, second] = tagLabels;

  let form = await opensBeneath(
    page,
    table,
    `tr[data-tag="${first}"]`,
    ids.tags[0] ?? "",
    edit(first),
  );
  await expect(form.getByLabel("Label (required)")).toBeFocused();
  await form.getByLabel("Description").fill("typed and let go");
  // One at a time: the second opens, the first closes, and what was typed is let go.
  await opensBeneath(page, table, `tr[data-tag="${second}"]`, ids.tags[1] ?? "", edit(second));
  form = await opensBeneath(page, table, `tr[data-tag="${first}"]`, ids.tags[0] ?? "", edit(first));
  await expect(form.getByLabel("Description")).toHaveValue("");

  // Saved: the form closes, and the focus is on the tag's Edit again.
  await form.getByLabel("Description").fill(`The first tag of ${suffix}`);
  await form.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText(`The tag ${first} was saved.`)).toBeVisible();
  await expect(table.locator(`tr[data-tag="${first}"]`)).toContainText(
    `The first tag of ${suffix}`,
  );
  await closedTo(page, edit(first));

  // Closed: the same.
  form = await opensBeneath(
    page,
    table,
    `tr[data-tag="${second}"]`,
    ids.tags[1] ?? "",
    edit(second),
  );
  await form.getByRole("button", { name: "Close", exact: true }).click();
  await closedTo(page, edit(second));
  for (const hid of ids.tags) await remove(request, headers, `/tags/${hid}`);
  await expectClean(page, seen);
});

test("P-171: Edit on Admin › Lifecycle rules opens the rule's form beneath its row", async ({
  page,
  account,
}) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 1280, height: 800 });
  const seen = await watch(page.context());
  await signIn(page, account);
  await page.goto("./admin/lifecycle-rules");
  await expect(page.getByRole("heading", { level: 1, name: "Lifecycle rules" })).toBeVisible();
  const rows = page.locator("tr[data-state]");
  await expect(rows.first()).toBeVisible();
  const states = await rows.evaluateAll((all) => all.map((one) => one.dataset.state ?? ""));
  const firstState = states[0] ?? "";
  const lastState = states[states.length - 1] ?? "";
  const table = page.locator("table", { has: rows.first() });
  const edit = (state: string) =>
    table.getByRole("button", { name: `Edit the rule of ${state}`, exact: true });
  // The first rule and the last: each opens beneath its own row, and nothing is saved.
  const rowOf = (state: string) => `tr[data-state="${state}"]`;
  await opensBeneath(page, table, rowOf(firstState), firstState, edit(firstState));
  const form = await opensBeneath(page, table, rowOf(lastState), lastState, edit(lastState));
  await expect(form.getByRole("heading", { name: `The rule of ${lastState}` })).toBeVisible();
  await form.getByRole("button", { name: "Close", exact: true }).click();
  await closedTo(page, edit(lastState));
  await expectClean(page, seen);
});

test("P-171: Change on Admin › Files, and on a record's Files and links, opens beneath the row", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 1280, height: 800 });
  const headers = await session(request, account);
  const region = await make(request, headers, "/regions", { name: regionName });
  ids.region = region.hid;
  for (const [place, title] of titles.entries()) {
    const link = await make(request, headers, "/reference-files/links", {
      attach_to: [region.hid],
      kind: "map",
      title,
      url: `https://maps.example.com/${suffix}/survey-${place + 1}`,
    });
    ids.links.push(link.hid);
  }
  const seen = await watch(page.context());
  await signIn(page, account);
  const [one, two] = titles;
  const [oneHid = "", twoHid = ""] = ids.links;

  // Admin › Files, narrowed to the two links of this file.
  await page.goto(`./admin/files?title=${encodeURIComponent(suffix)}`);
  await expect(page.getByRole("heading", { level: 1, name: "Files" })).toBeVisible();
  const files = page.getByTestId("reference-files");
  await expect(files.locator("tr[data-reference]")).toHaveCount(2);
  const change = (within: Locator, title: string) =>
    within.getByRole("button", { name: `Change ${title}`, exact: true });
  let form = await opensBeneath(
    page,
    files,
    `tr[data-reference="${oneHid}"]`,
    oneHid,
    change(files, one),
  );
  await expect(form.getByRole("heading", { name: `Change ${one}` })).toBeVisible();
  await form.getByLabel("Notes").fill("typed and let go");
  await opensBeneath(page, files, `tr[data-reference="${twoHid}"]`, twoHid, change(files, two));
  form = await opensBeneath(
    page,
    files,
    `tr[data-reference="${oneHid}"]`,
    oneHid,
    change(files, one),
  );
  await expect(form.getByLabel("Notes")).toHaveValue("");
  await form.getByRole("button", { name: "Close", exact: true }).click();
  await closedTo(page, change(files, one));

  // The Files and links of the region: the same.
  await openPlace(page, "region", region.hid, regionName);
  const section = filesOf(page);
  const own = section.locator("table", { has: page.locator(`tr[data-title="${one}"]`) });
  form = await opensBeneath(page, own, `tr[data-reference="${twoHid}"]`, twoHid, change(own, two));
  await expect(form.getByRole("heading", { name: `Change ${two}` })).toBeVisible();
  await opensBeneath(page, own, `tr[data-reference="${oneHid}"]`, oneHid, change(own, one));
  await page
    .locator(`tr[data-form-of="${oneHid}"]`)
    .getByRole("button", { name: "Close", exact: true })
    .click();
  await closedTo(page, change(own, one));
  // The links are erased again. The region, which is retired and never removed, stays.
  for (const hid of ids.links) await remove(request, headers, `/reference-files/${hid}`);
  await expectClean(page, seen);
});
