// The browser scenario of an edit that went stale when a term began, in release 0.6.1,
// for what only the tests of the API held before:
//
//   D-140  A renewal entered early is the next term of the contract. From the day it
//          begins, the contract is read with the version it will have once the term is
//          written down ("The row_version of a contract" in docs/data-model.md): an edit
//          that was read before that day and is sent after it is refused as stale, is not
//          made to a term it was not meant for, and the page says why it may be stale.
//
// No clock writes anything, and no test can wait for a day to come. The day is made to
// come by the `time_zone` setting, which says what today is: first the zone twelve hours
// behind UTC, in which the next term begins tomorrow, then the zone fourteen hours ahead
// of it, in which tomorrow has come, whatever the time of day. That changes what every
// other file reads, so this file runs in a project of its own, when the others have ended
// (playwright.config.ts), and puts the setting back as it found it.

import { type APIRequestContext, expect } from "@playwright/test";
import { dayAfter, newContract, openContract } from "./contractSteps";
import { importFile, region } from "./structure";
import { type Account, expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const suffix = mark("stale-term");
const vendor = `Example Networks ${suffix}`;
const number = `CON-${suffix}-1`;
const renewed = `CON-${suffix}-2`;
const note = "Checked with the vendor on the telephone";
// The zone where it is the earliest day on Earth, and the one where it is the latest.
const BEHIND = "Etc/GMT+12";
const AHEAD = "Etc/GMT-14";

type Headers = { Authorization: string };

/** Sign in through the API as the account of the file, for what the test does there. */
async function session(request: APIRequestContext, account: Account): Promise<Headers> {
  const answer = await request.post("./api/v1/auth/sign-in", {
    data: { username: account.username, access_code: account.accessCode },
  });
  expect(answer.status(), "the account of the file signs in through the API").toBe(200);
  const { token } = (await answer.json()) as { token: string };
  return { Authorization: `Bearer ${token}` };
}

interface Zone {
  value: string;
  is_default: boolean;
  row_version: number;
}

async function zoneSetting(request: APIRequestContext, headers: Headers): Promise<Zone> {
  const answer = await request.get("./api/v1/settings", { headers });
  expect(answer.status()).toBe(200);
  const settings = (await answer.json()) as Array<Zone & { key: string }>;
  const found = settings.find((setting) => setting.key === "time_zone");
  if (!found) throw new Error("there is no time_zone setting");
  return found;
}

/** Give the installation another time zone, or its default for null. */
async function setZone(request: APIRequestContext, headers: Headers, zone: string | null) {
  const { row_version } = await zoneSetting(request, headers);
  const answer = await request.put("./api/v1/settings/time_zone", {
    headers,
    data: { row_version, value: zone },
  });
  expect(answer.status(), await answer.text()).toBe(200);
}

/** Today, as the server has it: the day its coverage report is of. */
async function today(request: APIRequestContext, headers: Headers): Promise<string> {
  const answer = await request.get("./api/v1/reports/coverage", {
    headers,
    params: { filter: `hostname:eq:${suffix}` },
  });
  expect(answer.status()).toBe(200);
  return ((await answer.json()) as { as_of: string }).as_of;
}

test("an edit read before the next term began is refused once it has, and says why", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(180_000);
  const headers = await session(request, account);
  const was = await zoneSetting(request, headers);
  try {
    await setZone(request, headers, BEHIND);
    const seen = await watch(page.context());
    await signIn(page, account);
    const day = await today(request, headers);
    const tomorrow = dayAfter(day, 1);

    // A contract whose present term ends today, renewed early: the next term begins
    // tomorrow.
    await importFile(page, "vendors", `vendors-${suffix}.csv`, ["name"], [[vendor]]);
    await newContract(page, { number, vendor, starts: dayAfter(day, -300), ends: day });
    await region(page, "Renew").getByRole("button", { name: "Renew", exact: true }).click();
    const form = page.getByTestId("renew-form");
    await form.getByLabel("New number").fill(renewed);
    await form.getByLabel("New period: starts on").fill(tomorrow);
    await form.getByLabel("New period: ends on").fill(dayAfter(day, 366));
    await form.getByRole("button", { name: "Renew for 0 items" }).click();
    await expect(page.getByText(/^The renewal is kept as the next term\./)).toBeVisible();
    await expect(page.getByTestId("contract-next-term")).toContainText(
      `Renews as ${renewed} on ${tomorrow}`,
    );

    // A change is begun, and before it is sent the next term begins.
    const details = region(page, "Details");
    await details.getByLabel("Notes").fill(note);
    await setZone(request, headers, AHEAD);
    expect((await today(request, headers)) >= tomorrow).toBe(true);
    await details.getByRole("button", { name: "Save" }).click();

    // It is refused as stale, and the page says that the term may be why.
    const refusal = details.locator('.alert-error[data-status="409"]');
    await expect(refusal).toContainText("This record has changed.");
    await expect(refusal).toContainText(
      `or its next term, from ${tomorrow}, has begun: from that day the contract is read with that term, at a new version.`,
    );
    await expect(refusal).toContainText(
      "Your change was not saved, so that it is not made to a term it was not meant for.",
    );
    await refusal.getByRole("button", { name: "Reload" }).click();

    // Read again, it has the new term, and the one before is its history. The change was
    // made to neither.
    await expect(page.getByRole("heading", { level: 1, name: renewed })).toBeVisible();
    await expect(page.getByTestId("contract-number")).toHaveText(renewed);
    await expect(page.getByTestId("contract-next-term")).toHaveCount(0);
    const before = page.getByTestId("contract-terms").locator(`tr[data-term="${number}"]`);
    await expect(before.locator("td").nth(0)).toHaveText(dayAfter(day, -300));
    await expect(before.locator("td").nth(1)).toHaveText(day);
    await expect(page.getByTestId("contract-facts")).not.toContainText(note);

    // Made again, now that it is read with the term it is meant for, it is saved.
    await region(page, "Details").getByLabel("Notes").fill(note);
    await region(page, "Details").getByRole("button", { name: "Save" }).click();
    await expect(page.getByText("The contract was saved.")).toBeVisible();
    await expect(page.getByTestId("contract-facts")).toContainText(note);
    await openContract(page, renewed);
    await expect(page.getByTestId("contract-terms").locator("tbody tr")).toHaveCount(1);

    await expectClean(page, seen, ["409 PATCH"]);
  } finally {
    // The setting as it was, for every file that runs after.
    await setZone(request, headers, was.is_default ? null : was.value);
  }
});
