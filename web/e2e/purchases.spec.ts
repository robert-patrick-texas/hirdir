// The browser scenario of purchases in release 0.6.0:
//
//   S32  A purchase request with a line of ten switches is not in the component count.
//        Receiving six creates six items in Delivered, each linked to the line, and four
//        are still to come. The other four, received as a count, are named for the line,
//        and the request is then received.
//
// On the way: a serial number that is taken already is refused and nothing is received,
// a line is not lowered beneath what arrived on it, and an item says which line it
// arrived on.
//
// And of release 0.6.1:
//
//   D-161  An item put on a line is of the line's model: one with no model takes it, and
//          one of another model is refused, with the message beside its model, as is a
//          change of the model of an item on a line. What 0.6.0 let in is marked on the
//          item and counted on the line of the request, leading to those items.
//
// It keeps to the rules of support.ts: an account and names of its own, and a model of
// its own, so that the counts read are of this file's items alone.

import { expect, type Locator, type Page } from "@playwright/test";
import { chooseColumns, ROOM, resetGrid } from "./contractSteps";
import { importFile, main, openItem, region, summary } from "./structure";
import { expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const random = mark("x").slice(2);
const suffix = mark("purchases", random);
const upper = random.toUpperCase();

const vendor = `Example Networks ${suffix}`;
const pid = `EN-9300-24T-${suffix}`;
// Another model of the vendor, and two items that are put on a second line by hand.
const otherPid = `EN-9300-48T-${suffix}`;
const ofOtherModel = `site4-sw-${suffix}-x1`;
const noModel = `site4-sw-${suffix}-x2`;
// The reference of a request holds no slash: that separates it from the number of a line.
const reference = `RITM-${suffix}`;
const line = `${reference}/1`;
const secondLine = `${reference}/2`;
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

test("S32: a request with a line of ten switches: six are received, then four as a count", async ({
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
  const arrived = receive.getByLabel("Serial numbers", { exact: true });
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
  // Four are still to come, so the request is not received yet.
  await expect(page.getByTestId("request-status")).not.toHaveAttribute("data-status", "received");

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
    .getByLabel("Serial numbers", { exact: true })
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

  // A line is not lowered beneath what has arrived on it.
  await openRequest(page);
  await lineRow(page)
    .getByRole("button", { name: `Change ${line}` })
    .click();
  const change = page.getByTestId("change-line");
  await change.getByLabel("Quantity (required)").fill("5");
  await change.getByRole("button", { name: "Save" }).click();
  await expect(change.getByText(/6 have arrived on this line; not fewer than that/)).toBeVisible();
  await change.getByRole("button", { name: "Close" }).click();
  await expect(change).toHaveCount(0);
  await expect(lineRow(page).getByTestId("line-pending")).toHaveText("4");

  // The other four arrive with nothing to know them by yet: they are received as a
  // count. More than the line still expects is said before anything is sent.
  await lineRow(page)
    .getByRole("button", { name: `Receive on ${line}` })
    .click();
  await expect(receive).toContainText("4 items are still to come on this line.");
  const count = receive.getByLabel("How many more arrived, with nothing to know them by yet");
  await count.fill("5");
  await receive.getByRole("button", { name: "Receive 5 items" }).click();
  await expect(
    receive.getByText(
      "5 items are more than the 4 this line still expects. Raise its quantity first.",
    ),
  ).toBeVisible();
  await count.fill("4");
  await receive.getByRole("button", { name: "Receive 4 items" }).click();
  await expect(
    page.getByText(`4 items were received on ${line}, in the state Delivered.`),
  ).toBeVisible();
  await expect(lineRow(page).getByTestId("line-received")).toHaveText("10");
  await expect(lineRow(page).getByTestId("line-pending")).toHaveText("0");
  await expect(page.getByTestId("request-received")).toHaveText("10 items");
  await expect(page.getByTestId("request-pending")).toHaveText("0 items");
  // Every line has arrived in full: the request is received, by itself.
  await expect(page.getByTestId("request-status")).toHaveAttribute("data-status", "received");

  // The four are named for the line, after the six that arrived before them.
  await expect(rows).toHaveCount(10);
  for (const place of ["007", "008", "009", "010"]) {
    const named = rows.filter({ hasText: `${line}-${place}` });
    await expect(named).toHaveCount(1);
    await expect(named).toContainText("Delivered");
  }
  // One of them: it has its name from the line, no serial number, and says its line.
  await onLine.getByRole("link", { name: `${line}-007`, exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: `${line}-007` })).toBeVisible();
  await expect(page.getByTestId("state")).toHaveText("Delivered");
  await expect(
    page.getByTestId("item-purchase-line").getByRole("link", { name: line, exact: true }),
  ).toBeVisible();

  // All ten are inventory, and still in no component count.
  await summary(page, ofModel);
  await expect(page.getByTestId("total-items")).toHaveText("10");
  await expect(page.getByTestId("total-components")).toHaveText("0");

  // Nothing more is received on the line.
  await openRequest(page);
  await expect(page.getByTestId("request-status")).toHaveAttribute("data-status", "received");
  await lineRow(page)
    .getByRole("button", { name: `Receive on ${line}` })
    .click();
  await expect(page.getByTestId("receive-line")).toContainText(
    "Everything on this line has arrived.",
  );

  // The two refusals above are the only requests that failed.
  await expectClean(page, seen, ["409 POST", "422 PATCH"]);
});

/** Name a line on the page of the item on show, and save it. */
async function nameLine(page: Page, name: string) {
  const purchase = region(page, "Purchase");
  await purchase
    .getByRole("button", { name: /^Name (another line|the line it arrived on)$/ })
    .click();
  const form = page.getByTestId("set-purchase-line");
  await form.getByLabel("Purchase line", { exact: true }).fill(name);
  await form
    .getByRole("list", { name: "Lines that match" })
    .getByRole("button", { name: new RegExp(`^${name} · `) })
    .click();
  await form.getByRole("button", { name: "Save" }).click();
  return form;
}

test("D-161: an item put on a line is of its model, and what 0.6.0 let in is marked", async ({
  page,
  account,
}) => {
  test.setTimeout(240_000);
  const seen = await watch(page.context());
  await signIn(page, account);

  // Another model, an item of it, and a second line of the first model, with room.
  await importFile(
    page,
    "catalog_entries",
    `catalog-entries-${suffix}-2.csv`,
    ["vendor", "pid", "model_name", "type"],
    [[vendor, otherPid, "Example 9300 48-port", "switch"]],
  );
  await importFile(
    page,
    "items",
    `items-${suffix}-2.csv`,
    ["vendor", "pid", "serial_number", "hostname", "lifecycle_state"],
    [[vendor, otherPid, `ENP${upper}X1`, ofOtherModel, "Delivered"]],
  );
  await openRequest(page);
  await page.getByRole("button", { name: "Add a line" }).click();
  const newLine = region(page, `New line of ${reference}`);
  await newLine
    .getByLabel("Model (required)")
    .selectOption({ label: `${pid} (Example 9300 24-port)` });
  await newLine.getByLabel("Quantity (required)").fill("2");
  await newLine.getByRole("button", { name: "Add line" }).click();
  await expect(page.getByText(`${secondLine} was added: 2 × ${vendor} ${pid}.`)).toBeVisible();

  // An item of the other model is refused on the line, and the answer stands beside its
  // model, naming the line's.
  await openItem(page, ofOtherModel);
  const refused = await nameLine(page, secondLine);
  const model = refused.getByTestId("item-model");
  await expect(model).toContainText(`${vendor} ${otherPid}`);
  await expect(model.locator(".field-error")).toHaveText(
    `line ${secondLine} is of ${pid}; an item on it is of that model, or is taken off the line first`,
  );
  await expect(refused.locator(".alert-error")).not.toContainText("catalog_entry_hid");
  await expect(page.getByTestId("item-purchase-line")).toContainText(
    "No line of a purchase request",
  );

  // An item with no model takes the line's.
  await page.goto("./items");
  await page.getByRole("button", { name: "New item" }).click();
  const made = region(page, "New item");
  await made.getByLabel("Hostname").fill(noModel);
  await made.getByRole("button", { name: "Create item" }).click();
  await expect(page.getByRole("heading", { level: 1, name: noModel })).toBeVisible();
  const itemPage = page.url();
  await nameLine(page, secondLine);
  await expect(page.getByText(`${noModel} counts as received on ${secondLine}.`)).toBeVisible();
  await expect(
    region(page, "Identity").getByRole("link", { name: `${vendor} ${pid}` }),
  ).toBeVisible();
  await expect(page.getByTestId("purchase-line-mismatch")).toHaveCount(0);

  // While it is on the line its model is not changed, and the form says so beside it.
  const details = region(page, "Details");
  await details
    .getByLabel("Catalog entry")
    .selectOption({ label: `${otherPid} (Example 9300 48-port)` });
  await details.getByRole("button", { name: "Save" }).click();
  await expect(
    details.locator(".field-error", {
      hasText: `line ${secondLine} is of ${pid}; an item on it is of that model`,
    }),
  ).toBeVisible();
  await expect(details.getByLabel("Catalog entry")).toHaveAttribute("aria-invalid", "true");

  // Nothing of this file is on a line of another model: the grid finds none, and the
  // column is in its chooser.
  const ofThisModel = `catalog.pid:eq:${pid}`;
  await page.goto(
    `./items?filter=${encodeURIComponent(`${ofThisModel} purchase_line_mismatch:eq:false`)}&minor=1`,
  );
  await expect(page.getByTestId("grid-total")).toHaveText("11 items");
  await chooseColumns(page, ["Of another model than its line"], ROOM);
  await expect(
    page.getByTestId("grid-items").locator('.ag-header-cell[col-id="purchase_line_mismatch"]'),
  ).toContainText("Of another model than its line");
  await resetGrid(page);
  await page.goto(
    `./items?filter=${encodeURIComponent(`${ofThisModel} purchase_line_mismatch:eq:true`)}&minor=1`,
  );
  await expect(page.getByTestId("grid-total")).toHaveText("No items");
  await openRequest(page);
  const second = page.getByTestId("purchase-lines").locator(`tr[data-line="${secondLine}"]`);
  await expect(second).toHaveAttribute("data-received", "1");
  await expect(page.getByTestId("request-mismatched")).toHaveCount(0);
  await expect(page.getByTestId("line-mismatched")).toHaveCount(0);

  // What 0.6.0 let in cannot be made through the API any more: the answers of the server
  // are changed in the browser, to show what the pages do with an item on a line of
  // another model, and with a line that counts one.
  const requestPage = page.url();
  const requestHid = new URL(requestPage).pathname.split("/").pop() ?? "";
  const itemHid = new URL(itemPage).pathname.split("/").pop() ?? "";
  await page.route(
    (url) => url.pathname.endsWith(`/api/v1/items/${itemHid}`),
    async (route) => {
      const response = await route.fetch();
      const item = await response.json();
      item.purchase_line_mismatch = true;
      item.catalog = { ...item.catalog, pid: otherPid };
      await route.fulfill({ response, json: item });
    },
  );
  await page.route(
    (url) =>
      url.pathname.endsWith(`/api/v1/purchase-requests/${requestHid}`) ||
      url.pathname.endsWith(`/api/v1/purchase-requests/${requestHid}/lines`),
    async (route) => {
      const response = await route.fetch();
      const body = await response.json();
      for (const line of body.lines ?? body.items ?? []) {
        if (line.name === secondLine) line.mismatched_items = 1;
      }
      await route.fulfill({ response, json: body });
    },
  );

  await page.goto(itemPage);
  const mismatch = page.getByTestId("purchase-line-mismatch");
  await expect(mismatch).toContainText("Of another model than its line");
  await expect(mismatch).toContainText(
    `${noModel} is ${vendor} ${otherPid}, and ${secondLine} is a line of ${vendor} ${pid}. 0.6.0 let that in`,
  );
  await expect(mismatch).toContainText("To put it right");

  await page.goto(requestPage);
  const warning = page.getByTestId("request-mismatched");
  await expect(warning).toHaveAttribute("data-count", "1");
  await expect(warning).toContainText(
    "1 item on the lines of this request is of another model than the line's",
  );
  await expect(second.getByTestId("line-mismatched")).toHaveText("1 of another model");
  await warning.getByRole("link", { name: `1 item on ${secondLine}` }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Items" })).toBeVisible();
  await expect(page.getByLabel("Filter", { exact: true })).toHaveValue(
    /^purchase_line_hid:eq:\S+ purchase_line_mismatch:eq:true$/,
  );
  // The line counts them as the item list does: archived items are left out.
  await expect(page.getByLabel("Include archived")).not.toBeChecked();
  // The server, whose answers were not changed for the list, has none.
  await expect(page.getByTestId("grid-total")).toHaveText("No items");
  await page.unrouteAll({ behavior: "wait" });

  await expectClean(page, seen, ["422 PATCH", "422 PATCH"]);
});
