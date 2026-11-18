// The browser scenarios of 0.9.8, lane W1, P-238 and P-241 to P-245: the second part of
// working a stack. The first members of a new stack take its name and place; a member is
// replaced from its row in one press; a member that leaves is given its condition; an
// item lists its replacements, and an Admin removes one that was a mistake; a switch that
// stands alone is made a stack from its page.
//
// The file keeps the rules of support.ts. It signs in as an Admin of its own, and makes a
// viewer and an Inventory account of its own; its mark is in every name it gives a
// record: the region, the site, the rooms, the vendor, the catalog entry, the stacks and
// the switches, made through the API as that Admin or through the forms the scenarios
// walk. It changes no setting, no list of choices, no lifecycle rule and no account but
// its own, and reads only its own records, the lists filtered down to them. The
// scenarios run in order, on what the first makes.

import type { APIRequestContext, Locator, Page } from "@playwright/test";
import { expect } from "@playwright/test";
import { type Account, createAccount, expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const id = mark("stack-2");
const label = (name: string) => `${name} ${id}`;
/** A host name of this file, which begins with its mark. */
const host = (name: string) => `${id}-${name}`;
/** A serial number of this file: its mark's random part, in capitals, after a word. */
const serial = (name: string) => `${name}${id.slice(-6).toUpperCase()}`;
// Addresses of the documentation range, made of the mark so that a run again differs.
const net = `2001:db8:4${id.slice(-3)}`;

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
  status = 201,
): Promise<{ hid: string }> {
  const answer = await request.post(`./api/v1${path}`, { headers, data });
  expect(answer.status(), `post ${path}: ${await answer.text()}`).toBe(status);
  return (await answer.json()) as { hid: string };
}

// The places, and the switches the first scenario makes.
const site = label("Campus 80");
const room = label("IDF 02");
const depot = label("Spares Depot");
/** The spares of the pool: each has a host name, an FQDN, an address and the depot. */
const spares = ["01", "02", "03", "04", "05"].map((n) => host(`spare-sw-${n}`));
// A spare that joins a stack drops its host name: it is found by its serial number then.
const spareSerials = spares.map((one) => serial(`SP${one.slice(-2)}`));
const spareAddress = (index: number) => `${net}::${index + 10}`;

const standalone = host("lab-sw1");
const standaloneSerial = serial("LAB");
const standaloneAddress = `${net}::5`;

const made: { site?: string; room?: string; depot?: string; entry?: string } = {};

async function records(request: APIRequestContext, account: Account): Promise<void> {
  if (made.entry !== undefined) return;
  const headers = await session(request, account);
  const region = (await make(request, headers, "/regions", { name: label("Campus Works") })).hid;
  made.site = (
    await make(request, headers, "/sites", {
      name: site,
      code: `C80-${id}`,
      region_hid: region,
    })
  ).hid;
  made.room = (await make(request, headers, "/locations", { name: room, site_hid: made.site })).hid;
  made.depot = (
    await make(request, headers, "/locations", { name: depot, site_hid: made.site })
  ).hid;
  const vendor = (await make(request, headers, "/vendors", { name: label("Sample Networks") })).hid;
  const entry = (
    await make(request, headers, "/catalog-entries", {
      vendor_hid: vendor,
      pid: `SN-24P-${id}`,
      model_name: label("Edge Switch"),
      type: "switch",
    })
  ).hid;
  for (const [index, one] of spares.entries()) {
    const hid = (
      await make(request, headers, "/items", {
        catalog_entry_hid: entry,
        hostname: one,
        fqdn: `${one}.example.net`,
        serial_number: spareSerials[index],
        location_hid: made.depot,
        lifecycle_state: "Prod",
        disposition: "Spare",
        expected_online: false,
      })
    ).hid;
    await make(request, headers, "/addresses", {
      address: spareAddress(index),
      item_hid: hid,
      role: "management",
      is_primary: true,
    });
  }
  // A switch that stands alone in the room, with its names and an address of its own.
  const alone = (
    await make(request, headers, "/items", {
      catalog_entry_hid: entry,
      hostname: standalone,
      fqdn: `${standalone}.example.net`,
      serial_number: standaloneSerial,
      location_hid: made.room,
      lifecycle_state: "Prod",
      disposition: "Production",
      expected_online: true,
    })
  ).hid;
  await make(request, headers, "/addresses", {
    address: standaloneAddress,
    item_hid: alone,
    role: "management",
    is_primary: true,
  });
  made.entry = entry;
}

