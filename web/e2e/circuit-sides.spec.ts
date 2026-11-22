// The browser scenarios of a circuit's two sides and the carrier network a Z side
// reaches, of 0.9.18 (P-317, P-319, P-320, scenario S63 in the web page), with what the
// review of 0.9.18 found:
//
//   A carrier's MPLS network is made as a circuit group of the kind Network, with its
//   carrier; a group of the kind Collection is not offered for a Z side, and a draft
//   carrier network is offered marked so. A circuit from a site to the network has the A
//   side's dates under the A side and the Z side's under the Z side, a blank Z date read
//   as the A side's and said so, in the form beneath it and on the page, a blank date
//   shown as every blank fact; its cost is set to count at the Z side, whose dates in
//   force say whether it is in service, while its cost and weight count at the A side's
//   site, the two said apart. A location chosen for the Z side lets go of the network,
//   which comes back when the location is cleared; going through the carrier networks
//   with the keyboard on a circuit whose Z side is a location leaves the location as it
//   was, and a save of something else sends nothing of it. A change of the A side's date
//   that would put the Z side's in force out of order is refused at a Z side's field.
//   The network lists the circuit its Z side brings, marked so, beside one put into it by
//   hand, each once; taken out there, only what leaves is counted and what stays is
//   named, and the button is not to be pressed where nothing ticked can leave. Switching
//   the side whose dates decide says what it does to whether it is in service, and asks
//   first where it changes that today. An export writes each Z date in force with its
//   source. The network is not retired while a circuit names it, and the page says why;
//   bringing back a circuit whose network is retired is refused as a whole. The
//   carrier's page lists its carrier networks.
//
// It keeps to the rules of support.ts: an account and names of its own, and nothing
// changed that another file reads. The setting `circuit_cost_side` is read, not changed.

