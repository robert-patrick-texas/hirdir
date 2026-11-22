// The browser scenario of a bulk edit previewed in the background, release 0.9.19
// (P-325):
//
//   A bulk edit of more than a hundred items is answered at once, 202, with its job being
//   previewed. The panel says how far the preview has got, Previewing 50 of 120 items,
//   and offers nothing to apply meanwhile; the keyboard, whose button went with the form,
//   is on the preview, and is not lost to the page when the preview comes. Once it is
//   previewed it is shown as a preview answered at once is, and is applied.
//
// The items are loaded by a file of more than a hundred rows, which is itself previewed
// in the background. How far the bulk edit's preview has got shows for only a moment, so
// the page's reads of the job are answered here as being previewed, from the server's own
// answer, until the panel has been looked at.
//
// The file keeps the rules of support.ts: it signs in as an Admin of its own, and every
// item it loads is named with its mark, and the grid is filtered down to them.

import { expect, type Page, type Route } from "@playwright/test";
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

type Job = { hid: string; status: string; source: string };

/** A read of a job, `GET /imports/{hid}`. */
function readsJob(url: URL): boolean {
  return /\/api\/v1\/imports\/[^/]+$/.test(url.pathname);
}

/**
 * Answer the page's reads of a bulk edit's job, while `held` says so, as the server
 * answers them but being previewed, 50 of its items worked.
 */
async function holdBulk(page: Page, held: () => boolean): Promise<void> {
  await page.route(readsJob, async (route: Route) => {
    if (route.request().method() !== "GET") return route.fallback();
    const response = await route.fetch();
    const job = (await response.json()) as Job;
    if (!held() || job.source !== "bulk") return route.fulfill({ response });
    await route.fulfill({
      response,
      json: {
        ...job,
        status: "previewing",
        rows_previewed: 50,
        created: 0,
        updated: 0,
        unchanged: 0,
        rejected: 0,
      },
    });
  });
}

test("a bulk edit of more than a hundred items is followed in the panel while it is previewed, and applied", async ({
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
  await bulk
    .getByRole("group", { name: "Comments" })
    .getByLabel("Set to")
    .fill(`Edited in bulk ${suffix}`);

  let held = true;
  await holdBulk(page, () => held);
  const previewed = answer(page, "POST", "/items/bulk-update");
  await bulk.getByRole("button", { name: "Preview the change" }).click();
  const answered = await previewed;
  expect(answered.status(), "more than a hundred items are answered at once").toBe(202);
  expect(((await answered.json()) as { job: Job }).job.status).toBe("previewing");

  // Being previewed: how far it has got, and nothing to apply. The keyboard is on the
  // preview, which took the place of the form.
  const shown = bulk.getByTestId("bulk-preview");
  await expect(shown).toHaveAttribute("data-status", "previewing");
  await expect(shown).toBeFocused();
  const progress = shown.getByTestId("preview-progress");
  await expect(progress.getByTestId("preview-progress-text")).toHaveText(
    `Previewing 50 of ${MANY} items`,
  );
  await expect(progress.locator("progress")).toHaveAttribute("value", "50");
  await expect(shown.getByRole("button", { name: /^Apply/ })).toHaveCount(0);
  await expect(shown.getByTestId("preview-counts")).toHaveCount(0);
  await expect(shown.getByTestId("preview-rows")).toHaveCount(0);
  await expect(shown.getByRole("button", { name: "Change the edit" })).toBeVisible();
  await expect(shown.getByRole("button", { name: "Close" })).toBeVisible();

  // The keyboard on the link to its page among the imports, which goes with the block
  // when the preview comes: it is put on the apply, and not lost to the page.
  const link = progress.getByRole("link", { name: "its page among the imports" });
  await link.focus();
  await expect(link).toBeFocused();
  held = false;
  await expect(shown).toHaveAttribute("data-status", "previewed", { timeout: 120_000 });
  await expect(count(page, "updated")).toHaveText(String(MANY));
  await expect(count(page, "rejected")).toHaveText("0");
  const apply = shown.getByRole("button", { name: `Apply ${MANY} items` });
  await expect(apply).toBeFocused();
  await expect(shown.getByTestId("preview-rows").locator("tbody tr")).toHaveCount(100);

  await apply.click();
  await whenApplied(shown, MANY, { timeout: 120_000 });
  await expectClean(page, seen);
});