async function openItem(page: Page, name: string) {
  await page.goto(`./items?filter=${encodeURIComponent(name)}`);
  await page.getByTestId("grid-items").getByRole("link", { name, exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
}

function offers(scope: Locator): Locator {
  return scope.getByRole("list", { name: "Items that match" });
}

async function pick(form: Locator, name: string) {
  await form.getByLabel("Find an item to add", { exact: true }).fill(name);
  await offers(form)
    .getByRole("button", { name: new RegExp(`^${name}`) })
    .click();
}

const firstStack = host("idf2-acc1");

test("a stack made of two spares by New group: each has the box, ticked, and Production, and gives up its names, its address and the depot for the stack's (P-244)", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(150_000);
  await records(request, account);
  const seen = await watch(page.context());
  await signIn(page, account);
  await page.goto("./groups");
  await page.getByRole("button", { name: "New group" }).click();
  const form = page.getByRole("region", { name: "New group" });
  await form.getByLabel("Name (required)").fill(firstStack);
  await expect(form.getByLabel("Type")).toHaveValue("stack");
  await form.getByLabel("Hostname", { exact: true }).fill(firstStack);
  await form.getByLabel("Location", { exact: true }).fill(room);
  await form
    .getByRole("list", { name: "Locations that match" })
    .getByRole("button", { name: new RegExp(room) })
    .click();
  const two = [spares[0] ?? "", spares[1] ?? ""];
  for (const one of two) await pick(form, one);
  for (const [index, one] of two.entries()) {
    const box = form.getByRole("group", { name: one });
    await expect(box.getByLabel("It takes the stack's name and place")).toBeChecked();
    await expect(box.getByTestId("drops")).toContainText(
      `Removed from ${one}: the host name ${one}, the FQDN ${one}.example.net, the address ${spareAddress(index)}`,
    );
    await expect(box.getByLabel("Disposition")).toHaveValue("Production");
    await expect(box.getByLabel("Expected online")).toHaveValue("true");
  }
  // A cluster has no box; the stack has it again, ticked, when the type comes back.
  await form.getByLabel("Type").selectOption("cluster");
  await expect(form.getByTestId("join-box")).toHaveCount(0);
  await form.getByLabel("Type").selectOption("stack");
  await expect(form.getByTestId("join-box")).toHaveCount(2);
  await expect(
    form.getByRole("group", { name: two[1] }).getByLabel("It takes the stack's name and place"),
  ).toBeChecked();
  await form.getByRole("button", { name: "Create group" }).click();
  await expect(page.getByRole("heading", { level: 1, name: firstStack })).toBeVisible();

  // Each spare has the stack's names and place now, none of its own, and is in production.
  for (const [index, one] of two.entries()) {
    await openItem(page, spareSerials[index] ?? "");
    await expect(page.getByTestId("stack-member")).toHaveText(
      `Member ${index + 1} of ${firstStack}`,
    );
    await expect(page.getByTestId("stack-hostname")).toContainText(`${firstStack} · the stack's`);
    await expect(page.getByTestId("standing-fact")).toContainText("Production");
    await expect(page.getByTestId("location")).toHaveAttribute("data-source", "device_group");
    await expect(page.getByTestId("location")).toContainText(room);
    // Its own host name and address are gone: the history alone still names them.
    await expect(page.getByRole("heading", { level: 1 })).not.toHaveText(one);
    await expect(page.getByRole("region", { name: "Addresses" })).toContainText(
      `There is no address on ${spareSerials[index]}.`,
    );
  }
  // Who made each change is a link to the user's page, for an Admin (P-240).
  const who = page
    .getByRole("region", { name: "History" })
    .getByRole("link", { name: account.username, exact: true })
    .first();
  await expect(who).toHaveAttribute("href", new RegExp(`/admin/users/${account.hid}$`));
  await expectClean(page, seen);
});

/** The row of a member of the stack, by the name the row shows. */
function memberRow(page: Page, name: string): Locator {
  return page.getByTestId("members").locator("tbody tr[data-item]", { hasText: name });
}

async function openStack(page: Page, name: string) {
  await page.goto(`./groups?filter=${encodeURIComponent(`name:eq:${name}`)}`);
  await page.getByTestId("grid-device-groups").getByRole("link", { name, exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
}

test("a failed member is replaced from its row in one press: the spare takes its position, the stack's name and place, and Production, and the failed one is to go back to its maker, marked Failed (P-242, P-245)", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(150_000);
  await records(request, account);
  const seen = await watch(page.context());
  await signIn(page, account);
  await openStack(page, firstStack);
  const failed = spareSerials[1] ?? "";
  const spare = spares[2] ?? "";
  await memberRow(page, failed)
    .getByRole("button", { name: `Replace ${failed}` })
    .click();
  // The form opens under the row it replaces.
  const form = page.getByRole("region", { name: `Replace ${failed}` });
  await expect(page.locator("tr.row-form")).toHaveCount(1);
  await form.getByLabel("The item that takes its place", { exact: true }).fill(spare);
  // The picker of members: the spares first, each with where it stands (P-221).
  await expect(offers(form).locator("li").first()).toContainText(
    `Prod · Spare · ${site} > ${depot}`,
  );
  await offers(form)
    .getByRole("button", { name: new RegExp(`^${spare}`) })
    .click();
  const box = form.getByRole("group", { name: spare });
  await expect(box.getByLabel("It takes the stack's name and place")).toBeChecked();
  await expect(box.getByLabel("Disposition")).toHaveValue("Production");
  await expect(box.getByLabel("Expected online")).toHaveValue("true");
  await form.getByLabel("Reason").selectOption({ label: "RMA" });
  await form.getByLabel("Reference").fill(`RMA-${id}`);
  const what = form.getByRole("group", { name: "What becomes of it" });
  await what.getByLabel("To be returned to the manufacturer").check();
  await expect(what.getByLabel("Lifecycle state")).toHaveValue("Pending-Removal");
  await expect(what.getByLabel("Condition")).toHaveValue("failed");
  await form.getByRole("button", { name: "Replace", exact: true }).click();

  // The answer names both, each a link; the row shows the new member at the same position.
  const said = page.locator(".alert-ok");
  await expect(said).toContainText(`${failed} was replaced by `);
  await expect(said).toContainText(
    ` as member 2 of ${firstStack}. It takes the stack's name and place:`,
  );
  await expect(said).toContainText("marked Failed");
  await expect(said.getByRole("link", { name: failed })).toBeVisible();
  await expect(said.getByRole("link")).toHaveCount(2);
  const came = memberRow(page, spareSerials[2] ?? "");
  await expect(came.locator("td").first()).toHaveText("2");
  await expect(memberRow(page, failed)).toHaveCount(0);

  // What the server did, each item read again.
  await said.getByRole("link", { name: failed }).click();
  await expect(page.getByRole("heading", { level: 1, name: failed })).toBeVisible();
  await expect(page.getByTestId("standing-fact")).toContainText("Pending-Removal");
  await expect(page.getByRole("region", { name: "Condition and health" })).toContainText(
    "ConditionFailed",
  );
  await openItem(page, spareSerials[2] ?? "");
  await expect(page.getByTestId("stack-member")).toHaveText(`Member 2 of ${firstStack}`);
  await expect(page.getByTestId("standing-fact")).toContainText("Production");
  await expect(page.getByTestId("location")).toHaveAttribute("data-source", "device_group");
  await expectClean(page, seen);
});

test("a member that leaves by End is given its condition in the same form: Failed for one to be returned, which the person may change (P-245)", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(120_000);
  await records(request, account);
  const seen = await watch(page.context());
  await signIn(page, account);
  await openStack(page, firstStack);
  const leaving = spareSerials[0] ?? "";
  await memberRow(page, leaving)
    .getByRole("button", { name: `End the membership of ${leaving}` })
    .click();
  const ending = page.getByRole("region", { name: `End the membership of ${leaving}` });
  const what = ending.getByRole("group", { name: "What becomes of it" });
  await what.getByLabel("To the spare pool").check();
  await expect(what.getByLabel("Condition")).toHaveValue("");
  await what.getByLabel("To be returned to the manufacturer").check();
  await expect(what.getByLabel("Condition")).toHaveValue("failed");
  // The person may change it: this one is dead, not merely failed.
  await what.getByLabel("Condition").selectOption({ label: "Dead" });
  await ending.getByRole("button", { name: "End membership" }).click();
  const said = page.locator(".alert-ok");
  await expect(said).toContainText(`The membership of ${leaving} ended on`);
  await expect(said).toContainText("marked Dead");
  await said.getByRole("link", { name: leaving }).click();
  await expect(page.getByRole("heading", { level: 1, name: leaving })).toBeVisible();
  await expect(page.getByRole("region", { name: "Condition and health" })).toContainText(
    "ConditionDead",
  );
  await expect(page.getByTestId("standing-fact")).toContainText("Pending-Removal");
  await expectClean(page, seen);
});

// The spare that took a place in the second scenario, which goes back to the pool and
// takes a place again, as 0.9.7 refused.
const pooled = host("spare-sw-93");

async function replaceOnRow(page: Page, leaving: string, coming: string) {
  await memberRow(page, leaving)
    .getByRole("button", { name: `Replace ${leaving}` })
    .click();
  const form = page.getByRole("region", { name: `Replace ${leaving}` });
  await form.getByLabel("The item that takes its place", { exact: true }).fill(coming);
  await offers(form)
    .getByRole("button", { name: new RegExp(`^${coming}`) })
    .click();
  await form.getByLabel("Reason").selectOption({ label: "RMA" });
  return form;
}

test("a spare that took a place goes back to the pool by Replace and takes a place a second time; its page lists every replacement, and an Admin removes one that was a mistake (P-241, P-238)", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(180_000);
  await records(request, account);
  const seen = await watch(page.context());
  await signIn(page, account);
  await openStack(page, firstStack);
  const twice = spareSerials[2] ?? "";
  const between = spareSerials[3] ?? "";

  // It leaves for the pool, with a new name and the depot, as End sends it.
  let form = await replaceOnRow(page, twice, spares[3] ?? "");
  const what = form.getByRole("group", { name: "What becomes of it" });
  await what.getByLabel("To the spare pool").check();
  await what.getByLabel("Hostname").fill(pooled);
  await what.getByLabel("Location").fill(depot);
  await what
    .getByRole("button", { name: new RegExp(depot) })
    .first()
    .click();
  await form.getByRole("button", { name: "Replace", exact: true }).click();
  const said = page.locator(".alert-ok");
  await expect(said).toContainText(`${pooled} was replaced by ${between} as member 2`);
  await expect(said).toContainText(`named ${pooled}`);

  // It takes the place again, and is in the stack once more.
  form = await replaceOnRow(page, between, pooled);
  await expect(
    form.getByRole("group", { name: pooled }).getByLabel("It takes the stack's name and place"),
  ).toBeChecked();
  await form.getByRole("button", { name: "Replace", exact: true }).click();
  await expect(said).toContainText(`${between} was replaced by ${twice} as member 2`);
  await expect(memberRow(page, twice).locator("td").first()).toHaveText("2");

  // Its page lists the three, the latest first.
  await said.getByRole("link", { name: twice }).click();
  await expect(page.getByRole("heading", { level: 1, name: twice })).toBeVisible();
  const lines = page.getByTestId("replacements").locator("li");
  await expect(lines).toHaveCount(3);
  await expect(lines.nth(0)).toContainText(`Took the place of ${between}`);
  await expect(lines.nth(1)).toContainText(`Replaced by ${between}`);
  await expect(lines.nth(2)).toContainText(`Took the place of ${spareSerials[1]}`);
  await expect(lines.nth(0).getByRole("link", { name: new RegExp(`^${between}`) })).toBeVisible();

  // An Admin removes the latest, which asks first and wants a reason typed.
  await lines
    .nth(0)
    .getByRole("button", { name: /^Remove the replacement of/ })
    .click();
  const asked = page.getByRole("form", { name: /^Remove the replacement of/ });
  await expect(asked).toContainText("What it handed over stays");
  const go = asked.getByRole("button", { name: "Remove replacement" });
  await expect(go).toBeDisabled();
  await asked.getByLabel("Reason").fill(`recorded twice ${id}`);
  await go.click();
  await expect(said).toContainText(`The replacement of ${between} by ${twice} on`);
  await expect(said).toContainText("was removed.");
  await expect(lines).toHaveCount(2);
  // What it handed over stays: the switch is still member 2 of the stack.
  await expect(page.getByTestId("stack-member")).toHaveText(`Member 2 of ${firstStack}`);
  await expectClean(page, seen);
});

