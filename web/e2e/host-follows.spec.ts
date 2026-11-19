// The browser scenarios of 0.9.8, lane W4, P-247 to P-249: what follows from a host, and
// what a tool reports.
//
//   1. Retire on a server that something runs on names what goes with it, as links, and
//      how many, before it asks, on its page; for the rows ticked, with what the server's
//      dry run answers; and the message afterwards says both numbers.
//   2. A cluster that something runs on is not retired: its page and the rows ticked say
//      so with what runs on it, as links; and a deletion's refusal says that an item runs
//      on the server it is in the way of.
//   3. Replace asks whether what runs on the item that leaves goes to the new one: a box,
//      ticked, with the names beneath; unticked when an item that hosts nothing is chosen,
//      and the refusal said beside it when it is ticked all the same.
//   4. A tool's report: three machines loaded as read from Example vCenter, then a file
//      that names two of them and is everything it reports; the third is marked as not
//      reported and is not retired.
//   5. That registration reads Not reported, is marked as to be looked at on the item's
//      page with the two ways on, and is set back.
//   6. The first page counts what is to be looked at, as a link to the item list.
//
// A View-only account of the file's own sees each without the buttons that change it.
//
// The file keeps the rules of support.ts. It signs in as an Admin of its own, and its mark
// is in every name it gives a record: the vendor, the models, the servers, the cluster,
// the machines, the system and the files it imports, made through the API as that Admin
// or through the pages the scenarios walk. It changes no setting, no list of choices, no
// lifecycle rule and no account but its own, and reads only its own records, the lists
// filtered down to them. The count of the first page is of the whole inventory: it is
// looked at as a link and a number above none, never compared with a number. The
// scenarios run in order, on what the first makes.

import type { APIRequestContext, Browser, Locator, Page } from "@playwright/test";
import { expect } from "@playwright/test";
import { count, openGroup, openItem, whenApplied } from "./structure";
import { type Account, createAccount, expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const id = mark("host-follows");
const label = (name: string) => `${name} ${id}`;
/** A host name of this file, which begins with its mark. */
const host = (name: string) => `${id}-${name}`;

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
): Promise<string> {
  const answer = await request.post(`./api/v1${path}`, { headers, data });
  expect(answer.status(), `post ${path}: ${await answer.text()}`).toBe(201);
  return ((await answer.json()) as { hid: string }).hid;
}

const vendorName = label("Example Virtual");
const vmPid = `VM-${id}`;
const system = label("Example vCenter");

const esx = (n: number) => host(`esx-0${n}`);
const cluster = host("esx-cluster");
const lic = host("lic-01");
const orphan = host("vm-orphan");
const onFirst = [host("vm-a1"), host("vm-a2")];
const container = host("ctr-a1");
const onSecond = [host("vm-b1"), host("vm-b2")];
const onCluster = host("vm-c1");
const onFourth = host("vm-d1");
const onFifth = [host("vm-e1"), host("vm-e2"), host("vm-e3")];
const reported = [host("vm-r1"), host("vm-r2"), host("vm-r3")];
const onSeventh = Array.from({ length: 11 }, (_, n) =>
  host(`vm-g${String(n + 1).padStart(2, "0")}`),
);

const made: { hids: Record<string, string>; viewer?: Account; done: boolean } = {
  hids: {},
  done: false,
};

function hidOf(name: string): string {
  const hid = made.hids[name];
  expect(hid, `the record ${name} was made`).toBeDefined();
  return hid ?? "";
}

