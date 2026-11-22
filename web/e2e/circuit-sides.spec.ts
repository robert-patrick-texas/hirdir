// The browser scenarios of a circuit's two sides and the network a Z side reaches, of
// 0.9.18 (P-317, P-319, P-320, scenario S63 in the web page):
//
//   A carrier's MPLS network is made as a circuit group of the kind Network, with its
//   carrier; a group of the kind Collection is not offered for a Z side. A circuit from a
//   site to the network has the A side's dates under the A side and the Z side's under
//   the Z side, a blank Z date read as the A side's and said so, in the form beneath it
//   and on the page; its cost counts at the Z side, whose dates in force say whether it
//   is in service. A location chosen for the Z side lets go of the network. A change of
//   the A side's date that would put the Z side's in force out of order is refused at a
//   Z side's field. The network lists the circuit its Z side brings, marked so, beside
//   one put into it by hand, each once; the one its Z side brings stays when it is taken
//   out there. The network is not retired while the circuit names it, and the page says
//   why. The carrier's page lists its network.
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
const collection = `Branch links ${suffix}`;
const regionName = `Sides Region ${suffix}`;
const siteName = `Sides Site ${suffix}`;
const room = `Telecom room ${suffix}`;
const roomPath = `${regionName} > ${siteName} > ${room}`;
const branch = `Branch to MPLS ${suffix}`;
const branchId = `EC-${suffix}-01`;
const other = `Spare link ${suffix}`;
const later = `Ordered link ${suffix}`;

// What the scenarios hand on: the network's page, the circuit's.
const made = { network: "", circuit: "", room: "", carrier: "" };

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

