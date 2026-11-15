// The browser scenarios of support agreements in release 0.6.1:
//
//   D-159  What a contract overrides is said beside what it has in force, from what the
//          server answers: the page of a contract reads no agreement for it. An own value
//          that is the same as the agreement's is still an override, says so, and stays
//          as it is when the agreement's changes.
//   D-160  An earlier term of a contract that was co-termed with its agreement has the
//          dates it had, those of the agreement's term it began in (D-163), shown as
//          inherited. An agreement has a purchase history of its own, and a renewal of it
//          is not a term of the contracts that follow it.
//   D-140  Renewing an agreement, at once and early: the contracts co-termed with it, and
//          the items under them, follow.
//
// It keeps to the rules of support.ts: an account and names of its own, and nothing
// changed that another file reads. The dates are worked out from today, so that the
// agreement is in force whenever the file is run.

import { expect, type Page } from "@playwright/test";
import { inForce, openAgreement, openContract, pickContract } from "./contractSteps";
import { importFile, openItem, region } from "./structure";
import { expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const random = mark("x").slice(2);
const suffix = mark("agreements", random);
const upper = random.toUpperCase();
const year = new Date().getFullYear();

const vendor = `Example Networks ${suffix}`;
const reseller = `Example Reseller ${suffix}`;
const pid = `EN-9300-24P-${suffix}`;
const switchName = `site7-sw-${suffix}-01`;

const agreement = `Example Enterprise Agreement ${suffix}`;
const starts = `${year - 1}-01-01`;
const ends = `${year + 1}-12-31`;
const level = "24x7, four-hour response";
const otherLevel = "8x5, next business day";
const laterLevel = "24x7, two-hour response";
// Co-termed with the agreement: it says nothing of its own.
const coTermed = `CON-${suffix}-A1`;
const coTermedRenewed = `CON-${suffix}-A2`;
// It says of its own what the agreement says too.
const sameAsAgreement = `CON-${suffix}-B1`;
// The agreement renewed at once, and then early.
const renewedStarts = `${year}-01-01`;
const renewedEnds = `${year + 3}-12-31`;
const earlyStarts = `${year + 4}-01-01`;
const earlyEnds = `${year + 5}-12-31`;

/** One field of a contract, in the table of the contracts of the agreement on show. */
function ofAgreement(page: Page, number: string, field: string) {
  return page
    .getByTestId("agreement-contracts")
    .locator(`tr[data-contract="${number}"] [data-field="${field}"]`);
}

test("the vendor, its reseller, a model and a switch in service are loaded from files", async ({
  page,
  account,
}) => {
  test.setTimeout(180_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  await importFile(page, "vendors", `vendors-${suffix}.csv`, ["name"], [[vendor], [reseller]]);
  await importFile(
    page,
    "catalog_entries",
    `catalog-entries-${suffix}.csv`,
    ["vendor", "pid", "model_name", "type"],
    [[vendor, pid, "Example 9300 24-port", "switch"]],
  );
  await importFile(
    page,
    "items",
    `items-${suffix}.csv`,
    ["vendor", "pid", "serial_number", "hostname", "lifecycle_state"],
    [[vendor, pid, `ENA${upper}01`, switchName, "Prod"]],
  );
  await expectClean(page, seen);
});

test("D-159: an override says what the agreement gives, also where the two are the same", async ({
  page,
  account,
}) => {
  test.setTimeout(240_000);
  const seen = await watch(page.context());
  await signIn(page, account);

  // The agreement, with its reseller, its period and its support level.
  await page.goto("./agreements");
  await page.getByRole("button", { name: "New agreement" }).click();
  const made = region(page, "New support agreement");
  await made.getByLabel("Name (required)").fill(agreement);
  await made.getByLabel("Number", { exact: true }).fill(`EA-${upper}-1`);
  await made.getByLabel("Vendor (required)").selectOption({ label: vendor });
  await made.getByLabel("Reseller").selectOption({ label: reseller });
  await made.getByLabel("Starts on").fill(starts);
  await made.getByLabel("Ends on").fill(ends);
  await made.getByLabel("Support level").fill(level);
  await made.getByRole("button", { name: "Create agreement" }).click();
  await expect(page.getByRole("heading", { level: 1, name: agreement })).toBeVisible();
  // A new agreement has no purchase history yet.
  await expect(region(page, "Terms before this one").getByTestId("no-terms")).toBeVisible();

  // Two contracts in it: one that says nothing of its own, and one that is given, as its
  // own, the support level and the reseller the agreement gives.
  for (const number of [coTermed, sameAsAgreement]) {
    await openAgreement(page, agreement);
    await page.getByRole("button", { name: "New contract in this agreement" }).click();
    const form = region(page, `New contract in ${agreement}`);
    await form.getByLabel("Number (required)").fill(number);
    await form.getByRole("button", { name: "Create contract" }).click();
    await expect(page.getByRole("heading", { level: 1, name: number })).toBeVisible();
  }

  // What the page of a contract reads: the contract, and not its agreement, which the
  // server answers beside each value in force.
  const read: string[] = [];
  page.on("request", (request) => {
    const path = new URL(request.url()).pathname;
    if (/\/api\/v1\/agreements\/[^/]+$/.test(path)) read.push(path);
  });
  const details = region(page, "Details");
  await details.getByLabel("Support level").fill(level);
  await details.getByLabel("Reseller").selectOption({ label: reseller });
  await details.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("The contract was saved.")).toBeVisible();
  for (const [field, value] of [
    ["support_level", level],
    ["reseller_hid", reseller],
  ] as const) {
    const shown = inForce(page, field).locator('[data-standing="override"]');
    await expect(shown).toHaveAttribute("data-same", "true");
    await expect(shown).toContainText(value);
    await expect(shown).toContainText("Overrides");
    await expect(shown.getByTestId("override-same")).toContainText("which is the same");
  }
  // The form says so too, under the field.
  await expect(
    details.getByText(
      `Set here, and the same as ${agreement} gives. Clear it to follow ${agreement} when that changes.`,
    ),
  ).toHaveCount(2);
  // The period is still the agreement's.
  await expect(inForce(page, "ends_on")).toHaveAttribute("data-standing", "inherited");

  // Another level of its own is in place of the agreement's, which it names.
  await details.getByLabel("Support level").fill(otherLevel);
  await details.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("The contract was saved.")).toBeVisible();
  const other = inForce(page, "support_level").locator('[data-standing="override"]');
  await expect(other).toHaveAttribute("data-same", "false");
  await expect(other).toContainText(otherLevel);
  await expect(other.locator(".inherited")).toHaveText(level);
  await expect(
    details.getByText(`Set here, in place of ${level} from ${agreement}. Clear it to have that.`),
  ).toBeVisible();
  expect(read, "agreements the page of a contract read").toEqual([]);

  // The agreement lists both, with the same marks.
  await openAgreement(page, agreement);
  await expect(ofAgreement(page, coTermed, "support_level")).toHaveAttribute(
    "data-standing",
    "inherited",
  );
  await expect(ofAgreement(page, sameAsAgreement, "support_level")).toHaveAttribute(
    "data-same",
    "false",
  );
  await expect(ofAgreement(page, sameAsAgreement, "reseller_hid")).toHaveAttribute(
    "data-same",
    "true",
  );

  // The agreement gives another support level. The contract that says nothing of its own
  // has it at once; the one with its own keeps that, and says what it is in place of now.
  const agreementDetails = region(page, "Details");
  await agreementDetails.getByLabel("Support level").fill(laterLevel);
  await agreementDetails.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("The agreement was saved.")).toBeVisible();
  await expect(ofAgreement(page, coTermed, "support_level")).toContainText(laterLevel);
  await expect(ofAgreement(page, sameAsAgreement, "support_level")).toContainText(otherLevel);
  await openContract(page, sameAsAgreement);
  await expect(inForce(page, "support_level").locator(".inherited")).toHaveText(laterLevel);
  await openContract(page, coTermed);
  await expect(inForce(page, "support_level")).toHaveAttribute("data-standing", "inherited");
  await expect(inForce(page, "support_level")).toContainText(laterLevel);

  await expectClean(page, seen);
});

