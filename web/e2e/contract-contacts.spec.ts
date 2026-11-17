// The browser scenario of the contacts of agreements and contracts in release 0.7.0
// (P-119, P-132, scenario S43):
//
//   The account manager of an agreement is a contact record, and one contract in it
//   names another of its own. Each contract shows the contact in force with its source:
//   the one that names nobody has the agreement's, shown as inherited; the one that names
//   its own has its own in place of the agreement's. A change of the agreement's contact's
//   telephone number shows on the agreement and on the contract that has it from there,
//   with nothing copied; the contact retired is marked where it is named; and a naming
//   removed gives the contract the agreement's again.
//
// It keeps to the rules of support.ts: an account and names of its own, and nothing
// changed that another file reads.

import { expect, type Locator, type Page } from "@playwright/test";
import { openAgreement, openContract } from "./contractSteps";
import { importFile, region } from "./structure";
import { expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const random = mark("x").slice(2);
const suffix = mark("contract-contacts", random);
const upper = random.toUpperCase();
const year = new Date().getFullYear();

const vendor = `Example Carrier ${suffix}`;
const agreement = `Example Carrier Agreement ${suffix}`;
const inherits = `CON-${upper}-C1`;
const ownContact = `CON-${upper}-C2`;
const manager = `Avery Example ${suffix}`;
const managerMail = `avery-${random}@example.com`;
const other = `Blake Example ${suffix}`;
const otherMail = `blake-${random}@example.com`;

/** The row of a contact in the table of those in force on the page on show. */
function inForceRow(page: Page, name: string): Locator {
  return page.getByTestId("contacts-in-force").locator(`tr[data-contact="${name}"]`);
}

/** Name a contact as the account manager of the agreement or the contract on show. */
async function nameManager(page: Page, name: string, mail: string, of: string) {
  const form = region(page, "Name a contact");
  await form.getByLabel("Contact", { exact: true }).fill(mail.split("@")[0] ?? "");
  await form
    .getByRole("list", { name: "Contacts that match" })
    .getByRole("button", { name: `${name} (${mail})`, exact: true })
    .click();
  await form.getByLabel("Role (required)").selectOption({ label: "Account manager" });
  await form.getByRole("button", { name: "Name the contact" }).click();
  await expect(page.getByText(`${name} is now named as account manager of ${of}.`)).toBeVisible();
}

/** Open a contact from the grid of contacts, by its name. */
async function openContact(page: Page, name: string) {
  await page.goto(`./contacts?filter=${encodeURIComponent(`name:eq:${name}`)}`);
  await page.getByTestId("grid-contacts").getByRole("link", { name, exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
}

test("S43: the contacts in force, own or from the agreement, with their source", async ({
  page,
  account,
}) => {
  test.setTimeout(240_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  await importFile(page, "vendors", `vendors-${suffix}.csv`, ["name"], [[vendor]]);
  await importFile(
    page,
    "contacts",
    `contacts-${suffix}.csv`,
    ["name", "organization", "email", "phone"],
    [
      [manager, vendor, managerMail, "555 0101"],
      [other, vendor, otherMail, "555 0102"],
    ],
  );

  await page.goto("./agreements");
  await page.getByRole("button", { name: "New agreement" }).click();
  const made = region(page, "New support agreement");
  await made.getByLabel("Name (required)").fill(agreement);
  await made.getByLabel("Vendor (required)").selectOption({ label: vendor });
  await made.getByLabel("Starts on").fill(`${year - 1}-01-01`);
  await made.getByLabel("Ends on").fill(`${year + 1}-12-31`);
  await made.getByRole("button", { name: "Create agreement" }).click();
  await expect(page.getByRole("heading", { level: 1, name: agreement })).toBeVisible();
  for (const number of [inherits, ownContact]) {
    await openAgreement(page, agreement);
    await page.getByRole("button", { name: "New contract in this agreement" }).click();
    const form = region(page, `New contract in ${agreement}`);
    await form.getByLabel("Number (required)").fill(number);
    await form.getByRole("button", { name: "Create contract" }).click();
    await expect(page.getByRole("heading", { level: 1, name: number })).toBeVisible();
  }

  // The agreement names its account manager, a contact record.
  await openAgreement(page, agreement);
  await nameManager(page, manager, managerMail, agreement);
  await expect(inForceRow(page, manager)).toHaveAttribute("data-source", "own");
  await expect(inForceRow(page, manager).getByTestId("contact-phone")).toHaveText("555 0101");

  // The contract that names nobody has it from the agreement, with that source.
  await openContract(page, inherits);
  await expect(inForceRow(page, manager)).toHaveAttribute("data-source", "agreement");
  await expect(inForceRow(page, manager)).toHaveClass(/inherited/);
  await expect(inForceRow(page, manager).getByTestId("contact-source")).toHaveText(
    `Inherited from ${agreement}`,
  );
  await expect(
    page.getByTestId("contact-sources").locator('li[data-role="account_manager"]'),
  ).toHaveAttribute("data-source", "agreement");
  await expect(
    page.getByTestId("contact-sources").locator('li[data-role="support_contact"]'),
  ).toHaveAttribute("data-source", "none");

  // The other names its own, in place of the agreement's.
  await openContract(page, ownContact);
  await nameManager(page, other, otherMail, ownContact);
  await expect(inForceRow(page, other)).toHaveAttribute("data-source", "own");
  await expect(inForceRow(page, other).getByTestId("contact-source")).toHaveText("Named here");
  await expect(inForceRow(page, manager)).toHaveCount(0);

  // The telephone number of the agreement's contact is changed on the contact itself:
  // the agreement and the contract that has it from there show it, nothing copied.
  await openContact(page, manager);
  await region(page, "Details").getByLabel("Phone", { exact: true }).fill("555 0109");
  await region(page, "Details").getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("The contact was saved.")).toBeVisible();
  await openAgreement(page, agreement);
  await expect(inForceRow(page, manager).getByTestId("contact-phone")).toHaveText("555 0109");
  await openContract(page, inherits);
  await expect(inForceRow(page, manager).getByTestId("contact-phone")).toHaveText("555 0109");

  // Retired, it stays where it is named, marked so.
  await openContact(page, manager);
  await page.getByRole("button", { name: "Retire contact" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Retire contact" }).click();
  await openContract(page, inherits);
  await expect(inForceRow(page, manager).locator('[data-mark="contact-status"]')).toHaveText(
    "Retired",
  );

  // The naming of the contract's own removed, it has the agreement's again.
  await openContract(page, ownContact);
  await inForceRow(page, other).getByRole("button", { name: "Remove" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Remove the naming" }).click();
  await expect(
    page.getByText(`${other} is no longer named as account manager of ${ownContact}.`),
  ).toBeVisible();
  await expect(inForceRow(page, manager)).toHaveAttribute("data-source", "agreement");
  await expect(inForceRow(page, other)).toHaveCount(0);

  await expectClean(page, seen);
});