async function openCircuit(page: Page) {
  await page.goto(made.circuit);
  await expect(
    page.getByRole("heading", { level: 1, name: new RegExp(`^${branch}`) }),
  ).toBeVisible();
}

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
  const seen = await watch(page.context());
  await signIn(page, account);

  // A network, with its carrier: the carrier is asked only of a network.
  await page.goto("./circuit-groups");
  await page.getByRole("button", { name: "New circuit group" }).click();
  const groupForm = region(page, "New circuit group");
  await groupForm.getByLabel("Name (required)").fill(network);
  await expect(groupForm.getByLabel("Kind")).toHaveValue("collection");
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

  // A circuit from the room to the network: only networks are offered for the Z side.
  await page.goto("./circuits");
  await page.getByRole("button", { name: "New circuit" }).click();
  const form = region(page, "New circuit");
  await form.getByLabel("Name (required)").fill(branch);
  await form.getByLabel("Enterprise circuit ID").fill(branchId);
  await chooseSide(form, "a", room, roomPath);
  const zNetwork = form.getByLabel("Z side: network");
  await expect(zNetwork.locator("option", { hasText: network })).toHaveCount(1);
  await expect(zNetwork.locator("option", { hasText: collection })).toHaveCount(0);
  await zNetwork.selectOption({ label: `${network} (${carrier})` });
  await form.getByLabel("Z side: note").fill("hand-off at the carrier's edge");
  await form.getByLabel("A side: installed on").fill("2026-01-05");
  await form.getByLabel("A side: activated on").fill("2026-01-10");
  await form.getByLabel("Z side: activated on").fill("2026-02-01");
  // A blank Z date says what it is read as: the A side's, as the form holds it now.
  await expect(form).toContainText("Blank: the A side's, 2026-01-05, is read in its place.");
  await form.getByLabel("Its cost counts at").selectOption({ label: "Z side" });
  await form.getByRole("button", { name: "Create circuit" }).click();
  await expect(
    page.getByRole("heading", { level: 1, name: new RegExp(`^${branch}`) }),
  ).toBeVisible();
  made.circuit = new URL(page.url()).pathname;

  // The page: the Z side names the network, a link; each side has its dates beneath it.
  const zSide = page.getByTestId("side-z");
  await expect(zSide.getByRole("link", { name: network })).toHaveAttribute(
    "href",
    new RegExp(`${made.network}$`),
  );
  await expect(zSide).toContainText("hand-off at the carrier's edge");
  await expect(page.getByTestId("a-installed_on")).toHaveText("2026-01-05");
  await expect(page.getByTestId("a-activated_on")).toHaveText("2026-01-10");
  await expect(page.getByTestId("z-installed_on")).toContainText("2026-01-05");
  await expect(page.getByTestId("z-installed_on")).toContainText("the A side's");
  await expect(page.getByTestId("z-installed_on").locator("[data-source]")).toHaveAttribute(
    "data-source",
    "a_side",
  );
  await expect(page.getByTestId("z-activated_on")).toHaveText("2026-02-01");
  await expect(page.getByTestId("dates-decide-z")).toBeVisible();
  await expect(page.getByTestId("in-service")).toHaveText("Yes");
  // Its cost counts at the Z side, which has no location: at the A side's site.
  await expect(page.getByTestId("counts-at")).toHaveAttribute("data-side", "z");
  await expect(page.getByTestId("counts-at")).toHaveAttribute("data-counting", "a");

  // A location chosen for the Z side lets go of the network, and the other way about.
  const details = region(page, "Details");
  await chooseSide(details, "z", room, roomPath);
  await expect(details.getByLabel("Z side: network")).toHaveValue("");
  await details.getByLabel("Z side: network").selectOption({ label: `${network} (${carrier})` });
  await expect(details.getByTestId("chosen-z_location_hid")).toHaveText(/^No location/);
  // Back as it was, the form has nothing to save.
  await expect(details.getByRole("button", { name: "Save", exact: true })).toBeDisabled();
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
  const networkHid = made.network.split("/").at(-1) ?? "";
  // Another circuit, put into the network by hand; and the first, put into it by hand too.
  const spare = await make(request, headers, "/circuits", {
    name: other,
    a_location_hid: made.room,
    z_note: "carrier network",
  });
  const circuitHid = made.circuit.split("/").at(-1) ?? "";
  await make(request, headers, `/circuit-groups/${networkHid}/members`, {
    circuit_hids: [spare.hid, circuitHid],
  });
  // One ordered for later, whose cost counts at its Z side, activated there months on.
  await make(request, headers, "/circuits", {
    name: later,
    a_location_hid: made.room,
    z_group_hid: networkHid,
    cost_side: "z",
    a_activated_on: "2026-01-10",
    z_activated_on: "2099-06-01",
  });
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

  // Taken out there, the one put in by hand leaves; what its Z side brings stays.
  await row(later).getByRole("checkbox").check();
  await row(other).getByRole("checkbox").check();
  await page.getByRole("button", { name: "Take out of the group" }).click();
  await expect(page.getByRole("status").filter({ hasText: "taken out of" })).toContainText(
    `1 circuit was taken out of ${network}. ${later} stays in it by its Z side`,
  );
  await expect(grid.locator("[row-id]")).toHaveCount(2);

  // The one ordered for later is not in service until its Z side is activated.
  await grid.getByRole("link", { name: later, exact: true }).click();
  await expect(page.getByTestId("not-in-service")).toContainText(
    "It is not in service until its Z side is activated on 2099-06-01.",
  );

  // Not retired while a circuit names it: the page says why.
  await page.goto(made.network);
  const retire = region(page, "Retire");
  await expect(retire).toContainText(
    "A network is not retired while a circuit that is not retired names it on its Z side.",
  );
  await retire.getByRole("button", { name: "Retire this group" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Retire", exact: true }).click();
  await expect(retire.locator(".alert-error")).toContainText(
    `${network} is the network the Z side of 2 circuits not retired reaches`,
  );
  await expect(page.getByTestId("group-kind")).toHaveText("Network");
  await expect(page.getByRole("heading", { level: 1, name: network })).not.toContainText("Retired");

  // The carrier's page lists its network.
  await page.goto(made.carrier);
  const networks = page.getByTestId("grid-vendor-networks");
  await expect(networks.getByRole("link", { name: network, exact: true })).toBeVisible();
  await expectClean(page, seen, ["409 POST"]);
});
