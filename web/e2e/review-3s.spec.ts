// The browser scenarios of the third review of the web UI, lane S2, P-217 to P-222:
// working a stack. A stack is known by its name; its members have no name of their own;
// a spare that joins takes the stack's name and place; one that leaves goes to the spare
// pool, back to its maker, or to excess.
//
// The file keeps the rules of support.ts. It signs in as an Admin of its own, and its
// mark is in every name it gives a record: the region, the site, the rooms, the vendor,
// the catalog entry, the stacks and the switches, made through the API as that Admin or
// through the forms the scenarios walk. It changes no setting, no list of choices, no
// lifecycle rule and no account, and reads only its own records, the lists filtered down
// to them. The scenarios run in order, on what the first makes.

import type { APIRequestContext, Locator, Page } from "@playwright/test";
import { expect } from "@playwright/test";
import { type Account, expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const id = mark("review-3s");
const label = (name: string) => `${name} ${id}`;
/** A host name of this file, which begins with its mark. */
const host = (name: string) => `${id}-${name}`;
/** A serial number of this file: its mark's random part, in capitals, after a word. */
const serial = (name: string) => `${name}${id.slice(-6).toUpperCase()}`;
// An address of the documentation range, made of the mark so that a run again differs.
const stackAddress = `2001:db8:3${id.slice(-3)}::1`;

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

// The stacks and the switches the first scenario makes.
const stack = host("idf1-acc1");
const other = host("idf2-acc1");
const members = [serial("FCWA"), serial("FCWB")];
const strayMember = serial("FCWX");
const spares = [host("spare-sw-01"), host("spare-sw-02")];
const standalone = host("lab-sw1");
const site = label("Campus 70");
const room = label("IDF 01");
const depot = label("Spares Depot");

const made: { stack?: string; other?: string } = {};

async function records(request: APIRequestContext, account: Account): Promise<void> {
  if (made.stack !== undefined) return;
  const headers = await session(request, account);
  const region = (await make(request, headers, "/regions", { name: label("Campus Works") })).hid;
  const siteHid = (
    await make(request, headers, "/sites", {
      name: site,
      code: `C70-${id}`,
      region_hid: region,
    })
  ).hid;
  const roomHid = (await make(request, headers, "/locations", { name: room, site_hid: siteHid }))
    .hid;
  const depotHid = (await make(request, headers, "/locations", { name: depot, site_hid: siteHid }))
    .hid;
  const vendor = (await make(request, headers, "/vendors", { name: label("Sample Networks") })).hid;
  const entry = (
    await make(request, headers, "/catalog-entries", {
      vendor_hid: vendor,
      pid: `SN-48P-${id}`,
      model_name: label("Edge Switch"),
      type: "switch",
    })
  ).hid;
  const item = async (data: Record<string, unknown>) =>
    (await make(request, headers, "/items", { catalog_entry_hid: entry, ...data })).hid;
  const inService = { lifecycle_state: "Prod", disposition: "Production", expected_online: true };
  const memberHids = [];
  for (const one of members) memberHids.push(await item({ serial_number: one, ...inService }));
  const stray = await item({ serial_number: strayMember, ...inService });
  for (const one of spares) {
    await item({
      hostname: one,
      fqdn: `${one}.example.net`,
      serial_number: serial(`SP${one.slice(-2)}`),
      location_hid: depotHid,
      lifecycle_state: "Prod",
      disposition: "Spare",
      expected_online: false,
    });
  }
  await item({ hostname: standalone, location_hid: roomHid, ...inService });
  made.stack = (
    await make(request, headers, "/device-groups", {
      name: stack,
      type: "stack",
      hostname: stack,
      fqdn: `${stack}.example.net`,
      location_hid: roomHid,
      members: memberHids.map((item_hid, index) => ({
        item_hid,
        role: "member",
        position: index + 1,
      })),
    })
  ).hid;
  made.other = (
    await make(request, headers, "/device-groups", {
      name: other,
      type: "stack",
      hostname: other,
      location_hid: roomHid,
      members: [{ item_hid: stray, role: "member", position: 1 }],
    })
  ).hid;
  await make(request, headers, "/addresses", {
    address: stackAddress,
    group_hid: made.stack,
    role: "management",
    is_primary: true,
  });
}

/** A request held back until it is let go, as a busy server answers late. */
async function holdBack(page: Page, url: string, method: string) {
  let release = () => {};
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  let asked = 0;
  await page.route(url, async (route) => {
    if (route.request().method() === method) {
      asked += 1;
      await held;
    }
    // A request the page has given up meanwhile, as a read replaced by a newer one, is gone.
    await route.continue().catch(() => {});
  });
  return {
    release,
    asked: () => asked,
    done: () => page.unroute(url),
  };
}

async function openStack(page: Page, name: string) {
  await page.goto(`./groups?filter=${encodeURIComponent(`name:eq:${name}`)}`);
  await page.getByTestId("grid-device-groups").getByRole("link", { name, exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
}

async function openItem(page: Page, name: string) {
  await page.goto(`./items?filter=${encodeURIComponent(name)}`);
  await page.getByTestId("grid-items").getByRole("link", { name, exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
}

function offers(page: Page): Locator {
  return page.getByRole("list", { name: "Items that match" }).locator("li");
}

test("the picker of members says where each switch stands, the spares first, and one in another stack cannot be chosen (P-221)", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(120_000);
  await records(request, account);
  const seen = await watch(page.context());
  await signIn(page, account);
  await openStack(page, stack);
  await page.getByRole("button", { name: "Add members" }).click();
  const form = page.getByRole("region", { name: "Add members" });

  // The spares first, though by name the members come before them, each with its state,
  // disposition and place; asked while the server is busy, the offers come when it answers.
  const held = await holdBack(page, "**/api/v1/items/query", "POST");
  // The random part of the mark is in the host names and in the serial numbers.
  await form.getByLabel("Find an item to add", { exact: true }).fill(id.slice(-6));
  await expect.poll(held.asked).toBeGreaterThan(0);
  held.release();
  await held.done();
  await expect(offers(page).first()).toContainText(spares[0] ?? "");
  await expect(offers(page).nth(1)).toContainText(spares[1] ?? "");
  await expect(offers(page).first()).toContainText(`Prod · Spare · ${site} > ${depot}`);

  // The member of the other stack is shown, says which stack and position, and cannot be
  // chosen, with why. The members of this stack are not offered at all.
  const stray = offers(page).filter({ hasText: strayMember });
  await expect(stray).toContainText(`member 1 of the stack ${other}`);
  await expect(stray).toContainText(
    `It is in the stack ${other} already: an item is in one stack at a time.`,
  );
  await expect(stray.getByRole("button")).toBeDisabled();
  await expect(offers(page).filter({ hasText: members[0] ?? "" })).toHaveCount(0);

  // A spare is chosen as before.
  await offers(page).first().getByRole("button").click();
  await expect(page.getByTestId("pending-members")).toContainText(spares[0] ?? "");
  await form.getByRole("button", { name: "Cancel" }).click();
  await expectClean(page, seen);
});

test("a stack is found by its name in Find an item, which names it above the rows, and by a member's serial number in the list of groups (P-220)", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(120_000);
  await records(request, account);
  const seen = await watch(page.context());
  await signIn(page, account);

  // The line that names the stack comes late, beside the heading: the rows do not move.
  const held = await holdBack(page, "**/api/v1/device-groups/query", "POST");
  const find = page.getByRole("search", { name: "Find an item" });
  await find.getByRole("searchbox").fill(stack);
  await find.getByRole("button", { name: "Find" }).click();
  const grid = page.getByTestId("grid-items");
  await expect(page.getByTestId("grid-total")).toHaveText("2 items");
  await expect.poll(held.asked).toBeGreaterThan(0);
  const before = await grid.boundingBox();
  await expect(page.getByTestId("groups-named")).toHaveText("");
  held.release();
  await held.done();
  const named = page.getByTestId("groups-named");
  await expect(named).toHaveText(`The words name the stack ${stack}, with 2 members.`);
  expect((await grid.boundingBox())?.y, "the rows stay where they were").toBe(before?.y);

  // Each member's row says its stack and position, in view from the start.
  const row = grid.locator(".ag-row").filter({ hasText: members[1] ?? "" });
  const cell = row.locator('[col-id="stack"]');
  await expect(cell).toHaveText(`${stack} #2`);
  const box = await cell.boundingBox();
  expect((box?.x ?? 0) + (box?.width ?? 0), "the stack is in view at 1280").toBeLessThanOrEqual(
    1280,
  );

  // The link opens the stack.
  await named.getByRole("link", { name: stack }).click();
  await expect(page.getByRole("heading", { level: 1, name: stack })).toBeVisible();

  // The list of groups finds the stack by a member's serial number.
  await page.goto("./groups");
  const filter = page.getByLabel("Filter", { exact: true });
  await filter.fill(members[1] ?? "");
  await filter.press("Enter");
  await expect(page.getByTestId("grid-total")).toHaveText("1 group");
  await expect(
    page.getByTestId("grid-device-groups").getByRole("link", { name: stack, exact: true }),
  ).toBeVisible();
  await expectClean(page, seen);
});

test("a member's page says it is member 2 of its stack with the stack's names, and a spare joins a stack from its own page (P-222)", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(120_000);
  await records(request, account);
  const seen = await watch(page.context());
  await signIn(page, account);

  await openItem(page, members[1] ?? "");
  await expect(page.getByTestId("stack-member")).toHaveText(`Member 2 of ${stack}`);
  await expect(page.getByTestId("stack-hostname")).toContainText(`${stack} · the stack's`);
  await expect(page.getByTestId("stack-fqdn")).toHaveText(`${stack}.example.net`);
  await expect(page.getByTestId("stack-addresses")).toContainText(stackAddress);
  await page.getByTestId("stack-member").getByRole("link", { name: stack }).click();
  await expect(page.getByRole("heading", { level: 1, name: stack })).toBeVisible();

  // A spare in no stack joins one from its own page: the stack searched by its name, the
  // next position offered.
  const spare = spares[1] ?? "";
  await openItem(page, spare);
  const fact = page.getByTestId("stack-member");
  await fact.getByRole("button", { name: "Join a stack" }).click();
  const form = page.getByRole("region", { name: "Join a stack" });
  await form.getByLabel("Stack", { exact: true }).fill(stack);
  await form
    .getByRole("list", { name: "Stacks that match" })
    .getByRole("button", { name: stack })
    .click();
  await expect(form.getByLabel("Position")).toHaveValue("3");
  await form.getByRole("button", { name: "Join the stack" }).click();
  await expect(page.getByText(`${spare} joined the stack ${stack} as member 3.`)).toBeInViewport();
  await expect(fact).toHaveText(`Member 3 of ${stack}`);
  await expectClean(page, seen);
});
