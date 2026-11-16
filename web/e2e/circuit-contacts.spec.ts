// The browser scenario of the contacts of carriers and of circuits in release 0.8.0
// (P-149, scenario S49):
//
//   The A side's site has a site contact; the circuit's carrier has an account manager,
//   named on the carrier's page, and a second circuit of that carrier names its own. The
//   circuit shows the site contacts of each side, resolved from its locations with their
//   source, and the carrier's account manager with the source `vendor`; the second
//   circuit shows its own, and a site contact of its own for its A side, in place of the
//   site's. The carrier's page lists its contacts and its circuits.
//
// It keeps to the rules of support.ts: an account and names of its own, and nothing
// changed that another file reads.

import { expect, type Locator, type Page } from "@playwright/test";
import { importFile, region } from "./structure";
import { expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const random = mark("x").slice(2);
const suffix = mark("circuit-contacts", random);
const upper = random.toUpperCase();

const carrier = `Example Telecom ${suffix}`;
const regionName = `Contact Region ${suffix}`;
const siteName = `Contact Site ${suffix}`;
const site = `${regionName} > ${siteName}`;
const building = `Contact Building ${suffix}`;
const buildingPath = `${site} > ${building}`;
const first = `Contact internet ${suffix}`;
const firstId = `EC-${upper}-K1`;
const second = `Contact backup ${suffix}`;
const secondId = `EC-${upper}-K2`;

const siteContact = `Robin Example ${suffix}`;
const siteMail = `robin-${random}@example.net`;
const manager = `Morgan Example ${suffix}`;
const managerMail = `morgan-${random}@example.org`;
const ownManager = `Avery Example ${suffix}`;
const ownMail = `avery-${random}@example.org`;
const ownSite = `Kai Example ${suffix}`;
const ownSiteMail = `kai-${random}@example.net`;

async function openCircuit(page: Page, enterpriseId: string, name: string) {
  await page.goto(
    `./circuits?filter=${encodeURIComponent(`enterprise_circuit_id:eq:${enterpriseId}`)}`,
  );
  await page.getByTestId("grid-circuits").getByRole("link", { name, exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: new RegExp(`^${name}`) })).toBeVisible();
}

async function openVendor(page: Page) {
  await page.goto(`./vendors?filter=${encodeURIComponent(`name:eq:${carrier}`)}`);
  await page.getByTestId("grid-vendors").getByRole("link", { name: carrier, exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: carrier })).toBeVisible();
}

/** Choose a contact by a part of its address in the form of a naming. */
async function chooseContact(form: Locator, name: string, mail: string) {
  await form.getByLabel("Contact", { exact: true }).fill(mail.split("@")[0] ?? "");
  await form
    .getByRole("list", { name: "Contacts that match" })
    .getByRole("button", { name: `${name} (${mail})`, exact: true })
    .click();
}

/** The row of a contact among the carrier's contacts in force on the circuit on show. */
function carrierRow(page: Page, name: string): Locator {
  return page.getByTestId("carrier-contacts-in-force").locator(`tr[data-contact="${name}"]`);
}

/** The row of a contact among the site contacts of a side of the circuit on show. */
function siteRow(page: Page, side: "a" | "z", name: string): Locator {
  return page.getByTestId(`site-contacts-${side}`).locator(`tr[data-contact="${name}"]`);
}