async function records(request: APIRequestContext, account: Account): Promise<void> {
  if (made.done) return;
  const headers = await session(request, account);
  const vendor = await make(request, headers, "/vendors", { name: vendorName });
  const model = (pid: string, kind?: string) =>
    make(request, headers, "/catalog-entries", {
      vendor_hid: vendor,
      pid,
      ...(kind ? { kind } : {}),
    });
  const server = await model(`SRV-${id}`);
  const vm = await model(vmPid, "virtual_machine");
  made.hids[vmPid] = vm;
  const ctr = await model(`CTR-${id}`, "container");
  const software = await model(`LIC-${id}`, "software");
  const item = async (name: string, entry: string, more: Record<string, unknown> = {}) => {
    made.hids[name] = await make(request, headers, "/items", {
      catalog_entry_hid: entry,
      hostname: name,
      ...more,
    });
    return made.hids[name] ?? "";
  };
  for (const n of [1, 2, 3, 4, 5, 6, 7]) await item(esx(n), server, { lifecycle_state: "Prod" });
  await item(lic, software);
  await item(orphan, vm);
  for (const name of onFirst) await item(name, vm, { host_item_hid: hidOf(esx(1)) });
  await item(container, ctr, { host_item_hid: hidOf(onFirst[0] ?? "") });
  for (const name of onSecond) await item(name, vm, { host_item_hid: hidOf(esx(2)) });
  made.hids[cluster] = await make(request, headers, "/device-groups", {
    type: "cluster",
    name: cluster,
  });
  await item(onCluster, vm, { host_group_hid: hidOf(cluster) });
  await item(onFourth, vm, { host_item_hid: hidOf(esx(4)) });
  for (const name of onFifth) await item(name, vm, { host_item_hid: hidOf(esx(5)) });
  // Eleven on the seventh: too many to name beneath the box of Replace.
  for (const name of onSeventh) await item(name, vm, { host_item_hid: hidOf(esx(7)) });
  made.hids[system] = await make(request, headers, "/external-systems", {
    name: system,
    kind: "other",
  });
  made.viewer = await createAccount(request, `e2e-${id}-viewer`, "viewer");
  made.done = true;
}

async function signInAs(browser: Browser, account: Account) {
  const context = await browser.newContext();
  const page = await context.newPage();
  const seen = await watch(context);
  await signIn(page, account);
  return { context, page, seen };
}

function gridRow(page: Page, grid: string, text: string): Locator {
  return page.getByTestId(grid).locator("[row-id]", {
    has: page.locator('[col-id="name"], [col-id="hostname"]').getByRole("link", {
      name: text,
      exact: true,
    }),
  });
}

function rowBox(page: Page, grid: string, text: string): Locator {
  return gridRow(page, grid, text).locator(".ag-selection-checkbox input");
}

/** A link of the app, matched by the end of its address: the app may be under a prefix. */
function linkTo(scope: Locator, name: string, hid: string): Locator {
  return scope.locator(`a[href$="/items/${hid}"]`, { hasText: name });
}

/** Hold back the requests that match until `release` is called. */
async function holdBack(page: Page, pattern: string, method = "GET") {
  let release = () => {};
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route(pattern, async (route) => {
    if (route.request().method() === method) await held;
    await route.continue().catch(() => {});
  });
  return () => {
    release();
    return page.unroute(pattern);
  };
}