import { expect, type Locator, type Page } from "@playwright/test";
import { make, session } from "./referenceSteps";
import { region } from "./structure";
import { expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const suffix = mark("circuit-sides");
const carrier = `Example Carrier ${suffix}`;
const network = `Example MPLS ${suffix}`;
const draftNetwork = `Planned MPLS ${suffix}`;
const collection = `Branch links ${suffix}`;
const regionName = `Sides Region ${suffix}`;
const siteName = `Sides Site ${suffix}`;
const room = `Telecom room ${suffix}`;
const roomPath = `${regionName} > ${siteName} > ${room}`;
const branch = `Branch to MPLS ${suffix}`;
const branchId = `EC-${suffix}-01`;
const toRoom = `Room to room ${suffix}`;
const other = `Spare link ${suffix}`;
const later = `Ordered link ${suffix}`;

// What the scenarios hand on: the network's page, the circuits' pages and HIDs.
const made = { network: "", circuit: "", room: "", carrier: "", toRoom: "", later: "" };

/** Search for a location in a side's field of the form, and choose it by its path. */
async function chooseSide(form: Locator, side: "a" | "z", typed: string, path: string) {
  const field = form.locator(`[data-field="${side}_location_hid"]`);
  await field.getByRole("searchbox").fill(typed);
  await field
    .getByRole("list", { name: "Locations that match" })
    .getByRole("button", { name: path, exact: true })
    .click();
  await expect(field.getByTestId(`chosen-${side}_location_hid`)).toHaveText(path);
}

async function openCircuit(page: Page, path = made.circuit, name = branch) {
  await page.goto(path);
  await expect(page.getByRole("heading", { level: 1, name: new RegExp(`^${name}`) })).toBeVisible();
}

const hidOf = (path: string) => path.split("/").at(-1) ?? "";

test("P-320: a network is made with its carrier, and a circuit's Z side reaches it, with the dates of each side", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(180_000);
  const headers = await session(request, account);
  const vendor = await make(request, headers, "/vendors", { name: carrier });
  made.carrier = `./vendors/${vendor.hid}`;
  const top = await make(request, headers, "/regions", { name: regionName });
  const site = await make(request, headers, "/sites", { name: siteName, region_hid: top.hid });
  const at = await make(request, headers, "/locations", { name: room, site_hid: site.hid });
  made.room = at.hid;
  await make(request, headers, "/circuit-groups", { name: collection });
  await make(request, headers, "/circuit-groups", {
    name: draftNetwork,
    kind: "network",
    carrier_hid: vendor.hid,
    record_status: "draft",
  });
  const seen = await watch(page.context());
  await signIn(page, account);

  // A network, with its carrier: the carrier is asked only of a network.
  await page.goto("./circuit-groups");
  await page.getByRole("button", { name: "New circuit group" }).click();
  const groupForm = region(page, "New circuit group");
  await groupForm.getByLabel("Name (required)").fill(network);
  await expect(groupForm.getByLabel("Kind")).toHaveValue("collection");
  await expect(groupForm).toContainText("Network: a carrier network");
  await expect(groupForm.getByLabel("Carrier")).toHaveCount(0);
  await groupForm.getByLabel("Kind").selectOption({ label: "Network" });
  await groupForm.getByLabel("Carrier").selectOption({ label: carrier });
  await groupForm.getByRole("button", { name: "Create group" }).click();
  await expect(page.getByRole("heading", { level: 1, name: network })).toBeVisible();
  await expect(page.getByTestId("group-kind")).toHaveText("Network");
  await expect(
    page.getByTestId("group-carrier").getByRole("link", { name: carrier }),
  ).toBeVisible();
  made.network = new URL(page.url()).pathname;

  // A circuit from the room to the network: only carrier networks are offered for the Z
  // side, each by its name under its carrier, a draft marked so.
  await page.goto("./circuits");
  await page.getByRole("button", { name: "New circuit" }).click();
  const form = region(page, "New circuit");
  await form.getByLabel("Name (required)").fill(branch);
  await form.getByLabel("Enterprise circuit ID").fill(branchId);
  await chooseSide(form, "a", room, roomPath);
  const zNetwork = form.getByLabel("Z side: carrier network");
  const underCarrier = zNetwork.locator(`optgroup[label="${carrier}"]`);
  await expect(underCarrier.locator("option", { hasText: network })).toHaveText(network);
  await expect(underCarrier.locator("option", { hasText: draftNetwork })).toHaveText(
    `${draftNetwork} (draft)`,
  );
  await expect(zNetwork.locator("option", { hasText: collection })).toHaveCount(0);
  await zNetwork.selectOption({ label: network });
  await expect(form).toContainText(
    "Needed where the Z side names neither a location nor a carrier network.",
  );
  await form.getByLabel("Z side: note").fill("hand-off at the carrier's edge");
  await form.getByLabel("A side: installed on").fill("2026-01-05");
  await form.getByLabel("A side: activated on").fill("2026-01-10");
  await form.getByLabel("Z side: activated on").fill("2026-02-01");
  // A blank Z date says what it is read as: the A side's, as the form holds it now.
  await expect(form).toContainText("Blank: the A side's, 2026-01-05, is read in its place.");
  // Only the side whose dates decide says that the carrier bills it from its activation.
  await form.getByLabel("Its cost counts at").selectOption({ label: "Z side" });
  await expect(form.getByLabel("Z side: activated on")).toHaveAccessibleDescription(
    /^The carrier bills it from this day/,
  );
  await expect(form.getByLabel("A side: activated on")).toHaveAccessibleDescription(
    /The other side's dates say whether it is in service and when it is billed\./,
  );
  await form.getByRole("button", { name: "Create circuit" }).click();
  await expect(
    page.getByRole("heading", { level: 1, name: new RegExp(`^${branch}`) }),
  ).toBeVisible();
  made.circuit = new URL(page.url()).pathname;

  // The page: the Z side names the carrier network, a link; each side has its dates.
  const zSide = page.getByTestId("side-z");
  await expect(zSide).toContainText(`The carrier network ${network}`);
  await expect(zSide.getByRole("link", { name: network })).toHaveAttribute(
    "href",
    new RegExp(`${made.network}$`),
  );
  await expect(zSide).toContainText("hand-off at the carrier's edge");
  await expect(page.getByTestId("a-installed_on")).toHaveText("2026-01-05");
  await expect(page.getByTestId("a-activated_on")).toHaveText("2026-01-10");
  await expect(page.getByTestId("a-disconnected_on")).toHaveText("—");
  await expect(page.getByTestId("z-installed_on")).toContainText("2026-01-05");
  await expect(page.getByTestId("z-installed_on")).toContainText("the A side's");
  await expect(page.getByTestId("z-installed_on").locator("[data-source]")).toHaveAttribute(
    "data-source",
    "a_side",
  );
  await expect(page.getByTestId("z-activated_on")).toHaveText("2026-02-01");
  await expect(page.getByTestId("z-disconnected_on")).toHaveText("—");
  await expect(page.getByTestId("in-service")).toHaveText("Yes");
  // Set to count at the Z side, which has no location: the Z side's dates decide, while
  // its cost and weight count at the A side's site, the two said apart.
  await expect(page.getByTestId("counts-at")).toHaveAttribute("data-side", "z");
  await expect(page.getByTestId("counts-at")).toHaveAttribute("data-counting", "a");
  await expect(page.getByTestId("dates-decide-z")).toContainText(
    "The Z side has no location, so its cost and its weight count at the site of the A side.",
  );
  await expect(page.getByTestId("side-a")).toContainText(
    `${regionName} > ${siteName} Its cost and weight count at this site`,
  );

  // A location chosen for the Z side lets go of the network, which comes back when the
  // location is cleared: nothing is left to save.
  const details = region(page, "Details");
  await chooseSide(details, "z", room, roomPath);
  await expect(details.getByLabel("Z side: carrier network")).toHaveValue("");
  await details
    .locator('[data-field="z_location_hid"]')
    .getByRole("button", { name: /^Clear/ })
    .click();
  await expect(details.getByLabel("Z side: carrier network")).toHaveValue(hidOf(made.network));
  await expect(details.getByRole("button", { name: "Save", exact: true })).toBeDisabled();
  await expectClean(page, seen);
});

