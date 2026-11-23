// The browser scenario of a bulk edit previewed in the background, release 0.9.19
// (P-325):
//
//   A bulk edit of more than a hundred items is answered at once, 202, with its job being
//   previewed. The panel says how far the preview has got, Previewing 50 of 120 items,
//   offers nothing to apply meanwhile, and says where the job is found, its page among
//   the imports, which lists it with its items too. The keyboard, whose button went with
//   the form, is on the sentence that opens the preview; Change the edit says what it
//   leaves behind and puts the keyboard on the form's first field; and the keyboard on the
//   link that goes when the preview comes is put on the apply. Once it is previewed it is
//   shown as a preview answered at once is, and is applied.
//
// The items are loaded by a file of more than a hundred rows, which is itself previewed
// in the background. How far the bulk edit's preview has got shows for only a moment, so
// the reads of its job are answered here as being previewed, from the server's own
// answer, until the panel has been looked at.
//
// The file keeps the rules of support.ts: it signs in as an Admin of its own, and every
// item it loads is named with its mark, and the grid is filtered down to them; among the
// bulk edits, which every file adds to, it looks at its own row.

import { type BrowserContext, expect, type Route } from "@playwright/test";
import { answer } from "./answers";
import { count, importFile, whenApplied } from "./structure";
import { expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const suffix = mark("bulk-background");
/** More than a hundred: the server previews the file and the bulk edit in the background. */
const MANY = 120;
const prefix = `site8-bulk-${suffix}`;
const hostnames = Array.from(
  { length: MANY },
  (_, at) => `${prefix}-${String(at + 1).padStart(3, "0")}`,
);

type Job = { hid: string; status: string; source: string; created_by_name: string | null };

/** A read of a job, `GET /imports/{hid}`, or of the list of them, `GET /imports`. */
function readsJobs(url: URL): boolean {
  return /\/api\/v1\/imports(\/[^/]+)?$/.test(url.pathname);
}

/**
 * Answer every page's reads of the bulk edits this file's account made, while `held` says
 * so, as the server answers them but being previewed, 50 of their items worked.
 */
async function holdBulk(context: BrowserContext, by: string, held: () => boolean) {
  const changed = (job: Job) =>
    held() && job.source === "bulk" && job.created_by_name === by
      ? {
          ...job,
          status: "previewing",
          rows_previewed: 50,
          created: 0,
          updated: 0,
          unchanged: 0,
          rejected: 0,
        }
      : job;
  await context.route(readsJobs, async (route: Route) => {
    if (route.request().method() !== "GET") return route.fallback();
    const response = await route.fetch();
    if (response.status() !== 200) return route.fulfill({ response });
    const read = (await response.json()) as Job | { items: Job[] };
    const json = "items" in read ? { ...read, items: read.items.map(changed) } : changed(read);
    await route.fulfill({ response, json });
  });
}

test("a bulk edit of more than a hundred items is followed in the panel while it is previewed, changed, and applied", async ({
  page,
  account,
}) => {
  test.setTimeout(300_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  await importFile(
    page,
    "items",
    `items-${suffix}.csv`,
    ["hostname"],
    hostnames.map((name) => [name]),
    { timeout: 120_000 },
  );

  await page.goto(`./items?filter=${encodeURIComponent(`hostname:prefix:${prefix}-`)}`);
  await expect(page.getByTestId("grid-total")).toHaveText(`${MANY} items`);
  await page.getByRole("button", { name: "Select all that match" }).click();
  await page.getByRole("button", { name: "Bulk edit" }).click();
  const bulk = page.getByTestId("bulk-edit");
  await expect(bulk).toContainText(`all ${MANY} items that match the filter`);
  await bulk.getByLabel("Field to change").selectOption({ label: "Comments" });
  await bulk.getByRole("button", { name: "Add", exact: true }).click();
  const comments = bulk.getByRole("group", { name: "Comments" }).getByLabel("Set to");
  await comments.fill(`Edited in bulk ${suffix}`);

  let held = true;
  await holdBulk(page.context(), account.username, () => held);
  let previewed = answer(page, "POST", "/items/bulk-update");
  await bulk.getByRole("button", { name: "Preview the change" }).click();
  let answered = await previewed;
  expect(answered.status(), "more than a hundred items are answered at once").toBe(202);
  const first = ((await answered.json()) as { job: Job }).job;
  expect(first.status).toBe("previewing");

  // Being previewed: how far it has got, and nothing to apply. The keyboard is on the
  // sentence that opens the preview, which took the place of the form (review R8).
  const shown = bulk.getByTestId("bulk-preview");
  await expect(shown).toHaveAttribute("data-status", "previewing");
  const intro = shown.getByTestId("bulk-intro");
  await expect(intro).toBeFocused();
  await expect(intro).toHaveText(
    `What the change would do to all ${MANY} items that match the filter, row by row, once it is previewed. Nothing has been changed yet.`,
  );
  const progress = shown.getByTestId("preview-progress");
  await expect(progress.getByTestId("preview-progress-text")).toHaveText(
    `Previewing 50 of ${MANY} items`,
  );
  await expect(progress.locator("progress")).toHaveAttribute("value", "50");
  await expect(shown.getByTestId("job-said")).toHaveText(
    `A quarter of the ${MANY} items previewed.`,
  );
  // The panel is not there again once the list is left: it says where the job is found.
  await expect(progress).toContainText("It goes on in the background");
  await expect(progress).toContainText("and is found on its page among the imports.");
  await expect(progress).not.toContainText("may be left and come back to");
  await expect(shown.getByRole("button", { name: /^Apply/ })).toHaveCount(0);
  await expect(shown.getByTestId("preview-counts")).toHaveCount(0);
  await expect(shown.getByTestId("preview-rows")).toHaveCount(0);
  await expect(shown.getByRole("button", { name: "Close" })).toBeVisible();
  await expect(shown.getByTestId("bulk-change-hint")).toHaveText(
    "Changed now, this preview is still worked out to its end and kept among the imports, not applied, and the changed edit is previewed after it.",
  );

  // Among the bulk edits of the Import page, in another tab: its items, and how far.
  const other = await page.context().newPage();
  await other.goto("./import");
  await other.getByLabel("Show", { exact: true }).selectOption("bulk");
  const row = other.getByTestId("import-jobs").locator("tbody tr").filter({ hasText: first.hid });
  await expect(row.getByTestId("job-rows")).toHaveText(`Previewing 50 of ${MANY} items`);
  await other.close();

  // Changed while it is previewed: the keyboard is on the form's first field (review R3),
  // and the changed edit is previewed after the first.
  await shown.getByRole("button", { name: "Change the edit" }).click();
  await expect(bulk.getByLabel("Field to change")).toBeFocused();
  await comments.fill(`Edited in bulk again ${suffix}`);
  previewed = answer(page, "POST", "/items/bulk-update");
  await bulk.getByRole("button", { name: "Preview the change" }).click();
  answered = await previewed;
  expect(answered.status()).toBe(202);
  const second = ((await answered.json()) as { job: Job }).job;
  expect(second.hid).not.toBe(first.hid);
  await expect(shown).toHaveAttribute("data-status", "previewing");
  await expect(intro).toBeFocused();

  // The keyboard on the link to its page among the imports, which goes with the block
  // when the preview comes: it is put on the apply, and not lost to the page.
  const link = progress.getByRole("link", { name: "its page among the imports" });
  await expect(link).toHaveAttribute("href", new RegExp(`/import/${second.hid}$`));
  await link.focus();
  await expect(link).toBeFocused();
  held = false;
  await expect(shown).toHaveAttribute("data-status", "previewed", { timeout: 120_000 });
  await expect(count(page, "updated")).toHaveText(String(MANY));
  await expect(count(page, "rejected")).toHaveText("0");
  const apply = shown.getByRole("button", { name: `Apply ${MANY} items` });
  await expect(apply).toBeFocused();
  await expect(shown.getByTestId("bulk-change-hint")).toHaveCount(0);
  await expect(shown.getByTestId("preview-rows").locator("tbody tr")).toHaveCount(100);

  await apply.click();
  await whenApplied(shown, MANY, { timeout: 120_000 });
  await expectClean(page, seen);
});