test("a viewer sees no Replace; Inventory sees Replace on the row and on the item, and no Remove of a replacement (P-242, P-238)", async ({
  page,
  request,
}) => {
  test.setTimeout(120_000);
  const viewer = await createAccount(request, `e2e-${id}-viewer`, "viewer");
  const inventory = await createAccount(request, `e2e-${id}-inventory`, "inventory");
  const twice = spareSerials[2] ?? "";
  const seen = await watch(page.context());

  await signIn(page, viewer);
  await openStack(page, firstStack);
  await expect(memberRow(page, twice)).toBeVisible();
  await expect(page.getByRole("button", { name: `Replace ${twice}` })).toHaveCount(0);
  await openItem(page, twice);
  await expect(page.getByTestId("replacements").locator("li")).toHaveCount(2);
  await expect(page.getByRole("button", { name: "Replace this item" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /^Remove the replacement/ })).toHaveCount(0);
  // Who made a change is text for every role but Admin (P-240).
  await expect(page.getByRole("region", { name: "History" }).getByRole("link")).toHaveCount(0);
  // Nor Make it a stack on a switch in no stack (P-243).
  await openItem(page, standalone);
  await expect(page.getByRole("button", { name: "Make it a stack" })).toHaveCount(0);
  await page.getByRole("button", { name: "Sign out" }).click();

  await signIn(page, inventory);
  await openStack(page, firstStack);
  // Pressed while the server is slow to read the item, Replace says so, then shows its
  // form when the item comes, the box ticked.
  let release = () => {};
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/v1/items/*", async (route) => {
    if (route.request().method() === "GET") await held;
    await route.continue().catch(() => {});
  });
  await page.getByRole("button", { name: `Replace ${twice}` }).click();
  await expect(page.getByRole("status").filter({ hasText: "Reading the item" })).toBeVisible();
  release();
  const form = page.getByRole("region", { name: `Replace ${twice}` });
  await expect(form.getByLabel("The item that takes its place", { exact: true })).toBeEnabled();
  await page.unroute("**/api/v1/items/*");
  await form.getByRole("button", { name: "Cancel" }).click();
  await expect(form).toHaveCount(0);
  await openItem(page, twice);
  await expect(page.getByRole("button", { name: "Replace this item" })).toBeVisible();
  await expect(page.getByRole("button", { name: /^Remove the replacement/ })).toHaveCount(0);
  await expectClean(page, seen);
});

test("a switch that stands alone is made a stack from its page with a spare: the stack takes its names, its address and its place, and the spare joins with the box (P-243)", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(150_000);
  await records(request, account);
  const seen = await watch(page.context());
  await signIn(page, account);
  await openItem(page, standalone);
  const fact = page.getByTestId("stack-member");
  await expect(fact).toContainText("In no stack");
  await fact.getByRole("button", { name: "Make it a stack" }).click();
  const form = page.getByRole("region", { name: "Make it a stack" });
  // The switch's own name from the start, which the person may change.
  await expect(form.getByLabel("Name of the stack")).toHaveValue(standalone);
  await expect(form.getByTestId("make-stack-goes")).toContainText(
    `To the stack from ${standalone}: the host name ${standalone}, the FQDN ${standalone}.example.net, its address and the location ${label("Campus Works")} > ${site} > ${room}.`,
  );
  const stackName = host("lab-stk1");
  await form.getByLabel("Name of the stack").fill(stackName);
  const spare = spares[4] ?? "";
  await pick(form, spare);
  await expect(form.getByLabel(`Position of ${spare}`)).toHaveValue("2");
  const box = form.getByRole("group", { name: spare });
  await expect(box.getByLabel("It takes the stack's name and place")).toBeChecked();
  await expect(box.getByLabel("Disposition")).toHaveValue("Production");
  await form.getByRole("button", { name: "Make the stack" }).click();

  // The stack's page, saying what was made.
  await expect(page.getByRole("heading", { level: 1, name: stackName })).toBeVisible();
  await expect(page.locator(".alert-ok")).toHaveText(
    `The stack ${stackName} was made of ${standalone}, member 1, with 1 more member.`,
  );
  await expect(memberRow(page, standaloneSerial).locator("td").first()).toHaveText("1");
  await expect(
    memberRow(page, spareSerials[4] ?? "")
      .locator("td")
      .first(),
  ).toHaveText("2");

  // The switch has the stack's names, address and place, none of its own.
  await openItem(page, standaloneSerial);
  await expect(page.getByTestId("stack-member")).toHaveText(`Member 1 of ${stackName}`);
  await expect(page.getByTestId("stack-hostname")).toContainText(`${standalone} · the stack's`);
  await expect(page.getByTestId("stack-addresses")).toContainText(standaloneAddress);
  await expect(page.getByTestId("location")).toHaveAttribute("data-source", "device_group");
  await expect(page.getByRole("region", { name: "Addresses" })).toContainText(
    `There is no address on ${standaloneSerial}.`,
  );
  await expectClean(page, seen);
});
