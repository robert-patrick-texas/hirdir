// What the scenarios of agreements, contracts and their coverage do alike: open a record
// from its grid, make a contract, put the rows of the item grid under one, and choose a
// column of a grid. Each spec file makes its own records under its own names, as
// support.ts asks; this file holds only the steps.

import { expect, type Locator, type Page } from "@playwright/test";
import { region } from "./structure";

/** A row of a grid, by a text in it. */
export function gridRow(page: Page, grid: string, text: string): Locator {
  return page.getByTestId(grid).locator("[row-id]", { hasText: text });
}

/** One field of a contract as it is in force, on the page of the contract. */
export function inForce(page: Page, field: string): Locator {
  return page.getByTestId("contract-in-force").locator(`[data-field="${field}"]`);
}

/** Open a contract from the grid of contracts, by its number. */
export async function openContract(page: Page, number: string) {
  await page.goto(`./contracts?filter=${encodeURIComponent(`number:eq:${number}`)}`);
  await page.getByTestId("grid-contracts").getByRole("link", { name: number, exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: number })).toBeVisible();
}

/** Open an agreement from the grid of agreements, by its name. */
export async function openAgreement(page: Page, name: string) {
  await page.goto(`./agreements?filter=${encodeURIComponent(`name:eq:${name}`)}`);
  await page.getByTestId("grid-agreements").getByRole("link", { name, exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
}

export interface NewContract {
  number: string;
  vendor: string;
  starts?: string;
  ends?: string;
  manager?: string;
}

/** Make a contract that stands by itself, on the page of contracts, and open it. */
export async function newContract(page: Page, contract: NewContract) {
  await page.goto("./contracts");
  await page.getByRole("button", { name: "New contract" }).click();
  const form = region(page, "New contract");
  await form.getByLabel("Number (required)").fill(contract.number);
  await form.getByLabel("Vendor", { exact: true }).selectOption({ label: contract.vendor });
  if (contract.starts) await form.getByLabel("Starts on").fill(contract.starts);
  if (contract.ends) await form.getByLabel("Ends on").fill(contract.ends);
  if (contract.manager) await form.getByLabel("Account manager").fill(contract.manager);
  await form.getByRole("button", { name: "Create contract" }).click();
  await expect(page.getByRole("heading", { level: 1, name: contract.number })).toBeVisible();
}

/** Find a contract in a form by its number, and choose it. */
export async function pickContract(form: Locator, number: string) {
  await form.getByLabel("Contract", { exact: true }).fill(number);
  await form
    .getByRole("list", { name: "Contracts that match" })
    .getByRole("button", { name: new RegExp(`^${number} `) })
    .click();
  await expect(form.getByTestId("chosen-contract_hid")).toContainText(number);
}

/**
 * The columns of the item grid that are on show from the start and that a scenario can
 * do without: the grid draws only the columns in view, so room is made for those asked for.
 * 0.9.5: Location and Site are on show from the start, and Expected online is not (P-193).
 */
export const ROOM = [
  "Serial number",
  "Disposition",
  "Location",
  "Site",
  "Health",
  "Owner",
  "Operator",
  "Tags",
  "LDoS",
];

/** Show or hide columns of the grid on show, by their headers. */
export async function chooseColumns(page: Page, show: string[], hide: string[] = []) {
  await page.getByText("Columns", { exact: true }).click();
  const columns = page.getByRole("group", { name: "Columns to show" });
  for (const column of show) await columns.getByLabel(column, { exact: true }).check();
  for (const column of hide) await columns.getByLabel(column, { exact: true }).uncheck();
  await page.getByText("Columns", { exact: true }).click();
}

/** Put the layout of the grid on show back as a new reader has it. */
export async function resetGrid(page: Page) {
  await page.getByText("Columns", { exact: true }).click();
  await page.getByRole("button", { name: "Reset layout and filters" }).click();
}

/** The day `days` after a day written as YYYY-MM-DD. */
export function dayAfter(day: string, days: number): string {
  const moment = new Date(`${day}T12:00:00Z`);
  moment.setUTCDate(moment.getUTCDate() + days);
  return moment.toISOString().slice(0, 10);
}