test("Retire on a server names what runs on it, and on that, before it asks, and the message says how many went with it (P-247)", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(180_000);
  await records(request, account);
  const seen = await watch(page.context());
  await signIn(page, account);
  await openItem(page, esx(1));
  // What runs on it is read when the question opens: until it is, the question cannot
  // be answered.
  const release = await holdBack(page, "**/api/v1/items/*/hosted");
  await page.getByRole("button", { name: "Retire item", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: `Retire ${esx(1)}?` });
  await expect(dialog.getByRole("status")).toHaveText("Reading what runs on it…");
  await expect(dialog.getByRole("button", { name: "Retire item" })).toBeDisabled();
  await release();
  const hosted = dialog.getByTestId("hosted-question");
  await expect(hosted).toHaveAttribute("data-count", "3");
  await expect(hosted.locator("p").first()).toHaveText(
    "3 items run on it, or on what runs on it, and are retired with it, each as its own page retires it:",
  );
  for (const name of [...onFirst, container]) {
    await expect(linkTo(hosted, name, hidOf(name))).toBeVisible();
  }
  await expect(hosted.locator(`li[data-hid="${hidOf(container)}"]`)).toContainText(
    `on ${onFirst[0]}`,
  );
  // A machine put on it after the question was read goes with it too, and is counted: the
  // message says what the server retired, not what the question listed.
  const late = host("vm-a3");
  made.hids[late] = await make(request, await session(request, account), "/items", {
    catalog_entry_hid: hidOf(vmPid),
    hostname: late,
    host_item_hid: hidOf(esx(1)),
  });
  await dialog.getByRole("button", { name: "Retire item" }).click();
  await expect(page.locator(".alert-ok")).toHaveText(
    "The item was retired, and with it 4 items that ran on it.",
  );
  // What ran on it is retired, its own page says.
  await page.goto(`./items/${hidOf(container)}`);
  await expect(page.getByRole("heading", { level: 2, name: "Retired" })).toBeVisible();

  // The rows ticked: the dry run answers first, and Retire waits for it.
  await page.goto(`./items?filter=${encodeURIComponent(`hostname:prefix:${host("esx-0")}`)}`);
  await rowBox(page, "grid-items", esx(2)).check();
  await rowBox(page, "grid-items", esx(3)).check();
  const releaseDry = await holdBack(page, "**/api/v1/items/retire", "POST");
  await page.getByRole("button", { name: "Retire (2)" }).click();
  const ask = page.getByTestId("removal-dialog");
  await expect(ask.getByRole("status")).toHaveText("Asking the server what would be retired…");
  await expect(ask.getByRole("button", { name: "Retire", exact: true })).toBeDisabled();
  await releaseDry();
  await expect(ask.getByTestId("retire-will")).toHaveText("2 items will be retired.");
  const going = ask.getByTestId("retire-hosted");
  await expect(going).toHaveAttribute("data-count", "2");
  await expect(going.locator("p").first()).toHaveText(
    "With them, 2 items that run on them will be retired: what runs on it goes with its host.",
  );
  for (const name of onSecond) await expect(linkTo(going, name, hidOf(name))).toBeVisible();
  await ask.getByRole("button", { name: "Retire 2 items" }).click();
  const outcome = page.getByTestId("removal-outcome");
  await expect(outcome.locator("p").first()).toHaveText(
    "Retired 2 items. With them, 2 items that ran on them were retired.",
  );
  await outcome.getByText("What went with them").click();
  for (const name of onSecond) await expect(linkTo(outcome, name, hidOf(name))).toBeVisible();
  await expectClean(page, seen);
});

test("a cluster that something runs on is not retired, from its page or ticked, and a deletion says what runs on a server (P-247)", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(150_000);
  await records(request, account);
  const seen = await watch(page.context());
  await signIn(page, account);
  await openGroup(page, cluster);
  await page.getByRole("button", { name: "Retire group", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: `Retire ${cluster}?` });
  const hosted = dialog.getByTestId("hosted-question");
  await expect(hosted.locator("p").first()).toHaveText(
    "1 item runs on it, so it is not retired: give each another host, or retire it, first. What runs on it:",
  );
  await expect(linkTo(hosted, onCluster, hidOf(onCluster))).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Retire group" })).toBeDisabled();
  // Only why it is not retired is said: nothing of what a retirement would do.
  await expect(dialog).not.toContainText("membership");
  await expect(dialog).not.toContainText("no current member");
  await dialog.getByRole("button", { name: "Cancel" }).click();

  // Where the page did not know, the server's refusal says the same, with the links.
  await page.route(`**/api/v1/device-groups/${hidOf(cluster)}`, async (route) => {
    const response = await route.fetch();
    await route.fulfill({ response, json: { ...(await response.json()), hosted_count: 0 } });
  });
  await page.reload();
  await page.getByRole("button", { name: "Retire group", exact: true }).click();
  await page
    .getByRole("dialog", { name: `Retire ${cluster}?` })
    .getByRole("button", { name: "Retire group" })
    .click();
  const refusal = page.getByRole("region", { name: "Retire" }).locator(".alert-error");
  await expect(refusal).toContainText(
    `1 item runs on ${cluster}: give each another host, or retire it, first`,
  );
  const named = refusal.getByTestId("problem-depends-on");
  await expect(named).toContainText("What runs on it:");
  await expect(linkTo(named, onCluster, hidOf(onCluster))).toBeVisible();
  await page.unroute(`**/api/v1/device-groups/${hidOf(cluster)}`);

  // Ticked in the list of groups: the dry run refuses it, naming what runs on it.
  await page.goto(`./groups?filter=${encodeURIComponent(`name:eq:${cluster}`)}`);
  await rowBox(page, "grid-device-groups", cluster).check();
  await page.getByRole("button", { name: "Retire (1)" }).click();
  const ask = page.getByTestId("removal-dialog");
  await expect(ask.getByTestId("retire-will")).toHaveText(
    "None of the 1 group ticked can be retired. 1 group refused:",
  );
  const refused = ask.getByTestId("retire-refused");
  await expect(refused).toContainText("give each another host, or retire it, first");
  await expect(linkTo(refused, onCluster, hidOf(onCluster))).toBeVisible();
  await expect(ask.getByRole("button", { name: /^Retire/ })).toHaveCount(0);
  await ask.getByRole("button", { name: "Close" }).click();

  // A deletion of a server something runs on names it as running on it.
  await openItem(page, esx(4));
  await page.getByRole("button", { name: "Delete item" }).click();
  const deleting = page.getByTestId("delete-refused");
  await expect(deleting).toContainText(`${esx(4)}: in its way, item that runs on it ${onFourth}`);
  await expect(linkTo(deleting, onFourth, hidOf(onFourth))).toBeVisible();
  await page.getByTestId("removal-dialog").getByRole("button", { name: "Close" }).click();
  await expectClean(page, seen, ["409 POST"]);
});

