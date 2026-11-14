// The browser scenario of purchases in release 0.6.0:
//
//   S32  A purchase request with a line of ten switches is not in the component count.
//        Receiving six creates six items in Delivered, each linked to the line, and four
//        are still to come.
//
// On the way: a serial number that is taken already is refused and nothing is received,
// the line is taken back by lowering it to what arrived, and an item says which line it
// arrived on.
//
// It keeps to the rules of support.ts: an account and names of its own, and a model of
// its own, so that the counts read are of this file's items alone.

import { expect, type Locator, type Page } from "@playwright/test";
import { importFile, main, region, summary } from "./structure";
import { expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const random = mark("x").slice(2);
const suffix = mark("purchases", random);
const upper = random.toUpperCase();

const vendor = `Example Networks ${suffix}`;
const pid = `EN-9300-24T-${suffix}`;
// The reference of a request holds no slash: that separates it from the number of a line.
const reference = `RITM-${suffix}`;
const line = `${reference}/1`;
const serials = [1, 2, 3, 4, 5, 6].map((place) => `ENP${upper}0${place}`);
// What the summary counts of this model: nothing of a request is among it.
const ofModel = `catalog.pid:eq:${pid}`;

function lineRow(page: Page): Locator {
  return page.getByTestId("purchase-lines").locator(`tr[data-line="${line}"]`);
}

async function openRequest(page: Page) {
  await page.goto(`./purchases?filter=${encodeURIComponent(`reference:eq:${reference}`)}`);
  await page
    .getByTestId("grid-purchase-requests")
    .getByRole("link", { name: reference, exact: true })
    .click();
  await expect(page.getByRole("heading", { level: 1, name: reference })).toBeVisible();
}

test("S32: a request with a line of ten switches, of which six are received", async ({
  page,
  account,
}) => {
  test.setTimeout(240_000);
  const seen = await watch(page.context());
  await signIn(page, account);

  await importFile(page, "vendors", `vendors-${suffix}.csv`, ["name"], [[vendor]]);
  await importFile(
    page,
    "catalog_entries",
    `catalog-entries-${suffix}.csv`,
    ["vendor", "pid", "model_name", "type", "support_weight"],
    [[vendor, pid, "Example 9300 24-port", "switch", "1.00"]],
  );

  // A purchase request, and on its page a line of ten of the model.
  await main(page).getByRole("link", { name: "Purchases" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Purchases" })).toBeVisible();
  await page.getByRole("button", { name: "New request" }).click();
  const newRequest = region(page, "New purchase request");
  await newRequest.getByLabel("Reference (required)").fill(reference);
  await newRequest.getByRole("button", { name: "Create request" }).click();
  await expect(page.getByRole("heading", { level: 1, name: reference })).toBeVisible();
  await expect(region(page, "Lines")).toContainText(`${reference} has no line yet.`);
  await page.getByRole("button", { name: "Add a line" }).click();
  const newLine = region(page, `New line of ${reference}`);
  await newLine
    .getByLabel("Model (required)")
    .selectOption({ label: `${pid} (Example 9300 24-port)` });
  await newLine.getByLabel("Quantity (required)").fill("10");
  await newLine.getByRole("button", { name: "Add line" }).click();
  await expect(page.getByText(`${line} was added: 10 × ${vendor} ${pid}.`)).toBeVisible();
  await expect(lineRow(page)).toHaveAttribute("data-pending", "10");
  await expect(lineRow(page).getByTestId("line-received")).toHaveText("0");
  await expect(page.getByTestId("request-quantity")).toHaveText("10 items");
  await expect(page.getByTestId("request-pending")).toHaveText("10 items");
  // Nothing has arrived, so there is nothing to list.
  await expect(
    lineRow(page).getByRole("button", { name: `What arrived on ${line}` }),
  ).toBeDisabled();

  // A request and its lines are not inventory: no item of the model is counted.
  await summary(page, ofModel);
  await expect(page.getByTestId("total-items")).toHaveText("0");
  await expect(page.getByTestId("total-components")).toHaveText("0");

  // The lines of every request are a list of their own, with what is still to come.
  await page.goto(
    `./purchases/lines?filter=${encodeURIComponent(`request.reference:eq:${reference}`)}`,
  );
  await expect(page.getByRole("heading", { level: 1, name: "Purchase lines" })).toBeVisible();
  await expect(page.getByTestId("grid-total")).toHaveText("1 line");
  const listed = page.getByTestId("grid-purchase-lines").locator("[row-id]");
  await expect(listed.locator('[col-id="quantity"]')).toHaveText("10");
  await expect(listed.locator('[col-id="pending_quantity"]')).toHaveText("10");

  // Receive six: their serial numbers, one to a line. More than the line expects is
  // said before anything is sent.
  await openRequest(page);
  await lineRow(page)
    .getByRole("button", { name: `Receive on ${line}` })
    .click();
  const receive = page.getByTestId("receive-line");
  await expect(receive).toContainText("10 items are still to come on this line.");
  const arrived = receive.getByLabel("Serial numbers (required)");
  await arrived.fill(Array.from({ length: 11 }, (_, place) => `ENP${upper}9${place}`).join("\n"));
  await receive.getByRole("button", { name: "Receive 11 items" }).click();
  await expect(
    receive.getByText(
      "11 items are more than the 10 this line still expects. Raise its quantity first.",
    ),
  ).toBeVisible();
  await arrived.fill(serials.join("\n"));
  await receive.getByRole("button", { name: "Receive 6 items" }).click();
  await expect(
    page.getByText(`6 items were received on ${line}, in the state Delivered. 4 still to come.`),
  ).toBeVisible();
  await expect(lineRow(page).getByTestId("line-received")).toHaveText("6");
  await expect(lineRow(page).getByTestId("line-pending")).toHaveText("4");
  await expect(page.getByTestId("request-received")).toHaveText("6 items");
  await expect(page.getByTestId("request-pending")).toHaveText("4 items");

  // The six items that arrived on the line are listed, each in Delivered.
  const onLine = page.getByTestId("arrived-items");
  await expect(onLine.getByRole("heading", { name: `Arrived on ${line}` })).toBeVisible();
  const rows = onLine.getByTestId("arrived").locator("tbody tr");
  await expect(rows).toHaveCount(6);
  for (const serial of serials) {
    await expect(rows.filter({ hasText: serial })).toContainText("Delivered");
  }

  // A serial number that is taken is refused, and nothing of that delivery is received.
  await lineRow(page)
    .getByRole("button", { name: `Receive on ${line}` })
    .click();
  await receive
    .getByLabel("Serial numbers (required)")
    .fill([`ENP${upper}07`, serials[0]].join("\n"));
  await receive.getByRole("button", { name: "Receive 2 items" }).click();
  await expect(
    receive.getByText(/another item of this vendor and PID has this serial number/),
  ).toBeVisible();
  await receive.getByRole("button", { name: "Cancel" }).click();
  await expect(lineRow(page).getByTestId("line-received")).toHaveText("6");

  // One of the items: it is in Delivered, and says which line it arrived on.
  await lineRow(page)
    .getByRole("button", { name: `What arrived on ${line}` })
    .click();
  await page
    .getByTestId("arrived")
    .getByRole("link", { name: serials[0] ?? "", exact: true })
    .click();
  await expect(page.getByRole("heading", { level: 1, name: serials[0] })).toBeVisible();
  await expect(page.getByTestId("state")).toHaveText("Delivered");
  await expect(page.getByTestId("item-purchase-line")).toContainText(line);
  await expect(
    page.getByTestId("item-purchase-line").getByRole("link", { name: line, exact: true }),
  ).toBeVisible();

  // The six are inventory now, and in no component count: Delivered is not a state
  // that counts.
  await summary(page, ofModel);
  await expect(page.getByTestId("total-items")).toHaveText("6");
  await expect(page.getByTestId("total-components")).toHaveText("0");
  // The item grid lists them like any other items.
  await page.goto(`./items?filter=${encodeURIComponent(ofModel)}`);
  await expect(page.getByTestId("grid-total")).toHaveText("6 items");

  // The four that will not come: the line is taken back by lowering it to what arrived.
  await openRequest(page);
  await lineRow(page)
    .getByRole("button", { name: `Change ${line}` })
    .click();
  const change = page.getByTestId("change-line");
  await change.getByLabel("Quantity (required)").fill("5");
  await change.getByRole("button", { name: "Save" }).click();
  await expect(change.getByText(/6 have arrived on this line; not fewer than that/)).toBeVisible();
  await change.getByLabel("Quantity (required)").fill("6");
  await change.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText(`${line} was saved.`)).toBeVisible();
  await expect(lineRow(page).getByTestId("line-pending")).toHaveText("0");
  await expect(page.getByTestId("request-pending")).toHaveText("0 items");
  // Nothing more is received on it.
  await lineRow(page)
    .getByRole("button", { name: `Receive on ${line}` })
    .click();
  await expect(page.getByTestId("receive-line")).toContainText(
    "Everything on this line has arrived.",
  );

  // The two refusals above are the only requests that failed.
  await expectClean(page, seen, ["409 POST", "422 PATCH"]);
});
