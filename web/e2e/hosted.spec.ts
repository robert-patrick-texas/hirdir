// The browser scenarios of 0.9.8, lane W3, P-250 and P-249: a thing that runs on another,
// on the pages. A virtual machine entered with no host is marked to be looked at; given a
// server as its host it shows the server's site and room, as from its host; the server's
// page lists what runs on it, and what runs on that beneath it; the item list shows Runs
// on and To be looked at as columns to turn on; and twelve virtual machines are moved to a
// cluster by one bulk edit.
//
// The file keeps the rules of support.ts. It signs in as an Admin of its own, and its mark
// is in every name it gives a record: the region, the site, the room, the vendor, the
// models, the server, the cluster and the virtual machines, made through the API as that
// Admin or through the forms the scenarios walk. It changes no setting, no list of
// choices, no lifecycle rule and no account but its own, and reads only its own records,
// the lists filtered down to them. The scenarios run in order, on what the first makes.

import type { APIRequestContext, Locator, Page } from "@playwright/test";
import { expect } from "@playwright/test";
import { whenApplied } from "./structure";
import { type Account, expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const id = mark("hosted");
const label = (name: string) => `${name} ${id}`;
/** A host name of this file, which begins with its mark. */
const host = (name: string) => `${id}-${name}`;
const net = `2001:db8:5${id.slice(-3)}`;

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
): Promise<{ hid: string }> {
  const answer = await request.post(`./api/v1${path}`, { headers, data });
  expect(answer.status(), `post ${path}: ${await answer.text()}`).toBe(201);
  return (await answer.json()) as { hid: string };
}

const site = label("Site 2");
const room = label("Room 102");
const vmPid = `VM-${id}`;
const server = host("esx-01");
const gone = host("esx-old");
const cluster = host("esx-cluster");
const app = host("vm-app01");
/** The eleven virtual machines the API puts on the server beside the one the form makes. */
const others = Array.from({ length: 11 }, (_, n) => host(`vm-${String(n + 2).padStart(2, "0")}`));
const container = host("ctr-dns1");
const orphan = host("vm-orphan");
const legacy = host("vm-legacy");
const second = host("esx-02");
// 0.9.8: a stack of two switches, and what runs on one (P-252).
const stack = host("stk-1");
const switches = [host("sw-01"), host("sw-02")];
const onStack = host("ctr-app");
// 0.9.8: a virtual context reported before its switch, which has its serial number (P-251).
const vdcPid = `VDC-${id}`;
const context = host("n7k-01-vdc2");
const chassis = host("n7k-01");
const chassisSerial = `N7K${id.slice(-6).toUpperCase()}`;

const made: {
  server?: string;
  second?: string;
  cluster?: string;
  stack?: string;
  vdc?: string;
  box?: string;
  ctrPid?: string;
} = {};

