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
import { answer, queried } from "./answers";
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
// A spare that joins a stack drops its host name: it is found by its serial number then.
const spareSerials = spares.map((one) => serial(`SP${one.slice(-2)}`));
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
      serial_number: spareSerials[spares.indexOf(one)],
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

/** A stack's page, from the list of groups, once the server has answered with the stack. */
async function openStack(page: Page, name: string) {
  await page.goto(`./groups?filter=${encodeURIComponent(`name:eq:${name}`)}`);
  const opened = answer(page, "GET", /\/api\/v1\/device-groups\/[^/]+$/);
  await page.getByTestId("grid-device-groups").getByRole("link", { name, exact: true }).click();
  await opened;
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
}

/** An item's page, from the list of items, once the server has answered with the item. */
async function openItem(page: Page, name: string) {
  await page.goto(`./items?filter=${encodeURIComponent(name)}`);
  const opened = answer(page, "GET", /\/api\/v1\/items\/[^/]+$/);
  await page.getByTestId("grid-items").getByRole("link", { name, exact: true }).click();
  await opened;
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
}

/** End a membership in the form of End, once the server has answered that it is ended. */
async function endMembership(page: Page, ending: Locator) {
  const ended = answer(page, "PATCH", /\/api\/v1\/device-groups\/[^/]+\/members\/[^/]+$/);
  await ending.getByRole("button", { name: "End membership" }).click();
  expect((await ended).status(), "the membership is ended").toBe(200);
}

/** Add the members of the form of Add members, and wait for the server's answer. */
async function addMember(page: Page, form: Locator, status: number) {
  const added = answer(page, "POST", `/device-groups/${made.stack}/members`);
  await form.getByRole("button", { name: "Add member" }).click();
  expect((await added).status(), "the server's answer to the members added").toBe(status);
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
  const offered = queried(page, "/items/query", id.slice(-6));
  held.release();
  await offered;
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
  const listed = queried(page, "/items/query", stack);
  await find.getByRole("button", { name: "Find" }).click();
  const grid = page.getByTestId("grid-items");
  await listed;
  await expect(page.getByTestId("grid-total")).toHaveText("2 items");
  await expect.poll(held.asked).toBeGreaterThan(0);
  const before = await grid.boundingBox();
  await expect(page.getByTestId("groups-named")).toHaveText("");
  // Let go, the stack is looked for by the server, as late as a busy one answers.
  const looked = queried(page, "/device-groups/query", stack);
  held.release();
  await looked;
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
  const opened = answer(page, "GET", `/device-groups/${made.stack}`);
  await named.getByRole("link", { name: stack }).click();
  await opened;
  await expect(page.getByRole("heading", { level: 1, name: stack })).toBeVisible();

  // The list of groups finds the stack by a member's serial number.
  await page.goto("./groups");
  const filter = page.getByLabel("Filter", { exact: true });
  await filter.fill(members[1] ?? "");
  const bySerial = queried(page, "/device-groups/query", members[1] ?? "");
  await filter.press("Enter");
  await bySerial;
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

  // The member's page reads its stack, for what it says of it.
  const stackRead = () => answer(page, "GET", `/device-groups/${made.stack}`);
  const ofStack = stackRead();
  await openItem(page, members[1] ?? "");
  await ofStack;
  await expect(page.getByTestId("stack-member")).toHaveText(`Member 2 of ${stack}`);
  await expect(page.getByTestId("stack-hostname")).toContainText(`${stack} · the stack's`);
  await expect(page.getByTestId("stack-fqdn")).toHaveText(`${stack}.example.net`);
  await expect(page.getByTestId("stack-addresses")).toContainText(stackAddress);
  const stackOpened = stackRead();
  await page.getByTestId("stack-member").getByRole("link", { name: stack }).click();
  await stackOpened;
  await expect(page.getByRole("heading", { level: 1, name: stack })).toBeVisible();

  // A spare in no stack joins one from its own page: the stack searched by its name, the
  // next position offered.
  const spare = spares[1] ?? "";
  await openItem(page, spare);
  const fact = page.getByTestId("stack-member");
  await fact.getByRole("button", { name: "Join a stack" }).click();
  const form = page.getByRole("region", { name: "Join a stack" });
  await form.getByLabel("Stack", { exact: true }).fill(stack);
  const toJoin = stackRead();
  await form
    .getByRole("list", { name: "Stacks that match" })
    .getByRole("button", { name: stack })
    .click();
  await toJoin;
  await expect(form.getByLabel("Position", { exact: true })).toHaveValue("3");
  // The box of the stack's name and place is there, ticked, as on the stack's page (P-217).
  await expect(form.getByLabel("It takes the stack's name and place")).toBeChecked();
  // Joined: the item is read again, and the stack it is a member of now.
  const joined = answer(page, "POST", `/device-groups/${made.stack}/members`);
  const itemAgain = answer(page, "GET", /\/api\/v1\/items\/[^/]+$/);
  const memberOf = stackRead();
  await form.getByRole("button", { name: "Join the stack" }).click();
  expect((await joined).status(), "the spare joins the stack").toBe(201);
  await Promise.all([itemAgain, memberOf]);
  await expect(page.getByText(`${spare} was added to ${stack} as member 3.`)).toBeInViewport();
  await expect(fact).toHaveText(`Member 3 of ${stack}`);
  await expectClean(page, seen);
});