test("Replace asks whether what runs on the item that leaves goes to the new one, and says it went (P-247)", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(150_000);
  await records(request, account);
  const seen = await watch(page.context());
  await signIn(page, account);
  await openItem(page, esx(5));
  await page.getByRole("button", { name: "Replace this item" }).click();
  const form = page.getByRole("region", { name: `Replace ${esx(5)}` });
  const box = form.getByLabel("The 3 things that run on it go to the new one");
  await expect(box).toBeChecked();
  const names = form.getByTestId("hand-over-names");
  for (const name of onFifth) await expect(linkTo(names, name, hidOf(name))).toBeVisible();

  // An item that hosts nothing, by its kind: the box is unticked, and says why.
  const choose = async (name: string) => {
    await form.getByLabel("The item that takes its place", { exact: true }).fill(name);
    await form
      .getByRole("list", { name: "Items that match" })
      .getByRole("button", { name: new RegExp(`^${name}`) })
      .click();
  };
  await choose(lic);
  await expect(box).not.toBeChecked();
  await expect(form.getByTestId("hand-over")).toContainText(
    `Unticked: ${lic} is of the kind software, which hosts nothing.`,
  );
  await form.getByLabel("Reason").selectOption({ label: "Refresh" });
  // Ticked all the same, the server refuses it, said beside the box.
  await box.check();
  await form.getByRole("button", { name: "Replace", exact: true }).click();
  const refusedThere = form.getByTestId("hand-over").locator(".field-error");
  await expect(refusedThere).toBeVisible();
  await expect(box).toBeChecked();
  // The focus is on the field refused.
  await expect(box).toBeFocused();
  // A new item instead: the refusal is about the item chosen, and goes.
  await form.getByLabel("What takes its place").selectOption({ label: "A new item, created now" });
  await expect(refusedThere).toHaveCount(0);
  await expect(form.locator(".alert-error")).toHaveCount(0);
  await form
    .getByLabel("What takes its place")
    .selectOption({ label: "An item that is in the inventory" });
  await expect(refusedThere).toHaveCount(0);

  await form.getByRole("button", { name: "Choose another" }).click();
  await choose(esx(6));
  await expect(box).toBeChecked();
  await form.getByRole("button", { name: "Replace", exact: true }).click();
  await expect(page.locator(".alert-ok")).toContainText(
    `The 3 things that ran on it run on ${esx(6)} now.`,
  );
  // Each names the new one as its host.
  const headers = await session(request, account);
  for (const name of onFifth) {
    const answer = await request.get(`./api/v1/items/${hidOf(name)}`, { headers });
    expect(((await answer.json()) as { host_item_hid: string }).host_item_hid).toBe(hidOf(esx(6)));
  }

  // Eleven run on the seventh: no names beneath the box, and a link to them in the list.
  await openItem(page, esx(7));
  await page.getByRole("button", { name: "Replace this item" }).click();
  const seventh = page.getByRole("region", { name: `Replace ${esx(7)}` });
  await expect(seventh.getByLabel("The 11 things that run on it go to the new one")).toBeChecked();
  await expect(seventh.getByTestId("hand-over-names")).toHaveCount(0);
  const toList = seventh.getByTestId("hand-over-list").getByRole("link");
  await expect(toList).toHaveText("The 11 that run on it in the item list");
  await toList.click();
  await expect(page.getByLabel("Filter", { exact: true })).toHaveValue(
    `host_item_hid:eq:${hidOf(esx(7))}`,
  );
  await expect(page.getByTestId("grid-total")).toHaveText("11 items");
  await expectClean(page, seen, ["422 POST"]);
});

