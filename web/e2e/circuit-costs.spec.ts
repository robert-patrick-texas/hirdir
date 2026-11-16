// The browser scenario of the report of what circuits cost, in release 0.8.0 (P-151):
//
//   Two circuits of this file's own, made through the API, each at a site of its own: one
//   of 1,000 a month activated on 10 April, which costs 8,700 in its first year, May to
//   December in full and 21 of April's 30 days, as the carrier bills it; and one in service
//   all year, of a port and a credit billed by its carrier and a local loop billed by a
//   second carrier. The report of that year by carrier has a row for each carrier, the
//   second circuit in both, and the totals count each circuit once; by site, a row for each
//   site; each row with its circuits, the year's cost, the monthly figure on the last day of
//   the year and twelve times that, and leading to its circuits in the circuit grid.
//
// The year is a past one, so that the figures do not depend on the day the file is run,
// and the report is filtered down to the circuits of this file by their names (rule 4 of
// support.ts). The fiscal year is the calendar year: the `fiscal_year_start_month` setting
// at its default, which no file changes.

import { type APIRequestContext, expect } from "@playwright/test";
import { type Account, expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const suffix = mark("circuit-costs");
const carrier = `Example Telecom ${suffix}`;
const loop = `Northwind Fiber ${suffix}`;
const regionName = `Circuit Costs Region ${suffix}`;
const east = `Circuit Costs East ${suffix}`;
const west = `Circuit Costs West ${suffix}`;
const first = `WAN east ${suffix}`;
const second = `WAN west ${suffix}`;
const mine = `name:contains:${suffix}`;
const YEAR = 2025;

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
): Promise<{ hid: string }> {
  const answer = await request.post(`./api/v1${path}`, { headers, data });
  expect(answer.status(), `post ${path}: ${await answer.text()}`).toBe(201);
  return (await answer.json()) as { hid: string };
}

const ids: Record<string, string> = {};

