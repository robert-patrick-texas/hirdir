// The browser scenarios of a file previewed in the background, release 0.9.19 (P-325):
//
//   A file of more than a hundred rows is answered at once, 202, with its job being
//   previewed and no rows. The Import page says how far the preview has got, Previewing
//   50 of 120 rows, offers nothing to apply and lists no rows meanwhile, may be left and
//   come back to, and the past imports say the same. Once it is previewed it is shown as
//   a preview answered at once is, its counts and its first rows, and is applied. A
//   preview that failed says why, offers to send the file again, and has no Apply.
//
// How far a preview has got shows for only a moment on a host that previews a few
// hundred rows a second, so the page's reads of the job are answered here as being
// previewed, from the server's own answer, until the page has been looked at; and a
// failure, which nothing the browser does can cause, is answered here too.
//
// The file keeps the rules of support.ts: it signs in as an Admin of its own, every
// contact and file it loads is named with its mark, and in the past imports, which every
// file adds to, it looks at its own rows.

import { expect, type Page, type Route } from "@playwright/test";
import { answer } from "./answers";
import { count, whenApplied } from "./structure";
import { expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const suffix = mark("preview-background");
/** More than a hundred: the server previews it in the background. */
const MANY = 120;

type Job = { hid: string; status: string; file_name: string | null; row_count: number };

/** A file of new contacts, named by the file's `part` and its mark: none of another test's. */
function contacts(name: string, part: string, rows: number) {
  const lines = Array.from(
    { length: rows },
    (_, at) =>
      `Background Preview ${suffix} ${part} ${at + 1},pb-${suffix}-${part}-${at + 1}@example.org`,
  );
  return {
    name,
    mimeType: "text/csv",
    buffer: Buffer.from(`${["name,email", ...lines].join("\n")}\n`, "utf8"),
  };
}

/** A read of a job, `GET /imports/{hid}`, or of the past imports, `GET /imports`. */
function readsJobs(url: URL): boolean {
  return /\/api\/v1\/imports(\/[^/]+)?$/.test(url.pathname);
}

/**
 * Answer the page's reads of the job of a file, and of the past imports that hold it,
 * while `held` says so, as the server answers them but changed by `as`: the job as it
 * would be while it is previewed. Taken away by `page.unroute(readsJobs)`.
 */
async function holdJob(
  page: Page,
  file: string,
  held: () => boolean,
  as: Record<string, unknown>,
): Promise<void> {
  const changed = (job: Job) => (held() && job.file_name === file ? { ...job, ...as } : job);
  await page.route(readsJobs, async (route: Route) => {
    if (route.request().method() !== "GET") return route.fallback();
    const response = await route.fetch();
    if (response.status() !== 200) return route.fulfill({ response });
    const read = (await response.json()) as Job | { items: Job[] };
    const json = "items" in read ? { ...read, items: read.items.map(changed) } : changed(read);
    await route.fulfill({ response, json });
  });
}

/** Choose a file on the Import page and press Preview: the answer is the job, at once. */
async function send(page: Page, file: ReturnType<typeof contacts>) {
  await page.goto("./import");
  await expect(page.getByRole("heading", { level: 1, name: "Import" })).toBeVisible();
  await page.getByLabel("File", { exact: true }).setInputFiles(file);
  await expect(page.getByLabel("Records", { exact: true })).toHaveValue("contacts");
  const previewed = answer(page, "POST", "/imports/preview");
  await page.getByRole("button", { name: "Preview", exact: true }).click();
  const answered = await previewed;
  expect(answered.status(), "a file of more than a hundred rows is answered at once").toBe(202);
  const body = (await answered.json()) as { job: Job & { rows_previewed: number }; rows: [] };
  expect(body.job.status).toBe("previewing");
  expect(body.job.rows_previewed).toBe(0);
  expect(body.rows).toEqual([]);
  return body.job;
}

/** The row of the past imports of a file of this file's own. */
function pastRow(page: Page, file: string) {
  return page.getByTestId("import-jobs").locator("tbody tr").filter({ hasText: file });
}

test("a file of more than a hundred rows is followed while it is previewed, left and come back to, and applied", async ({
  page,
  account,
}) => {
  test.setTimeout(240_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  const name = `contacts-${suffix}-many.csv`;
  let held = true;
  await holdJob(page, name, () => held, {
    status: "previewing",
    rows_previewed: 50,
    created: 0,
    updated: 0,
    unchanged: 0,
    rejected: 0,
  });
  const sent = await send(page, contacts(name, "many", MANY));

  // Being previewed: how far it has got, said politely, and nothing to apply or page.
  const job = page.getByTestId("import-job");
  await expect(job).toHaveAttribute("data-status", "previewing");
  await expect(page).toHaveURL(new RegExp(`/import/${sent.hid}$`));
  await expect(page.getByTestId("import-status")).toHaveText("Being previewed");
  const progress = page.getByTestId("preview-progress");
  await expect(progress.getByTestId("preview-progress-text")).toHaveText(
    `Previewing 50 of ${MANY} rows`,
  );
  await expect(progress.locator("progress")).toHaveAttribute("value", "50");
  await expect(progress).toContainText("this page may be left and come back to");
  await expect(page.getByRole("status").filter({ has: progress })).toHaveAttribute(
    "aria-live",
    "polite",
  );
  await expect(job.getByRole("button", { name: /^Apply/ })).toHaveCount(0);
  await expect(page.getByTestId("preview-counts")).toHaveCount(0);
  await expect(page.getByTestId("preview-rows")).toHaveCount(0);
  // Among the past imports, with its label and how far it has got.
  const past = pastRow(page, name);
  await expect(past).toHaveAttribute("data-status", "previewing");
  await expect(past).toContainText("Being previewed");
  await expect(past.getByTestId("job-rows")).toHaveText(`Previewing 50 of ${MANY} rows`);
  await expect(past.getByTestId("job-worked")).toHaveText("—");

  // Left and come back to, it is read afresh and followed again.
  await page.goto("./");
  await page.goto(`./import/${encodeURIComponent(sent.hid)}`);
  await expect(job).toHaveAttribute("data-status", "previewing");
  await expect(page.getByTestId("preview-progress-text")).toHaveText(
    `Previewing 50 of ${MANY} rows`,
  );

  // Previewed, it is shown as a preview answered at once is: its counts, its first rows.
  held = false;
  await expect(job).toHaveAttribute("data-status", "previewed", { timeout: 120_000 });
  await expect(page.getByTestId("preview-progress")).toHaveCount(0);
  await expect(page.getByTestId("import-status")).toHaveText("Previewed, not applied");
  await expect(count(page, "created")).toHaveText(String(MANY));
  await expect(count(page, "rejected")).toHaveText("0");
  await expect(page.getByTestId("preview-arrived")).toHaveText(
    `Previewed: ${MANY} to create, 0 to update, 0 unchanged, 0 rejected.`,
  );
  const rows = page.getByTestId("preview-rows").locator("tbody tr");
  await expect(rows).toHaveCount(100);
  await expect(rows.first()).toHaveAttribute("data-row", "1");
  await expect(rows.first()).toContainText(`Background Preview ${suffix} many 1`);
  await expect(past).toContainText("Previewed, not applied");
  await expect(past.getByTestId("job-rows")).toHaveText(
    `${MANY} to create, 0 to update, 0 unchanged, 0 rejected`,
  );

  // And it is applied, as any preview is.
  await job.getByRole("button", { name: `Apply ${MANY} rows` }).click();
  await whenApplied(page, MANY, { timeout: 120_000 });
  await expect(past).toContainText("Applied");
  await expectClean(page, seen);
});

test("a preview that failed in the background says why, offers to send the file again, and has no Apply", async ({
  page,
  account,
}) => {
  test.setTimeout(240_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  const name = `contacts-${suffix}-failed.csv`;
  const why = "An error nobody foresaw ended the preview (request 0000-example).";
  await holdJob(page, name, () => true, {
    status: "failed",
    rows_previewed: 40,
    created: 0,
    updated: 0,
    unchanged: 0,
    rejected: 0,
    failure: why,
  });
  const first = await send(page, contacts(name, "failed", MANY));

  const job = page.getByTestId("import-job");
  await expect(job).toHaveAttribute("data-status", "failed");
  await expect(page.getByTestId("import-status")).toHaveText("Preview failed");
  const failed = page.getByTestId("preview-failed");
  await expect(failed).toHaveAttribute("data-whole", "false");
  await expect(failed).toContainText("The preview failed, and nothing was applied.");
  await expect(failed.getByTestId("preview-failure")).toHaveText(why);
  await expect(job.getByRole("button", { name: /^Apply/ })).toHaveCount(0);
  await expect(page.getByTestId("preview-counts")).toHaveCount(0);
  await expect(page.getByTestId("preview-rows")).toHaveCount(0);
  await expect(pastRow(page, name).filter({ hasText: first.hid })).toContainText("Preview failed");

  // Sent again, it is a new preview, made in the background in its turn.
  await page.unroute(readsJobs);
  const again = answer(page, "POST", "/imports/preview");
  await failed.getByRole("button", { name: "Preview again" }).click();
  const answered = await again;
  expect(answered.status()).toBe(202);
  const second = ((await answered.json()) as { job: Job }).job;
  expect(second.hid).not.toBe(first.hid);
  await expect(page).toHaveURL(new RegExp(`/import/${second.hid}$`));
  await expect(job).toHaveAttribute("data-status", "previewed", { timeout: 120_000 });
  await expect(count(page, "created")).toHaveText(String(MANY));
  await expect(job.getByRole("button", { name: `Apply ${MANY} rows` })).toBeEnabled();
  await expectClean(page, seen);
});
