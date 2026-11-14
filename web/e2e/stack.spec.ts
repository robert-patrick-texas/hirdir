// The browser scenarios of release 0.4.0, as release 0.4.1 has them, for a stack and for
// addresses: what a person does in S19 to S21 and in S23.
//
//   S19  A stack of four switches with one marked as the intended master shows that
//        master's serial number; another member is recorded as the master that is seen,
//        and the stack shows that one's at once. It is found by the serial number of any
//        member.
//   S20  The stack weighs 2.00 under the global discount of 50, and 2.80 with 30 set on
//        its model; four components and one managed node throughout; the annual support
//        cost, read from the management report, is that of four switches.
//   S21  The stack's master is replaced for an RMA: two item records linked by the
//        replacement, the departed switch's membership ended, the stack's HID unchanged.
//   S23  The same address under two networks, then twice under one: all are accepted,
//        and only the pair under one network is in the report of duplicates.
//
// And what 0.4.1 added: a stack has a health; a record has a primary management address
// of each family; the summary holds no money, which is in the management report.
//
// On the way: the files of the catalog, the owners and the items on the Import page, a
// membership changed, an address marked as primary, changed and removed, a network
// renamed and removed.
//
// The scenarios of an item and what is in it are in minor-items.spec.ts, and those of a
// controller domain in wireless.spec.ts. The three were one file, and are three so that
// they run side by side: each loads the catalog and the items it needs, under names of
// its own.
//
// The environment that names the server and the Admin is described in support.ts, with
// what a spec file does to be run beside the others: this one signs in as an Admin of its
// own, and every summary, report and grid it counts in is filtered down to what it made.
// Every name, serial number and address below is made up, with the mark of this file and
// a random part, so that the scenarios can be run again on the same server. The
// addresses are of the ranges reserved for documentation. The scenarios run in order:
// the later ones use what the earlier ones made.

