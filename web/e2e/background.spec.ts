// The browser scenarios of imports applied in the background, release 0.7.0 (P-116,
// P-134):
//
//   An apply answers at once and goes on beside the requests: its page shows how far it
//   has got, may be left and come back to, and the past imports say what became of it.
//   A job that stops partway says why, and is resumed from its page, from the first row
//   it had not applied.
//
// How a stop is made. The server applies one job at a time and checks, as it takes a
// job up, that whoever asked for it still holds the Inventory role. So a second account
// of this file, with that role, asks through the API for a large file to be applied and
// then for a small one, which waits behind it; the account is then disabled, and the
// small one stops when its turn comes. The file's own Admin resumes it in the browser.
// How far an apply has got shows for only a moment on a host that applies a few hundred
// rows a second, so that part changes the server's answer in the page, for one read.
//
// The file keeps the rules of support.ts: it signs in as an Admin of its own, the second
// account is its own and named with its mark, and so is every contact it loads. In the
// past imports, which every file adds to, it looks at its own rows.

import { type APIRequestContext, expect, type Page } from "@playwright/test";
import { whenApplied } from "./structure";
import { type Account, createAccount, expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const suffix = mark("background");
// Enough rows for the first apply to take a moment: 50 rows to a batch, with a pause
// between batches for the requests that wait.
const MANY = 300;

type Headers = { Authorization: string };
type Job = { hid: string; status: string; rows_done: number; row_count: number };

async function signedIn(api: APIRequestContext, account: Account): Promise<Headers> {
  const answer = await api.post("./api/v1/auth/sign-in", {
    data: { username: account.username, access_code: account.accessCode },
  });
  expect(answer.status(), `${account.username} signs in`).toBe(200);
  const { token } = (await answer.json()) as { token: string };
  return { Authorization: `Bearer ${token}` };
}

/** Preview a file of contacts, as the person whose headers these are. */
async function preview(
  api: APIRequestContext,
  headers: Headers,
  name: string,
  people: number[],
): Promise<Job> {
  const rows = people.map(
    (number) => `Background Contact ${suffix} ${number},bg-${suffix}-${number}@example.org`,
  );
  const query = new URLSearchParams({ entity: "contacts", mode: "upsert", file_name: name });
  const answer = await api.post(`./api/v1/imports/preview?${query.toString()}`, {
    headers: { ...headers, "Content-Type": "text/csv" },
    data: Buffer.from(`${["name,email", ...rows].join("\n")}\n`, "utf8"),
  });
  expect(answer.status(), await answer.text()).toBe(201);
  return ((await answer.json()) as { job: Job }).job;
}

/** Ask for a preview to be applied: the answer is at once, the job. */
async function apply(api: APIRequestContext, headers: Headers, job: Job): Promise<Job> {
  const answer = await api.post(`./api/v1/imports/${encodeURIComponent(job.hid)}/apply`, {
    headers,
  });
  expect(answer.status(), await answer.text()).toBe(202);
  return (await answer.json()) as Job;
}

/** Disable an account of this file, as this file's own Admin. */
async function disable(api: APIRequestContext, headers: Headers, account: Account) {
  const path = `./api/v1/users/${encodeURIComponent(account.hid)}`;
  const found = (await (await api.get(path, { headers })).json()) as { row_version: number };
  const answer = await api.patch(path, {
    headers,
    data: { disabled: true, row_version: found.row_version },
  });
  expect(answer.status(), await answer.text()).toBe(200);
}

function range(count: number): number[] {
  return Array.from({ length: count }, (_, place) => place + 1);
}

/** The rows of the past imports that one account made. */
function jobsOf(page: Page, account: Account) {
  return page
    .getByTestId("import-jobs")
    .locator("tbody tr")
    .filter({ has: page.getByRole("cell", { name: account.username, exact: true }) });
}

/** Wait for the apply of the job on show to end, whichever way. */
async function ended(page: Page): Promise<string> {
  const job = page.getByTestId("import-job");
  await expect(job).toHaveAttribute("data-status", /^(applied|stopped)$/, { timeout: 120_000 });
  return (await job.getAttribute("data-status")) ?? "";
}

test("an apply is followed, left and come back to, and one that stopped is resumed", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(300_000);
  const seen = await watch(page.context());

  // The second account asks for a large apply and then a small one, which waits behind
  // it, and is disabled while it waits.
  const ivy = await createAccount(request, `e2e-${suffix}-ivy`, "inventory");
  const asIvy = await signedIn(request, ivy);
  const many = await preview(request, asIvy, `contacts-${suffix}-many.csv`, range(MANY));
  const few = await preview(request, asIvy, `contacts-${suffix}-few.csv`, [MANY + 1, MANY + 2]);
  const first = await apply(request, asIvy, many);
  expect(first.status, "an apply waits to be taken up by the background work").toBe("queued");
  const second = await apply(request, asIvy, few);
  expect(second.status, "the small file waits behind the large one").toBe("queued");
  await disable(request, await signedIn(request, account), ivy);

  await signIn(page, account);

  // How far an apply has got: the page shows it, while the server says the large file is
  // a third of the way. Every read says so until the page has been looked at: the page
  // reads the job again as it follows it, and on a busy host the apply itself may have
  // ended by the second read.
  await page.route(`**/api/v1/imports/${many.hid}`, async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    const answer = await route.fetch();
    const job = (await answer.json()) as Job;
    await route.fulfill({
      response: answer,
      json: { ...job, status: "applying", rows_done: 100, applied: 100, stale: 0 },
    });
  });
  await page.goto(`./import/${encodeURIComponent(many.hid)}`);
  const job = page.getByTestId("import-job");
  await expect(job).toHaveAttribute("data-status", "applying");
  await expect(page.getByTestId("apply-progress-text")).toHaveText(`100 of ${MANY} rows worked`);
  await expect(page.getByTestId("apply-progress").locator("progress")).toHaveAttribute(
    "value",
    "100",
  );
  await expect(page.getByTestId("apply-progress")).toContainText("this page may be left");
  await page.unroute(`**/api/v1/imports/${many.hid}`);

  // The page is left, and come back to: it reads the job afresh and follows it to its end.
  await page.goto("./");
  await page.goto(`./import/${encodeURIComponent(many.hid)}`);
  // It ends applied, or, had it still waited behind another file's import when the
  // account was disabled, stopped too: then it is resumed here as well.
  if ((await ended(page)) === "stopped") {
    await page.getByRole("button", { name: "Resume the apply" }).click();
  }
  await whenApplied(page, MANY, { timeout: 120_000 });
  await expect(page.getByTestId("apply-counts").locator('[data-count="worked"] dd')).toHaveText(
    `${MANY} of ${MANY}`,
  );

  // The small file stopped when its turn came, and says why.
  await page.goto(`./import/${encodeURIComponent(few.hid)}`);
  expect(await ended(page)).toBe("stopped");
  const stopped = page.getByTestId("preview-stopped");
  await expect(stopped.getByTestId("apply-failure")).toContainText(
    "no longer holds the Inventory role",
  );
  await expect(stopped).toContainText("0 of 2 rows had been worked");
  await expect(page.getByTestId("import-status")).toHaveText("Stopped partway, to be resumed");
  // Among the past imports, as the second account made it.
  const jobs = jobsOf(page, ivy);
  await expect(jobs.filter({ hasText: `contacts-${suffix}-few.csv` })).toContainText(
    "Stopped partway, to be resumed",
  );
  await expect(jobs.filter({ hasText: `contacts-${suffix}-many.csv` })).toContainText("Applied");

  // Resumed by somebody who holds the role, it is applied, and says so in the list too.
  await stopped.getByRole("button", { name: "Resume the apply" }).click();
  await whenApplied(page, 2);
  await expect(page.getByTestId("preview-stopped")).toHaveCount(0);
  await expect(jobs.filter({ hasText: `contacts-${suffix}-few.csv` })).toContainText("Applied");
  await expect(
    jobs.filter({ hasText: `contacts-${suffix}-few.csv` }).getByTestId("job-worked"),
  ).toHaveText("2 of 2");

  await expectClean(page, seen);
});
