// What the browser scenarios of a retired account and of a person retired together share
// (release 0.9.14, P-291, P-292, P-296 to P-298): a person made through the API as the
// spec file's own Admin, the pages of the three records, the chain and the confirmation.

import { type APIRequestContext, expect, type Locator, type Page } from "@playwright/test";
import { type Headers, make } from "./referenceSteps";

/** One person: a user who is a contact behind one label, or more. */
export interface Person {
  user: { hid: string; username: string };
  contact: { hid: string; name: string };
  labels: Array<{ hid: string; label: string }>;
  accessCode: string;
}

export interface Label {
  hid: string;
  label: string;
}

/**
 * Make a person through the API: the user, its contact and its labels, by one name with
 * the mark of the file in it. The file keeps the user's HID, to put the account away.
 */
export async function makePerson(
  request: APIRequestContext,
  headers: Headers,
  suffix: string,
  key: string,
  options: { labels?: number; role?: string } = {},
): Promise<Person> {
  const username = `e2e-${suffix}-${key}`;
  const name = `${key.charAt(0).toUpperCase()}${key.slice(1)} Example ${suffix}`;
  const answer = await request.post("./api/v1/users", {
    headers,
    data: {
      username,
      contact: { name, email: `${key}.${suffix}@example.net` },
      operator: { label: `${suffix}-${key}` },
      ...(options.role ? { role: options.role } : {}),
    },
  });
  expect(answer.status(), `post /users: ${await answer.text()}`).toBe(201);
  const created = (await answer.json()) as {
    user: { hid: string; username: string; contact: { hid: string; name: string } };
    operator: { hid: string; label: string };
    access_code: string;
  };
  const labels = [{ hid: created.operator.hid, label: created.operator.label }];
  for (let more = 2; more <= (options.labels ?? 1); more += 1) {
    const label = `${suffix}-${key}${more}`;
    const made = await make(request, headers, "/operators", {
      label,
      contact_hid: created.user.contact.hid,
      record_status: "active",
    });
    labels.push({ hid: made.hid, label });
  }
  return {
    user: { hid: created.user.hid, username: created.user.username },
    contact: { hid: created.user.contact.hid, name: created.user.contact.name },
    labels,
    accessCode: created.access_code,
  };
}

/** What the API answers of a record, read as the file's own Admin. */
export async function read<T>(
  request: APIRequestContext,
  headers: Headers,
  path: string,
): Promise<T> {
  const answer = await request.get(`./api/v1${path}`, { headers });
  expect(answer.status(), `get ${path}: ${await answer.text()}`).toBe(200);
  return (await answer.json()) as T;
}

export interface Status {
  record_status: string;
}

/** Change a record through the API, with the version it has now: a `PATCH`, or a `POST` under it. */
export async function change(
  request: APIRequestContext,
  headers: Headers,
  method: "patch" | "post",
  path: string,
  data: Record<string, unknown> = {},
): Promise<void> {
  const record = path.replace(/\/(retire|bring-back)$/, "");
  const now = await read<{ row_version: number }>(request, headers, record);
  const answer = await request[method](`./api/v1${path}`, {
    headers,
    data: { row_version: now.row_version, ...data },
  });
  expect(answer.status(), `${method} ${path}: ${await answer.text()}`).toBe(200);
}

export async function openUser(page: Page, user: { hid: string; username: string }) {
  await page.goto(`./admin/users/${encodeURIComponent(user.hid)}`);
  await expect(page.getByRole("heading", { level: 1, name: user.username })).toBeVisible();
}

export async function openContact(page: Page, contact: { hid: string; name: string }) {
  await page.goto(`./contacts/${encodeURIComponent(contact.hid)}`);
  await expect(page.getByRole("heading", { level: 1, name: contact.name })).toBeVisible();
}

export async function openOperator(page: Page, operator: Label) {
  await page.goto(`./operators/${encodeURIComponent(operator.hid)}`);
  await expect(page.getByTestId("operator-heading")).toContainText(operator.label);
}

/** The chain of a page: its three parts, as they read. */
export function chain(page: Page) {
  const nav = page.getByTestId("chain");
  return {
    nav,
    operators: nav.locator('[data-part="operator"]'),
    contact: nav.locator('[data-part="contact"]'),
    user: nav.locator('[data-part="user"]'),
    here: nav.locator('[data-here="true"]'),
  };
}

/** The row of a label in the confirmation, by its HID. */
export function labelRow(dialog: Locator, operator: { hid: string }): Locator {
  return dialog.locator(`[data-row="operator"][data-operator="${operator.hid}"]`);
}

/** The button of the confirmation that goes ahead, whatever it says it will do. */
export function goAhead(dialog: Locator): Locator {
  return dialog.getByTestId("retire-go");
}

/**
 * A run leaves no account of its own that can sign in: those the file made are
 * disabled, where they are not retired, which cannot sign in already.
 */
export async function putAway(
  request: APIRequestContext,
  headers: Headers,
  hids: readonly string[],
): Promise<void> {
  for (const hid of hids) {
    const path = `./api/v1/users/${encodeURIComponent(hid)}`;
    const found = await request.get(path, { headers });
    if (found.status() !== 200) continue;
    const user = (await found.json()) as { row_version: number; record_status: string };
    if (user.record_status === "retired") continue;
    await request.patch(path, { headers, data: { disabled: true, row_version: user.row_version } });
  }
}