test("D-160, D-140: the dates of an earlier term, the history of the agreement, and the agreement renewed", async ({
  page,
  account,
}) => {
  test.setTimeout(240_000);
  const seen = await watch(page.context());
  await signIn(page, account);

  // The switch is put under the contract that is co-termed with the agreement: its cover
  // runs to the end of the agreement.
  await openItem(page, switchName);
  await page.getByRole("button", { name: "Cover with a contract" }).click();
  const cover = page.getByTestId("cover-items");
  await pickContract(cover, coTermed);
  await cover.getByRole("button", { name: `Cover ${switchName}` }).click();
  await expect(page.getByTestId("item-covered-until")).toHaveText(ends);

  // The contract is renewed with a new number alone: it stays co-termed. The term it had
  // before has the agreement's dates, as they stood then, shown as inherited.
  await openContract(page, coTermed);
  await region(page, "Renew").getByRole("button", { name: "Renew", exact: true }).click();
  const form = page.getByTestId("renew-form");
  await form.getByLabel("New number").fill(coTermedRenewed);
  await form.getByLabel("Purchase reference").fill(`RITM-${upper}-1`);
  await form.getByRole("button", { name: "Renew for 1 item" }).click();
  await expect(page.getByRole("heading", { level: 1, name: coTermedRenewed })).toBeVisible();
  const before = page.getByTestId("contract-terms").locator(`tr[data-term="${coTermed}"]`);
  await expect(before).toBeVisible();
  const [started, ended] = [before.locator("td").nth(0), before.locator("td").nth(1)];
  await expect(started).toHaveText(new RegExp(`^${starts}`));
  await expect(ended).toHaveText(new RegExp(`^${ends}`));
  for (const day of [started, ended]) {
    await expect(day).toHaveAttribute("data-source", "agreement");
    await expect(day).toHaveClass(/inherited/);
    await expect(day).toHaveAttribute("title", new RegExp(`^Inherited from ${agreement}: `));
  }
  await expect(before).toContainText(account.username);

  // The agreement is renewed, in force at once: its own term before is its history, and
  // the contract and the switch follow, with nothing written to either.
  await openAgreement(page, agreement);
  await expect(page.getByTestId("agreement-period")).toHaveText(`${starts} to ${ends}`);
  await region(page, "Renew").getByRole("button", { name: "Renew", exact: true }).click();
  const renewal = page.getByTestId("renew-form");
  await renewal.getByLabel("New number").fill(`EA-${upper}-2`);
  await renewal.getByLabel("New period: starts on").fill(renewedStarts);
  await renewal.getByLabel("New period: ends on").fill(renewedEnds);
  await renewal.getByLabel("Purchase reference").fill(`RITM-${upper}-2`);
  await renewal.getByRole("button", { name: "Renew the agreement" }).click();
  await expect(
    page.getByText(
      `${agreement} was renewed: ${renewedStarts} to ${renewedEnds}. The contracts that are co-termed with it follow.`,
    ),
  ).toBeVisible();
  await expect(page.getByTestId("agreement-period")).toHaveText(
    `${renewedStarts} to ${renewedEnds}`,
  );
  const history = page.getByTestId("agreement-terms").locator(`tr[data-term="EA-${upper}-1"]`);
  await expect(history).toBeVisible();
  await expect(history.locator("td").nth(0)).toHaveText(starts);
  await expect(history.locator("td").nth(1)).toHaveText(ends);
  await expect(history).toContainText(account.username);
  await expect(ofAgreement(page, coTermedRenewed, "ends_on")).toContainText(renewedEnds);

  await openContract(page, coTermedRenewed);
  await expect(inForce(page, "ends_on")).toHaveAttribute("data-standing", "inherited");
  await expect(inForce(page, "ends_on")).toContainText(renewedEnds);
  // The renewal of the agreement is not a term of the contract: it had one renewal, and
  // that term keeps the dates it had.
  await expect(page.getByTestId("contract-terms").locator("tbody tr")).toHaveCount(1);
  await expect(
    page.getByTestId("contract-terms").locator(`tr[data-term="${coTermed}"] td`).nth(1),
  ).toHaveText(new RegExp(`^${ends}`));
  await openItem(page, switchName);
  await expect(page.getByTestId("item-covered-until")).toHaveText(renewedEnds);
  await expect(region(page, "History").locator('tbody[data-action="update"]')).toHaveCount(0);

  // Renewed early, the agreement keeps its present period, and the switch is covered to
  // the end of the term to come.
  await openAgreement(page, agreement);
  await region(page, "Renew").getByRole("button", { name: "Renew", exact: true }).click();
  await renewal.getByLabel("New period: starts on").fill(earlyStarts);
  await renewal.getByLabel("New period: ends on").fill(earlyEnds);
  await renewal.getByRole("button", { name: "Renew the agreement" }).click();
  await expect(page.getByText(/^The renewal is kept as the next term\./)).toBeVisible();
  await expect(
    page.getByRole("heading", { level: 1, name: agreement }).locator('[data-mark="next-term"]'),
  ).toHaveText(`Renewed from ${earlyStarts}`);
  await expect(page.getByTestId("agreement-period")).toHaveText(
    `${renewedStarts} to ${renewedEnds}`,
  );
  await openItem(page, switchName);
  await expect(page.getByTestId("item-covered-until")).toHaveText(earlyEnds);

  // Withdrawn again, the switch is covered to the end of the present term.
  await openAgreement(page, agreement);
  await page
    .getByTestId("next-term")
    .getByRole("button", { name: "Withdraw the next term" })
    .click();
  await page.getByRole("button", { name: "Withdraw", exact: true }).click();
  await expect(
    page.getByText(
      `The next term was withdrawn: ${agreement} keeps its present number and period.`,
    ),
  ).toBeVisible();
  await openItem(page, switchName);
  await expect(page.getByTestId("item-covered-until")).toHaveText(renewedEnds);

  await expectClean(page, seen);
});