// Review of 0.9.18, finding 1: looking through the list loses no location.
test("P-320: going through the carrier networks with the keyboard leaves a Z side's location as it was", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(90_000);
  const headers = await session(request, account);
  const made2 = await make(request, headers, "/circuits", {
    name: toRoom,
    a_location_hid: made.room,
    z_location_hid: made.room,
    z_note: "patch panel 4",
  });
  made.toRoom = `/circuits/${made2.hid}`;
  const seen = await watch(page.context());
  await signIn(page, account);
  await openCircuit(page, made.toRoom, toRoom);
  const details = region(page, "Details");
  const zNetwork = details.getByLabel("Z side: carrier network");
  await zNetwork.focus();
  await page.keyboard.press("ArrowDown");
  await expect(zNetwork).not.toHaveValue("");
  await expect(details.getByTestId("chosen-z_location_hid")).toHaveText(/^No location/);
  await page.keyboard.press("ArrowUp");
  await expect(zNetwork).toHaveValue("");
  await expect(details.getByTestId("chosen-z_location_hid")).toHaveText(roomPath);
  await details.getByLabel("Description").fill("Moved to rack 2");
  await details.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("The circuit was saved.")).toBeVisible();
  await expect(page.getByTestId("side-z")).toContainText(roomPath);
  await expect(page.getByTestId("side-z")).toContainText("patch panel 4");
  await expectClean(page, seen);
});

