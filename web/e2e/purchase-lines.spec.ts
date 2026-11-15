// The browser scenarios of purchase lines as procurement has them, in release 0.7.0:
//
//   P-121  A line of what this inventory does not follow has its part number and its
//          description as procurement gave them, and no model: it is not tracked, takes
//          nothing to receive, and is found by `tracked` in the list of lines.
//   P-120  The model of a line on which items have arrived is corrected, and the page
//          asks what becomes of the items: they follow, and are then of the corrected
//          model.
//   P-135  A model is taken off a line on which nothing has arrived, which is then not
//          tracked; a line on which something has arrived keeps a model.
//
// It keeps to the rules of support.ts: an account and names of its own, and models of
// its own, so that the lists it reads are of this file's lines and items alone.

import { expect, type Locator, type Page } from "@playwright/test";
import { importFile, region } from "./structure";
import { expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const random = mark("x").slice(2);
const suffix = mark("purchase-lines", random);
const upper = random.toUpperCase();

const vendor = `Example Networks ${suffix}`;
const pid = `EN-9200-24T-${suffix}`;
const model = "Example 9200 24-port";
const correctedPid = `EN-9200-48T-${suffix}`;
const corrected = "Example 9200 48-port";
// The reference of a request holds no slash: that separates it from the number of a line.
const reference = `RITM-${suffix}`;
const untracked = `${reference}/1`;
const corrects = `${reference}/2`;
const takenOff = `${reference}/3`;
const partNumber = `CAB-TIE-${upper}`;
const description = "Hook-and-loop cable ties, a bag of 100";
const serials = [1, 2].map((place) => `ENL${upper}0${place}`);

function lineRow(page: Page, name: string): Locator {
  return page.getByTestId("purchase-lines").locator(`tr[data-line="${name}"]`);
}

async function openRequest(page: Page) {
  await page.goto(`./purchases?filter=${encodeURIComponent(`reference:eq:${reference}`)}`);
  await page
    .getByTestId("grid-purchase-requests")
    .getByRole("link", { name: reference, exact: true })
    .click();
  await expect(page.getByRole("heading", { level: 1, name: reference })).toBeVisible();
}

/** Add a line on the page of the request on show. A model left out leaves it not tracked. */
async function addLine(
  page: Page,
  line: { model?: string; partNumber?: string; description?: string; quantity: string },
) {
  await page.getByRole("button", { name: "Add a line" }).click();
  const form = region(page, `New line of ${reference}`);
  if (line.model) {
    await form.getByLabel("Model", { exact: true }).selectOption({ label: line.model });
  }
  if (line.partNumber) await form.getByLabel("Part number").fill(line.partNumber);
  if (line.description) await form.getByLabel("Description").fill(line.description);
  await form.getByLabel("Quantity (required)").fill(line.quantity);
  await form.getByRole("button", { name: "Add line" }).click();
}

test("P-121: a line of what is not tracked, with its part number, takes nothing to receive", async ({
  page,
  account,
}) => {
  test.setTimeout(180_000);
  const seen = await watch(page.context());
  await signIn(page, account);

  await importFile(page, "vendors", `vendors-${suffix}.csv`, ["name"], [[vendor]]);
  await importFile(
    page,
    "catalog_entries",
    `catalog-entries-${suffix}.csv`,
    ["vendor", "pid", "model_name", "type"],
    [
      [vendor, pid, model, "switch"],
      [vendor, correctedPid, corrected, "switch"],
    ],
  );

  await page.goto("./purchases");
  await page.getByRole("button", { name: "New request" }).click();
  const newRequest = region(page, "New purchase request");
  await newRequest.getByLabel("Reference (required)").fill(reference);
  await newRequest.getByRole("button", { name: "Create request" }).click();
  await expect(page.getByRole("heading", { level: 1, name: reference })).toBeVisible();

  // Cable ties are bought on the request: the part number and the description as
  // procurement gave them, and no model.
  await addLine(page, { partNumber, description, quantity: "5" });
  await expect(
    page.getByText(`${untracked} was added: 5 × ${partNumber}, not tracked.`),
  ).toBeVisible();
  const row = lineRow(page, untracked);
  await expect(row).toHaveAttribute("data-tracked", "false");
  await expect(row.getByTestId("line-not-tracked")).toHaveText("Not tracked");
  await expect(row.getByTestId("line-part-number")).toContainText(partNumber);
  await expect(row.getByTestId("line-part-number")).toContainText(description);
  // It takes no item: there is nothing to receive on it, and nothing is to come.
  await expect(row.getByRole("button", { name: `Receive on ${untracked}` })).toHaveCount(0);
  await expect(row.getByTestId("line-pending")).toHaveText("—");
  // The request asks for nothing that is tracked yet, and says the line is not counted.
  await expect(page.getByTestId("request-quantity")).toHaveText("0 items");
  await expect(page.getByTestId("request-untracked")).toHaveAttribute("data-count", "1");

  // The list of every line finds it by `tracked`, and says it is not tracked.
  const ofRequest = `request.reference:eq:${reference}`;
  await page.goto(
    `./purchases/lines?filter=${encodeURIComponent(`${ofRequest} tracked:eq:false`)}`,
  );
  await expect(page.getByRole("heading", { level: 1, name: "Purchase lines" })).toBeVisible();
  await expect(page.getByTestId("grid-total")).toHaveText("1 line");
  const listed = page.getByTestId("grid-purchase-lines").locator("[row-id]");
  await expect(listed.locator('[col-id="tracked"]')).toHaveText("Not tracked");
  await expect(listed.locator('[col-id="part_number"]')).toHaveText(partNumber);
  await page.goto(`./purchases/lines?filter=${encodeURIComponent(`${ofRequest} tracked:eq:true`)}`);
  await expect(page.getByTestId("grid-total")).toHaveText("No lines");

  await expectClean(page, seen);
});

test("P-120: a line's model is corrected after items arrived, and the items follow", async ({
  page,
  account,
}) => {
  test.setTimeout(180_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  await openRequest(page);

  // A line of the first model, and two switches received on it.
  await addLine(page, { model: `${pid} (${model})`, quantity: "2" });
  await expect(page.getByText(`${corrects} was added: 2 × ${vendor} ${pid}.`)).toBeVisible();
  const row = lineRow(page, corrects);
  await expect(row).toHaveAttribute("data-tracked", "true");
  await row.getByRole("button", { name: `Receive on ${corrects}` }).click();
  const receive = page.getByTestId("receive-line");
  await receive.getByLabel("Serial numbers", { exact: true }).fill(serials.join("\n"));
  await receive.getByRole("button", { name: "Receive 2 items" }).click();
  await expect(
    page.getByText(`2 items were received on ${corrects}, in the state Delivered.`),
  ).toBeVisible();
  await expect(row).toHaveAttribute("data-received", "2");

  // The request was typed with the wrong model. The line keeps a model, since items
  // are on it: the form offers no blank, and asks what becomes of the two once another
  // model is chosen.
  await row.getByRole("button", { name: `Change ${corrects}` }).click();
  const change = page.getByTestId("change-line");
  const modelField = change.getByLabel("Model", { exact: true });
  await expect(change).toContainText("2 items have arrived on it, so it keeps a model");
  await expect(
    modelField.locator("option", { hasText: "None: the line is not tracked" }),
  ).toHaveCount(0);
  const question = change.getByLabel("What becomes of the 2 items that arrived on it");
  await expect(question).toHaveCount(0);
  await modelField.selectOption({ label: `${correctedPid} (${corrected})` });
  await expect(question).toBeVisible();
  await expect(change).toContainText("Follow gives every item on the line that is not retired");
  await expect(change).toContainText("Stay leaves each item with the model it has");
  await question.selectOption("follow");
  await change.getByRole("button", { name: "Save" }).click();
  await expect(
    page.getByText(
      `${corrects} is of ${vendor} ${correctedPid} now. The 2 items that arrived on it follow: each that is not retired is of ${vendor} ${correctedPid} as well.`,
    ),
  ).toBeVisible();
  await expect(row.getByRole("link", { name: `${vendor} ${correctedPid}` })).toBeVisible();
  // They followed: none is of another model than its line.
  await expect(row.getByTestId("line-mismatched")).toHaveCount(0);

  // The two are of the corrected model now, and none is left of the first.
  await page.goto(`./items?filter=${encodeURIComponent(`catalog.pid:eq:${correctedPid}`)}&minor=1`);
  await expect(page.getByTestId("grid-total")).toHaveText("2 items");
  await page.goto(`./items?filter=${encodeURIComponent(`catalog.pid:eq:${pid}`)}&minor=1`);
  await expect(page.getByTestId("grid-total")).toHaveText("No items");

  await expectClean(page, seen);
});

test("P-135: a model is taken off a line on which nothing has arrived", async ({
  page,
  account,
}) => {
  test.setTimeout(120_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  await openRequest(page);

  await addLine(page, { model: `${pid} (${model})`, partNumber: `${pid}=`, quantity: "1" });
  await expect(page.getByText(`${takenOff} was added: 1 × ${vendor} ${pid}.`)).toBeVisible();
  const row = lineRow(page, takenOff);
  await expect(row).toHaveAttribute("data-tracked", "true");
  await row.getByRole("button", { name: `Change ${takenOff}` }).click();
  const change = page.getByTestId("change-line");
  await expect(change).toContainText(
    "Nothing has arrived on it, so the model may also be taken off",
  );
  await change
    .getByLabel("Model", { exact: true })
    .selectOption({ label: "None: the line is not tracked" });
  // Nothing has arrived, so nothing is asked of the items.
  await expect(change.getByLabel(/What becomes of the/)).toHaveCount(0);
  await change.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText(`${takenOff} is not tracked any more`)).toBeVisible();
  await expect(row).toHaveAttribute("data-tracked", "false");
  await expect(row.getByTestId("line-not-tracked")).toBeVisible();
  await expect(row.getByRole("button", { name: `Receive on ${takenOff}` })).toHaveCount(0);

  await expectClean(page, seen);
});
