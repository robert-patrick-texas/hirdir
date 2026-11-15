// The browser scenarios of renewals in release 0.7.0:
//
//   P-129  An agreement renewed with its members: each contract that shares its period is
//          listed in the form of the renewal, one kept under its number, one given a new
//          number that begins with the new term, and one let go with this term, which
//          takes the present term's dates as its own and is marked not to renew. The
//          answer says what was done with each. No member's status is changed: one that
//          still says Renewal pending is listed to review in the answer, on the agreement
//          and on the worklist, and is made active there by a person.
//   P-130  A contract's history in parts: an earlier part with its days, what began it and
//          the agreement it was in, and the present part with the day it began and how,
//          by a renewal, by joining an agreement and by leaving it.
//   P-127  The worklist: the counts of each list first, of the whole and of each vendor
//          and agreement, each leading to its rows, which are read when the list is
//          opened; a renewal pending for too long is marked overdue.
//
// It keeps to the rules of support.ts: an account and names of its own, and nothing
// changed that another file reads. The worklist is read with a filter of this file's
// vendor, so that it counts this file's contracts alone. The dates are worked out from
// today, far enough from the edges of each list that the zone of the day does not matter.

import { expect, type Page } from "@playwright/test";
import { dayAfter, gridRow, inForce, openAgreement, openContract } from "./contractSteps";
import { importFile, region } from "./structure";
import { expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const random = mark("x").slice(2);
const suffix = mark("renewals", random);
const upper = random.toUpperCase();
const year = new Date().getFullYear();
const today = new Date().toISOString().slice(0, 10);

const vendor = `Example Renewals ${suffix}`;
const agreement = `Example Campus Agreement ${suffix}`;
const starts = `${year - 1}-01-01`;
const ends = `${year + 1}-12-31`;
const renewedStarts = `${year}-01-01`;
const renewedEnds = `${year + 3}-12-31`;

// The members of the agreement: kept, given a new number, and let go.
const kept = `CON-${upper}-K1`;
const renumbered = `CON-${upper}-N1`;
const newNumber = `CON-${upper}-N2`;
const letGo = `CON-${upper}-E1`;
// A member whose renewal is pending: the renewal of the agreement leaves it to review.
const stillPending = `CON-${upper}-P1`;

// A contract that stands by itself, renewed, then rolled into the agreement and out.
const history = `CON-${upper}-H1`;
const historyRenewed = `CON-${upper}-H2`;

// The contracts of the worklist, each on one list.
const ending = `CON-${upper}-W1`;
const lapsed = `CON-${upper}-W2`;
const pending = `CON-${upper}-W3`;
const ended = `CON-${upper}-W4`;

interface Made {
  number: string;
  starts: string;
  ends: string;
  status?: string;
  endsWithTerm?: boolean;
}

/** Make a contract that stands by itself, with its status and its mark, and open it. */
async function makeContract(page: Page, made: Made) {
  await page.goto("./contracts");
  await page.getByRole("button", { name: "New contract" }).click();
  const form = region(page, "New contract");
  await form.getByLabel("Number (required)").fill(made.number);
  await form.getByLabel("Vendor", { exact: true }).selectOption({ label: vendor });
  if (made.status) await form.getByLabel("Status", { exact: true }).selectOption(made.status);
  await form.getByLabel("Starts on").fill(made.starts);
  await form.getByLabel("Ends on").fill(made.ends);
  if (made.endsWithTerm) await form.getByLabel("Not to be renewed: the team's note").check();
  await form.getByRole("button", { name: "Create contract" }).click();
  await expect(page.getByRole("heading", { level: 1, name: made.number })).toBeVisible();
}

test("P-129: an agreement renewed, with a member given a new number and one let go", async ({
  page,
  account,
}) => {
  test.setTimeout(240_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  await importFile(page, "vendors", `vendors-${suffix}.csv`, ["name"], [[vendor]]);

  await page.goto("./agreements");
  await page.getByRole("button", { name: "New agreement" }).click();
  const made = region(page, "New support agreement");
  await made.getByLabel("Name (required)").fill(agreement);
  await made.getByLabel("Number", { exact: true }).fill(`EA-${upper}-1`);
  await made.getByLabel("Vendor (required)").selectOption({ label: vendor });
  await made.getByLabel("Starts on").fill(starts);
  await made.getByLabel("Ends on").fill(ends);
  await made.getByRole("button", { name: "Create agreement" }).click();
  await expect(page.getByRole("heading", { level: 1, name: agreement })).toBeVisible();

  // Four contracts in it that say nothing of their dates: each shares its period. One
  // says that its renewal is pending.
  for (const number of [kept, renumbered, letGo, stillPending]) {
    await openAgreement(page, agreement);
    await page.getByRole("button", { name: "New contract in this agreement" }).click();
    const form = region(page, `New contract in ${agreement}`);
    await form.getByLabel("Number (required)").fill(number);
    if (number === stillPending) {
      await form.getByLabel("Status", { exact: true }).selectOption("renewal_pending");
    }
    await form.getByRole("button", { name: "Create contract" }).click();
    await expect(page.getByRole("heading", { level: 1, name: number })).toBeVisible();
  }

  // The renewal lists each, kept under its number until something else is chosen.
  await openAgreement(page, agreement);
  await region(page, "Renew").getByRole("button", { name: "Renew", exact: true }).click();
  const form = page.getByTestId("renew-form");
  const members = form.getByTestId("renew-members-table");
  for (const number of [kept, renumbered, letGo, stillPending]) {
    await expect(members.locator(`tr[data-member="${number}"]`)).toHaveAttribute(
      "data-choice",
      "same",
    );
  }
  await form.getByLabel("New number", { exact: true }).fill(`EA-${upper}-2`);
  await form.getByLabel("New period: starts on").fill(renewedStarts);
  await form.getByLabel("New period: ends on").fill(renewedEnds);
  await form
    .getByLabel(`What the renewal does with ${renumbered}`)
    .selectOption({ label: "A new number" });
  await form.getByLabel(`New number of ${renumbered}`).fill(newNumber);
  await form.getByLabel(`Annual cost of ${renumbered}`).fill("1200.00");
  await form.getByLabel(`Purchase reference of ${renumbered}`).fill(`RITM-${upper}-2`);
  await form
    .getByLabel(`What the renewal does with ${letGo}`)
    .selectOption({ label: "End with this term" });
  await form.getByRole("button", { name: "Renew the agreement" }).click();

  // The answer says what was done with each.
  await expect(
    page.getByText(
      `${agreement} was renewed: ${renewedStarts} to ${renewedEnds}. The contracts that are co-termed with it follow.`,
    ),
  ).toBeVisible();
  await expect(page.getByText(`${kept} keeps its number.`)).toBeVisible();
  await expect(
    page.getByText(`${renumbered} takes the new number ${newNumber} with the new term.`),
  ).toBeVisible();
  await expect(page.getByText(`${letGo} ends with this term.`)).toBeVisible();
  await expect(page.getByTestId("agreement-period")).toHaveText(
    `${renewedStarts} to ${renewedEnds}`,
  );

  // The renewal changed no member's status: the one still pending is to be reviewed, in
  // the answer, on the agreement, and on the worklist.
  await expect(page.getByTestId("renewal-to-review")).toContainText(
    "1 member still says renewal pending or expired",
  );
  await expect(
    page.getByTestId("renewal-to-review").getByRole("link", { name: stillPending, exact: true }),
  ).toBeVisible();
  const review = page.getByTestId("members-to-review");
  await expect(review.locator(`tr[data-contract="${stillPending}"]`)).toHaveAttribute(
    "data-status",
    "renewal_pending",
  );
  await page.goto(
    `./contracts/renewals?${new URLSearchParams({ filter: `vendor:eq:${vendor}` }).toString()}`,
  );
  await expect(page.getByTestId("renewals-count-to_review")).toHaveAttribute("data-count", "1");
  await page.getByTestId("renewals-count-to_review").getByRole("link").click();
  await expect(gridRow(page, "grid-renewals-to_review", stillPending)).toBeVisible();

  // Made active by a person, on the agreement's page, it is reviewed.
  await openAgreement(page, agreement);
  await page
    .getByTestId("members-to-review")
    .locator(`tr[data-contract="${stillPending}"]`)
    .getByRole("button", { name: /^Make active/ })
    .click();
  await expect(
    page.getByText(`${stillPending} is Active again, under ${agreement}.`),
  ).toBeVisible();
  await expect(page.getByTestId("members-to-review")).toHaveCount(0);

  // The one let go stays in the agreement, marked, with the present term as its own.
  const table = page.getByTestId("agreement-contracts");
  await expect(
    table.locator(`tr[data-contract="${letGo}"] [data-mark="ends-with-term"]`),
  ).toBeVisible();
  await expect(table.locator(`tr[data-contract="${newNumber}"]`)).toBeVisible();
  await expect(table.locator(`tr[data-contract="${kept}"] [data-field="ends_on"]`)).toHaveAttribute(
    "data-standing",
    "inherited",
  );
  await openContract(page, letGo);
  await expect(
    page.getByRole("heading", { level: 1, name: letGo }).locator('[data-mark="ends-with-term"]'),
  ).toHaveText("Not to be renewed");
  await expect(page.getByTestId("ends-with-term")).toContainText("Marked not to renew");
  // A note of the team: it changes no status.
  await expect(page.getByTestId("contract-status")).toHaveAttribute("data-status", "active");
  await expect(inForce(page, "ends_on")).toContainText(ends);
  await expect(inForce(page, "ends_on")).toHaveAttribute("data-standing", "override");
  // Its form says so, to be taken off by hand.
  await expect(
    region(page, "Details").getByLabel("Not to be renewed: the team's note"),
  ).toBeChecked();

  // The one given a new number was renewed at once, as the agreement's new term is in
  // force: its number before is the part of its history before this one.
  await openContract(page, newNumber);
  await expect(page.getByTestId("contract-part")).toHaveAttribute("data-began-by", "renewal");
  const before = page.getByTestId("contract-terms").locator(`tr[data-term="${renumbered}"]`);
  await expect(before).toHaveAttribute("data-began-by", "created");
  await expect(before.locator('[data-part="agreement"]')).toHaveAttribute(
    "data-agreement",
    agreement,
  );
  await expect(inForce(page, "ends_on")).toHaveAttribute("data-standing", "inherited");
  await expect(inForce(page, "ends_on")).toContainText(renewedEnds);

  await expectClean(page, seen);
});

test("P-130: a contract's history in parts, by a renewal, by joining and by leaving", async ({
  page,
  account,
}) => {
  test.setTimeout(180_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  await makeContract(page, { number: history, starts, ends });
  await expect(page.getByTestId("no-terms")).toBeVisible();
  await expect(page.getByTestId("contract-part")).toHaveAttribute("data-began-by", "created");

  // Renewed under a new number: the part before is listed, as of this day.
  await region(page, "Renew").getByRole("button", { name: "Renew", exact: true }).click();
  const form = page.getByTestId("renew-form");
  await form.getByLabel("New number").fill(historyRenewed);
  await form.getByRole("button", { name: "Renew for 0 items" }).click();
  await expect(page.getByRole("heading", { level: 1, name: historyRenewed })).toBeVisible();
  const terms = page.getByTestId("contract-terms");
  const first = terms.locator(`tr[data-term="${history}"]`);
  await expect(first).toHaveAttribute("data-began-by", "created");
  await expect(first.locator('[data-part="began-by"]')).toHaveText("Made");
  await expect(first.locator('[data-part="agreement"]')).toContainText("Standing by itself");
  await expect(page.getByTestId("contract-part")).toHaveAttribute("data-began-by", "renewal");

  // Rolled into the agreement, its present part began by joining it. The part of the
  // renewal lasted no day, and is not listed.
  const into = region(page, "Support agreement");
  await into.getByLabel("Put it into").selectOption({ label: `${agreement} (${vendor})` });
  await into.getByRole("button", { name: "Put into the agreement" }).click();
  await expect(page.getByTestId("contract-agreement")).toHaveText(agreement);
  await expect(page.getByTestId("contract-part")).toHaveAttribute("data-began-by", "joined");
  await expect(page.getByTestId("contract-part")).toContainText("joining an agreement");
  await expect(terms.locator("tbody tr")).toHaveCount(1);

  // Taken out again, it began its present part by leaving.
  await region(page, "Support agreement")
    .getByRole("button", { name: `Take out of ${agreement}` })
    .click();
  await expect(page.getByTestId("contract-part")).toHaveAttribute("data-began-by", "left");
  await expect(page.getByTestId("contract-part")).toHaveAttribute("data-began-on", /^\d{4}-/);

  await expectClean(page, seen);
});

test("P-127: the worklist counts first, by vendor, and a list's rows when it is opened", async ({
  page,
  account,
}) => {
  test.setTimeout(240_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  await makeContract(page, { number: ending, starts, ends: dayAfter(today, 30) });
  await makeContract(page, { number: lapsed, starts, ends: dayAfter(today, -10) });
  await makeContract(page, {
    number: pending,
    starts,
    ends: dayAfter(today, -100),
    status: "renewal_pending",
  });
  // Pending for longer than the 60 days of renewal_pending_overdue_days: overdue.
  const days = page.getByTestId("renewal-pending-days");
  await expect(days).toHaveAttribute("data-overdue", "true");
  await expect(days.locator('[data-mark="overdue"]')).toHaveText("Overdue");
  await makeContract(page, {
    number: ended,
    starts,
    ends: dayAfter(today, 40),
    endsWithTerm: true,
  });
  await expect(
    page.getByRole("heading", { level: 1, name: ended }).locator('[data-mark="ends-with-term"]'),
  ).toBeVisible();

  // The worklist of this file's vendor: the counts, and no list until one is opened.
  const asked = new URLSearchParams({ filter: `vendor:eq:${vendor}` });
  const read: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname.endsWith("/api/v1/contracts")) read.push(url.search);
  });
  await page.goto(`./contracts/renewals?${asked.toString()}`);
  await expect(page.getByRole("heading", { level: 1, name: "Renewals" })).toBeVisible();
  for (const [list, count] of [
    ["ending", "1"],
    ["lapsed", "1"],
    ["renewal_pending", "1"],
    ["overdue", "1"],
    ["ends_with_term", "1"],
    ["overlapping", "0"],
  ] as const) {
    await expect(page.getByTestId(`renewals-count-${list}`)).toHaveAttribute("data-count", count);
  }
  await expect(page.getByTestId("renewal-open")).toHaveCount(0);
  expect(read, "lists of contracts read before one was opened").toEqual([]);

  // The contracts that stand by themselves, under their vendor.
  const alone = page
    .getByTestId("renewal-groups")
    .locator(`tr[data-vendor="${vendor}"][data-agreement=""]`);
  await expect(alone.locator('[data-section="ending"]')).toHaveAttribute("data-count", "1");
  await expect(alone.locator('[data-section="renewal_pending"]')).toHaveAttribute(
    "data-count",
    "1",
  );

  // A count opens its rows: how long the renewal has been pending, and overdue.
  await page.getByTestId("renewals-count-renewal_pending").getByRole("link").click();
  await expect(page.getByTestId("renewal-open")).toHaveAttribute("data-section", "renewal_pending");
  const row = gridRow(page, "grid-renewals-renewal_pending", pending);
  await expect(row.locator('[col-id="renewal_overdue"]')).toHaveText("Overdue");
  await expect(row.locator('[col-id="renewal_pending_days"]')).toHaveText(/^\d+ days$/);
  await expect(page.getByTestId("grid-total")).toHaveText("1 contract");

  // The count of the vendor's own contracts opens the list of that group alone.
  await alone.locator('[data-section="ending"]').getByRole("link").click();
  await expect(page.getByRole("heading", { level: 2, name: /^Ending soon: / })).toContainText(
    vendor,
  );
  await expect(gridRow(page, "grid-renewals-ending", ending)).toBeVisible();
  await expect(
    gridRow(page, "grid-renewals-ending", ending).locator('[col-id="effective.ends_on"]'),
  ).toHaveText(dayAfter(today, 30));

  // What is let go is listed by itself, and never in the alert.
  await page.getByTestId("renewals-count-ends_with_term").getByRole("link").click();
  await expect(gridRow(page, "grid-renewals-ends_with_term", ended)).toBeVisible();

  await expectClean(page, seen);
});