test("a failed member is replaced from the stack's page: End, to be returned to its maker, then Add, the freed position offered, and the spare takes the stack's name and place (P-217 to P-219)", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(150_000);
  await records(request, account);
  const seen = await watch(page.context());
  await signIn(page, account);
  await openStack(page, stack);
  const failed = members[1] ?? "";
  const table = page.getByTestId("members");

  // End, with what becomes of it: to be returned to the manufacturer, which fills the
  // move to Pending-Removal for the reason RMA, not expected online.
  await table
    .locator("tbody tr", { hasText: failed })
    .getByRole("button", { name: `End the membership of ${failed}` })
    .click();
  const ending = page.getByRole("region", { name: `End the membership of ${failed}` });
  const what = ending.getByRole("group", { name: "What becomes of it" });
  await expect(what.getByLabel("Nothing now")).toBeChecked();
  await what.getByLabel("To be returned to the manufacturer").check();
  await expect(what.getByLabel("Lifecycle state")).toHaveValue("Pending-Removal");
  await expect(what.getByLabel("Reason")).toHaveValue("rma");
  await expect(what.getByLabel("Expected online")).toHaveValue("false");
  await endMembership(page, ending);
  const said = page.locator(".alert-ok");
  await expect(said).toContainText(`The membership of ${failed} ended on`);
  await expect(said).toContainText("moved to Pending-Removal");
  await expect(said.getByRole("link", { name: failed })).toBeVisible();
  // The ended row stays in view, marked ended.
  const gone = table.locator("tbody tr", { hasText: failed });
  await expect(gone).toHaveAttribute("data-current", "false");
  await expect(gone).toContainText("Ended");

  // Add: the spare, the freed position offered, the box ticked with what it removes.
  await page.getByRole("button", { name: "Add members" }).click();
  const form = page.getByRole("region", { name: "Add members" });
  const spare = spares[0] ?? "";
  await form.getByLabel("Find an item to add", { exact: true }).fill(spare);
  await form
    .getByRole("list", { name: "Items that match" })
    .getByRole("button", { name: new RegExp(`^${spare}`) })
    .click();
  await expect(form.getByLabel(`Position of ${spare}`)).toHaveValue("2");
  const box = form.getByRole("group", { name: spare });
  await expect(box.getByLabel("It takes the stack's name and place")).toBeChecked();
  await expect(box.getByTestId("drops")).toHaveText(
    `Removed from ${spare}: the host name ${spare}, the FQDN ${spare}.example.net and its own location ${label("Campus Works")} > ${site} > ${depot}. The stack's are in force for it.`,
  );
  await expect(box.getByLabel("Disposition")).toHaveValue("Production");
  await expect(box.getByLabel("Expected online")).toHaveValue("true");
  await addMember(page, form, 201);
  await expect(said).toContainText(
    `${spare} was added to ${stack} as member 2. It takes the stack's name and place:`,
  );
  await expect(said).toBeInViewport();

  // What the server did: the failed switch is to go back; the spare has the stack's names.
  await openItem(page, failed);
  await expect(page.getByTestId("standing-fact")).toContainText("Pending-Removal");
  const ofStack = answer(page, "GET", `/device-groups/${made.stack}`);
  await openItem(page, spareSerials[0] ?? "");
  await ofStack;
  await expect(page.getByTestId("stack-member")).toHaveText(`Member 2 of ${stack}`);
  await expect(page.getByTestId("stack-hostname")).toContainText(stack);
  await expect(page.getByTestId("standing-fact")).toContainText("Production");
  await expect(page.getByTestId("location")).toHaveAttribute("data-source", "device_group");
  await expectClean(page, seen);
});