test("S49: the site contacts of each side and the carrier's account manager, each with its source", async ({
  page,
  account,
}) => {
  test.setTimeout(300_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  await importFile(page, "vendors", `vendors-${suffix}.csv`, ["name"], [[carrier]]);
  await importFile(
    page,
    "contacts",
    `contacts-${suffix}.csv`,
    ["name", "organization", "email", "phone"],
    [
      [siteContact, "", siteMail, "555 0110"],
      [manager, carrier, managerMail, "555 0120"],
      [ownManager, carrier, ownMail, "555 0130"],
      [ownSite, "", ownSiteMail, "555 0140"],
    ],
  );
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
    [[building, site, "building"]],
  );
  // The A side's site has a site contact.
  await importFile(
    page,
    "contact_assignments",
    `contact-assignments-${suffix}.csv`,
    ["site", "role", "contact", "priority"],
    [[site, "technical", siteMail, "1"]],
  );
  await importFile(
    page,
    "circuits",
    `circuits-${suffix}.csv`,
    ["name", "enterprise_circuit_id", "a_location", "z_note", "carrier"],
    [
      [first, firstId, buildingPath, "carrier network", carrier],
      [second, secondId, buildingPath, "carrier network", carrier],
    ],
  );

  // The carrier names its account manager once, on its own page.
  await openVendor(page);
  const naming = region(page, "Name a contact");
  await chooseContact(naming, manager, managerMail);
  await naming.getByLabel("Role (required)").selectOption({ label: "Account manager" });
  await naming.getByRole("button", { name: "Name the contact" }).click();
  await expect(
    page.getByText(`${manager} is now named as account manager of ${carrier}.`),
  ).toBeVisible();
  await expect(
    page.getByTestId("vendor-contacts").locator(`tr[data-contact="${manager}"]`),
  ).toHaveAttribute("data-role", "account_manager");
  // Its page lists its circuits.
  await expect(
    page.getByTestId("grid-vendor-circuits").getByRole("link", { name: first, exact: true }),
  ).toBeVisible();
  await expect(
    page.getByTestId("grid-vendor-circuits").getByRole("link", { name: second, exact: true }),
  ).toBeVisible();

  // The first circuit has the carrier's account manager, with the source `vendor`.
  await openCircuit(page, firstId, first);
  await expect(carrierRow(page, manager)).toHaveAttribute("data-source", "vendor");
  await expect(carrierRow(page, manager)).toHaveClass(/inherited/);
  await expect(carrierRow(page, manager).getByTestId("contact-source")).toHaveText(
    `From the carrier ${carrier}`,
  );
  await expect(carrierRow(page, manager).getByTestId("contact-phone")).toHaveText("555 0120");
  await expect(
    page.getByTestId("carrier-contact-sources").locator('li[data-role="account_manager"]'),
  ).toHaveAttribute("data-source", "vendor");
  await expect(
    page.getByTestId("carrier-contact-sources").locator('li[data-role="support_contact"]'),
  ).toHaveAttribute("data-source", "none");
  // The site contacts of the A side come from its site, with that level; the Z side,
  // which ends in the carrier's network, has none.
  await expect(siteRow(page, "a", siteContact)).toHaveAttribute("data-source", "site");
  await expect(siteRow(page, "a", siteContact)).toHaveAttribute("data-role", "technical");
  await expect(siteRow(page, "a", siteContact).getByTestId("contact-source")).toHaveText(
    `From its site, ${site}`,
  );
  await expect(page.getByTestId("site-contacts-z")).toContainText("This side has no location");

  // The second circuit names its own account manager, in place of the carrier's, and a
  // site contact of its own for its A side, in place of the site's.
  await openCircuit(page, secondId, second);
  const own = region(page, "Name a contact");
  await chooseContact(own, ownManager, ownMail);
  await own.getByLabel("Role (required)").selectOption({ label: "Account manager" });
  await own.getByRole("button", { name: "Name the contact" }).click();
  await expect(
    page.getByText(`${ownManager} is now named as account manager of ${second}.`),
  ).toBeVisible();
  await expect(carrierRow(page, ownManager)).toHaveAttribute("data-source", "own");
  await expect(carrierRow(page, ownManager).getByTestId("contact-source")).toHaveText("Named here");
  await expect(carrierRow(page, manager)).toHaveCount(0);

  await chooseContact(own, ownSite, ownSiteMail);
  await own
    .getByLabel("For", { exact: true })
    .selectOption({ label: "A site contact of the A side" });
  await own.getByLabel("Role (required)").selectOption({ label: "Technical" });
  await own.getByRole("button", { name: "Name the contact" }).click();
  await expect(page.getByText(`${ownSite} is now named as technical of ${second}.`)).toBeVisible();
  await expect(siteRow(page, "a", ownSite)).toHaveAttribute("data-source", "own");
  await expect(siteRow(page, "a", siteContact)).toHaveCount(0);

  // The first circuit still has the carrier's and the site's.
  await openCircuit(page, firstId, first);
  await expect(carrierRow(page, manager)).toHaveAttribute("data-source", "vendor");
  await expect(siteRow(page, "a", siteContact)).toHaveAttribute("data-source", "site");

  // The naming of its own removed, the second circuit has the carrier's again.
  await openCircuit(page, secondId, second);
  await page
    .getByTestId("own-contacts")
    .locator(`tr[data-contact="${ownManager}"]`)
    .getByRole("button", { name: "Remove" })
    .click();
  await page.getByRole("dialog").getByRole("button", { name: "Remove the naming" }).click();
  await expect(
    page.getByText(`${ownManager} is no longer named as account manager of ${second}.`),
  ).toBeVisible();
  await expect(carrierRow(page, manager)).toHaveAttribute("data-source", "vendor");
  await expect(siteRow(page, "a", ownSite)).toHaveAttribute("data-source", "own");

  await expectClean(page, seen);
});