test("what circuits cost in a year, by carrier and by site, each row leading to its circuits", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(150_000);
  const headers = await session(request, account);
  const telecom = await make(request, headers, "/vendors", { name: carrier });
  const fiber = await make(request, headers, "/vendors", { name: loop });
  const top = await make(request, headers, "/regions", { name: regionName });
  const eastSite = await make(request, headers, "/sites", { name: east, region_hid: top.hid });
  const westSite = await make(request, headers, "/sites", { name: west, region_hid: top.hid });
  const eastRoom = await make(request, headers, "/locations", {
    name: "Telecom room",
    site_hid: eastSite.hid,
  });
  const westRoom = await make(request, headers, "/locations", {
    name: "Telecom room",
    site_hid: westSite.hid,
  });
  const one = await make(request, headers, "/circuits", {
    name: first,
    a_location_hid: eastRoom.hid,
    z_note: "carrier network",
    carrier_hid: telecom.hid,
    activated_on: `${YEAR}-04-10`,
    port_mbps: "1000",
  });
  await make(request, headers, `/circuits/${one.hid}/costs`, {
    description: "Port",
    monthly_cost: "1000",
  });
  const two = await make(request, headers, "/circuits", {
    name: second,
    a_location_hid: westRoom.hid,
    z_note: "carrier network",
    carrier_hid: telecom.hid,
    activated_on: `${YEAR - 1}-06-01`,
    port_mbps: "500",
  });
  // The second carrier provides the last mile, and bills it.
  await make(request, headers, `/circuits/${two.hid}/carriers`, {
    vendor_hid: fiber.hid,
    role: "last_mile",
  });
  for (const line of [
    { description: "Port", monthly_cost: "500" },
    { description: "Local loop", monthly_cost: "250", vendor_hid: fiber.hid },
    { description: "Credit", monthly_cost: "-50" },
  ]) {
    await make(request, headers, `/circuits/${two.hid}/costs`, line);
  }
  Object.assign(ids, {
    telecom: telecom.hid,
    fiber: fiber.hid,
    east: eastSite.hid,
    west: westSite.hid,
  });

  const seen = await watch(page.context());
  await signIn(page, account);
  await page.goto(`./reports/circuit-costs?filter=${encodeURIComponent(mine)}`);
  await expect(page.getByRole("heading", { level: 1, name: "Circuit costs" })).toBeVisible();
  // The present year unless another is chosen, and by carrier.
  const report = page.getByTestId("circuit-costs");
  await expect(report).toHaveAttribute("data-by", "carrier");
  await page.getByRole("textbox", { name: "Fiscal year" }).fill(String(YEAR));
  await page.getByRole("button", { name: "Apply" }).click();
  await expect(report).toHaveAttribute("data-fiscal-year", String(YEAR));
  await expect(page.getByTestId("circuit-costs-period")).toContainText(
    `From ${YEAR}-01-01 to ${YEAR}-12-31.`,
  );
  await expect(page.getByTestId("circuit-costs-period")).toContainText(`a month on ${YEAR}-12-31`);

  const rows = page.getByTestId("circuit-costs-rows");
  const expectRow = async (key: string, figures: [number, string, string, string]) => {
    const row =
      key === "totals"
        ? rows.getByTestId("circuit-costs-totals")
        : rows.locator(`tbody tr[data-key="${key}"]`);
    const [circuits, cost, monthly, annual] = figures;
    await expect(row.getByTestId("cost-circuits")).toHaveAttribute("data-value", String(circuits));
    await expect(row.getByTestId("cost-year")).toHaveText(cost);
    await expect(row.getByTestId("cost-monthly")).toHaveText(monthly);
    await expect(row.getByTestId("cost-annual")).toHaveText(annual);
    return row;
  };

  // By carrier: the first circuit's 8,700 for its part year and the second's port and
  // credit under the carrier, the second's local loop under the carrier that bills it.
  await expect(rows.locator("tbody tr")).toHaveCount(2);
  const telecomRow = await expectRow(ids.telecom ?? "", [2, "14,100.00", "1,450.00", "17,400.00"]);
  await expectRow(ids.fiber ?? "", [1, "3,000.00", "250.00", "3,000.00"]);
  // The totals count each circuit once.
  await expectRow("totals", [2, "17,100.00", "1,700.00", "20,400.00"]);
  // A row leads to its circuits in the circuit grid, with its filter in the address.
  const link = telecomRow.getByRole("link", { name: carrier, exact: true });
  const href = (await link.getAttribute("href")) ?? "";
  expect(href).toContain("/circuits?");
  const asked = new URL(href, "http://example.invalid/").searchParams;
  expect(asked.get("filter")).toBe(`${mine} carriers.vendor_hid:eq:${ids.telecom}`);
  expect(asked.get("archived")).toBe("1");

  // By site: each circuit at the site of its A side.
  await page.getByRole("combobox", { name: "By", exact: true }).selectOption({ label: "Site" });
  await expect(report).toHaveAttribute("data-by", "site");
  await expect(page).toHaveURL(/by=site/);
  await expect(rows.locator("tbody tr")).toHaveCount(2);
  const eastRow = await expectRow(ids.east ?? "", [1, "8,700.00", "1,000.00", "12,000.00"]);
  await expectRow(ids.west ?? "", [1, "8,400.00", "700.00", "8,400.00"]);
  await expectRow("totals", [2, "17,100.00", "1,700.00", "20,400.00"]);
  await expect(eastRow.locator("th")).toContainText(`${regionName} > ${east}`);
  const siteHref = (await eastRow.getByRole("link").getAttribute("href")) ?? "";
  expect(new URL(siteHref, "http://example.invalid/").searchParams.get("filter")).toBe(
    `${mine} cost_site_hid:eq:${ids.east}`,
  );
  // Sorted by its headers: the dearer site first, by the year's cost turned round.
  const costHeader = rows.getByRole("button", { name: /^Cost of the year/ });
  await costHeader.click();
  await costHeader.click();
  await expect(rows.locator("tbody tr").first()).toHaveAttribute("data-key", ids.east ?? "");

  // The view is in the address: read again, it is the same report.
  await page.reload();
  await expect(report).toHaveAttribute("data-fiscal-year", String(YEAR));
  await expect(report).toHaveAttribute("data-by", "site");
  await expectRow("totals", [2, "17,100.00", "1,700.00", "20,400.00"]);
  await expectClean(page, seen);
});