import { randomBytes } from "node:crypto";
import { expect, type Page } from "@playwright/test";
import {
  freshGrid,
  importFile,
  main,
  memberRow,
  openGroup,
  openItem,
  pick,
  region,
  summary,
} from "./structure";
import { expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

// The random part by itself is what the addresses below are made from.
const random = randomBytes(3).toString("hex");
const suffix = mark("stack", random);
const upper = suffix.toUpperCase();
const vendor = `Example Networks ${suffix}`;
const switchPid = `EN-9300-48P-${suffix}`;
const engineering = `Network Engineering ${suffix}`;
const campus = `Campus Services ${suffix}`;

// S19 to S21: a stack of four, and the switch that replaces its master.
const stackPrefix = `site2-sw-stk-${suffix}`;
const stackHosts = [1, 2, 3, 4].map((place) => `${stackPrefix}-0${place}`);
const stackSerials = [1, 2, 3, 4].map((place) => `ENS${upper}0${place}`);
const stack = `site2-sw-stack-${suffix}`;
const spare = `${stackPrefix}-09`;
const spareSerial = `ENS${upper}09`;

// S23: networks and addresses. The address is in the range reserved for documentation,
// and written as the server stores it: lower case, with no leading zeros in a group.
const red = `Red ${suffix}`;
const black = `Black ${suffix}`;
const shared = `2001:db8:${Number.parseInt(random.slice(0, 4), 16).toString(16)}:${Number.parseInt(
  random.slice(4),
  16,
).toString(16)}::10`;
const second = shared.replace(/::10$/, "::11");
// An IPv4 address beside them, for the primary of the other family.
const fourth = `192.0.2.${(Number.parseInt(random.slice(0, 2), 16) % 250) + 2}`;

/** The management report of the items a filter keeps: the money, and nothing of health. */
async function management(page: Page, filter: string, by = "") {
  const query = new URLSearchParams({ filter, ...(by ? { by } : {}) });
  await page.goto(`./reports/management?${query.toString()}`);
  await expect(page.getByRole("heading", { level: 1, name: "Management report" })).toBeVisible();
  await expect(page.getByTestId("management-totals")).toBeVisible();
}

test("the catalog, the owners and the switches of the stack are loaded from files", async ({
  page,
  account,
}) => {
  test.setTimeout(180_000);
  const seen = await watch(page.context());
  await signIn(page, account);

  await importFile(
    page,
    "catalog_entries",
    `catalog-entries-${suffix}.csv`,
    ["vendor", "pid", "model_name", "type", "est_value", "support_weight", "annual_support_cost"],
    [[vendor, switchPid, "Example 9300 48-port", "switch", "18000.00", "1.00", "1200.00"]],
  );
  await importFile(
    page,
    "owners",
    `owners-${suffix}.csv`,
    ["label", "organization"],
    [
      [engineering, "Example Operations"],
      [campus, "Example Operations"],
    ],
  );
  // The four switches of the stack, in Prod so that they carry weight.
  await importFile(
    page,
    "items",
    `items-${suffix}-stack.csv`,
    ["vendor", "pid", "serial_number", "hostname", "lifecycle_state", "owner"],
    stackHosts.map((host, place) => [
      vendor,
      switchPid,
      stackSerials[place] ?? "",
      host,
      "Prod",
      engineering,
    ]),
  );
  await expectClean(page, seen);
});

test("S19, S20: the two masters of a stack, its serial number, its health and its discount", async ({
  page,
  account,
}) => {
  test.setTimeout(300_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  const filter = `group.name:eq:${stack}`;
  const [one = "", two = "", three = "", four = ""] = stackHosts;

  // A stack of four, made with its members by one request.
  await main(page).getByRole("link", { name: "Groups" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Groups" })).toBeVisible();
  await page.getByRole("button", { name: "New group" }).click();
  const form = region(page, "New group");
  await form.getByLabel("Name (required)").fill(stack);
  await form.getByLabel("Type").selectOption("stack");
  // Only a cluster says how it is managed: a stack is always one managed node.
  await expect(form.getByLabel("Managed as")).toHaveCount(0);
  await form.getByLabel("Hostname").fill(stack);
  await form.getByLabel("Owner").selectOption({ label: engineering });
  for (const host of stackHosts) {
    await pick(form, "Find an item to add", stackPrefix, host);
  }
  const pending = page.getByTestId("pending-members").locator("tbody tr");
  await expect(pending).toHaveCount(4);
  // Each was given the next position. A stack needs no master: nothing is said of that.
  await expect(form.getByLabel(`Position of ${four}`)).toHaveValue("4");
  await expect(page.getByTestId("stack-problem")).toHaveCount(0);
  // Two intended masters in one request is the one thing the page warns of.
  await form.getByLabel(`Role of ${one}`).selectOption("master");
  await form.getByLabel(`Role of ${two}`).selectOption("master");
  await expect(page.getByTestId("stack-problem")).toContainText("at most one intended master");
  await form.getByLabel(`Role of ${two}`).selectOption("member");
  await expect(page.getByTestId("stack-problem")).toHaveCount(0);
  await form.getByRole("button", { name: "Create group" }).click();
  await expect(page.getByRole("heading", { level: 1, name: stack })).toBeVisible();
  const stackPath = new URL(page.url()).pathname;

  // S19. The stack shows the serial number of its intended master, and says which it is from.
  const serial = page.getByTestId("group-serial");
  const source = page.getByTestId("serial-source");
  await expect(serial).toHaveText(stackSerials[0] ?? "");
  await expect(source).toHaveAttribute("data-source", "intended");
  await expect(source).toContainText("read from the intended master");
  await expect(page.getByTestId("group-master")).toContainText(one);
  await expect(page.getByTestId("group-observed-master")).toHaveText("Nobody has recorded one");
  await expect(page.getByTestId("master-differs")).toHaveCount(0);
  await expect(page.getByTestId("member-count")).toHaveText("4 current members");
  await expect(page.getByTestId("members").locator("tbody tr")).toHaveCount(4);
  await expect(memberRow(page, one)).toHaveAttribute("data-role", "master");
  // Nobody disagrees about the owner: every member has the owner the stack has.
  await expect(page.getByTestId("group-owner")).toHaveAttribute("data-disputed", "false");

  // Another member is recorded as the master that is seen: the serial number is that
  // one's at once. The intended master keeps its mark, and the page says the two differ.
  const seenMaster = region(page, "The master that is seen");
  await seenMaster.getByLabel("Member seen as master").selectOption({ label: `2: ${two}` });
  await seenMaster.getByRole("button", { name: "Record the master that is seen" }).click();
  await expect(
    page.getByText(`${two} is recorded as the master that is seen of ${stack}.`),
  ).toBeVisible();
  await expect(serial).toHaveText(stackSerials[1] ?? "");
  await expect(source).toHaveAttribute("data-source", "observed");
  await expect(source).toContainText("read from the master that is seen");
  await expect(page.getByTestId("group-observed-master")).toContainText(two);
  await expect(page.getByTestId("group-observed-master").locator("time")).toBeVisible();
  await expect(page.getByTestId("group-master")).toContainText(one);
  await expect(memberRow(page, one)).toHaveAttribute("data-role", "master");
  await expect(memberRow(page, two)).toHaveAttribute("data-role", "member");
  await expect(memberRow(page, two)).toHaveAttribute("data-seen-master", "true");
  await expect(memberRow(page, two)).toContainText("Seen as master");
  const differs = page.getByTestId("master-differs");
  await expect(differs).toContainText("The master that is seen is not the one intended.");
  await expect(differs).toContainText("this is no fault");
  // Seen again, with the present moment.
  await region(page, "The master that is seen").getByRole("button", { name: "Seen now" }).click();
  await expect(page.getByText(`${two} was seen as the master again, now.`)).toBeVisible();

  // The stack is found by the serial number of any of its current members.
  for (const memberSerial of [stackSerials[2] ?? "", stackSerials[0] ?? ""]) {
    await page.goto(
      `./groups?filter=${encodeURIComponent(`member.serial_number:eq:${memberSerial}`)}`,
    );
    await expect(page.getByTestId("grid-total")).toHaveText("1 group");
    const found = page.getByTestId("grid-device-groups").locator("[row-id]").first();
    await expect(found.getByRole("link", { name: stack, exact: true })).toBeVisible();
    // The grid shows the serial number the stack answers with: the observed master's.
    await expect(found.locator('[col-id="serial_number"]')).toHaveText(stackSerials[1] ?? "");
    await expect(found.locator('[col-id="type"]')).toHaveText("Stack");
    await expect(found.locator('[col-id="member_count"]')).toHaveText("4");
  }

  // The mark of the intended master moves to another member by one change, and takes the
  // mark from the one that had it. The two masters then agree, and nothing is said.
  await openGroup(page, stack);
  await memberRow(page, two)
    .getByRole("button", { name: `Mark ${two} as the intended master` })
    .click();
  await expect(page.getByText(`${two} is now the intended master of ${stack}.`)).toBeVisible();
  await expect(memberRow(page, two)).toHaveAttribute("data-role", "master");
  await expect(memberRow(page, one)).toHaveAttribute("data-role", "member");
  await expect(page.getByTestId("master-differs")).toHaveCount(0);
  await expect(serial).toHaveText(stackSerials[1] ?? "");
  // The intended master is optional: the mark is taken off, and the stack stands.
  await memberRow(page, two)
    .getByRole("button", { name: `Change the membership of ${two}` })
    .click();
  const change = region(page, `The membership of ${two}`);
  await change.getByLabel("Role").selectOption("member");
  await change.getByRole("button", { name: "Save membership" }).click();
  await expect(page.getByText(`The membership of ${two} was saved.`)).toBeVisible();
  await expect(page.getByTestId("group-master")).toHaveText("None is marked");
  await expect(page.getByTestId("members").locator('tbody tr[data-role="master"]')).toHaveCount(0);
  // The serial number is still read from the master that is seen.
  await expect(serial).toHaveText(stackSerials[1] ?? "");
  // The master that is seen is cleared: with neither, there is none to read it from.
  await region(page, "The master that is seen")
    .getByRole("button", { name: "Clear the master that is seen" })
    .click();
  await expect(page.getByText("The master that was seen was cleared.")).toBeVisible();
  await expect(page.getByTestId("group-observed-master")).toHaveText("Nobody has recorded one");
  await expect(serial).toHaveCount(0);
  await expect(source).toContainText("no master is recorded to read it from");
  // The first switch is the intended master again.
  await memberRow(page, one)
    .getByRole("button", { name: `Mark ${one} as the intended master` })
    .click();
  await expect(serial).toHaveText(stackSerials[0] ?? "");
  await expect(source).toHaveAttribute("data-source", "intended");
  // Nothing stops a member leaving, the master among them, and the page says so.
  await memberRow(page, one)
    .getByRole("button", { name: `End the membership of ${one}` })
    .click();
  const ending = region(page, `End the membership of ${one}`);
  await expect(ending).toContainText("Any member may leave, the master among them");
  await ending.getByRole("button", { name: "Cancel" }).click();

  // The health of the stack, from its members. Nothing is said of any of them: unknown.
  const health = region(page, "Health").getByTestId("health");
  await expect(health).toHaveAttribute("data-health", "unknown");
  // It is meant to have five members and has four: degraded, and says why.
  const groupDetails = region(page, "Details");
  await groupDetails.getByLabel("Expected members").fill("5");
  await groupDetails.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("The group was saved.")).toBeVisible();
  await expect(health).toHaveAttribute("data-health", "degraded");
  await expect(health).toContainText("it has 4 of the 5 members it is to have");
  await expect(page.getByTestId("expected-members")).toContainText("5 expected");
  await region(page, "Details").getByLabel("Expected members").fill("4");
  await region(page, "Details").getByRole("button", { name: "Save" }).click();
  await expect(health).toHaveAttribute("data-health", "unknown");
  // What is seen of the stack itself, as one device: online, and so good.
  const seeing = region(page, "Record what is seen of the stack");
  await seeing.getByLabel("Observed status").selectOption("online");
  await seeing.getByRole("button", { name: "Record what is seen" }).click();
  await expect(page.getByText(`What is seen of ${stack} was recorded.`)).toBeVisible();
  await expect(region(page, "Health").getByTestId("observed")).toContainText("Online · seen");
  await expect(health).toHaveAttribute("data-health", "good");
  await expect(health).toContainText("it is observed online");
  // A member whose hardware has failed: the stack is degraded, and says how many.
  await openItem(page, three);
  await region(page, "Record the condition").getByLabel("Condition").selectOption("failed");
  await region(page, "Record the condition")
    .getByRole("button", { name: "Save condition" })
    .click();
  await expect(page.getByTestId("health")).toHaveAttribute("data-health", "failed");
  await openGroup(page, stack);
  await expect(health).toHaveAttribute("data-health", "degraded");
  await expect(health).toContainText("1 member is failed");
  // The grid of groups shows the health as a mark, with the expected members to be asked for.
  await page.goto(`./groups?filter=${encodeURIComponent(`name:eq:${stack}`)}`);
  await expect(page.getByTestId("grid-total")).toHaveText("1 group");
  const groupRow = page.getByTestId("grid-device-groups").locator("[row-id]").first();
  await expect(groupRow.locator('[col-id="health"]')).toHaveText("Degraded");
  await expect(groupRow.locator('[col-id="health"] .health')).toHaveClass(/health-degraded/);
  await groupRow.locator('[col-id="health"]').click();
  await expect(page.getByTestId("grid-cell-note")).toContainText("Health: 1 member is failed");
  await page.getByText("Columns", { exact: true }).click();
  const groupColumns = page.getByRole("group", { name: "Columns to show" });
  await groupColumns.getByLabel("Expected members", { exact: true }).check();
  await groupColumns.getByLabel("Observed status", { exact: true }).check();
  await page.getByText("Columns", { exact: true }).click();
  await expect(groupRow.locator('[col-id="expected_members"]')).toHaveText("4");
  await expect(groupRow.locator('[col-id="observed_status"]')).toHaveText("Online");
  await page.getByText("Columns", { exact: true }).click();
  await page.getByRole("button", { name: "Reset layout and filters" }).click();
  await page.getByText("Columns", { exact: true }).click();
  // The switch is good again, and so is the stack.
  await openItem(page, three);
  await region(page, "Record the condition").getByLabel("Condition").selectOption("good");
  await region(page, "Record the condition")
    .getByRole("button", { name: "Save condition" })
    .click();
  await expect(page.getByTestId("health")).toHaveAttribute("data-health", "good");

  // A member of the stack with another owner: the owner of the stack is marked (P-67).
  await openItem(page, four);
  const details = region(page, "Details");
  await details.getByLabel("Owner").selectOption({ label: campus });
  await details.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("The item was saved.")).toBeVisible();
  // Its page lists the stack it is in, and as what.
  const memberships = page.getByTestId("memberships").locator("tbody tr");
  await expect(memberships).toHaveCount(1);
  await expect(memberships.first()).toContainText(stack);
  await expect(memberships.first()).toContainText("Member, position 4");
  await memberships.first().getByRole("link", { name: stack }).click();
  await expect(page.getByRole("heading", { level: 1, name: stack })).toBeVisible();
  expect(new URL(page.url()).pathname).toBe(stackPath);
  await expect(page.getByTestId("group-owner")).toHaveAttribute("data-disputed", "true");
  await expect(page.getByTestId("group-owner")).toContainText(engineering);
  await expect(page.getByTestId("group-owner")).toContainText("Members disagree");
  await expect(page.getByTestId("owner-disputed")).toBeVisible();

  // S20. Under the global discount of 50, four switches of weight 1.00 weigh 2.00 as a
  // stack: four components and one managed node.
  await page.goto(`./catalog?filter=${encodeURIComponent(`pid:eq:${switchPid}`)}`);
  await page.getByTestId("grid-catalog").getByRole("link", { name: switchPid }).click();
  await expect(
    page.getByRole("heading", { level: 1, name: `${vendor} ${switchPid}` }),
  ).toBeVisible();
  await expect(page.getByTestId("stack-discount")).toHaveAttribute("data-source", "setting");
  await expect(page.getByTestId("stack-discount")).toContainText("50");
  await summary(page, filter);
  await expect(page.getByTestId("total-components")).toHaveText("4");
  await expect(page.getByTestId("total-nodes")).toHaveText("1");
  // A weight is written without the zeros that say nothing: 2, or 2.00.
  await expect(page.getByTestId("total-weight")).toHaveText(/^2(\.00?)?$/);
  // The summary holds no money, and counts the four components by their health.
  await expect(page.getByTestId("total-cost")).toHaveCount(0);
  await expect(page.getByTestId("total-value")).toHaveCount(0);
  await expect(page.getByTestId("total-health-good")).toHaveText("1");
  await expect(page.getByTestId("total-health-unknown")).toHaveText("3");
  // The kinds beside the headline count: these are hardware, which the count takes.
  const hardware = page.getByTestId("totals-by-kind").locator('tr[data-kind="hardware"]');
  await expect(hardware.locator("td").nth(0)).toHaveText("4");
  await expect(hardware.locator("td").nth(2)).toHaveText("Yes");
  // The money is in the management report: the support cost of four switches, with no
  // stack discount, and their value. It has neither condition nor health.
  await page
    .getByRole("navigation", { name: "Reports" })
    .getByRole("link", { name: "Management" })
    .click();
  await expect(page.getByRole("heading", { level: 1, name: "Management report" })).toBeVisible();
  await management(page, filter);
  await expect(page.getByTestId("total-cost")).toHaveText("4,800.00");
  await expect(page.getByTestId("total-value")).toHaveText("72,000.00");
  await expect(page.getByTestId("total-components")).toHaveText("4");
  await expect(page.getByTestId("total-items")).toHaveText("4");
  await expect(page.getByTestId("totals-by-health")).toHaveCount(0);
  // It is by site unless asked otherwise, and has no view of the totals alone.
  await expect(page.getByLabel("By", { exact: true })).toHaveValue("site");
  await expect(page.getByLabel("By", { exact: true }).locator("option")).toHaveText([
    "Site",
    "Region",
    "Vendor",
    "Kind",
    "Type",
    "Function",
    "Owner",
    "Operator",
    "Tag",
  ]);

  // The model sets its own discount of 30: the stack weighs 2.80. Nothing else changes.
  await page.goto(`./catalog?filter=${encodeURIComponent(`pid:eq:${switchPid}`)}`);
  await page.getByTestId("grid-catalog").getByRole("link", { name: switchPid }).click();
  const entry = region(page, "Details");
  await entry.getByLabel("Stack discount %").fill("30");
  await entry.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("The catalog entry was saved.")).toBeVisible();
  await expect(page.getByTestId("stack-discount")).toHaveAttribute("data-source", "own");
  await summary(page, filter);
  await expect(page.getByTestId("total-weight")).toHaveText(/^2\.80?$/);
  await expect(page.getByTestId("total-components")).toHaveText("4");
  await expect(page.getByTestId("total-nodes")).toHaveText("1");
  // By owner: the stack's members fall in two rows, and it is a managed node in both.
  await page.getByLabel("By", { exact: true }).selectOption("owner");
  const rows = page.getByTestId("summary-rows").locator("tbody tr");
  await expect(rows).toHaveCount(2);
  await expect(rows.filter({ hasText: campus }).locator("td").nth(2)).toHaveText("1");
  await expect(rows.filter({ hasText: engineering }).locator("td").nth(2)).toHaveText("1");
  await expect(page.getByTestId("total-nodes")).toHaveText("1");
  // The cost is what it was: the discount never applies to it. By owner, it is in two rows.
  await management(page, filter, "owner");
  await expect(page.getByTestId("total-cost")).toHaveText("4,800.00");
  const paid = page.getByTestId("management-rows").locator("tbody tr");
  await expect(paid).toHaveCount(2);
  await expect(paid.filter({ hasText: campus }).locator("td").nth(3)).toHaveText("1,200.00");
  await expect(paid.filter({ hasText: engineering }).locator("td").nth(3)).toHaveText("3,600.00");
  await expect(paid.filter({ hasText: engineering }).locator("td").nth(2)).toHaveText("54,000.00");
  // The report can be come back to: what it is by and its filter are in the address.
  await page.reload();
  await expect(page.getByLabel("By", { exact: true })).toHaveValue("owner");
  await expect(page.getByTestId("total-cost")).toHaveText("4,800.00");

  // The item grid finds the members by the group they are in, and by its type.
  await page.goto(`./items?filter=${encodeURIComponent(`${filter} group.type:eq:stack`)}`);
  await expect(page.getByTestId("grid-total")).toHaveText("4 items");

  await expectClean(page, seen);
});

test("S21: the master of the stack is replaced, and the stack stays the stack", async ({
  page,
  account,
}) => {
  test.setTimeout(180_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  const master = stackHosts[0] ?? "";
  await openGroup(page, stack);
  const stackPath = new URL(page.url()).pathname;
  await expect(page.getByTestId("group-serial")).toHaveText(stackSerials[0] ?? "");

  // The master goes back under an RMA. What takes its place is a new item, made here.
  await openItem(page, master);
  await expect(region(page, "Replacement")).toContainText(
    `${master} replaced no item, and was not replaced.`,
  );
  await region(page, "Replacement").getByRole("button", { name: "Replace this item" }).click();
  const replace = region(page, `Replace ${master}`);
  await replace.getByLabel("Reason").selectOption({ label: "RMA" });
  await replace.getByLabel("Reference").fill(`RMA-${upper}`);
  await replace
    .getByLabel("What takes its place")
    .selectOption({ label: "A new item, created now" });
  const fresh = replace.getByRole("group", { name: "The new item" });
  // The same model is offered, as it is more often than not.
  await expect(fresh.getByLabel("Catalog entry").locator("option:checked")).toContainText(
    switchPid,
  );
  await fresh.getByLabel("Serial number").fill(spareSerial);
  await fresh.getByLabel("Hostname").fill(spare);
  await replace.getByRole("button", { name: "Replace", exact: true }).click();
  await expect(page.getByText(`${master} was replaced by ${spare}.`)).toBeVisible();

  // Two item records, linked by the replacement. The one that left is in no group now.
  const replacedBy = page.getByTestId("replaced-by");
  await expect(replacedBy).toContainText(spare);
  await expect(replacedBy).toContainText("RMA");
  await expect(replacedBy).toContainText(`RMA-${upper}`);
  await expect(region(page, "Groups")).toContainText(`${master} is a member of no group.`);
  // An item is replaced once: the action is no longer offered.
  await expect(page.getByRole("button", { name: "Replace this item" })).toHaveCount(0);
  await replacedBy.getByRole("link").click();
  await expect(page.getByRole("heading", { level: 1, name: spare })).toBeVisible();
  await expect(page.getByTestId("replaces")).toContainText(master);
  const memberships = page.getByTestId("memberships").locator("tbody tr");
  await expect(memberships.first()).toContainText(stack);
  await expect(memberships.first()).toContainText("Intended master, position 1");

  // The stack is the same record: its HID is unchanged, and its intended master is the
  // new switch, whose serial number it shows.
  await memberships.first().getByRole("link", { name: stack }).click();
  await expect(page.getByRole("heading", { level: 1, name: stack })).toBeVisible();
  expect(new URL(page.url()).pathname).toBe(stackPath);
  await expect(page.getByTestId("group-serial")).toHaveText(spareSerial);
  await expect(page.getByTestId("serial-source")).toHaveAttribute("data-source", "intended");
  await expect(page.getByTestId("group-master")).toContainText(spare);
  await expect(page.getByTestId("member-count")).toHaveText("4 current members");
  await expect(page.getByTestId("members").locator("tbody tr")).toHaveCount(4);
  await expect(memberRow(page, spare)).toHaveAttribute("data-role", "master");
  // The departed switch's membership has an end date, and is kept.
  await region(page, "Members").getByLabel("Show past memberships").check();
  await expect(page.getByTestId("members").locator("tbody tr")).toHaveCount(5);
  const departed = memberRow(page, master);
  await expect(departed).toHaveAttribute("data-current", "false");
  await expect(departed.locator("td").nth(-2)).toHaveText(/^\d{4}-\d{2}-\d{2}$/);
  await region(page, "Members").getByLabel("Show past memberships").uncheck();
  await expect(page.getByTestId("members").locator("tbody tr")).toHaveCount(4);

  // A membership is changed: the last member is given another position.
  await memberRow(page, stackHosts[3] ?? "")
    .getByRole("button", { name: `Change the membership of ${stackHosts[3]}` })
    .click();
  const change = region(page, `The membership of ${stackHosts[3]}`);
  await change.getByLabel("Position").fill("8");
  await change.getByRole("button", { name: "Save membership" }).click();
  await expect(page.getByText(`The membership of ${stackHosts[3]} was saved.`)).toBeVisible();
  await expect(
    memberRow(page, stackHosts[3] ?? "")
      .locator("td")
      .first(),
  ).toHaveText("8");

  await expectClean(page, seen);
});

test("S23: the same address under two networks, and twice under one", async ({ page, account }) => {
  test.setTimeout(240_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  const [first = "", other = "", third = ""] = stackHosts.slice(1);

  // Two networks, and one more to rename and remove.
  await main(page).getByRole("link", { name: "Addresses" }).click();
  await page
    .getByRole("navigation", { name: "Addresses" })
    .getByRole("link", { name: "Networks" })
    .click();
  await expect(page.getByRole("heading", { level: 1, name: "Networks" })).toBeVisible();
  for (const label of [red, black, `Green ${suffix}`]) {
    await page.getByRole("button", { name: "New network" }).click();
    await region(page, "New network").getByLabel("Label").fill(label);
    await region(page, "New network").getByRole("button", { name: "Create network" }).click();
    await expect(page.getByText(`The network ${label} was created.`)).toBeVisible();
  }
  const networks = page.getByTestId("networks").locator("tbody tr");
  const green = networks.filter({ hasText: `Green ${suffix}` });
  await green.getByRole("button", { name: `Rename or change the network Green ${suffix}` }).click();
  const edit = region(page, `The network Green ${suffix}`);
  await edit.getByLabel("Label").fill(`Amber ${suffix}`);
  await edit.getByLabel("Kind").selectOption("vrf");
  await edit.getByRole("button", { name: "Save" }).click();
  const amber = networks.filter({ hasText: `Amber ${suffix}` });
  await expect(amber).toContainText("VRF");
  await expect(amber).toContainText("0 addresses");
  await amber.getByRole("button", { name: "Remove" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Remove network" }).click();
  await expect(page.getByText(`The network Amber ${suffix} was removed.`)).toBeVisible();
  await expect(amber).toHaveCount(0);

  /** Give the item on show an address under a network. `stored` is the address as the server keeps it. */
  async function addAddress(address: string, network: string, stored = address) {
    const addresses = region(page, "Addresses");
    await addresses.getByRole("button", { name: "Add an address" }).click();
    const form = region(page, "New address");
    await form.getByLabel("Address (required)").fill(address);
    await form.getByLabel("Network").selectOption({ label: network });
    await expect(form.getByLabel("Role")).toHaveValue("management");
    await form.getByRole("button", { name: "Add address" }).click();
    await expect(page.getByText(`The address ${stored} was added.`)).toBeVisible();
  }
  const addressRow = (address: string) =>
    page.getByTestId("addresses").locator(`tbody tr[data-address="${address}"]`);

  // The same address under Red on one switch and under Black on another: two addresses.
  await openItem(page, first);
  await expect(region(page, "Addresses")).toContainText(`There is no address on ${first}.`);
  // Written in upper case and with leading zeros: the server stores the canonical form.
  await addAddress(shared.toUpperCase().replace("::10", "::0010"), red, shared);
  await expect(addressRow(shared)).toContainText(red);
  // The first management address of its family is the primary one of that family.
  await expect(addressRow(shared)).toContainText("Primary IPv6");
  await openItem(page, other);
  await addAddress(shared, black);
  await expect(addressRow(shared)).toContainText(black);

  // Nothing is held more than once yet.
  await page.goto("./reports/duplicates");
  await expect(
    page.getByRole("heading", { level: 1, name: "Addresses held more than once" }),
  ).toBeVisible();
  await expect(page.getByTestId("duplicates")).toBeVisible();
  await expect(page.getByTestId("duplicates").locator(`tr[data-address="${shared}"]`)).toHaveCount(
    0,
  );

  // The same address a second time under Red: accepted, and reported.
  await openItem(page, third);
  await addAddress(shared, red);
  await page.goto("./reports/duplicates");
  const held = page.getByTestId("duplicates").locator(`tr[data-address="${shared}"]`);
  await expect(held).toHaveCount(1);
  await expect(held).toHaveAttribute("data-network", red);
  await expect(held).toContainText("2 times");
  await expect(held.getByRole("link", { name: first })).toBeVisible();
  await expect(held.getByRole("link", { name: third })).toBeVisible();
  await expect(held.getByRole("link", { name: other })).toHaveCount(0);
  // A holder leads to its own page.
  await held.getByRole("link", { name: third }).click();
  await expect(page.getByRole("heading", { level: 1, name: third })).toBeVisible();

  // A second management address of the same family, marked as primary: the mark leaves
  // the first.
  await addAddress(second, red);
  await expect(addressRow(shared)).toContainText("Primary IPv6");
  await expect(addressRow(second)).not.toContainText("Primary");
  await addressRow(second)
    .getByRole("button", { name: `Make ${second} (${red}) the primary IPv6 management address` })
    .click();
  await expect(
    page.getByText(`${second} is now the primary IPv6 management address.`),
  ).toBeVisible();
  await expect(addressRow(second).locator("td").nth(2)).toHaveText("Primary IPv6");
  await expect(addressRow(shared).locator("td").nth(2)).toHaveText("");
  // An address of the other family: the first IPv4 one is the primary IPv4 address, and
  // the IPv6 one keeps its mark. The item has a primary management address of each.
  await region(page, "Addresses").getByRole("button", { name: "Add an address" }).click();
  const newAddress = region(page, "New address");
  await newAddress.getByLabel("Address (required)").fill(fourth);
  await expect(newAddress.getByLabel("The primary IPv4 management address")).toBeChecked();
  await newAddress.getByLabel("Network").selectOption({ label: red });
  await newAddress.getByRole("button", { name: "Add address" }).click();
  await expect(page.getByText(`The address ${fourth} was added.`)).toBeVisible();
  await expect(addressRow(fourth).locator("td").nth(2)).toHaveText("Primary IPv4");
  await expect(addressRow(second).locator("td").nth(2)).toHaveText("Primary IPv6");
  await expect(page.getByTestId("addresses").locator("tbody td[data-primary]")).toHaveCount(2);
  // The primary ones are listed first, and the page states both among the item's facts.
  await expect(page.getByTestId("addresses").locator("tbody tr").nth(2)).toHaveAttribute(
    "data-address",
    shared,
  );
  const stated = region(page, "Identity").getByTestId("mgmt-addresses").getByRole("listitem");
  await expect(stated).toHaveCount(2);
  await expect(stated.nth(0)).toContainText(`IPv4 ${fourth}`);
  await expect(stated.nth(1)).toContainText(`IPv6 ${second}`);
  // And so does the grid of items, in its Management address column.
  await freshGrid(page, `hostname:eq:${third}`);
  await page.getByText("Columns", { exact: true }).click();
  await page
    .getByRole("group", { name: "Columns to show" })
    .getByLabel("Management address", { exact: true })
    .check();
  // The grid draws only the columns in view: room is made for the one looked at here.
  await page
    .getByRole("group", { name: "Columns to show" })
    .getByLabel("Operator", { exact: true })
    .uncheck();
  await page.getByText("Columns", { exact: true }).click();
  await expect(
    page.getByTestId("grid-items").locator("[row-id]").first().locator('[col-id="mgmt_address"]'),
  ).toHaveText(`${fourth}, ${second}`);
  await page.getByText("Columns", { exact: true }).click();
  await page.getByRole("button", { name: "Reset layout and filters" }).click();
  await page.getByText("Columns", { exact: true }).click();
  await openItem(page, third);
  // An address is changed: a loopback now, which cannot be primary.
  await addressRow(shared)
    .getByRole("button", { name: `Change the address ${shared} (${red})` })
    .click();
  const change = region(page, `The address ${shared}`);
  await change.getByLabel("Role").selectOption("loopback");
  await change.getByRole("button", { name: "Save address" }).click();
  await expect(page.getByText(`The address ${shared} was saved.`)).toBeVisible();
  await expect(addressRow(shared)).toContainText("Loopback");
  await expect(
    addressRow(shared).getByRole("button", { name: /the primary management address$/ }),
  ).toHaveCount(0);

  // The grid of every address: the four of this run that are under Red.
  await page.goto(`./addresses?filter=${encodeURIComponent(`network.label:eq:${red}`)}`);
  await expect(page.getByRole("heading", { level: 1, name: "Addresses" })).toBeVisible();
  await expect(page.getByTestId("grid-total")).toHaveText("4 addresses");
  // The item grid finds an item by any of its addresses, and by the network of one.
  await page.goto(
    `./items?filter=${encodeURIComponent(`address:eq:${shared} network.label:eq:${black}`)}`,
  );
  await expect(page.getByTestId("grid-total")).toHaveText("1 item");
  await expect(page.getByTestId("grid-items").getByRole("link", { name: other })).toBeVisible();

  // A network that addresses are under cannot be removed.
  await page.goto("./networks");
  const redRow = page.getByTestId("networks").locator("tbody tr").filter({ hasText: red });
  await expect(redRow).toContainText("4 addresses");
  await expect(redRow.getByRole("button", { name: "Remove" })).toBeDisabled();

  // The second address is removed. The pair under Red stays in the report.
  await openItem(page, third);
  await addressRow(second).getByRole("button", { name: "Remove" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Remove address" }).click();
  await expect(page.getByText(`The address ${second} was removed.`)).toBeVisible();
  await expect(addressRow(second)).toHaveCount(0);
  await page.goto("./reports/duplicates");
  await expect(page.getByTestId("duplicates").locator(`tr[data-address="${shared}"]`)).toHaveCount(
    1,
  );

  await expectClean(page, seen);
});