async function records(request: APIRequestContext, account: Account): Promise<void> {
  if (made.server !== undefined) return;
  const headers = await session(request, account);
  const region = (await make(request, headers, "/regions", { name: label("Region") })).hid;
  const siteHid = (
    await make(request, headers, "/sites", { name: site, code: `S2-${id}`, region_hid: region })
  ).hid;
  const roomHid = (await make(request, headers, "/locations", { name: room, site_hid: siteHid }))
    .hid;
  const vendor = (await make(request, headers, "/vendors", { name: label("Example Virtual") })).hid;
  const vm = (
    await make(request, headers, "/catalog-entries", {
      vendor_hid: vendor,
      pid: vmPid,
      model_name: label("Virtual machine"),
      kind: "virtual_machine",
    })
  ).hid;
  const ctr = (
    await make(request, headers, "/catalog-entries", {
      vendor_hid: vendor,
      pid: `CTR-${id}`,
      kind: "container",
    })
  ).hid;
  const box = (
    await make(request, headers, "/catalog-entries", {
      vendor_hid: vendor,
      pid: `SRV-${id}`,
      model_name: label("Example Server"),
    })
  ).hid;
  made.server = (
    await make(request, headers, "/items", {
      catalog_entry_hid: box,
      hostname: server,
      serial_number: `SRV${id.slice(-6).toUpperCase()}`,
      location_hid: roomHid,
      lifecycle_state: "Prod",
    })
  ).hid;
  // A server out of the team's hands, which hosts nothing more.
  await make(request, headers, "/items", {
    catalog_entry_hid: box,
    hostname: gone,
    location_hid: roomHid,
    lifecycle_state: "Released",
  });
  // A machine entered, as before 0.9.8, as installed in its server, a second one.
  made.second = (
    await make(request, headers, "/items", {
      catalog_entry_hid: box,
      hostname: second,
      location_hid: roomHid,
      lifecycle_state: "Prod",
    })
  ).hid;
  await make(request, headers, "/items", {
    catalog_entry_hid: vm,
    hostname: legacy,
    parent_item_hid: made.second,
  });
  // A machine that names no host, to be looked at.
  await make(request, headers, "/items", { catalog_entry_hid: vm, hostname: orphan });
  // A stack of two switches.
  const members: string[] = [];
  for (const name of switches) {
    members.push(
      (
        await make(request, headers, "/items", {
          catalog_entry_hid: box,
          hostname: name,
          location_hid: roomHid,
          lifecycle_state: "Prod",
        })
      ).hid,
    );
  }
  made.stack = (
    await make(request, headers, "/device-groups", {
      type: "stack",
      name: stack,
      location_hid: roomHid,
      members: members.map((hid, index) => ({
        item_hid: hid,
        role: "member",
        position: index + 1,
      })),
    })
  ).hid;
  // A model of virtual contexts, and one context reported with its switch's serial number.
  const vdc = (
    await make(request, headers, "/catalog-entries", {
      vendor_hid: vendor,
      pid: vdcPid,
      kind: "virtual_context",
    })
  ).hid;
  made.vdc = (
    await make(request, headers, "/items", {
      catalog_entry_hid: vdc,
      hostname: context,
      serial_number: chassisSerial,
    })
  ).hid;
  made.box = box;
  made.ctrPid = `CTR-${id}`;
  made.cluster = (
    await make(request, headers, "/device-groups", {
      type: "cluster",
      name: cluster,
      location_hid: roomHid,
    })
  ).hid;
  for (const [index, name] of others.entries()) {
    const vmHid = (
      await make(request, headers, "/items", {
        catalog_entry_hid: vm,
        hostname: name,
        host_item_hid: made.server,
        lifecycle_state: "Prod",
      })
    ).hid;
    await make(request, headers, "/addresses", {
      address: `${net}::${index + 10}`,
      item_hid: vmHid,
      role: "management",
      is_primary: true,
    });
    // A container runs on the first of them.
    if (index === 0) {
      await make(request, headers, "/items", {
        catalog_entry_hid: ctr,
        hostname: container,
        host_item_hid: vmHid,
      });
    }
  }
}

function region(page: Page, name: string): Locator {
  return page.getByRole("region", { name, exact: true });
}

