// The browser scenario of circuits in release 0.8.0 (P-145 to P-150, P-154, scenario S47),
// with the switch of the side a circuit's cost counts at:
//
//   A circuit between two locations, with a name, an enterprise circuit ID, a primary
//   carrier, a local exchange carrier, a circuit number for each, and a router at each
//   end: its page shows both sides, both carriers and both devices, and each router and
//   each location shows it. A dark fiber between two buildings, with an enterprise
//   circuit ID and no carrier's number, is accepted and found by that ID in the grid,
//   and the ID is refused for another circuit, under its field. Its cost counts at its A
//   side until it is switched to its Z side.
//
// It keeps to the rules of support.ts: an account and names of its own, and nothing
// changed that another file reads. The setting `circuit_cost_side` is read, not changed.

import { expect, type Locator, type Page } from "@playwright/test";
import { importFile, openGroup, openItem, region } from "./structure";
import { expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const random = mark("x").slice(2);
const suffix = mark("circuits", random);
const upper = random.toUpperCase();

const carrier = `Example Telecom ${suffix}`;
const exchange = `Example Local Exchange ${suffix}`;
const regionName = `Circuit Region ${suffix}`;
const siteName = `Circuit Site ${suffix}`;
const site = `${regionName} > ${siteName}`;
const east = `East Building ${suffix}`;
const west = `West Building ${suffix}`;
const eastPath = `${site} > ${east}`;
const westPath = `${site} > ${west}`;
const eastRouter = `cir-rtr-${random}-east`;
const westRouter = `cir-rtr-${random}-west`;

const link = `East to West ${suffix}`;
const linkId = `EC-${upper}-01`;
const linkNumber = `EXT/${upper}/000/EXTL`;
const loopNumber = `LEC-${upper}-0001`;
const fiber = `Dark fiber ${suffix}`;
const fiberId = `EC-${upper}-DF`;
const pair = `cir-pair-${random}`;

/** Search for a location in one side's field of the form, and choose it by its path. */
async function chooseSide(form: Locator, side: "a" | "z", typed: string, path: string) {
  const field = form.locator(`[data-field="${side}_location_hid"]`);
  await field.getByRole("searchbox").fill(typed);
  await field
    .getByRole("list", { name: "Locations that match" })
    .getByRole("button", { name: path, exact: true })
    .click();
  await expect(field.getByTestId(`chosen-${side}_location_hid`)).toHaveText(path);
}

/** Open a circuit from the grid of circuits, by its enterprise circuit ID. */
async function openCircuit(page: Page, enterpriseId: string, name: string) {
  await page.goto(
    `./circuits?filter=${encodeURIComponent(`enterprise_circuit_id:eq:${enterpriseId}`)}`,
  );
  await page.getByTestId("grid-circuits").getByRole("link", { name, exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: new RegExp(`^${name}`) })).toBeVisible();
}

/** The form of a new circuit, opened from the Circuits page. */
async function newCircuit(page: Page): Promise<Locator> {
  await page
    .getByRole("navigation", { name: "Main" })
    .getByRole("link", { name: "Circuits" })
    .click();
  await expect(page.getByRole("heading", { level: 1, name: "Circuits" })).toBeVisible();
  await page.getByRole("button", { name: "New circuit" }).click();
  return region(page, "New circuit");
}