function csvOf(rows: string[][]): Buffer {
  return Buffer.from(rows.map((row) => `${row.join(",")}\n`).join(""), "utf8");
}

async function importReport(page: Page, file: string, names: string[], complete: boolean) {
  await page.goto("./import");
  await page.getByLabel("File", { exact: true }).setInputFiles({
    name: file,
    mimeType: "text/csv",
    buffer: csvOf([
      ["vendor", "pid", "hostname", "external_id"],
      ...names.map((name) => [vendorName, vmPid, name, `vm-${name}`]),
    ]),
  });
  await expect(page.getByLabel("Records")).toHaveValue("items");
  // The box shows once a system is chosen, unticked.
  await expect(page.getByLabel("This file is everything it reports")).toHaveCount(0);
  await page.getByLabel("Read from").selectOption({ label: system });
  const box = page.getByLabel("This file is everything it reports");
  await expect(box).not.toBeChecked();
  if (complete) await box.check();
  await page.getByRole("button", { name: "Preview", exact: true }).click();
  const job = page.getByTestId("import-job");
  await expect(job).toHaveAttribute("data-status", "previewed", { timeout: 20_000 });
  await expect(count(page, "rejected")).toHaveText("0");
  await expect(job.getByTestId("import-system")).toHaveText(
    complete ? `${system} · everything it reports` : system,
  );
  return job;
}

test("a tool's report: three machines, then a file of two that is everything it reports, and the third is marked as not reported, not retired (P-248)", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(180_000);
  await records(request, account);
  const seen = await watch(page.context());
  await signIn(page, account);
  const first = `items-${id}-vcenter-1.csv`;
  let job = await importReport(page, first, reported, false);
  await expect(count(page, "created")).toHaveText("3");
  await expect(job.getByTestId("import-not-reported")).toHaveCount(0);
  await page.getByRole("button", { name: "Apply 3 rows" }).click();
  await whenApplied(page, 3);

  const second = `items-${id}-vcenter-2.csv`;
  job = await importReport(page, second, reported.slice(0, 2), true);
  const marks = job.getByTestId("import-not-reported");
  await expect(marks).toHaveAttribute("data-count", "1");
  await expect(marks.locator("p")).toHaveText(
    `1 item registered with ${system} is not named by the file, and will be marked as not reported once it is applied whole:`,
  );
  const third = reported[2] ?? "";
  const thirdHid = (
    (await (
      await request.get(
        `./api/v1/items?filter=${encodeURIComponent(`hostname:eq:${third}`)}&fields=hostname`,
        { headers: await session(request, account) },
      )
    ).json()) as { items: { hid: string }[] }
  ).items[0]?.hid;
  made.hids[third] = thirdHid ?? "";
  await expect(linkTo(marks, third, hidOf(third))).toBeVisible();
  // Left and come back to, the preview names them again, from the job itself.
  const there = page.url();
  await page.goto("./import");
  await page.goto(there);
  await expect(marks.locator("p")).toHaveText(
    `1 item registered with ${system} is not named by the file, and will be marked as not reported once it is applied whole:`,
  );
  await expect(linkTo(marks, third, hidOf(third))).toBeVisible();
  await page.getByRole("button", { name: "Apply 2 rows" }).click();
  await whenApplied(page, 2);
  await expect(marks.locator("p")).toHaveText(
    `1 item was marked as not reported by ${system}, each to be looked at.`,
  );
  // A past import says which system it was read from.
  const past = page.getByTestId("import-jobs").locator("tr", { hasText: second });
  await expect(past.getByTestId("job-system")).toHaveText(
    `Read from ${system}, everything it reports`,
  );
  // The third is not retired: it is found by the list as before.
  await openItem(page, third);
  await expect(page.getByRole("heading", { level: 2, name: "Retire", exact: true })).toBeVisible();
  // A file that names it again would bring its registration back, which its row says in
  // words; it is previewed only, so that it stays marked.
  await importReport(page, `items-${id}-vcenter-3.csv`, [third], false);
  await expect(page.getByTestId("preview-rows")).toContainText(
    "registration with the system: Not reported → Registered",
  );
  await expectClean(page, seen);
});