async function openItem(page: Page, name: string) {
  await page.goto(`./items?filter=${encodeURIComponent(`hostname:eq:${name}`)}`);
  await page.getByTestId("grid-items").getByRole("link", { name, exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
}

/** Choose a record a field of a form searches for, by what is typed and the start of its offer. */
async function choose(within: Locator, field: string, typed: string, offer: string, list: string) {
  await within.getByLabel(field, { exact: true }).fill(typed);
  await within
    .getByRole("list", { name: list })
    .getByRole("button", { name: new RegExp(`^${offer.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")} ·`) })
    .click();
}

test("a virtual machine entered with no host is marked, and given a server as its host it is where the server is", async ({
  page,
  request,
  account,
}) => {
  test.setTimeout(180_000);
  await records(request, account);
  const seen = await watch(page.context());
  await signIn(page, account);

  // New item: the model is of a kind that runs on a host, and the form asks for one.
  await page.goto("./items");
  await page.getByRole("button", { name: "New item" }).click();
  const form = region(page, "New item");
  await expect(form.getByLabel("Host", { exact: true })).toHaveCount(0);
  await choose(form, "Catalog entry", vmPid, vmPid, "Catalog entries that match");
  await expect(form.getByLabel("Host", { exact: true })).toBeVisible();
  await form.getByLabel("Hostname").fill(app);
  await form.getByRole("button", { name: "Create item" }).click();
  await expect(page.getByRole("heading", { level: 1, name: app })).toBeVisible();

  // It names no host: it says so, marked to be looked at, with the way to name one.
  const runsOn = page.getByTestId("runs-on");
  await expect(runsOn).toHaveAttribute("data-review", "no_host");
  await expect(runsOn).toContainText("It names no host.");
  await expect(runsOn).toContainText("To be looked at");

  // Name its host: the keyboard goes to Host in Details. A server out of the team's
  // hands is refused, at Host, and what else was typed stays.
  await runsOn.getByRole("button", { name: "Name its host" }).click();
  const details = region(page, "Details");
  await expect(details.getByLabel("Host", { exact: true })).toBeFocused();
  await choose(details, "Host", gone, gone, "Hosts that match");
  await details.getByLabel("Comments").fill(`Built for ${id}`);
  await details.getByRole("button", { name: "Save", exact: true }).click();
  const hostField = details.locator('[data-field="host_hid"]');
  await expect(hostField.locator(".field-error")).toBeVisible();
  await expect(details.getByLabel("Comments")).toHaveValue(`Built for ${id}`);

  // The server, and the item it was seen on, whose moment is filled with now.
  await choose(details, "Host", server, server, "Hosts that match");
  await expect(details.getByTestId("chosen-host_hid")).toContainText("an item");
  await choose(details, "Seen on", server, server, "Items that match");
  await expect(details.getByLabel("Seen at", { exact: true })).not.toHaveValue("");
  await details.getByRole("button", { name: "Save", exact: true }).click();

  // It runs on the server, as a link, and is where the server is, as from its host.
  await expect(runsOn.getByRole("link", { name: server, exact: true })).toBeVisible();
  await expect(runsOn).not.toHaveAttribute("data-review", /./);
  await expect(page.getByTestId("seen-on")).toContainText(server);
  await expect(page.getByTestId("host-differs")).toHaveCount(0);
  const location = page.getByTestId("location");
  await expect(location).toHaveAttribute("data-source", "host");
  await expect(location).toContainText(room);
  await expect(location.getByRole("link", { name: `the host ${server}` })).toHaveAttribute(
    "href",
    new RegExp(`/items/${made.server}$`),
  );
  await expect(page.getByTestId("site")).toHaveText(site);

  await expectClean(page, seen, ["422 PATCH"]);
});

test("a machine entered as installed in its server is made to run on it in one press", async ({
  page,
  request,
  account,
}) => {
  test.setTimeout(120_000);
  await records(request, account);
  const seen = await watch(page.context());
  await signIn(page, account);
  // A minor item, so the list is asked for minor items too.
  await page.goto(`./items?filter=${encodeURIComponent(`hostname:eq:${legacy}`)}&minor=1`);
  await page.getByTestId("grid-items").getByRole("link", { name: legacy, exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: legacy })).toBeVisible();
  const runsOn = page.getByTestId("runs-on");
  await expect(runsOn).toHaveAttribute("data-review", "no_host");
  const installed = runsOn.getByTestId("installed-in");
  await expect(installed.getByRole("link", { name: second, exact: true })).toHaveAttribute(
    "href",
    new RegExp(`/items/${made.second}$`),
  );
  await installed.getByRole("button", { name: `Make ${second} its host` }).click();
  await expect(runsOn.getByTestId("host-link")).toHaveText(second);
  await expect(runsOn).not.toHaveAttribute("data-review", /./);
  await expect(page.getByTestId("installed-in")).toHaveCount(0);
  await expect(page.getByTestId("location")).toHaveAttribute("data-source", "host");

  await expectClean(page, seen);
});

test("the server's page lists what runs on it, and what runs on that beneath it", async ({
  page,
  request,
  account,
}) => {
  test.setTimeout(120_000);
  await records(request, account);
  const seen = await watch(page.context());
  await signIn(page, account);
  // The list comes late: the page stands, and fills it when it comes.
  await page.route("**/api/v1/items/*/hosted*", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 1500));
    await route.continue();
  });
  await openItem(page, server);
  const hosted = region(page, "What runs on it (12)");
  await expect(hosted).toBeVisible();
  // The way to the list of them is there before the list has come.
  await expect(hosted.getByTestId("hosted-in-list")).toHaveAttribute(
    "href",
    new RegExp(`host_item_hid%3Aeq%3A${made.server}`),
  );
  const list = hosted.getByTestId("hosted-list");
  await expect(list.locator("tbody tr")).toHaveCount(13, { timeout: 15_000 });
  const vm = list.locator("tbody tr", { hasText: others[0] ?? "" });
  await expect(vm).toHaveAttribute("data-depth", "1");
  await expect(vm.getByRole("link", { name: others[0] ?? "" })).toBeVisible();
  await expect(vm).toContainText("Virtual machine");
  await expect(vm).toContainText("Prod");
  await expect(vm).toContainText(`${net}::10`);
  const inner = list.locator("tbody tr", { hasText: container });
  await expect(inner).toHaveAttribute("data-depth", "2");
  await expect(inner).toContainText("Container");
  // A server nothing runs on shows nothing of it; nor does a machine with nothing on it.
  await openItem(page, app);
  await expect(page.getByTestId("hosted")).toHaveCount(0);

  await expectClean(page, seen);
});