test("a position that a current member holds is refused beside its row, naming that member (P-219)", async ({
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
  await form.getByLabel("Find an item to add", { exact: true }).fill(standalone);
  await form
    .getByRole("list", { name: "Items that match" })
    .getByRole("button", { name: new RegExp(`^${standalone}`) })
    .click();
  await form.getByLabel(`Position of ${standalone}`).fill("1");
  await form
    .getByRole("group", { name: standalone })
    .getByLabel("It takes the stack's name and place")
    .uncheck();
  await expect(form.getByRole("group", { name: standalone }).getByTestId("drops")).toHaveText(
    `${standalone} keeps its own name, addresses and place: nothing of it is changed.`,
  );
  await addMember(page, form, 409);
  const refused = form.getByTestId("member-error");
  await expect(refused).toBeVisible();
  await expect(refused.getByRole("link", { name: members[0] ?? "" })).toBeVisible();
  await form.getByRole("button", { name: "Cancel" }).click();
  await expectClean(page, seen, ["409 POST"]);
});

test("a member leaves a stack to the spare pool with a new name and a place, in the one form of End (P-218)", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(120_000);
  await records(request, account);
  const seen = await watch(page.context());
  await signIn(page, account);
  await openStack(page, stack);
  // The spare that joined from its own page, member 3, which has no name of its own now.
  const leaving = spareSerials[1] ?? "";
  const pooled = host("spare-sw-91");
  await page
    .getByTestId("members")
    .locator("tbody tr", { hasText: leaving })
    .getByRole("button", { name: `End the membership of ${leaving}` })
    .click();
  const ending = page.getByRole("region", { name: `End the membership of ${leaving}` });
  const what = ending.getByRole("group", { name: "What becomes of it" });
  // What the form shows is what is sent: Excess is of the state it moves to, and is
  // not kept, out of sight, once the state is put back as it is.
  await what.getByLabel("Excess").check();
  await expect(what.getByLabel("Lifecycle state")).toHaveValue("Pending-Removal");
  await expect(what.getByLabel("Disposition")).toHaveValue("Excess");
  await what.getByLabel("Lifecycle state").selectOption("");
  await expect(what.getByLabel("Disposition")).toHaveValue("");
  await what.getByLabel("To the spare pool").check();
  // A spare with no name and no place is said to be so, before it is sent.
  await expect(what).toContainText("Left blank, it has no name");
  await expect(what).toContainText("Left as it is, it is nowhere");
  await expect(what.getByLabel("Disposition")).toHaveValue("Spare");
  await expect(what.getByLabel("Expected online")).toHaveValue("false");
  await expect(what.getByLabel("Lifecycle state")).toHaveValue("");
  await what.getByLabel("Hostname").fill(pooled);
  await what.getByLabel("FQDN").fill(`${pooled}.example.net`);
  await what.getByLabel("Location").fill(depot);
  await what
    .getByRole("button", { name: new RegExp(depot) })
    .first()
    .click();
  await endMembership(page, ending);
  const said = page.locator(".alert-ok");
  await expect(said).toContainText(`named ${pooled}`);
  const opened = answer(page, "GET", /\/api\/v1\/items\/[^/]+$/);
  await said.getByRole("link", { name: pooled }).click();
  await opened;
  await expect(page.getByRole("heading", { level: 1, name: pooled })).toBeVisible();
  await expect(page.getByTestId("standing-fact")).toContainText("Spare");
  await expect(page.getByTestId("location")).toContainText(depot);
  await expect(page.getByTestId("stack-member")).toContainText("In no stack");
  await expectClean(page, seen);
});