test("P-320: a change of the A side's date that puts the Z side's in force out of order is refused at the Z side", async ({
  page,
  account,
}) => {
  test.setTimeout(90_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  await openCircuit(page);
  // The Z side's installation is the A side's: the A side's dates moved on, in their own
  // order, would put the Z side's activation before its installation in force.
  const details = region(page, "Details");
  await details.getByLabel("A side: installed on").fill("2026-02-15");
  await details.getByLabel("A side: activated on").fill("2026-03-01");
  await expect(details).toContainText("Blank: the A side's, 2026-02-15, is read in its place.");
  await details.getByRole("button", { name: "Save", exact: true }).click();
  await expect(details.locator(".alert-error")).toHaveAttribute("data-status", "422");
  const zRefused = details.locator('input[aria-invalid="true"]');
  await expect(zRefused).toHaveCount(1);
  await expect(zRefused).toHaveAccessibleName("Z side: activated on");
  await expect(page.getByTestId("a-installed_on")).toHaveText("2026-01-05");
  await expectClean(page, seen, ["422 PATCH"]);
});

test("P-320: a network lists the circuits its Z side brings, marked so, and is not retired while one names it", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(180_000);
  const headers = await session(request, account);
  const networkHid = hidOf(made.network);
  // Another circuit, put into the network by hand; and the first, put into it by hand too.
  const spare = await make(request, headers, "/circuits", {
    name: other,
    a_location_hid: made.room,
    z_note: "carrier network",
  });
  const circuitHid = hidOf(made.circuit);
  await make(request, headers, `/circuit-groups/${networkHid}/members`, {
    circuit_hids: [spare.hid, circuitHid],
  });
  // One ordered for later, whose cost counts at its Z side, activated there months on.
  const ordered = await make(request, headers, "/circuits", {
    name: later,
    a_location_hid: made.room,
    z_group_hid: networkHid,
    cost_side: "z",
    a_activated_on: "2026-01-10",
    z_activated_on: "2099-06-01",
  });
  made.later = `/circuits/${ordered.hid}`;
  const seen = await watch(page.context());
  await signIn(page, account);

  // Each once: the two put in by hand, and the one its Z side alone brings.
  await page.goto(made.network);
  await expect(page.getByTestId("group-circuits")).toHaveText("3");
  const grid = page.getByTestId("grid-circuit-group-circuits");
  await expect(grid.locator("[row-id]")).toHaveCount(3);
  const row = (name: string) => grid.locator("[row-id]", { hasText: name });
  await expect(row(branch).locator('[col-id="in_group"]')).toHaveText("By its Z side");
  await expect(row(later).locator('[col-id="in_group"]')).toHaveText("By its Z side");
  await expect(row(other).locator('[col-id="in_group"]')).toHaveText("Put in it");

  // Review of 0.9.18, finding 7: only what leaves is counted, what stays is named.
  const takeOut = page.getByRole("button", { name: /^Take out of the group/ });
  await row(branch).getByRole("checkbox").check();
  await row(other).getByRole("checkbox").check();
  await takeOut.click();
  await expect(page.getByRole("status").filter({ hasText: "taken out of" })).toContainText(
    `1 circuit was taken out of ${network}. ${branch} stays in it by its Z side`,
  );
  await expect(grid.locator("[row-id]")).toHaveCount(2);
  await expect(row(branch)).toHaveCount(1);
  // Nothing ticked can leave: the button is not to be pressed, and says why.
  await row(later).getByRole("checkbox").check();
  await expect(takeOut).toBeDisabled();
  await expect(page.getByTestId("grid-too-many")).toContainText(
    "Those ticked are in it by their Z side",
  );
  await row(later).getByRole("checkbox").uncheck();

  // Review of 0.9.18, finding 6: an export writes each Z date in force, with its source.
  const exported = await request.post("./api/v1/exports", {
    headers,
    data: {
      entity: "circuits",
      format: "csv",
      columns: [
        "hid",
        "name",
        "z_installed_on",
        "z_installed_on_source",
        "z_activated_on",
        "z_activated_on_source",
      ],
      hids: [circuitHid],
    },
  });
  expect(exported.status(), await exported.text()).toBe(200);
  const lines = (await exported.text()).trim().split(/\r?\n/);
  expect(lines[0]).toBe(
    "hid,name,z_installed_on,z_installed_on_source,z_activated_on,z_activated_on_source",
  );
  expect(lines[1]).toBe(`${circuitHid},${branch},2026-01-05,a_side,2026-02-01,own`);

  // The one ordered for later is not in service until its Z side is activated.
  await grid.getByRole("link", { name: later, exact: true }).click();
  await expect(page.getByTestId("not-in-service")).toContainText(
    "It is not in service until its Z side is activated on 2099-06-01.",
  );
  // Review of 0.9.18, finding 4: switching the side whose dates decide says what it does
  // to whether it is in service, and asks first where it changes that today.
  await expect(page.getByTestId("switch-side-words")).toContainText(
    "The A side's dates then decide whether it is in service, and the months its cost counts: it would be in service today, which it is not now.",
  );
  await page.getByRole("button", { name: "Count it at the A side" }).click();
  const ask = page.getByRole("dialog");
  await expect(ask).toContainText("it would be in service today, which it is not now");
  await ask.getByRole("button", { name: "Cancel" }).click();
  await expect(page.getByTestId("in-service")).toHaveText("No");
  // Where both sides' dates in force put it in service today, the switch is one press.
  await openCircuit(page);
  await expect(page.getByTestId("switch-side-words")).toContainText(
    "it is in service today either way",
  );

  // Not retired while a circuit names it: the page says why, with the circuits as links.
  await page.goto(made.network);
  const retire = region(page, "Retire");
  await expect(retire).toContainText(
    "A carrier network is not retired while a circuit that is not retired names it on its Z side.",
  );
  await retire.getByRole("button", { name: "Retire this group" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Retire", exact: true }).click();
  await expect(retire.locator(".alert-error")).toContainText(
    `${network} is the network the Z side of 2 circuits not retired reaches`,
  );
  await expect(retire.locator(".alert-error")).toContainText("The circuits that reach it:");
  await expect(page.getByTestId("group-kind")).toHaveText("Network");

  // The carrier's page lists its carrier networks.
  await page.goto(made.carrier);
  await expect(page.getByRole("heading", { level: 2, name: "Carrier networks" })).toBeVisible();
  const networks = page.getByTestId("grid-vendor-networks");
  await expect(networks.getByRole("link", { name: network, exact: true })).toBeVisible();
  await expectClean(page, seen, ["409 POST"]);
});

// Review of 0.9.18, finding 3: a refusal of the record as a whole is a sentence of its own.
test("P-320: a circuit whose carrier network is retired is brought back only with another", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(90_000);
  const headers = await session(request, account);
  // The circuits that reach the network are retired, and then the network.
  for (const path of [made.circuit, made.later]) {
    const read = await request.get(`./api/v1${path}`, { headers });
    const { row_version } = (await read.json()) as { row_version: number };
    const retired = await request.post(`./api/v1${path}/retire`, {
      headers,
      data: { row_version },
    });
    expect(retired.status(), await retired.text()).toBe(200);
  }
  const group = await request.get(`./api/v1${made.network}`, { headers });
  const { row_version } = (await group.json()) as { row_version: number };
  const gone = await request.post(`./api/v1${made.network}/retire`, {
    headers,
    data: { row_version },
  });
  expect(gone.status(), await gone.text()).toBe(200);
  const seen = await watch(page.context());
  await signIn(page, account);
  await page.goto(`${made.later}?archived=1`);
  await expect(
    page.getByRole("heading", { level: 1, name: new RegExp(`^${later}`) }),
  ).toBeVisible();
  const retire = region(page, "Retired");
  await retire.getByRole("button", { name: "Bring back" }).click();
  const refusal = retire.locator(".alert-error");
  await expect(refusal).toContainText(network);
  await expect(refusal).not.toContainText("record_status");
  await expectClean(page, seen, ["422 PATCH"]);
});
