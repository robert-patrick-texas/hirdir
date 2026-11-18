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
import { type Account, expectClean, mark, signIn, test, watch } from "./support";

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
  await expectClean(page, seen);
});