test("S47: a circuit between two locations, with both carriers and a router at each end", async ({
  page,
  account,
}) => {
  test.setTimeout(300_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  await importFile(page, "vendors", `vendors-${suffix}.csv`, ["name"], [[carrier], [exchange]]);
  await importFile(page, "regions", `regions-${suffix}.csv`, ["name"], [[regionName]]);
  await importFile(
    page,
    "sites",
    `sites-${suffix}.csv`,
    ["name", "region"],
    [[siteName, regionName]],
  );
  await importFile(
    page,
    "locations",
    `locations-${suffix}.csv`,
    ["name", "site", "kind"],
    [
      [east, site, "building"],
      [west, site, "building"],
    ],
  );
  await importFile(
    page,
    "items",
    `items-${suffix}.csv`,
    ["hostname", "location"],
    [
      [eastRouter, eastPath],
      [westRouter, westPath],
    ],
  );

  // The circuit: its speed entered as the port and the two rates, its sides chosen as a
  // location is chosen elsewhere, its primary carrier a vendor.
  const form = await newCircuit(page);
  await form.getByLabel("Name (required)").fill(link);
  await form.getByLabel("Enterprise circuit ID").fill(linkId);
  await form.getByLabel("Type").selectOption({ label: "Point-to-point" });
  await form.getByLabel("Port speed (Mbps)").fill("1000");
  await form.getByLabel("Rate down (Mbps)").fill("200");
  await form.getByLabel("Rate up (Mbps)").fill("20");
  await chooseSide(form, "a", east, eastPath);
  await chooseSide(form, "z", west, westPath);
  await form.getByLabel("Carrier", { exact: true }).selectOption({ label: carrier });
  await form.getByLabel("Carrier's circuit number").fill(linkNumber);
  await form.getByRole("button", { name: "Create circuit" }).click();
  await expect(page.getByRole("heading", { level: 1, name: new RegExp(`^${link}`) })).toBeVisible();
  await expect(page.getByTestId("speed")).toContainText("1G / 200M / 20M");
  await expect(page.getByTestId("side-a")).toContainText(eastPath);
  await expect(page.getByTestId("side-z")).toContainText(westPath);
  // A new circuit counts at the side the setting names, A unless an Admin changed it.
  await expect(page.getByTestId("counts-at")).toContainText(site);

  // The local exchange carrier, with the number it gives the circuit.
  const named = region(page, "Name another carrier");
  await named.getByLabel("Carrier (required)").selectOption({ label: exchange });
  await named.getByLabel("Part (required)").selectOption({ label: "Local exchange carrier" });
  await named.getByLabel("Circuit number").fill(loopNumber);
  await named.getByRole("button", { name: "Name the carrier" }).click();
  await expect(page.getByText(`${exchange} is now a carrier of ${link}.`)).toBeVisible();
  const carriers = page.getByTestId("carriers");
  await expect(
    carriers.locator(`tr[data-carrier="${carrier}"] [data-testid="carrier-number"]`),
  ).toHaveText(linkNumber);
  await expect(
    carriers.locator(`tr[data-carrier="${carrier}"] [data-testid="carrier-role"]`),
  ).toHaveText("Primary carrier");
  await expect(
    carriers.locator(`tr[data-carrier="${exchange}"] [data-testid="carrier-number"]`),
  ).toHaveText(loopNumber);

  // A router at each end, chosen from the inventory and connected together.
  const connect = region(page, "Connect devices");
  await connect.getByLabel("Side of what is chosen next").selectOption("a");
  await connect.getByLabel("Add an item").fill(eastRouter);
  await connect
    .getByRole("list", { name: "Items that match" })
    .getByRole("button", { name: new RegExp(`^${eastRouter}`) })
    .click();
  await connect.getByLabel("Side of what is chosen next").selectOption("z");
  await connect.getByLabel("Add an item").fill(westRouter);
  await connect
    .getByRole("list", { name: "Items that match" })
    .getByRole("button", { name: new RegExp(`^${westRouter}`) })
    .click();
  await expect(connect.getByTestId("devices-to-connect").locator("tbody tr")).toHaveCount(2);
  await connect.getByRole("button", { name: "Connect 2 devices" }).click();
  await expect(page.getByText(`2 devices are now connected to ${link}.`)).toBeVisible();
  const devices = page.getByTestId("devices");
  await expect(devices.locator(`tr[data-device="${eastRouter}"]`)).toHaveAttribute(
    "data-side",
    "a",
  );
  await expect(devices.locator(`tr[data-device="${westRouter}"]`)).toHaveAttribute(
    "data-side",
    "z",
  );

  // Each router shows the circuit, with its side.
  await openItem(page, eastRouter);
  const onEast = page.getByTestId("connected-circuits").locator(`tr[data-circuit="${link}"]`);
  await expect(onEast.getByTestId("circuit-side")).toHaveText("A side");
  await openItem(page, westRouter);
  const onWest = page.getByTestId("connected-circuits").locator(`tr[data-circuit="${link}"]`);
  await expect(onWest.getByTestId("circuit-side")).toHaveText("Z side");
  await onWest.getByRole("link", { name: link }).click();
  await expect(page.getByRole("heading", { level: 1, name: new RegExp(`^${link}`) })).toBeVisible();

  // Each location shows it, and so does the site, with the side or the sides there.
  await page.getByTestId("side-a").getByRole("link", { name: eastPath }).click();
  const atEast = page.getByTestId("circuits-here").locator(`tr[data-circuit="${link}"]`);
  await expect(atEast.getByTestId("circuit-sides")).toHaveText("A side");
  await page.goBack();
  await page.getByTestId("side-z").getByRole("link", { name: westPath }).click();
  const atWest = page.getByTestId("circuits-here").locator(`tr[data-circuit="${link}"]`);
  await expect(atWest.getByTestId("circuit-sides")).toHaveText("Z side");
  await page.goBack();
  await page.getByTestId("side-a").getByRole("link", { name: site, exact: true }).click();
  const atSite = page.getByTestId("circuits-here").locator(`tr[data-circuit="${link}"]`);
  await expect(atSite.getByTestId("circuit-sides")).toHaveText("A side, Z side");

  // The grid finds it by any of its carriers' numbers, the other carrier's among them.
  await page.goto(
    `./circuits?filter=${encodeURIComponent(`carriers.circuit_number:eq:${loopNumber}`)}`,
  );
  await expect(page.getByTestId("grid-total")).toHaveText("1 circuit");
  await expect(page.getByTestId("grid-circuits").getByRole("link", { name: link })).toBeVisible();

  await expectClean(page, seen);
});

test("S47: a dark fiber found by its enterprise ID, which no other circuit may have", async ({
  page,
  account,
}) => {
  test.setTimeout(240_000);
  const seen = await watch(page.context());
  await signIn(page, account);

  // Dark fiber that a business partner lets the enterprise use: no carrier's number.
  const form = await newCircuit(page);
  await form.getByLabel("Name (required)").fill(fiber);
  await form.getByLabel("Enterprise circuit ID").fill(fiberId);
  await form.getByLabel("Type").selectOption({ label: "Dark fiber" });
  await chooseSide(form, "a", east, eastPath);
  await chooseSide(form, "z", west, westPath);
  await form.getByRole("button", { name: "Create circuit" }).click();
  await expect(page.getByRole("heading", { level: 1, name: fiber })).toBeVisible();
  await expect(page.getByTestId("enterprise-id")).toHaveText(fiberId);

  // Found by its enterprise ID in the grid of circuits.
  await openCircuit(page, fiberId, fiber);

  // The ID, in other letters, is refused for another circuit, under its field.
  const again = await newCircuit(page);
  await again.getByLabel("Name (required)").fill(`${fiber} copy`);
  await again.getByLabel("Enterprise circuit ID").fill(fiberId.toLowerCase());
  await chooseSide(again, "a", east, eastPath);
  await again.getByLabel("Z side: note").fill("carrier network");
  await again.getByRole("button", { name: "Create circuit" }).click();
  await expect(again.getByLabel("Enterprise circuit ID")).toHaveAttribute("aria-invalid", "true");
  await expect(again.getByText("another circuit has this enterprise circuit ID")).toBeVisible();
  await again.getByRole("button", { name: "Cancel" }).click();

  // Its cost counts at its A side, until it is switched to count at its Z side.
  await openCircuit(page, fiberId, fiber);
  await expect(page.getByTestId("counts-at")).toHaveAttribute("data-side", "a");
  await expect(page.getByTestId("counts-a")).toBeVisible();
  await page.getByRole("button", { name: "Count it at the Z side" }).click();
  await expect(page.getByText(`The cost of ${fiber} now counts at its Z side.`)).toBeVisible();
  await expect(page.getByTestId("counts-at")).toHaveAttribute("data-side", "z");
  await expect(page.getByTestId("counts-z")).toBeVisible();
  await expect(page.getByTestId("counts-a")).toHaveCount(0);
  await expect(page.getByTestId("cost-site")).toHaveText(site);

  // The grid says so too, in the column chosen for it.
  await page.goto(
    `./circuits?filter=${encodeURIComponent(`enterprise_circuit_id:eq:${fiberId} cost_side:eq:z`)}`,
  );
  await expect(page.getByTestId("grid-total")).toHaveText("1 circuit");

  await expectClean(page, seen, ["409 POST"]);
});

test("the parts of a circuit changed: a carrier, the devices, a refused value, retired and back", async ({
  page,
  account,
}) => {
  test.setTimeout(300_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  await importFile(
    page,
    "device_groups",
    `device-groups-${suffix}.csv`,
    ["name", "type", "location"],
    [[pair, "cluster", westPath]],
  );

  // A pair of routers in a group shares the circuit at its Z side.
  await openCircuit(page, linkId, link);
  const connect = region(page, "Connect devices");
  await connect.getByLabel("Side of what is chosen next").selectOption("z");
  await connect.getByLabel("Add a device group").fill(pair);
  await connect
    .getByRole("list", { name: "Device groups that match" })
    .getByRole("button", { name: pair, exact: true })
    .click();
  await connect.getByRole("button", { name: "Connect 1 device" }).click();
  await expect(page.getByText(`${pair} is now connected to ${link}.`)).toBeVisible();
  await openGroup(page, pair);
  const onPair = page.getByTestId("connected-circuits").locator(`tr[data-circuit="${link}"]`);
  await expect(onPair.getByTestId("circuit-side")).toHaveText("Z side");

  // A router moved to the other side, and one disconnected.
  await openCircuit(page, linkId, link);
  const devices = page.getByTestId("devices");
  await devices
    .locator(`tr[data-device="${eastRouter}"]`)
    .getByRole("button", { name: "To the Z side" })
    .click();
  await expect(page.getByText(`${eastRouter} is now on the Z side of ${link}.`)).toBeVisible();
  await expect(devices.locator(`tr[data-device="${eastRouter}"]`)).toHaveAttribute(
    "data-side",
    "z",
  );
  await devices
    .locator(`tr[data-device="${westRouter}"]`)
    .getByRole("button", { name: "Disconnect" })
    .click();
  await page.getByRole("dialog").getByRole("button", { name: "Disconnect" }).click();
  await expect(page.getByText(`${westRouter} is no longer connected to ${link}.`)).toBeVisible();
  await expect(devices.locator(`tr[data-device="${westRouter}"]`)).toHaveCount(0);
  await openItem(page, westRouter);
  await expect(page.getByTestId("connected-circuits")).toContainText(
    "It is connected to no circuit.",
  );

  // The local exchange carrier's number changed, and the carrier then removed.
  await openCircuit(page, linkId, link);
  const carriers = page.getByTestId("carriers");
  await carriers
    .locator(`tr[data-carrier="${exchange}"]`)
    .getByRole("button", { name: "Change" })
    .click();
  const change = region(page, `Change ${exchange}`);
  await change.getByLabel("Circuit number").fill(`${loopNumber}-B`);
  await change.getByRole("button", { name: "Save the carrier" }).click();
  await expect(page.getByText(`${exchange} was saved as a carrier of ${link}.`)).toBeVisible();
  await expect(
    carriers.locator(`tr[data-carrier="${exchange}"] [data-testid="carrier-number"]`),
  ).toHaveText(`${loopNumber}-B`);
  await carriers
    .locator(`tr[data-carrier="${exchange}"]`)
    .getByRole("button", { name: "Remove" })
    .click();
  await page.getByRole("dialog").getByRole("button", { name: "Remove the carrier" }).click();
  await expect(page.getByText(`${exchange} is no longer a carrier of ${link}.`)).toBeVisible();
  await expect(carriers.locator(`tr[data-carrier="${exchange}"]`)).toHaveCount(0);

  // A rate above the port speed is refused by the server, under its field, with its reason.
  const details = region(page, "Details");
  await details.getByLabel("Rate down (Mbps)").fill("2000");
  await details.getByRole("button", { name: "Save" }).click();
  await expect(details.getByLabel("Rate down (Mbps)")).toHaveAttribute("aria-invalid", "true");
  await expect(details.getByText("not more than port_mbps")).toBeVisible();
  await details.getByRole("button", { name: "Undo changes" }).click();

  // Retired, it is marked so and stays on its devices; brought back, it is active again.
  await page.getByRole("button", { name: "Retire this circuit" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Retire", exact: true }).click();
  await expect(page.getByText(`${link} was retired.`)).toBeVisible();
  await expect(page.getByTestId("circuit-status")).toHaveText("Retired");
  await expect(page.getByTestId("in-service")).toHaveText("No");
  await openGroup(page, pair);
  await expect(
    page.getByTestId("connected-circuits").locator(`tr[data-circuit="${link}"]`),
  ).toContainText("Retired");
  await page
    .getByTestId("connected-circuits")
    .getByRole("link", { name: link, exact: true })
    .click();
  await page.getByRole("button", { name: "Bring back" }).click();
  await expect(page.getByText(`${link} is back.`)).toBeVisible();
  await expect(page.getByTestId("circuit-status")).toHaveCount(0);

  await expectClean(page, seen, ["422 PATCH"]);
});
