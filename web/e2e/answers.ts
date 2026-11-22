// P-309: what a scenario waits for before it reads what a page shows of the server.
//
// The server under test is one process, and on a busy host, with the files of a run side
// by side, it answers a read or a save in more than the 5 seconds an expectation waits.
// A scenario that expects what the page shows right after a navigation or a press then
// fails, though nothing is wrong. So a scenario waits for the server's answer to the very
// request whose data it is about to read, for as long as that takes within the scenario's
// own time, and then expects what the page shows of it with the ordinary 5 seconds, the
// time the page needs to draw it. A wait is asked for before what sends its request.
//
// The spec files whose scenarios stalled on a busy host take these from here:
// coverage, export-tables, leaderboard, review-2b, review-3a, review-3c and review-3s.

import { expect, type Page, type Request, type Response } from "@playwright/test";
import { count } from "./structure";

/** Whether `text` holds each of `parts`, whatever their case. */
function holds(text: string, parts: readonly string[]): boolean {
  const lower = text.toLowerCase();
  return parts.every((part) => lower.includes(part.toLowerCase()));
}

/**
 * The page's next answer from the API to `method` on `path`, the end of a path under
 * /api/v1 or a pattern of the whole path, and to a request that `sent` takes where it is
 * given.
 */
export function answer(
  page: Page,
  method: string,
  path: string | RegExp,
  sent?: (request: Request) => boolean,
): Promise<Response> {
  return page.waitForResponse((response) => {
    const request = response.request();
    const at = new URL(response.url()).pathname;
    return (
      request.method() === method &&
      (typeof path === "string" ? at.endsWith(`/api/v1${path}`) : path.test(at)) &&
      (sent === undefined || sent(request))
    );
  });
}

/**
 * The last of the page's next `times` answers to `method` on `path`, as when a page sends
 * one request for each row a person chose, one after another.
 */
export function answers(
  page: Page,
  times: number,
  method: string,
  path: string | RegExp,
): Promise<Response> {
  let heard = 0;
  return answer(page, method, path, () => {
    heard += 1;
    return heard === times;
  });
}

/** The page's answer to a `GET` of `path` whose address, decoded, holds each of `parts`. */
export function listed(page: Page, path: string, ...parts: string[]): Promise<Response> {
  return answer(page, "GET", path, (request) => holds(decodeURIComponent(request.url()), parts));
}

/** The page's answer to a `POST` of `path` whose body holds each of `parts`. */
export function queried(page: Page, path: string, ...parts: string[]): Promise<Response> {
  return answer(page, "POST", path, (request) => holds(request.postData() ?? "", parts));
}

/**
 * The page's answer that the import `hid`, or any where it is not given, is applied, as
 * the page reads it while it follows the job: an apply waits behind those of the other
 * files, and is waited for as long as it takes.
 */
export function appliedAnswer(page: Page, hid?: string): Promise<Response> {
  return page.waitForResponse(async (response) => {
    const at = new URL(response.url()).pathname;
    const job = /\/api\/v1\/imports\/([^/]+)$/.exec(at);
    if (response.request().method() !== "GET" || !job || (hid && job[1] !== hid)) return false;
    const read = (await response.json().catch(() => null)) as { status?: string } | null;
    return read?.status === "applied";
  });
}

/** The Import page, opened afresh, once the server has said what each table holds. */
export async function openImport(page: Page): Promise<void> {
  const counted = answer(page, "GET", "/exports/tables");
  await page.goto("./import");
  await counted;
  await expect(page.getByRole("heading", { level: 1, name: "Import" })).toBeVisible();
}

/**
 * Choose a file on the Import page and press Preview: the preview is the server's answer
 * to the file, and is on show once it has come.
 */
export async function previewFile(
  page: Page,
  file: { name: string; mimeType: string; buffer: Buffer },
  entity: string,
): Promise<void> {
  await page.getByLabel("File", { exact: true }).setInputFiles(file);
  // The name of the file suggested what it holds, the new kinds of record among them.
  await expect(page.getByLabel("Records", { exact: true })).toHaveValue(entity);
  const previewed = answer(page, "POST", "/imports/preview");
  await page.getByRole("button", { name: "Preview", exact: true }).click();
  expect((await previewed).status(), "the file is previewed").toBe(201);
  await expect(page.getByTestId("import-job")).toHaveAttribute("data-status", "previewed");
}

/**
 * Load a CSV file on the Import page, as structure.ts does, waiting for each answer of
 * the server: the page, the preview, and the apply, which may wait behind other files'.
 */
export async function importFile(
  page: Page,
  entity: string,
  name: string,
  header: string[],
  rows: string[][],
): Promise<void> {
  await openImport(page);
  const text = [header, ...rows].map((row) => `${row.join(",")}\n`).join("");
  await previewFile(
    page,
    { name, mimeType: "text/csv", buffer: Buffer.from(text, "utf8") },
    entity,
  );
  await expect(count(page, "created")).toHaveText(String(rows.length));
  await expect(count(page, "rejected")).toHaveText("0");
  const applied = appliedAnswer(page);
  await page
    // A count in a sentence has the separator of thousands (P-195): "Apply 1,000 rows".
    .getByRole("button", {
      name: `Apply ${rows.length.toLocaleString("en-US")} ${rows.length === 1 ? "row" : "rows"}`,
    })
    .click();
  await applied;
  const notice = page.getByTestId("preview-applied");
  await expect(notice).toHaveAttribute("data-applied", String(rows.length));
  await expect(notice).toHaveAttribute("data-stale", "0");
  await expect(notice).toHaveAttribute("data-refused", "0");
  await expect(page.getByTestId("import-job")).toHaveAttribute("data-status", "applied");
}