test("the registration reads Not reported and is to be looked at, with the two ways on; View-only reads it without them (P-249)", async ({
  page,
  account,
  request,
  browser,
}) => {
  test.setTimeout(150_000);
  await records(request, account);
  const third = reported[2] ?? "";
  // View-only: the mark and what it means, and no button that changes it.
  const viewer = await signInAs(browser, made.viewer as Account);
  await openItem(viewer.page, third);
  const viewed = viewer.page.getByTestId("registrations");
  await expect(viewed.locator(`tr[data-system="${system}"]`)).toHaveAttribute(
    "data-review",
    "not_reported",
  );
  await expect(viewed.getByTestId("not-reported-line")).toContainText(
    "The Inventory role sets the registration back to Registered, or retires the item.",
  );
  await expect(viewed.getByRole("button", { name: "Set back to Registered" })).toHaveCount(0);
  await expect(viewed.getByRole("button", { name: /^Remove/ })).toHaveCount(0);
  await expect(viewer.page.getByRole("button", { name: "Retire item" })).toHaveCount(0);
  await expectClean(viewer.page, viewer.seen);
  await viewer.context.close();

  const seen = await watch(page.context());
  await signIn(page, account);
  await openItem(page, third);
  const table = page.getByTestId("registrations");
  const row = table.locator(`tr[data-system="${system}"]`);
  await expect(row).toHaveAttribute("data-status", "not_reported");
  await expect(row).toContainText("Not reported");
  await expect(row).toContainText("To be looked at");
  const line = table.getByTestId("not-reported-line");
  await expect(line).toContainText(
    `${system} reports ${third} no more: find out what became of it.`,
  );
  // The second way on is the Retire of the page.
  await expect(line.getByRole("link", { name: "retire the item" })).toHaveAttribute(
    "href",
    /#retire$/,
  );
  await line.getByRole("button", { name: "Set back to Registered" }).click();
  await expect(row).toHaveAttribute("data-status", "registered");
  await expect(row).toContainText("Registered");
  await expect(table.getByTestId("not-reported-line")).toHaveCount(0);
  await expectClean(page, seen);
});

test("the first page counts what is to be looked at, as a link to the item list, and says nothing where there is none (P-249)", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(120_000);
  await records(request, account);
  const seen = await watch(page.context());
  await signIn(page, account);
  // A machine of this file names no host: there is at least one.
  const line = page.getByTestId("home-review");
  await expect(line).toBeVisible({ timeout: 20_000 });
  expect(Number(await line.getAttribute("data-count"))).toBeGreaterThan(0);
  // The reasons are counted after the line: on a busy host that takes a while.
  await expect(line).toContainText("to be looked at:", { timeout: 20_000 });
  await line.getByRole("link").first().click();
  await expect(page.getByLabel("Filter", { exact: true })).toHaveValue("review:empty:false");
  await expect(page.getByTestId("grid-items")).toBeVisible();
  // Why, a link for each reason, to the list filtered by it, which says the reason in its
  // filter with no column for it.
  await page.goto("./");
  const noHost = line.getByTestId("home-review-reasons").locator('[data-reason="no_host"]');
  await expect(noHost.getByRole("link")).toHaveText(/^[\d,]+ names? no host$/, { timeout: 20_000 });
  await noHost.getByRole("link").click();
  await expect(page.getByLabel("Filter", { exact: true })).toHaveValue("review:eq:no_host");
  await page.getByLabel("Filter", { exact: true }).fill(`review:eq:no_host hostname:eq:${orphan}`);
  await page.getByRole("button", { name: "Apply", exact: true }).click();
  await expect(page.getByTestId("grid-total")).toHaveText("1 item");

  // Where the list counts none, the line is not there.
  await page.route(
    (url) =>
      url.pathname.endsWith("/api/v1/items") &&
      (url.searchParams.get("filter") ?? "").startsWith("review:"),
    (route) => route.fulfill({ json: { items: [], total: 0, limit: 1, offset: 0 } }),
  );
  await page.goto("./");
  await expect(page.getByTestId("unassigned")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId("home-review")).toHaveCount(0);
  await expectClean(page, seen);
});