test("the item list shows Runs on and To be looked at, and finds the items of a host", async ({
  page,
  request,
  account,
}) => {
  test.setTimeout(120_000);
  await records(request, account);
  const seen = await watch(page.context());
  await signIn(page, account);
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto(`./items?filter=${encodeURIComponent(`host.name:eq:${server}`)}`);
  await expect(page.getByTestId("grid-total")).toHaveText("12 items");
  await page.getByText("Columns", { exact: true }).click();
  const columns = page.getByRole("group", { name: "Columns to show" });
  await columns.getByLabel("Runs on", { exact: true }).check();
  await columns.getByLabel("To be looked at", { exact: true }).check();
  await page.getByText("Columns", { exact: true }).click();
  const grid = page.getByTestId("grid-items");
  // Turned on, the two stand after the place: the columns the owner asked to see in a
  // window 1280 pixels wide are still all in view (P-193).
  for (const column of [
    "name",
    "catalog.pid",
    "serial_number",
    "lifecycle_state",
    "health",
    "location.name",
    "site",
  ]) {
    await expect(
      grid.locator(`[role="columnheader"][col-id="${column}"]`),
      `${column} is in view at 1280`,
    ).toBeInViewport({ ratio: 1 });
  }
  const row = grid.locator("[row-id]", { hasText: app });
  await expect(
    row.locator('[col-id="host.name"]').getByRole("link", { name: server }),
  ).toHaveAttribute("href", new RegExp(`/items/${made.server}$`));
  // What names no host is found by its reason, and says it in words.
  await page.goto(
    `./items?filter=${encodeURIComponent(`hostname:prefix:${id}-vm review:eq:no_host`)}`,
  );
  await expect(page.getByTestId("grid-total")).toHaveText("1 item");
  await expect(
    grid.locator("[row-id]", { hasText: orphan }).locator('[col-id="review"]'),
  ).toHaveText("Names no host");

  await expectClean(page, seen);
});

test("twelve virtual machines are moved to a cluster by one bulk edit", async ({
  page,
  request,
  account,
}) => {
  test.setTimeout(180_000);
  await records(request, account);
  const seen = await watch(page.context());
  await signIn(page, account);
  // The task, from the server's page, counted in the report: a press on the way to the
  // list of what runs on it, and on from there.
  await openItem(page, server);
  await page.getByTestId("hosted-in-list").click();
  await expect(page.getByTestId("grid-total")).toHaveText("12 items");
  await page.getByRole("button", { name: "Select all that match" }).click();
  await page.getByRole("button", { name: "Bulk edit" }).click();
  const bulk = page.getByTestId("bulk-edit");
  await bulk.getByLabel("Field to change").selectOption({ label: "Host" });
  await bulk.getByRole("button", { name: "Add", exact: true }).click();
  const line = bulk.getByRole("group", { name: "Host" });
  await choose(line, "Set to", cluster, cluster, "Hosts that match");
  await expect(line.getByTestId("chosen-host")).toContainText("a cluster");
  await bulk.getByRole("button", { name: "Preview the change" }).click();
  await bulk.getByRole("button", { name: "Apply 12 items" }).click();
  await whenApplied(page, 12);

  // The cluster's page lists them, and the server's none.
  await page.goto(`./groups?filter=${encodeURIComponent(`name:eq:${cluster}`)}`);
  await page.getByTestId("grid-device-groups").getByRole("link", { name: cluster }).click();
  await expect(region(page, "What runs on it (12)")).toBeVisible();
  await openItem(page, server);
  await expect(page.getByTestId("hosted")).toHaveCount(0);
  // A machine has the cluster's room, as from the cluster: a group, whose page it links to.
  await openItem(page, app);
  await expect(page.getByTestId("runs-on").getByRole("link", { name: cluster })).toBeVisible();
  const place = page.getByTestId("location");
  await expect(place).toHaveAttribute("data-source", "device_group");
  await expect(place.getByRole("link", { name: `the group ${cluster}` })).toHaveAttribute(
    "href",
    new RegExp(`/groups/${made.cluster}$`),
  );

  await expectClean(page, seen);
});

