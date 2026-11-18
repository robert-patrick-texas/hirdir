// The browser scenarios of lane B of the third review of the web UI: a refusal says where
// to go (P-207), counts that open their rows (P-206) and where a contact is named
// (P-205).
//
// The file keeps the rules of support.ts. It signs in as an Admin of its own, and its
// mark is in every name it gives a record: the vendors, the models, the items, the
// contacts and the records that name them, all made through the API as that Admin. It
// changes no setting, no list of choices and no account, and counts only its own
// records: a report is filtered down to them before a number of it is read.

import type { APIRequestContext, Locator, Page } from "@playwright/test";
import { expect } from "@playwright/test";
import { type Account, expectClean, mark, signIn, test, watch } from "./support";

test.describe.configure({ mode: "serial" });

const id = mark("review-3b");

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

function region(page: Page, name: string): Locator {
  return page.getByRole("region", { name, exact: true });
}

test("P-207: a duplicate asset tag names the item that has it, as a link to it", async ({
  page,
  account,
  request,
}) => {
  test.setTimeout(120_000);
  const headers = await session(request, account);
  const tag = `AT-${id}`;
  const first = `ex-sw-${id}-01.example.net`;
  await make(request, headers, "/items", { hostname: first, asset_tag: tag });
  const seen = await watch(page.context());
  await signIn(page, account);

  await page.goto("./items");
  await page.getByRole("button", { name: "New item" }).click();
  const form = region(page, "New item");
  await form.getByLabel("Asset tag").fill(tag.toLowerCase());
  await form.getByLabel("Hostname").fill(`ex-sw-${id}-02.example.net`);
  await form.getByRole("button", { name: "Create item" }).click();

  const refusal = page.locator(".alert-error");
  await expect(refusal).toContainText("There is already an item with the asset tag");
  await expect(refusal).toContainText("The item that has it:");
  await refusal.getByRole("link", { name: first }).click();
  await expect(page.getByRole("heading", { level: 1, name: first })).toBeVisible();
  await expectClean(page, seen, ["409 POST"]);
});

test("P-207: a filter of a field the item list has not names the nearest it has", async ({
  page,
  account,
}) => {
  test.setTimeout(120_000);
  const seen = await watch(page.context());
  await signIn(page, account);
  await page.goto("./items");
  const box = page.getByLabel("Filter", { exact: true });
  await box.fill("type:eq:switch");
  await page.getByRole("button", { name: "Apply", exact: true }).click();
  await expect(
    page.getByText(
      "type is not a field this list can be filtered by; the nearest fields it has are catalog.type and group.type",
    ),
  ).toBeVisible();
  await expectClean(page, seen, ["422 POST"]);
});