test("a container given a member of a stack as its host runs on the stack, and was seen on the member (P-252)", async ({
  page,
  request,
  account,
}) => {
  test.setTimeout(120_000);
  await records(request, account);
  const seen = await watch(page.context());
  await signIn(page, account);
  await page.goto("./items");
  await page.getByRole("button", { name: "New item" }).click();
  const form = region(page, "New item");
  await choose(
    form,
    "Catalog entry",
    made.ctrPid ?? "",
    made.ctrPid ?? "",
    "Catalog entries that match",
  );
  await form.getByLabel("Hostname").fill(onStack);
  // The member says it is in the stack, and that it names the stack; the stack is offered beside it.
  const member = switches[1] ?? "";
  await form.getByLabel("Host", { exact: true }).fill(member);
  const offers = form.getByRole("list", { name: "Hosts that match" });
  await expect(offers.getByRole("button", { name: `${stack} · a stack` })).toBeVisible();
  const line = offers.getByRole("button", { name: new RegExp(`^${member} ·`) });
  await expect(line).toContainText(`in the stack ${stack}, position 2: names the stack ${stack}`);
  await line.click();
  await form.getByRole("button", { name: "Create item" }).click();
  await expect(page.getByRole("heading", { level: 1, name: onStack })).toBeVisible();
  // The answer says the stack is the host, and the member what it was seen on.
  const runsOn = page.getByTestId("runs-on");
  await expect(runsOn.getByTestId("host-link")).toHaveText(stack);
  await expect(runsOn.getByTestId("host-link")).toHaveAttribute(
    "href",
    new RegExp(`/groups/${made.stack}$`),
  );
  await expect(page.getByTestId("seen-on")).toContainText(member);
  await expect(page.getByTestId("host-differs")).toHaveCount(0);

  await expectClean(page, seen);
});

test("a virtual context reported before its switch is joined to it in one press, and shows its serial number as its host's (P-251)", async ({
  page,
  request,
  account,
}) => {
  test.setTimeout(120_000);
  await records(request, account);
  const headers = await session(request, account);
  const seen = await watch(page.context());
  await signIn(page, account);
  await openItem(page, context);
  const runsOn = page.getByTestId("runs-on");
  await expect(runsOn).toHaveAttribute("data-review", "no_host");
  // No item has its serial number yet.
  await expect(page.getByTestId("serial-of")).toHaveCount(0);

  // The switch is entered, and the context's page says it has that serial number.
  const switchHid = (
    await make(request, headers, "/items", {
      catalog_entry_hid: made.box,
      hostname: chassis,
      serial_number: chassisSerial,
      lifecycle_state: "Prod",
    })
  ).hid;
  await page.reload();
  const of = page.getByTestId("serial-of");
  await expect(of).toContainText(`${chassisSerial} is the serial number of ${chassis}`);
  await expect(of.getByRole("link", { name: chassis })).toHaveAttribute(
    "href",
    new RegExp(`/items/${switchHid}$`),
  );
  await of.getByRole("button", { name: "Make it its host" }).click();
  await expect(runsOn.getByTestId("host-link")).toHaveText(chassis);
  await expect(page.getByTestId("serial-from-host")).toContainText(chassisSerial);
  // It holds none of its own now.
  const now = (await (await request.get(`./api/v1/items/${made.vdc}`, { headers })).json()) as {
    serial_number: string | null;
  };
  expect(now.serial_number).toBeNull();
  // Its form shows the host's, not a box to type in.
  await expect(region(page, "Details").getByTestId("shown-serial_number")).toContainText(
    `${chassisSerial}, the serial number of its host`,
  );

  await expectClean(page, seen);
});
